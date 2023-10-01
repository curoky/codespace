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

curl -sSL -o nsightsystems_linux.run \
  https://developer.nvidia.com/downloads/assets/tools/secure/nsight-systems/2024_1/nsightsystems-linux-public-2024.1.1.59-3380207.run
# https://developer.nvidia.com/downloads/assets/tools/secure/nsight-systems/2023_2/nsightsystems-linux-public-2023.2.1.122-3259852.run
chmod +x nsightsystems_linux.run
./nsightsystems_linux.run --accept -- -targetpath=/opt/nvidia/ns -noprompt
rm -rf nsightsystems_linux.run

# mkdir /opt/nvns
# curl -sSL https://developer.download.nvidia.com/compute/cuda/redist/nsight_systems/linux-x86_64/nsight_systems-linux-x86_64-2023.1.2.43-archive.tar.xz \
#   | tar -xv --xz -C /opt/nvns --strip-components 1
