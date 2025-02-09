#!/usr/bin/env bash

# Ref:
# - https://segmentfault.com/q/1010000000118837
# - https://stackoverflow.com/questions/19161960/connect-with-ssh-through-a-proxy

set -euo pipefail

export PATH=/home/linuxbrew/.linuxbrew/bin:$HOME/.linuxbrew/bin:$PATH

echo "use ssh proxy on $_SSH_PROXY" >&2
# ssh -o ProxyCommand="connect -S $_HTTP_PROXY %h %p" "$@"
ssh -o ProxyCommand="ssh -W %h:%p $_SSH_PROXY" "$@"
