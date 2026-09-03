export XDG_CACHE_HOME="$HOME/.cache"
export XDG_CONFIG_HOME="$HOME/.config"
export XDG_DATA_HOME="$HOME/.local/share"
export XDG_RUNTIME_DIR="$XDG_CACHE_HOME/runtime"
export TMPDIR="$XDG_CACHE_HOME/tmp"
export KRB5CCNAME=/tmp/krb5_ccache
export NPM_CONFIG_CACHE="$XDG_CACHE_HOME/npm"
export TMUX_CONF_LOCAL="$XDG_CONFIG_HOME/tmux/tmux.conf.local"
export GOPROXY="https://goproxy.cn,direct"
export WORKSPACE=/workspace

mkdir -p "$XDG_CACHE_HOME" "$XDG_RUNTIME_DIR" "$XDG_DATA_HOME" "$TMPDIR"

ulimit -Sn 1024768 2>/dev/null || true

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

export PATH="$PATH:$HOME/.local/bin:$HOME/.nix-profile/bin"

fpath=(
  /opt/bm/share/zsh/site-functions
  /opt/bm/store/zsh-plugins/share/oh-my-zsh/custom/plugins/zsh-completions/src
  /opt/bm/store/zsh-plugins/share/oh-my-zsh/custom/plugins/conda-zsh-completion
  $fpath
)
typeset -U fpath FPATH

export ZSH=/opt/bm/store/zsh-plugins/share/oh-my-zsh

# Plugin settings must be defined before the corresponding plugins are loaded.
ZSH_HIGHLIGHT_HIGHLIGHTERS=(main brackets cursor)
export ZSH_AUTOSUGGEST_BUFFER_MAX_SIZE=40
export ZSH_AUTOSUGGEST_HIGHLIGHT_STYLE="fg=244"

setopt HIST_FIND_NO_DUPS
setopt HIST_SAVE_NO_DUPS

# Plugins below register completions through compdef.
autoload -Uz compinit
compinit -u -d "$XDG_CACHE_HOME/zcompdump"

source "$ZSH/lib/history.zsh"
source "$ZSH/lib/completion.zsh"
source "$ZSH/lib/key-bindings.zsh"
source "$ZSH/lib/directories.zsh"
source "$ZSH/lib/git.zsh"
source "$ZSH/plugins/extract/extract.plugin.zsh"
source "$ZSH/plugins/git/git.plugin.zsh"

source "$XDG_CACHE_HOME/conda.plugin.zsh"
source "$XDG_CACHE_HOME/starship.plugin.zsh"

# Atuin must create its widgets before autosuggestions wraps them.
source "$XDG_CACHE_HOME/atuin.plugin.zsh"

# User definitions take precedence over framework aliases and functions.
source "$XDG_CONFIG_HOME/zsh/aliases.zsh"
source "$XDG_CONFIG_HOME/zsh/functions.zsh"
source "$XDG_CONFIG_HOME/zsh/git.zsh"

source "$ZSH/custom/plugins/zsh-autosuggestions/zsh-autosuggestions.zsh"

# Syntax highlighting must be loaded after all custom widgets.
source "$ZSH/custom/plugins/zsh-syntax-highlighting/zsh-syntax-highlighting.zsh"
