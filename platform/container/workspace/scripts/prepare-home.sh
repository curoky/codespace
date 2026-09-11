#!/usr/bin/env bash
# Build shell integrations for the fixed image toolchain as x.
set -euo pipefail

install -d -m 0700 /home/x/.local/share/codespace
conda shell.zsh hook >/home/x/.local/share/codespace/conda.plugin.zsh
starship init zsh >/home/x/.local/share/codespace/starship.plugin.zsh
atuin init zsh --disable-up-arrow >/home/x/.local/share/codespace/atuin.plugin.zsh
