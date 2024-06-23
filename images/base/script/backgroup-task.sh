#!/usr/bin/env bash
set -xeuo pipefail
export PATH=$PATH:/opt/rust/cargo/bin:/opt/sbt/bin

/opt/devspace/images/base/stage/uv/conda/install.sh py3
