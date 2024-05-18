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

# remove user ubuntu
userdel ubuntu -r || echo "ignore userdel failed"

# update user root
echo "root:123456" | chpasswd

# add user x
useradd --create-home --uid 5230 --user-group x
echo "x:123456" | chpasswd
usermod -aG sudo x
echo "x ALL=(ALL:ALL) NOPASSWD:ALL" >>/etc/sudoers.d/nopasswd_user
