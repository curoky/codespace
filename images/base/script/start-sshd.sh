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

SSHD_PORT=${1:-61000}

sed -i -e "s/Port 61000/Port ${SSHD_PORT}/g" \
  /opt/devspace/dotfiles/sshd/sshd_config.conf

chmod 600 /opt/devspace/dotfiles/sshd/host-key/*

mkdir -p /var/log
# https://github.com/un-def/openssh-static-build/blob/master/run-sshd.sh#L30
/opt/tools/store/openssh_gssapi/bin/sshd \
  -f /opt/devspace/dotfiles/sshd/sshd_config.conf -e
# -E /var/log/mysshd.log
