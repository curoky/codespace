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

BASE_IMAGE=$1

if [[ $BASE_IMAGE == "debian:10" ]]; then
  sed -i 's/deb.debian.org/archive.debian.org/g' /etc/apt/sources.list
  # sed -i 's/deb.debian.org/archive.debian.org/g' /etc/apt/sources.list.d/backports.list
  sed -i 's/security.debian.org/archive.debian.org/g' /etc/apt/sources.list
  sed -i '/stretch-updates/d' /etc/apt/sources.list
  apt-get update -y
fi
