#!/usr/bin/env bash
# Build OpenCV (dnn+objdetect, CUDA/cuDNN) and librealsense (CUDA) into side prefixes, keeping the pip versions as fallback
# Logs: /var/log/robot/build-gpu-vision.log (WARN/ERROR also in errors.log)
source /opt/robot/lib/robotlog.sh "build-gpu-vision"

# GPU optimisation step 2 (PLAN-jetson.md): YuNet face detection on CUDA + RealSense align on CUDA.
# Builds go to /opt/robot/engines/*-cuda/install and are NOT activated here: the working pip
# packages stay in place until the CUDA builds are verified (fallback rule).
set -e
export PATH=/usr/local/cuda/bin:$PATH
E=/opt/robot/engines
VENV_PY=/opt/robot/nanterino/.venv/bin/python
JOBS=3  # 8 GB board: -j3 keeps CUDA compilation away from OOM

# Free RAM/GPU memory during the build; always restart the engines, even on failure.
systemctl --user stop nanterino-llm nanterino-stt || true
trap 'systemctl --user start nanterino-stt nanterino-llm; log_info "engines restarted"' EXIT
log_info "engines paused for the build"

sudo -n apt-get install -y -qq ninja-build libusb-1.0-0-dev libssl-dev pkg-config >/dev/null
log_info "nvcc $(nvcc --version | tail -1) ; cudnn $(dpkg -l | awk '/libcudnn[0-9]+-dev/{print $3; exit}')"

# ---------------------------------------------------------------- OpenCV (minimal module list)
CV_VER=$($VENV_PY -c "import cv2; print(cv2.__version__)")  # same version as the working pip build
log_info "opencv target version $CV_VER"
cd $E
[ -d opencv ] || git clone --depth 1 -b "$CV_VER" https://github.com/opencv/opencv.git
[ -d opencv_contrib ] || git clone --depth 1 -b "$CV_VER" https://github.com/opencv/opencv_contrib.git
NUMPY_INC=$($VENV_PY -c "import numpy; print(numpy.get_include())")
cmake -S opencv -B opencv-cuda/build -G Ninja \
  -DCMAKE_BUILD_TYPE=Release -DCMAKE_INSTALL_PREFIX=$E/opencv-cuda/install \
  -DOPENCV_EXTRA_MODULES_PATH=$E/opencv_contrib/modules \
  -DBUILD_LIST=core,imgproc,imgcodecs,dnn,objdetect,python3,cudev \
  -DWITH_CUDA=ON -DWITH_CUDNN=ON -DOPENCV_DNN_CUDA=ON -DCUDA_ARCH_BIN=8.7 -DCUDA_ARCH_PTX= \
  -DWITH_GTK=OFF -DWITH_QT=OFF -DBUILD_TESTS=OFF -DBUILD_PERF_TESTS=OFF -DBUILD_EXAMPLES=OFF -DBUILD_DOCS=OFF \
  -DPYTHON3_EXECUTABLE=$VENV_PY -DPYTHON3_NUMPY_INCLUDE_DIRS=$NUMPY_INC \
  -DOPENCV_PYTHON3_INSTALL_PATH=$E/opencv-cuda/install/python
cmake --build opencv-cuda/build -j $JOBS
cmake --install opencv-cuda/build
log_info "opencv cuda installed"
PYTHONPATH=$E/opencv-cuda/install/python $VENV_PY -c "import cv2; print('cv2', cv2.__version__, 'cuda devices', cv2.cuda.getCudaEnabledDeviceCount())" \
  || log_warn "opencv cuda import check failed"

# ---------------------------------------------------------------- librealsense (CUDA align)
RS_VER=v$($VENV_PY -c "import pyrealsense2 as rs; print(rs.__version__)" | cut -d. -f1-3)
log_info "librealsense target version $RS_VER"
[ -d librealsense ] || git clone --depth 1 -b "$RS_VER" https://github.com/realsenseai/librealsense.git
cmake -S librealsense -B librealsense-cuda/build -G Ninja \
  -DCMAKE_BUILD_TYPE=Release -DCMAKE_INSTALL_PREFIX=$E/librealsense-cuda/install \
  -DBUILD_WITH_CUDA=ON -DCMAKE_CUDA_ARCHITECTURES=87 -DFORCE_RSUSB_BACKEND=ON \
  -DBUILD_PYTHON_BINDINGS=ON -DPYTHON_EXECUTABLE=$VENV_PY \
  -DPYTHON_INSTALL_DIR=$E/librealsense-cuda/install/python \
  -DBUILD_EXAMPLES=OFF -DBUILD_GRAPHICAL_EXAMPLES=OFF -DBUILD_UNIT_TESTS=OFF -DBUILD_TOOLS=OFF
cmake --build librealsense-cuda/build -j $JOBS
cmake --install librealsense-cuda/build
log_info "librealsense cuda installed"
log_info "BUILD DONE: activate after verification (see PLAN-jetson.md GPU step 2)"
