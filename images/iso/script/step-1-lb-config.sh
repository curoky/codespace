#!/usr/bin/env bash
set -xeuo pipefail

lb clean --purge
lb config \
  --architectures arm64 \
  --bootloader grub-efi \
  --bootstrap-qemu-arch arm64 \
  --bootstrap-qemu-static /usr/bin/qemu-aarch64-static \
  --bootappend-live "boot=live components locales=en_US.UTF-8 keyboard-layouts=us persistence noprompt autologin" \
  --debian-installer live \
  --distribution trixie \
  --apt-recommends false \
  --archive-areas "main contrib non-free non-free-firmware" \
  --binary-images iso-hybrid
# --debootstrap-options "--variant=minbase" \
# --mirror-bootstrap "http://deb.debian.org/debian/" \

cp /config/package-lists/desktop.list.chroot config/package-lists/my-desktop.list.chroot
# cp /config/hooks/live/001-set-password.chroot config/hooks/live/001-set-password.chroot
