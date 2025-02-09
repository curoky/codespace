#!/usr/bin/env bash

set -xeuo pipefail

abi_version=$1

sed -i -e "s|third_party/gpus/cuda/include/||g" \
  /opt/conda/envs/tf2.5-abi${abi_version}/lib/python3.7/site-packages/tensorflow/include/tensorflow/core/util/gpu_kernel_helper.h \
  /opt/conda/envs/tf2.5-abi${abi_version}/lib/python3.7/site-packages/tensorflow/include/tensorflow/core/util/gpu_device_functions.h
