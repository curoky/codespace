#!/command/with-contenv bash
set -xeuo pipefail

echo "SSHD_PORT: $SSHD_PORT"

sed -i -e "s/Port 61000/Port ${SSHD_PORT}/g" \
  /opt/devspace/dotfiles/sshd/sshd_config.conf

chmod 600 /opt/devspace/dotfiles/sshd/host-key/*

mkdir -p /var/log
# https://github.com/un-def/openssh-static-build/blob/master/run-sshd.sh#L30
exec /opt/sbt/store/openssh_gssapi/bin/sshd -D \
  -f /opt/devspace/dotfiles/sshd/sshd_config.conf -e
# -E /var/log/mysshd.log
