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

# $(readlink -f
conf_path=${1:-/data/share/dotbox/images/base/conan/pip}
echo "use conf_path=$conf_path"

function create_conda_env() {
  local env_name=$1
  local py_version=$2
  echo "create $env_name($py_version)"
  /o/conda/bin/conda env remove -y -n $env_name
  /o/conda/bin/conda create -n $env_name python=$py_version --yes
  /o/conda/envs/$env_name/bin/pip install --no-cache-dir -r $conf_path/requirements-${env_name}.txt
}

function insert_tf_ldpath() {
  local env_name=$1
  local py_version=$2
  # echo "export LD_LIBRARY_PATH=/o/conda/envs/ml/lib/:/nix/var/nix/profiles/cuda11_8/lib:/o/conda/envs/ml/lib/python3.11/site-packages/nvidia/cudnn/lib:$LD_LIBRARY_PATH" >> /o/conda/envs/$env_name/etc/conda/activate.d/env_vars.sh
  mkdir -p /o/conda/envs/$env_name/etc/conda/activate.d
  echo "export LD_LIBRARY_PATH=/o/conda/envs/$env_name/lib/python$py_version/site-packages/nvidia/cudnn/lib:/nix/var/nix/profiles/cuda11_4/lib:\$LD_LIBRARY_PATH" >>/o/conda/envs/$env_name/etc/conda/activate.d/env_vars.sh
}

create_conda_env py2 '2'
create_conda_env py3 '3.11'
# create_conda_env tf1.15 '3.7'
# insert_tf_ldpath tf1.15 '3.7'
# create_conda_env tf2.5 '3.8'
# insert_tf_ldpath tf2.5 '3.8'
# create_conda_env tf2.9.2 '3.10'
# insert_tf_ldpath tf2.9.2 '3.10'
create_conda_env tf2.15 '3.11'
insert_tf_ldpath tf2.15 '3.11'

/o/conda/bin/conda clean --all -y
