#!/usr/bin/env bash
set -xeuo pipefail

find /home/x/app/gcc/gcc-14.2.0/bin/ -type f -exec ln -sf {} /usr/bin \;
find /home/x/app/binutils/bin/ -type f -exec ln -sf {} /usr/bin \;

echo '/home/x/app/gcc/gcc-14.2.0/lib64' >>/etc/ld.so.conf.d/000-gcc14.conf
ldconfig -v
