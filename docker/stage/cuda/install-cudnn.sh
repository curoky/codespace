#!/usr/bin/env bash
# Copyright (c) 2018-2024 curoky(cccuroky@gmail.com).
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

cudnn_version=${1-'8.9.7.29_cuda11'}
cudnn_short_version="$(echo $cudnn_version | cut -d '.' -f 1,2)-cu$(echo $cudnn_version | grep -oP '\d\d$')" # cudnn8.9-cu12
install_path=${2:-/home/x/app/nvidia/cudnn${cudnn_short_version}}

mkdir -p $install_path
echo "Installing cudnn $cudnn_version" >$install_path/version.txt
if [[ $cudnn_version == 8.1.0.77_cuda11* ]]; then
  curl -sSL https://developer.download.nvidia.com/compute/redist/cudnn/v8.1.0/cudnn-11.2-linux-x64-v8.1.0.77.tgz |
    tar -xv --gzip -C $install_path --strip-components 1
elif [[ $cudnn_version == 8.9.7.29_cuda11* ]]; then
  curl -sSL https://developer.download.nvidia.com/compute/cudnn/redist/cudnn/linux-x86_64/cudnn-linux-x86_64-8.9.7.29_cuda11-archive.tar.xz |
    tar -xv --xz -C $install_path --strip-components 1
elif [[ $cudnn_version == 8.9.7.29_cuda12* ]]; then
  curl -sSL https://developer.download.nvidia.com/compute/cudnn/redist/cudnn/linux-x86_64/cudnn-linux-x86_64-8.9.7.29_cuda12-archive.tar.xz |
    tar -xv --xz -C $install_path --strip-components 1
fi
