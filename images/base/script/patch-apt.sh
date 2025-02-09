#!/usr/bin/env bash
set -xeuo pipefail

BASE_IMAGE=$1

if [[ $BASE_IMAGE == "debian:10" ]]; then
  sed -i 's/deb.debian.org/archive.debian.org/g' /etc/apt/sources.list
  # sed -i 's/deb.debian.org/archive.debian.org/g' /etc/apt/sources.list.d/backports.list
  sed -i 's/security.debian.org/archive.debian.org/g' /etc/apt/sources.list
  sed -i '/stretch-updates/d' /etc/apt/sources.list
  apt-get update -y
fi
