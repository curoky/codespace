#!/usr/bin/env bash
# Copyright (c) 2018-2022 curoky(cccuroky@gmail.com).
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
set -xeu

if [[ ! -d $PWD/.git ]]; then
  echo "must run in git root path"
  exit 1
fi

GitURL=$(git ls-remote --get-url | sed -e 's|git@github.com:|https://github.com/|' -e 's|\.git||')
FirstCommitYear=$(git log --reverse --date="format:%Y" --format="format:%ad" | head -n 1)
CurrentYear=$(date +'%Y')

licenseheaders \
  --tmpl=$HOME/dotbox/config/licenseheaders/apache-2.tmpl \
  --owner='curoky(cccuroky@gmail.com)' \
  --projname=$(basename "$PWD") \
  --projurl=$GitURL \
  --settings=$HOME/dotbox/config/licenseheaders/license-settings.json \
  --exclude '*.yaml' '.md' \
  --years="$FirstCommitYear-$CurrentYear"
