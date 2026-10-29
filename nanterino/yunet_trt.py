"""YuNet face detector on the GPU with TensorRT (FP16 engine built by build-yunet-trt).

logging: robotlog via nanterino.log (load / errors only).
Why: on real frames OpenCV's CPU YuNet took 17 ms and ~55% of a core (measured 2026-10-15);
OpenCV 5 cannot run it on CUDA (new DNN engine is CPU-only, the classic engine fails on YuNet).
The decoding below mirrors OpenCV's FaceDetectorYN post-processing (YuNet 2023mar):
score = sqrt(clamp(cls) * clamp(obj)); box centre = (col + dx, row + dy) * stride,
size = exp(dw, dh) * stride; then NMS. Output rows match cv2.FaceDetectorYN:
[x, y, w, h, 10 landmark coords, score] in input-image pixels.
"""
import numpy as np
import cv2
import tensorrt as trt
from cuda.bindings import runtime as rt

from .log import log

SIZE = 640                 # the ONNX model has a fixed 640x640 input
STRIDES = (8, 16, 32)


def _check(err):
    err = err[0] if isinstance(err, tuple) else err
    if err != rt.cudaError_t.cudaSuccess:
        raise RuntimeError(f"CUDA error {err}")


class YuNetTRT:
    def __init__(self, engine_path: str, score_threshold: float = 0.75, nms_threshold: float = 0.3):
        self.score_thr, self.nms_thr = score_threshold, nms_threshold
        logger = trt.Logger(trt.Logger.ERROR)
        with open(engine_path, "rb") as f:
            self.engine = trt.Runtime(logger).deserialize_cuda_engine(f.read())
        self.ctx = self.engine.create_execution_context()
        err, self.stream = rt.cudaStreamCreate(); _check(err)
        self.host, self.dev = {}, {}
        for i in range(self.engine.num_io_tensors):
            name = self.engine.get_tensor_name(i)
            shape = tuple(self.engine.get_tensor_shape(name))
            arr = np.empty(shape, dtype=trt.nptype(self.engine.get_tensor_dtype(name)))
            err, ptr = rt.cudaMalloc(arr.nbytes); _check(err)
            self.host[name], self.dev[name] = arr, ptr
            self.ctx.set_tensor_address(name, ptr)
        # The host input tensor doubles as the letterbox canvas: zeroed once, then only the image
        # area is rewritten; the padding is re-zeroed only if the image size changes.
        self.host["input"][...] = 0
        self._pad_hw = None
        log.info("yunet trt engine loaded tensors=%d", len(self.host))

    def detect(self, bgr: np.ndarray) -> np.ndarray:
        """bgr: HxW (H, W <= 640) uint8 image -> (N, 15) float32 detections."""
        h, w = bgr.shape[:2]
        inp = self.host["input"]
        if self._pad_hw != (h, w):  # letterbox: image top-left, zero padding (same as OpenCV padding)
            inp[...] = 0
            self._pad_hw = (h, w)
        inp[0, :, :h, :w] = bgr.transpose(2, 0, 1)
        H2D, D2H = rt.cudaMemcpyKind.cudaMemcpyHostToDevice, rt.cudaMemcpyKind.cudaMemcpyDeviceToHost
        _check(rt.cudaMemcpyAsync(self.dev["input"], inp.ctypes.data, inp.nbytes, H2D, self.stream))
        if not self.ctx.execute_async_v3(self.stream):
            raise RuntimeError("TensorRT execution failed")
        for name, arr in self.host.items():
            if name != "input":
                _check(rt.cudaMemcpyAsync(arr.ctypes.data, self.dev[name], arr.nbytes, D2H, self.stream))
        _check(rt.cudaStreamSynchronize(self.stream))
        return self._decode(w, h)

    def _decode(self, w: int, h: int) -> np.ndarray:
        boxes, scores, kpss = [], [], []
        for s in STRIDES:
            cols = SIZE // s
            cls = np.clip(self.host[f"cls_{s}"][0, :, 0], 0, 1)
            obj = np.clip(self.host[f"obj_{s}"][0, :, 0], 0, 1)
            score = np.sqrt(cls * obj)
            keep = np.where(score >= self.score_thr)[0]
            if not keep.size:
                continue
            r, c = (keep // cols).astype(np.float32), (keep % cols).astype(np.float32)
            bb = self.host[f"bbox_{s}"][0, keep]
            cx, cy = (c + bb[:, 0]) * s, (r + bb[:, 1]) * s
            bw, bh = np.exp(bb[:, 2]) * s, np.exp(bb[:, 3]) * s
            boxes.append(np.stack([cx - bw / 2, cy - bh / 2, bw, bh], 1))
            kp = self.host[f"kps_{s}"][0, keep].reshape(-1, 5, 2)
            kp = (kp + np.stack([c, r], 1)[:, None, :]) * s
            kpss.append(kp.reshape(-1, 10)); scores.append(score[keep])
        if not boxes:
            return np.zeros((0, 15), np.float32)
        boxes, scores, kpss = np.concatenate(boxes), np.concatenate(scores), np.concatenate(kpss)
        idx = cv2.dnn.NMSBoxes(boxes.tolist(), scores.tolist(), self.score_thr, self.nms_thr)
        idx = np.array(idx).reshape(-1)
        out = np.concatenate([boxes[idx], kpss[idx], scores[idx, None]], 1).astype(np.float32)
        inside = (out[:, 0] < w) & (out[:, 1] < h)  # drop anything found in the padding
        return out[inside]