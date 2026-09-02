export TOOLS_ROOT=/opt/bm
export XDG_CACHE_HOME="${XDG_CACHE_HOME:-$HOME/.cache}"
export XDG_CONFIG_HOME="${XDG_CONFIG_HOME:-$HOME/.config}"
export XDG_DATA_HOME="${XDG_DATA_HOME:-$HOME/.local/share}"
export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-$XDG_CACHE_HOME/runtime}"
export TMPDIR="${TMPDIR:-$XDG_CACHE_HOME/tmp}"
export KRB5CCNAME=/tmp/krb5_ccache
export NPM_CONFIG_CACHE="$XDG_CACHE_HOME/npm"
export TMUX_CONF_LOCAL="$HOME/.config/tmux/tmux.conf.local"
export GOPROXY="https://goproxy.cn,direct"

if [[ -d /workspace ]]; then
  export WORKSPACE=/workspace
else
  export WORKSPACE="$HOME/workspace"
fi

mkdir -p "$XDG_RUNTIME_DIR" "$XDG_DATA_HOME" "$TMPDIR"

if [[ "$(uname)" == Linux ]]; then
  ulimit -Sn 1024768 2>/dev/null || true
fi

if [[ -r /run/s6/container_environment/HTTP_PROXY ]]; then
  proxy_url="$(</run/s6/container_environment/HTTP_PROXY)"
  export http_proxy="$proxy_url"
  export HTTP_PROXY="$proxy_url"
  export https_proxy="$proxy_url"
  export HTTPS_PROXY="$proxy_url"
  export all_proxy="$proxy_url"
  export ALL_PROXY="$proxy_url"
  export no_proxy="localhost,127.0.0.1,192.168.0.0/16,10.0.0.0/8,releases.nixos.org"
  export NO_PROXY="$no_proxy"
  unset proxy_url
fi

if [[ -d /opt/homebrew ]]; then
  export HOMEBREW_NO_ANALYTICS=1
  export HOMEBREW_NO_AUTO_UPDATE=1
  export HOMEBREW_BOOTSNAP=1
  export HOMEBREW_BAT=1
  export HOMEBREW_BAT_CONFIG_PATH="$HOME/.config/bat/config"
  export HOMEBREW_CC=gcc
  export HOMEBREW_API_DOMAIN="https://mirrors.tuna.tsinghua.edu.cn/homebrew-bottles/api"
  export HOMEBREW_BOTTLE_DOMAIN="https://mirrors.tuna.tsinghua.edu.cn/homebrew-bottles"
  export HOMEBREW_CORE_GIT_REMOTE="https://mirrors.tuna.tsinghua.edu.cn/git/homebrew/homebrew-core.git"
fi

typeset -ga ZSH_HIGHLIGHT_HIGHLIGHTERS
ZSH_HIGHLIGHT_HIGHLIGHTERS=(main brackets pattern cursor)
export ZSH_AUTOSUGGEST_BUFFER_MAX_SIZE=40
export ZSH_AUTOSUGGEST_USE_ASYNC=1
export ZSH_AUTOSUGGEST_HIGHLIGHT_STYLE="fg=244"

setopt HIST_FIND_NO_DUPS
setopt HIST_SAVE_NO_DUPS
