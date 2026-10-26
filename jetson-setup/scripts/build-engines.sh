#!/usr/bin/env bash
# Build whisper.cpp and llama.cpp with CUDA (Orin sm_87) into /opt/robot/engines
# Logs: /var/log/robot/build-engines.log (WARN/ERROR also in errors.log)
source /opt/robot/lib/robotlog.sh "build-engines"

# Builds are reproducible from upstream sources; binaries stay on the Jetson (not in Drive).
set -e
export PATH=/usr/local/cuda/bin:$PATH
E=/opt/robot/engines
mkdir -p "$E"
command -v nvcc >/dev/null || { log_error "nvcc missing: install nvidia-jetpack first"; exit 1; }
log_info "nvcc $(nvcc --version | tail -1)"

build() {  # $1=name $2=repo $3=cmake flags...
  local name=$1 repo=$2; shift 2
  if [ -d "$E/$name/.git" ]; then git -C "$E/$name" pull --ff-only; else git clone --depth 1 "$repo" "$E/$name"; fi
  log_info "$name commit $(git -C "$E/$name" rev-parse --short HEAD)"
  cmake -S "$E/$name" -B "$E/$name/build" -DCMAKE_BUILD_TYPE=Release -DCMAKE_CUDA_ARCHITECTURES=87 "$@"
  # -j4 keeps RAM usage bounded on the 8 GB board (CUDA compilation is memory hungry).
  cmake --build "$E/$name/build" -j4 --config Release
  log_info "$name build ok"
}

build whisper.cpp https://github.com/ggml-org/whisper.cpp.git -DGGML_CUDA=ON -DWHISPER_BUILD_SERVER=ON
build llama.cpp   https://github.com/ggml-org/llama.cpp.git   -DGGML_CUDA=ON -DLLAMA_CURL=OFF
ls -la "$E/whisper.cpp/build/bin/whisper-server" "$E/llama.cpp/build/bin/llama-server"
log_info "engines ready"
