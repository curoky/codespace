#!/usr/bin/env bash

set -xeuo pipefail

cuda_version=${1:-}
cuda_short_version="$(echo $cuda_version | cut -d '.' -f 1)"
cudnn_version=${2:-'8.9.7.29'}
cudnn_short_version="$(echo $cudnn_version | cut -d '.' -f 1,2,3)"
install_path=${3:-/opt/nvidia/cudnn${cudnn_short_version}-cu${cuda_short_version}}

echo "cuda_version: $cuda_version"
echo "cuda_short_version: $cuda_short_version"
echo "cudnn_version: $cudnn_version"
echo "cudnn_short_version: $cudnn_short_version"
echo "install_path: $install_path"

mkdir -p $install_path
echo "Installing cudnn $cudnn_version" >$install_path/version.txt

if [[ $cudnn_version == 8.1.0.77 ]] && [[ $cuda_short_version == 11 ]]; then
  curl -sSL https://developer.download.nvidia.com/compute/redist/cudnn/v8.1.0/cudnn-11.2-linux-x64-v8.1.0.77.tgz |
    tar -xv --gzip -C $install_path --strip-components 1
elif [[ $cudnn_version == 8.9.7.29 ]] && [[ $cuda_short_version == 11 ]]; then
  curl -sSL https://developer.download.nvidia.com/compute/cudnn/redist/cudnn/linux-x86_64/cudnn-linux-x86_64-8.9.7.29_cuda11-archive.tar.xz |
    tar -xv --xz -C $install_path --strip-components 1
elif [[ $cudnn_version == 8.9.2.26 ]] && [[ $cuda_short_version == 12 ]]; then
  curl -sSL https://developer.download.nvidia.com/compute/cudnn/redist/cudnn/linux-x86_64/cudnn-linux-x86_64-8.9.2.26_cuda12-archive.tar.xz |
    tar -xv --xz -C $install_path --strip-components 1
elif [[ $cudnn_version == 8.9.7.29 ]] && [[ $cuda_short_version == 12 ]]; then
  curl -sSL https://developer.download.nvidia.com/compute/cudnn/redist/cudnn/linux-x86_64/cudnn-linux-x86_64-8.9.7.29_cuda12-archive.tar.xz |
    tar -xv --xz -C $install_path --strip-components 1
fi
