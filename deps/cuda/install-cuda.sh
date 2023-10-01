#!/usr/bin/env bash
# Copyright (c) 2018-2025 curoky(cccuroky@gmail.com).
#
# This file is part of devspace.
# See https://github.com/curoky/devspace for further info.
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

cuda_version=${1:-'11.4.0'}
driver_version=${2:-'470.42.01'}

function install_cuda() {
  local toolkitpath=$1
  mkdir -p $toolkitpath
  chmod +x /tmp/cuda_linux.run
  /tmp/cuda_linux.run --silent --toolkit --override --toolkitpath=$toolkitpath
  rm -f /tmp/cuda_linux.run
}
if [[ $cuda_version == "10.0.130" ]] && [[ $driver_version == "410.48" ]]; then
  curl -sSL -o /tmp/cuda_linux.run \
    https://developer.nvidia.com/compute/cuda/10.0/Prod/local_installers/cuda_10.0.130_410.48_linux
  # http://developer.download.nvidia.com/compute/cuda/10.0/Prod/patches/1/cuda_10.0.130.1_linux.run
  install_cuda /opt/nvidia/cuda-10.0.130
  rm -rf \
    /opt/nvidia/cuda-10.0.130/NsightCompute-1.0 \
    /opt/nvidia/cuda-10.0.130/doc \
    /opt/nvidia/cuda-10.0.130/jre \
    /opt/nvidia/cuda-10.0.130/samples \
    /opt/nvidia/cuda-10.0.130/nsightee_plugins

elif [[ $cuda_version == "11.0.3" ]] && [[ $driver_version == "450.51.06" ]]; then
  curl -sSL -o /tmp/cuda_linux.run \
    https://developer.download.nvidia.com/compute/cuda/11.0.3/local_installers/cuda_11.0.3_450.51.06_linux.run
  install_cuda /opt/nvidia/cuda-11.0.3
  rm -rf \
    /opt/nvidia/cuda-11.0.3/nsight-systems-2020.3.2 \
    /opt/nvidia/cuda-11.0.3/nsight-systems-2020.3.2/host-linux-x64 \
    /opt/nvidia/cuda-11.0.3/nsight-systems-2020.3.2/target-linux-armv8 \
    /opt/nvidia/cuda-11.0.3/nsight-compute-2020.1.2 \
    /opt/nvidia/cuda-11.0.3/nsight-compute-2020.1.2/target/linux-desktop-glibc_2_19_0-ppc64le \
    /opt/nvidia/cuda-11.0.3/nsight-compute-2020.1.2/target/linux-desktop-t210-a64 \
    /opt/nvidia/cuda-11.0.3/nsight-compute-2020.1.2/host \
    /opt/nvidia/cuda-11.0.3/doc \
    /opt/nvidia/cuda-11.0.3/libnvvp \
    /opt/nvidia/cuda-11.0.3/nsightee_plugins \
    /opt/nvidia/cuda-11.0.3/Sanitizer

elif [[ $cuda_version == "11.2.0" ]] && [[ $driver_version == "460.27.04" ]]; then
  curl -sSL -o /tmp/cuda_linux.run \
    https://developer.download.nvidia.com/compute/cuda/11.2.0/local_installers/cuda_11.2.0_460.27.04_linux.run
  install_cuda /opt/nvidia/cuda-11.2.0
  rm -rf \
    /opt/nvidia/cuda-11.2.0/nsight-systems-2020.4.3 \
    /opt/nvidia/cuda-11.2.0/nsight-systems-2020.4.3/host-linux-x64 \
    /opt/nvidia/cuda-11.2.0/nsight-systems-2020.4.3/target-linux-armv8 \
    /opt/nvidia/cuda-11.2.0/nsight-compute-2020.3.0 \
    /opt/nvidia/cuda-11.2.0/doc \
    /opt/nvidia/cuda-11.2.0/libnvvp \
    /opt/nvidia/cuda-11.2.0/nsightee_plugins \
    /opt/nvidia/cuda-11.2.0/Sanitizer

