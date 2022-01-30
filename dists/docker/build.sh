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
cd "$(dirname $0)" || exit 1

base_image=${1:-'ubuntu23.10'} #debian9

# --cache-to=type=inline \
# --cache-from=type=registry,ref=curoky/dotbox:${base_image} \
docker buildx build ../.. --network=host --file Dockerfile "${@:2}" \
  --build-arg="BASE_IMAGE=${base_image}" \
  --tag curoky/dotbox:${base_image}
# --output type=local,dest=$PWD/temp
