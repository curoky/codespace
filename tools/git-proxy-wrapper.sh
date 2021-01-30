#!/usr/bin/env bash
# Copyright 2021 curoky(cccuroky@gmail.com).
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

# Ref:
# - https://segmentfault.com/q/1010000000118837
# - https://stackoverflow.com/questions/19161960/connect-with-ssh-through-a-proxy

set -euo pipefail

export PATH=/home/linuxbrew/.linuxbrew/bin:$HOME/.linuxbrew/bin:$PATH

echo "use ssh proxy on $_SSH_PROXY" >&2
# ssh -o ProxyCommand="connect -S $_HTTP_PROXY %h %p" "$@"
ssh -o ProxyCommand="ssh -W %h:%p $_SSH_PROXY" "$@"
