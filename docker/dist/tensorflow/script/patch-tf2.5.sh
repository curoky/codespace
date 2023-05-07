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

abi_version=$1

sed -i -e "s|third_party/gpus/cuda/include/||g" \
  /home/x/app/conda/envs/tf2.5-abi${abi_version}/lib/python3.7/site-packages/tensorflow/include/tensorflow/core/util/gpu_kernel_helper.h \
  /home/x/app/conda/envs/tf2.5-abi${abi_version}/lib/python3.7/site-packages/tensorflow/include/tensorflow/core/util/gpu_device_functions.h
