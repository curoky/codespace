#!/usr/bin/bash
# Copyright (c) 2018-2025 curoky(cccuroky@gmail.com).
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

docker pull curoky/dotbox:tabby
docker tag curoky/dotbox:tabby tabbyml/tabby
docker rmi curoky/dotbox:tabby
docker rm --force tabbyd
mkdir -p $HOME/tabby/data
# --chat-model Qwen2.5-Coder-32B-Instruct
docker run -d --network=host --gpus all \
  -v $HOME/tabby/data:/data \
  --name tabbyd tabbyml/tabby \
  serve --no-webserver --model Qwen2.5-Coder-14B --device cuda --port 5847 --host ::
