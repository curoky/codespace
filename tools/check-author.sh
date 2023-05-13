#!/usr/bin/env bash
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
set -euo pipefail

# expected_author_name=${1:-unknown}
# expected_author_email=${2:-unknown}
expected_author_name='unset'
expected_author_email='unset'

# get args from cmdline with getopt, --name and --email
# if not provided, use default values
while getopts ":n:e:" opt; do
  case $opt in
    n)
      expected_author_name=$OPTARG
      ;;
    e)
      expected_author_email=$OPTARG
      ;;
    \?)
      echo "Invalid option: -$OPTARG" >&2
      exit 1
      ;;
  esac
done

if [[ $expected_author_name != "unset" ]] && [[ $expected_author_name != "$GIT_AUTHOR_NAME" ]]; then
  echo "Expected author name to be '$expected_author_name', but was '$GIT_AUTHOR_NAME'"
  exit 1
fi

if [[ $expected_author_email != "unset" ]] && [[ $expected_author_email != "$GIT_AUTHOR_EMAIL" ]]; then
  echo "Expected author email to be '$expected_author_email', but was '$GIT_AUTHOR_EMAIL'"
  exit 1
fi
