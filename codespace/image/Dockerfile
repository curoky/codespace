# Reference development image for the codespace scheme.
# Satisfies the minimal container contract in codespace/DESIGN.md §3:
#   1. sshd listens on container port 22 (public-key auth, no passwords).
#   2. A non-root login user `dev` with a writable home and ~/.ssh.
#   3. A `/workspace` mount point writable by `dev`.
#   4. git and an ssh client available.
# The image is intentionally generic: it contains NO codespace-specific
# scripts or hooks (the agent injects keys at runtime via `podman exec`).

FROM docker.io/debian:12-slim

ENV DEBIAN_FRONTEND=noninteractive

# Install openssh-server/client, git and supporting packages, create the
# `dev` user with passwordless sudo, generate sshd host keys, harden the
# sshd config and prepare the /workspace mount point and ~/.ssh directory.
RUN apt-get update \
  && apt-get install -y --no-install-recommends \
    openssh-server \
    openssh-client \
    git \
    ca-certificates \
    sudo \
  && rm -rf /var/lib/apt/lists/* \
  # non-root login user with a writable home
  && useradd -m -s /bin/bash dev \
  # passwordless sudo for convenient development
  && echo 'dev ALL=(ALL) NOPASSWD:ALL' > /etc/sudoers.d/dev \
  && chmod 0440 /etc/sudoers.d/dev \
  # sshd runtime dir + host keys (generated at build time)
  && mkdir -p /run/sshd \
  && ssh-keygen -A \
  # workspace mount point, owned by dev (agent re-chowns after bind mount)
  && mkdir -p /workspace \
  && chown dev:dev /workspace \
  # pre-create ~/.ssh so key injection is robust
  && mkdir -p /home/dev/.ssh \
  && chown -R dev:dev /home/dev/.ssh \
  && chmod 700 /home/dev/.ssh

# Public-key only sshd hardening. Drop-in overrides the shipped defaults.
RUN printf '%s\n' \
    'Port 22' \
    'PubkeyAuthentication yes' \
    'PasswordAuthentication no' \
    'PermitRootLogin no' \
    'ChallengeResponseAuthentication no' \
    'UsePAM yes' \
    > /etc/ssh/sshd_config.d/codespace.conf

EXPOSE 22

# Run sshd in the foreground as the container's main process.
CMD ["/usr/sbin/sshd", "-D", "-e"]
