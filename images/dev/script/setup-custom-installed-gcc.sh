#!/usr/bin/env bash
set -xeuo pipefail

version=${1:-15.1.0}

find /opt/gcc/gcc-${version}/bin/ -type f -exec ln -sf {} /usr/bin \;
find /opt/binutils/bin/ -type f -exec ln -sf {} /usr/bin \;

echo "/opt/gcc/gcc-${version}/lib64" >>/etc/ld.so.conf.d/000-gcc.conf
ldconfig -v
