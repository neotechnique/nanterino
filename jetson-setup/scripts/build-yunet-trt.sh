#!/usr/bin/env bash
# Build the YuNet TensorRT FP16 engine and give the Nanterino venv TensorRT + CUDA Python bindings
# Logs: /var/log/robot/build-yunet-trt.log (WARN/ERROR also in errors.log)
source /opt/robot/lib/robotlog.sh "build-yunet-trt"

# GPU step 2 (revised 2026-10-15): YuNet = 55% of a CPU core at 17 ms/frame (measured);
# OpenCV 5 cannot run it on CUDA, so we use TensorRT directly. CPU path stays as fallback.
set -e
M=/opt/robot/nanterino/models/vision
VENV=/opt/robot/nanterino/.venv
/usr/src/tensorrt/bin/trtexec --onnx=$M/face_detection_yunet_2023mar.onnx \
  --saveEngine=$M/yunet_640_fp16.engine --fp16 --skipInference 2>&1 | grep -E "Engine built|Error|error" | head -5 || true
ls -la $M/yunet_640_fp16.engine
log_info "yunet trt engine built"
# Expose ONLY the system tensorrt packages to the venv (not the whole system site-packages,
# whose numpy etc. would conflict with the venv versions).
SP=$($VENV/bin/python -c "import site; print(site.getsitepackages()[0])")
for d in /usr/lib/python3.12/dist-packages/tensorrt*; do  # python3-libnvinfer installs here, not in python3/ ln -sfn "$d" "$SP/$(basename "$d")"; done
$VENV/bin/python -c "import tensorrt as t; print('venv tensorrt', t.__version__)"
$VENV/bin/pip install --quiet "cuda-python>=13,<14"
$VENV/bin/python -c "from cuda.bindings import runtime as rt; e, n = rt.cudaGetDeviceCount(); print('cuda-python devices', n, e)"
log_info "tensorrt + cuda-python available in venv"
