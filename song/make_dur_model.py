#!/usr/bin/env python3
"""Expose Piper VITS phoneme durations: copy of the voice ONNX with the Ceil (w_ceil) tensor as
an extra graph output. Used offline by the Daisy-style singer (song/build_song_v3.py) to know
exactly where each phoneme sits in the generated audio (frames of hop 256 samples).
logging: robotlog via nanterino.log
"""
import sys

import onnx
import numpy as np
import onnxruntime as ort

src = sys.argv[1] if len(sys.argv) > 1 else "/opt/robot/nanterino/models/piper/fr_FR-siwis-medium.onnx"
dst = src.replace(".onnx", "-durations.onnx")
m = onnx.load(src)
ceils = [n for n in m.graph.node if n.op_type == "Ceil"]
print("Ceil nodes:", [(n.name, list(n.output)) for n in ceils])
if not ceils:
    sys.exit("no Ceil node: durations not exposed this way")
out = ceils[0].output[0]
m.graph.output.append(onnx.helper.make_tensor_value_info(out, onnx.TensorProto.FLOAT, None))
onnx.save(m, dst)
s = ort.InferenceSession(dst, providers=["CPUExecutionProvider"])
print("outputs:", [o.name for o in s.get_outputs()])
ids = np.array([[1, 0, 20, 0, 14, 0, 2]], dtype=np.int64)
res = s.run(None, {"input": ids, "input_lengths": np.array([ids.shape[1]], dtype=np.int64),
                   "scales": np.array([0.667, 1.0, 0.8], dtype=np.float32)})
print("audio samples", res[0].shape, "durations", res[1].squeeze(), "sum", res[1].sum(), "x256 =", res[1].sum() * 256)
print("saved", dst)
