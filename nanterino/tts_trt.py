"""Piper voice with the heavy half on the GPU (TensorRT), front half on the CPU.

logging: robotlog via nanterino.log (load / errors only).
Why: Piper ran fully on the CPU (~360 ms for a first sentence, measured 2026-10-15); no
onnxruntime-gpu exists for JetPack 7 / CUDA 13, and TensorRT cannot take the whole VITS graph
(data-dependent `Range` in the duration predictor). The graph is cut at the flow input
(`/Add_output_0` latent + `/Cast_2_output_0` mask, cut point reused from the Pi Hailo
experiment): front half (text -> durations -> latent) on onnxruntime CPU, back half
(flow + HiFi-GAN vocoder, ~all the compute) as a TensorRT FP16 engine.
"""
import numpy as np
import onnxruntime as ort
import tensorrt as trt
from cuda.bindings import runtime as rt

from .log import log

D = "/opt/robot/nanterino/models/piper/"
MAX_FRAMES = 1500  # engine profile max (~17 s of audio per sentence)


def _ok(r):
    e = r[0] if isinstance(r, tuple) else r
    if e != rt.cudaError_t.cudaSuccess:
        raise RuntimeError(f"CUDA error {e}")
    return r[1] if isinstance(r, tuple) and len(r) > 1 else None


class PiperTRT:
    def __init__(self, voice, front=D + "siwis_frontend.onnx", engine=D + "siwis_backend_fp16.engine"):
        self.voice = voice  # PiperVoice: phonemisation + config only
        self.rate = voice.config.sample_rate
        inf = voice.config
        self.scales = np.array([inf.noise_scale, inf.length_scale, inf.noise_w_scale], dtype=np.float32)  # piper-tts 1.3 names
        # The front half is tiny: 2 intra-op threads are enough and, with spinning off, idle
        # onnxruntime workers sleep instead of burning CPU between sentences.
        so = ort.SessionOptions()
        so.intra_op_num_threads, so.inter_op_num_threads = 2, 1
        so.add_session_config_entry("session.intra_op.allow_spinning", "0")
        self.front = ort.InferenceSession(front, sess_options=so, providers=["CPUExecutionProvider"])
        with open(engine, "rb") as f:
            self.engine = trt.Runtime(trt.Logger(trt.Logger.ERROR)).deserialize_cuda_engine(f.read())
        self.ctx = self.engine.create_execution_context()
        self.stream = _ok(rt.cudaStreamCreate())
        self.z_name, self.m_name, self.out_name = "/Add_output_0", "/Cast_2_output_0", "output"
        self.dz = _ok(rt.cudaMalloc(192 * MAX_FRAMES * 4))
        self.dm = _ok(rt.cudaMalloc(MAX_FRAMES * 4))
        self.out_max = MAX_FRAMES * 256 * 2  # generous: hop 256 samples per frame
        self.dout = _ok(rt.cudaMalloc(self.out_max * 4))
        for n, p in ((self.z_name, self.dz), (self.m_name, self.dm), (self.out_name, self.dout)):
            self.ctx.set_tensor_address(n, p)
        log.info("piper trt loaded rate=%s", self.rate)

    def _ids(self, text):
        for phonemes in self.voice.phonemize(text):  # one list per sentence
            yield np.array(self.voice.phonemes_to_ids(phonemes), dtype=np.int64)

    def _backend(self, z: np.ndarray, mask: np.ndarray) -> np.ndarray:
        frames = z.shape[-1]
        if frames > MAX_FRAMES:
            raise ValueError(f"sentence too long for the engine ({frames} frames)")
        z = np.ascontiguousarray(z, dtype=np.float32); mask = np.ascontiguousarray(mask, dtype=np.float32)
        self.ctx.set_input_shape(self.z_name, z.shape); self.ctx.set_input_shape(self.m_name, mask.shape)
        oshape = tuple(self.ctx.get_tensor_shape(self.out_name))
        out = np.empty(oshape, dtype=np.float32)
        if out.size > self.out_max:
            raise ValueError("output larger than the preallocated buffer")
        H2D, D2H = rt.cudaMemcpyKind.cudaMemcpyHostToDevice, rt.cudaMemcpyKind.cudaMemcpyDeviceToHost
        _ok(rt.cudaMemcpyAsync(self.dz, z.ctypes.data, z.nbytes, H2D, self.stream))
        _ok(rt.cudaMemcpyAsync(self.dm, mask.ctypes.data, mask.nbytes, H2D, self.stream))
        if not self.ctx.execute_async_v3(self.stream):
            raise RuntimeError("TensorRT execution failed")
        _ok(rt.cudaMemcpyAsync(out.ctypes.data, self.dout, out.nbytes, D2H, self.stream))
        _ok(rt.cudaStreamSynchronize(self.stream))
        return out.reshape(-1)

    def synth(self, text: str, scales=None) -> np.ndarray:
        """Same contract as engines.TTS.synth: int16 PCM at self.rate."""
        sc = self.scales if scales is None else np.asarray(scales, dtype=np.float32)
        chunks = []
        for ids in self._ids(text):
            z, mask = self.front.run(None, {"input": ids[None, :], "input_lengths": np.array([ids.size], np.int64), "scales": sc})
            audio = self._backend(z, mask)
            peak = max(1e-6, float(np.abs(audio).max()))
            chunks.append(np.clip(audio / max(peak, 1.0), -1, 1))  # Piper normalises only if clipping
        if not chunks:
            return np.zeros(0, np.int16)
        return (np.concatenate(chunks) * 32767).astype(np.int16)