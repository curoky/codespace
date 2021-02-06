#!/usr/bin/env bash
# Copyright 2019 curoky(cccuroky@gmail.com).
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
cd "$(dirname $0)" || exit 1

cp ../config.yaml config.yaml
cp -r ../config config

docker buildx build . --network=host --file Dockerfile.v2 "${@:1}" \
  --cache-to=type=inline \
  --cache-from=type=registry,ref=curoky/dotbox:ubuntu22.04 \
  --tag curoky/dotbox:ubuntu22.04
# --output type=local,dest=$PWD/temp
