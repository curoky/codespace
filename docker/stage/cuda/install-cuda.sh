#!/usr/bin/env bash
# Copyright (c) 2018-2025 curoky(cccuroky@gmail.com).
#
# This file is part of dotbox.
# See https://github.com/curoky/dotbox for further info.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
set -xeuo pipefail

cuda_version=${1:-'11.4'}
driver_version=${2:-'470.42.01'}

function install_cuda() {
  chmod +x /tmp/cuda_linux.run
  /tmp/cuda_linux.run --silent --toolkit --override
  rm -f /tmp/cuda_linux.run
}
if [[ $cuda_version == "10.0.130" ]] && [[ $driver_version == "410.48" ]]; then
  curl -sSL -o /tmp/cuda_linux.run \
    https://developer.nvidia.com/compute/cuda/10.0/Prod/local_installers/cuda_10.0.130_410.48_linux
  # http://developer.download.nvidia.com/compute/cuda/10.0/Prod/patches/1/cuda_10.0.130.1_linux.run
  install_cuda
  rm -rf \
    /usr/local/cuda-10.0/NsightCompute-1.0 \
    /usr/local/cuda-10.0/doc \
    /usr/local/cuda-10.0/jre \
    /usr/local/cuda-10.0/samples \
    /usr/local/cuda-10.0/nsightee_plugins

elif [[ $cuda_version == "11.0.3" ]] && [[ $driver_version == "450.51.06" ]]; then
  curl -sSL -o /tmp/cuda_linux.run \
    https://developer.download.nvidia.com/compute/cuda/11.0.3/local_installers/cuda_11.0.3_450.51.06_linux.run
  install_cuda
  rm -rf \
    /usr/local/cuda-11.0/nsight-systems-2020.3.2 \
    /usr/local/cuda-11.0/nsight-systems-2020.3.2/host-linux-x64 \
    /usr/local/cuda-11.0/nsight-systems-2020.3.2/target-linux-armv8 \
    /usr/local/cuda-11.0/nsight-compute-2020.1.2 \
    /usr/local/cuda-11.0/nsight-compute-2020.1.2/target/linux-desktop-glibc_2_19_0-ppc64le \
    /usr/local/cuda-11.0/nsight-compute-2020.1.2/target/linux-desktop-t210-a64 \
    /usr/local/cuda-11.0/nsight-compute-2020.1.2/host \
    /usr/local/cuda-11.0/doc \
    /usr/local/cuda-11.0/libnvvp \
    /usr/local/cuda-11.0/nsightee_plugins \
    /usr/local/cuda-11.0/Sanitizer

elif [[ $cuda_version == "11.2.0" ]] && [[ $driver_version == "460.27.04" ]]; then
  curl -sSL -o /tmp/cuda_linux.run \
    https://developer.download.nvidia.com/compute/cuda/11.2.0/local_installers/cuda_11.2.0_460.27.04_linux.run
  install_cuda
  rm -rf \
    /usr/local/cuda-11.2/nsight-systems-2020.4.3 \
    /usr/local/cuda-11.2/nsight-systems-2020.4.3/host-linux-x64 \
    /usr/local/cuda-11.2/nsight-systems-2020.4.3/target-linux-armv8 \
    /usr/local/cuda-11.2/nsight-compute-2020.3.0 \
    /usr/local/cuda-11.2/doc \
    /usr/local/cuda-11.2/libnvvp \
    /usr/local/cuda-11.2/nsightee_plugins \
    /usr/local/cuda-11.2/Sanitizer

elif [[ $cuda_version == "11.4.0" ]] && [[ $driver_version == "470.42.01" ]]; then
  curl -sSL -o /tmp/cuda_linux.run \
    https://developer.download.nvidia.com/compute/cuda/11.4.0/local_installers/cuda_11.4.0_470.42.01_linux.run
  install_cuda
  rm -rf \
    /usr/local/cuda-11.4/nsight-systems-2021.2.4 \
    /usr/local/cuda-11.4/nsight-systems-2021.2.4/host-linux-x64 \
    /usr/local/cuda-11.4/nsight-systems-2021.2.4/target-linux-armv8 \
    /usr/local/cuda-11.4/nsight-compute-2021.2.0 \
    /usr/local/cuda-11.4/libnvvp \
    /usr/local/cuda-11.4/nsightee_plugins \
    /usr/local/cuda-11.4/compute-sanitizer

elif [[ $cuda_version == "11.4.4" ]] && [[ $driver_version == "470.82.01" ]]; then
  curl -sSL -o /tmp/cuda_linux.run \
    https://developer.download.nvidia.com/compute/cuda/11.4.4/local_installers/cuda_11.4.4_470.82.01_linux.run
  install_cuda
  rm -rf \
    /usr/local/cuda-11.4/nsight-systems-2021.3.2 \
    /usr/local/cuda-11.4/nsight-systems-2021.3.2/host-linux-x64 \
    /usr/local/cuda-11.4/nsight-systems-2021.3.2/target-linux-armv8 \
    /usr/local/cuda-11.4/nsight-compute-2021.2.2 \
    /usr/local/cuda-11.4/libnvvp \
    /usr/local/cuda-11.4/nsightee_plugins \
    /usr/local/cuda-11.4/compute-sanitizer

elif [[ $cuda_version == "12.3.2" ]] && [[ $driver_version == "545.23.08" ]]; then
  curl -sSL -o /tmp/cuda_linux.run \
    https://developer.download.nvidia.com/compute/cuda/12.3.2/local_installers/cuda_12.3.2_545.23.08_linux.run
  install_cuda
  rm -rf \
    /usr/local/cuda-12.3/nsight-systems-2023.3.3 \
    /usr/local/cuda-12.3/nsight-systems-2023.3.3/host-linux-x64 \
    /usr/local/cuda-12.3/nsight-compute-2023.3.1 \
    /usr/local/cuda-12.3/libnvvp \
    /usr/local/cuda-12.3/nsightee_plugins \
    /usr/local/cuda-12.3/compute-sanitizer

# elif [[ $version == "11.4-t" ]]; then
#   curl -sSL -o /tmp/cuda_linux.run \
#     https://us.download.nvidia.com/tesla/450.248.02/NVIDIA-Linux-x86_64-450.248.02.run
fi

# install cuda driver
# RUN curl -sSL -o nvidia_linux.run \
#      \
#   && chmod +x nvidia_linux.run \
#   && ./nvidia_linux.run --silent \
#     --no-kernel-module \
#   && rm -f nvidia_linux.run

# install nvidia
# RUN curl -fsSL https://developer.download.nvidia.com/compute/cuda/repos/ubuntu2204/x86_64/3bf863cc.pub | apt-key add - \
#   && echo "deb https://developer.download.nvidia.com/compute/cuda/repos/ubuntu2204/x86_64 /" > /etc/apt/sources.list.d/cuda.list \
#   && apt-get update \
#   cuda-cudart-11-8 cuda-compat-11-8
#   && apt-get install -y --no-install-recommends cuda-11-8
