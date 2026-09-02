#!/usr/bin/env bash
set -xeuo pipefail

if [[ $# -ne 1 ]]; then
  echo "usage: configure-apt.sh <base-image>" >&2
  exit 2
fi

base_image=$1

if [[ $base_image == "debian:10" ]]; then
  sed -i 's/deb.debian.org/archive.debian.org/g' /etc/apt/sources.list
  sed -i 's/security.debian.org/archive.debian.org/g' /etc/apt/sources.list
  sed -i '/stretch-updates/d' /etc/apt/sources.list
  apt-get update -y
fi
