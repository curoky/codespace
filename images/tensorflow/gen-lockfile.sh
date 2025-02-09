#!/usr/bin/env bash

setup-conda-env.sh -e ./config/conda/tf2.5-cu11.4.0-abi0.yaml -d
setup-conda-env.sh -e ./config/conda/tf2.5-cu11.4.0-abi1.yaml -d
setup-conda-env.sh -e ./config/conda/tf2.5-cu11.4.4-abi0.yaml -d
setup-conda-env.sh -e ./config/conda/tf2.5-cu11.4.4-abi1.yaml -d
setup-conda-env.sh -e ./config/conda/tf2.16-clang.yaml -d
setup-conda-env.sh -e ./config/conda/tf2.16-gcc.yaml -d
setup-conda-env.sh -e ./config/conda/tf2.17.yaml -d
setup-conda-env.sh -e ./config/conda/tf2.18.yaml -d
