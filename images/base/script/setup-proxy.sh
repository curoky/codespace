#!/usr/bin/env bash
set -xeuo pipefail

function write_proxy() {
  echo "export http_proxy=$1" >>$2
  echo "export HTTP_PROXY=$1" >>$2
  echo "export https_proxy=$1" >>$2
  echo "export HTTPS_PROXY=$1" >>$2
  echo "export all_proxy=$1" >>$2
  echo "export ALL_PROXY=$1" >>$2
  echo "export no_proxy=localhost,127.0.0.1" >>$2
  echo "export NO_PROXY=localhost,127.0.0.1" >>$2
}

if [[ -f /var/run/s6/container_environment/HTTP_PROXY ]]; then
  HTTP_PROXY=$(cat /var/run/s6/container_environment/HTTP_PROXY)
  write_proxy $HTTP_PROXY /etc/environment
  write_proxy $HTTP_PROXY /etc/profile
  write_proxy $HTTP_PROXY /etc/bash.bashrc
  write_proxy $HTTP_PROXY /etc/zshenv
fi
