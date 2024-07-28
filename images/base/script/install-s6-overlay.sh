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
export PATH=$PATH:/opt/sbt/bin

cd /tmp
wget https://github.com/just-containers/s6-overlay/releases/download/v3.2.2.0/s6-overlay-x86_64.tar.xz
wget https://github.com/just-containers/s6-overlay/releases/download/v3.2.2.0/s6-overlay-noarch.tar.xz

mkdir -p /opt/s6-overlay
tar -xf s6-overlay-x86_64.tar.xz -C /opt/s6-overlay
tar -xf s6-overlay-noarch.tar.xz -C /opt/s6-overlay

for f in $(find /opt/s6-overlay -type f); do
  if file --brief "$f" | grep -q 'text'; then
    sed -e 's|/package|/opt/s6-overlay/package|g' -i"" "$f" || true
    sed -e 's|/command|/opt/s6-overlay/command|g' -i"" "$f" || true
  fi
done

sed -e 's|bin/sh -e|bin/bash -xe|g' -i"" /opt/s6-overlay/package/admin/s6-overlay-3.2.2.0/libexec/stage0
sudo ln -sf /opt/s6-overlay/package /package
# sed -e 's|exec|exec execlineb|g' -i"" /opt/s6-overlay/package/admin/s6-overlay-3.2.2.0/libexec/stage0

rm -rf s6-overlay-x86_64.tar.xz s6-overlay-noarch.tar.xz