elif [[ $cuda_version == "11.4.0" ]] && [[ $driver_version == "470.42.01" ]]; then
  curl -sSL -o /tmp/cuda_linux.run \
    https://developer.download.nvidia.com/compute/cuda/11.4.0/local_installers/cuda_11.4.0_470.42.01_linux.run
  install_cuda /opt/nvidia/cuda-11.4.0
  rm -rf \
    /opt/nvidia/cuda-11.4.0/nsight-systems-2021.2.4 \
    /opt/nvidia/cuda-11.4.0/nsight-systems-2021.2.4/host-linux-x64 \
    /opt/nvidia/cuda-11.4.0/nsight-systems-2021.2.4/target-linux-armv8 \
    /opt/nvidia/cuda-11.4.0/nsight-compute-2021.2.0 \
    /opt/nvidia/cuda-11.4.0/libnvvp \
    /opt/nvidia/cuda-11.4.0/nsightee_plugins \
    /opt/nvidia/cuda-11.4.0/compute-sanitizer

elif [[ $cuda_version == "11.4.4" ]] && [[ $driver_version == "470.82.01" ]]; then
  curl -sSL -o /tmp/cuda_linux.run \
    https://developer.download.nvidia.com/compute/cuda/11.4.4/local_installers/cuda_11.4.4_470.82.01_linux.run
  install_cuda /opt/nvidia/cuda-11.4.4
  rm -rf \
    /opt/nvidia/cuda-11.4.4/nsight-systems-2021.3.2 \
    /opt/nvidia/cuda-11.4.4/nsight-systems-2021.3.2/host-linux-x64 \
    /opt/nvidia/cuda-11.4.4/nsight-systems-2021.3.2/target-linux-armv8 \
    /opt/nvidia/cuda-11.4.4/nsight-compute-2021.2.2 \
    /opt/nvidia/cuda-11.4.4/libnvvp \
    /opt/nvidia/cuda-11.4.4/nsightee_plugins \
    /opt/nvidia/cuda-11.4.4/compute-sanitizer

elif [[ $cuda_version == "12.3.2" ]] && [[ $driver_version == "545.23.08" ]]; then
  curl -sSL -o /tmp/cuda_linux.run \
    https://developer.download.nvidia.com/compute/cuda/12.3.2/local_installers/cuda_12.3.2_545.23.08_linux.run
  install_cuda /opt/nvidia/cuda-12.3.2
  rm -rf \
    /opt/nvidia/cuda-12.3.2/nsight-systems-2023.3.3 \
    /opt/nvidia/cuda-12.3.2/nsight-systems-2023.3.3/host-linux-x64 \
    /opt/nvidia/cuda-12.3.2/nsight-compute-2023.3.1 \
    /opt/nvidia/cuda-12.3.2/libnvvp \
    /opt/nvidia/cuda-12.3.2/nsightee_plugins \
    /opt/nvidia/cuda-12.3.2/compute-sanitizer

elif [[ $cuda_version == "12.4.0" ]] && [[ $driver_version == "550.54.14" ]]; then
  curl -sSL -o /tmp/cuda_linux.run \
    https://developer.download.nvidia.com/compute/cuda/12.4.0/local_installers/cuda_12.4.0_550.54.14_linux.run
  install_cuda /opt/nvidia/cuda-12.4.0
  rm -rf \
    /opt/nvidia/cuda-12.4.0/nsight-systems-2023.4.4 \
    /opt/nvidia/cuda-12.4.0/nsight-systems-2023.4.4/host-linux-x64 \
    /opt/nvidia/cuda-12.4.0/nsight-compute-2024.1.0 \
    /opt/nvidia/cuda-12.4.0/libnvvp \
    /opt/nvidia/cuda-12.4.0/nsightee_plugins \
    /opt/nvidia/cuda-12.4.0/compute-sanitizer

elif [[ $cuda_version == "12.4.1" ]] && [[ $driver_version == "550.54.15" ]]; then
  curl -sSL -o /tmp/cuda_linux.run \
    https://developer.download.nvidia.com/compute/cuda/12.4.1/local_installers/cuda_12.4.1_550.54.15_linux.run
  install_cuda /opt/nvidia/cuda-12.4.1
  rm -rf \
    /opt/nvidia/cuda-12.4.1/nsight-systems-2023.4.4 \
    /opt/nvidia/cuda-12.4.1/nsight-systems-2023.4.4/host-linux-x64 \
    /opt/nvidia/cuda-12.4.1/nsight-compute-2024.4.1 \
    /opt/nvidia/cuda-12.4.1/libnvvp \
    /opt/nvidia/cuda-12.4.1/nsightee_plugins \
    /opt/nvidia/cuda-12.4.1/compute-sanitizer

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
