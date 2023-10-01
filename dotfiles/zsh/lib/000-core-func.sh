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
function source_if_exists() {
  local target=${1}
  [[ -s ${target} ]] && source ${target}
}

function mkdir_if_not_exists() {
  if [[ ! -d $1 ]]; then
    mkdir -p $1
  fi
}

function PATH_REMOVE() {
  local DIR=$1
  export PATH=$(echo -n $PATH | awk -v RS=: -v ORS=: '$0 != "'$DIR'"' | sed 's/:$//')
}

function PATH_REMOVE_CONTAIN() {
  local DIR=$1
  export PATH=$(echo ${PATH} | awk -v RS=: -v ORS=: '/'$DIR'/ {next} {print}' | sed 's/:*$//')
}

function PATH_PUSH_FRONT() {
  local DIR=$1
  [ -d "${DIR}" ] && export PATH=${DIR}:$PATH #|| echo "${DIR} does not exist"
}

function PATH_PUSH_BACK() {
  local DIR=$1
  [ -d "${DIR}" ] && export PATH=$PATH:${DIR} #|| echo "${DIR} does not exist"
}

function FPATH_PUSH_FRONT() {
  local DIR=$1
  [ -d "${DIR}" ] && fpath=(${DIR} $fpath) #|| echo "${DIR} does not exist"
}
