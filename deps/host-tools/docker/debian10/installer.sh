#!/usr/bin/env bash
set -xeuo pipefail

enable_gpu=${1:-0}

packages=(docker-ce docker-ce-cli containerd.io
  docker-buildx-plugin docker-compose-plugin
  nvidia-container-toolkit
  nvidia-container-toolkit-base
  libnvidia-container-tools
  libnvidia-container1
)

for package in "${packages[@]}"; do
  apt-get remove -y "$package" || true
done

apt-get update -y
# apt-get install -y iptables

# dpkg: warning: downgrading containerd.io from 1.6.33-1 to 1.6.22-1
# dpkg: warning: downgrading docker-ce from 5:26.1.4-1~debian.10~buster to 5:24.0.5-1~debian.11~bullseye
# dpkg: warning: downgrading docker-ce-cli from 5:26.1.4-1~debian.10~buster to 5:24.0.5-1~debian.11~bullseye
# dpkg: warning: downgrading docker-compose-plugin from 2.27.1-1~debian.10~buster to 2.20.2-1~debian.11~bullseye

urls=(
  https://ftp.debian.org/debian/pool/main/libs/libseccomp/libseccomp2_2.6.0-2_amd64.deb

  # https://download.docker.com/linux/debian/dists/bullseye/pool/stable/amd64/
  # https://download.docker.com/linux/debian/dists/bullseye/pool/stable/amd64/containerd.io_1.6.22-1_amd64.deb
  # https://download.docker.com/linux/debian/dists/bullseye/pool/stable/amd64/docker-ce-cli_24.0.5-1~debian.11~bullseye_amd64.deb
  # https://download.docker.com/linux/debian/dists/bullseye/pool/stable/amd64/docker-ce_24.0.5-1~debian.11~bullseye_amd64.deb
  # https://download.docker.com/linux/debian/dists/bullseye/pool/stable/amd64/docker-buildx-plugin_0.16.2-1~debian.11~bullseye_amd64.deb
  # https://download.docker.com/linux/debian/dists/bullseye/pool/stable/amd64/docker-compose-plugin_2.20.2-1~debian.11~bullseye_amd64.deb

  https://download.docker.com/linux/debian/dists/bullseye/pool/stable/amd64/containerd.io_1.7.27-1_amd64.deb
  https://download.docker.com/linux/debian/dists/bullseye/pool/stable/amd64/docker-ce-cli_28.0.4-1~debian.11~bullseye_amd64.deb
  https://download.docker.com/linux/debian/dists/bullseye/pool/stable/amd64/docker-ce_28.0.4-1~debian.11~bullseye_amd64.deb
  https://download.docker.com/linux/debian/dists/bullseye/pool/stable/amd64/docker-buildx-plugin_0.22.0-1~debian.11~bullseye_amd64.deb
  https://download.docker.com/linux/debian/dists/bullseye/pool/stable/amd64/docker-compose-plugin_2.29.7-1~debian.11~bullseye_amd64.deb

  # https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html
  # https://github.com/NVIDIA/libnvidia-container/raw/gh-pages/stable/debian10/amd64/libnvidia-container1_1.13.5-1_amd64.deb
  # https://github.com/NVIDIA/libnvidia-container/raw/gh-pages/stable/debian10/amd64/libnvidia-container-tools_1.13.5-1_amd64.deb
  # https://github.com/NVIDIA/libnvidia-container/raw/gh-pages/stable/debian10/amd64/nvidia-container-toolkit-base_1.13.5-1_amd64.deb
  # https://github.com/NVIDIA/libnvidia-container/raw/gh-pages/stable/debian10/amd64/nvidia-container-toolkit_1.13.5-1_amd64.deb

  https://github.com/NVIDIA/libnvidia-container/raw/gh-pages/stable/deb/amd64/libnvidia-container1_1.17.5-1_amd64.deb
  https://github.com/NVIDIA/libnvidia-container/raw/gh-pages/stable/deb/amd64/libnvidia-container-tools_1.17.5-1_amd64.deb
  https://github.com/NVIDIA/libnvidia-container/raw/gh-pages/stable/deb/amd64/nvidia-container-toolkit-base_1.17.5-1_amd64.deb
  https://github.com/NVIDIA/libnvidia-container/raw/gh-pages/stable/deb/amd64/nvidia-container-toolkit_1.17.5-1_amd64.deb
)

dpkg_command="dpkg -i"

for url in "${urls[@]}"; do
  filename=$(basename "$url")
  dpkg_command="$dpkg_command ./$filename"
done

eval "$dpkg_command"

systemctl daemon-reload
systemctl restart docker

# Post stage for docker

# usermod -aG docker $USER

# cat /etc/docker/daemon.json
# {
#     "data-root": "/data00/docker",
#     "runtimes": {
#         "nvidia": {
#             "path": "nvidia-container-runtime",
#             "runtimeArgs": []
#         }
#     }
# }

# docker run --rm --runtime=nvidia --gpus all ubuntu nvidia-smi
