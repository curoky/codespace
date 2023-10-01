#!/usr/bin/env bash
set -xeuo pipefail

find /opt/gcc/gcc-14.2.0/bin/ -type f -exec ln -sf {} /usr/bin \;
find /opt/binutils/bin/ -type f -exec ln -sf {} /usr/bin \;

echo '/opt/gcc/gcc-14.2.0/lib64' >>/etc/ld.so.conf.d/000-gcc14.conf
ldconfig -v
