export XDG_CACHE_HOME="$HOME/.cache"
export XDG_CONFIG_HOME="$HOME/.config"
export XDG_DATA_HOME="$HOME/.local/share"
export XDG_RUNTIME_DIR="$XDG_CACHE_HOME/runtime"
export TMPDIR="$XDG_CACHE_HOME/tmp"

typeset -g +x ZSH="$HOME/.local/store/zsh-plugins/share/oh-my-zsh"
typeset -g +x ZSH_CACHE_DIR="$XDG_CACHE_HOME/oh-my-zsh"
typeset -g +x HISTFILE="$HOME/.zsh_history"

mkdir -p \
  "$XDG_CACHE_HOME" \
  "$XDG_CONFIG_HOME" \
  "$XDG_DATA_HOME" \
  "$XDG_RUNTIME_DIR" \
  "$TMPDIR" \
  "$ZSH_CACHE_DIR"

export KRB5CCNAME="/tmp/krb5_ccache"
export NPM_CONFIG_CACHE="$XDG_CACHE_HOME/npm"
export TMUX_CONF_LOCAL="$XDG_CONFIG_HOME/tmux/tmux.conf.local"
export GOPROXY="https://goproxy.cn,direct"
export HOMEBREW_NO_ANALYTICS=1
export HOMEBREW_NO_AUTO_UPDATE=1
export UV_SYSTEM_CERTS=true
export UV_TOOL_DIR="$HOME/.local/share/uv/tools"
export UV_TOOL_BIN_DIR="$HOME/.local/share/uv/bin"
export UV_PYTHON_INSTALL_DIR="$HOME/.local/share/uv/python"
export UV_PYTHON_BIN_DIR="$HOME/.local/share/uv/bin"

eval "$(/opt/homebrew/bin/brew shellenv)"

if [[ -r /nix/var/nix/profiles/default/etc/profile.d/nix-daemon.sh ]]; then
  source /nix/var/nix/profiles/default/etc/profile.d/nix-daemon.sh
fi

typeset -U path PATH
path=(
  "$HOME/.local/bin"
  "$HOME/.local/share/uv/bin"
  "$HOME/.local/share/node/tools/bin"
  "$HOME/.local/share/node/node-tool"
  "$HOME/.local/share/node/nodejs26/bin"
  "$HOME/go/bin"
  "$HOME/.local/share/go/go1.27.1/bin"
  "$HOME/.local/profile/go/bin"
  "${path[@]}"
)

typeset -U fpath FPATH
fpath=(
  "$HOME/.local/share/zsh/site-functions"
  "$ZSH/custom/plugins/zsh-completions/src"
  "${fpath[@]}"
)

typeset -ga ZSH_HIGHLIGHT_HIGHLIGHTERS=(main brackets cursor)
typeset -g +x ZSH_AUTOSUGGEST_BUFFER_MAX_SIZE=40
typeset -g +x ZSH_AUTOSUGGEST_HIGHLIGHT_STYLE="fg=244"

autoload -Uz compinit
compinit -i -d "$ZSH_CACHE_DIR/zcompdump"

source "$ZSH/lib/history.zsh"
setopt hist_find_no_dups hist_save_no_dups

source "$ZSH/lib/completion.zsh"
source "$ZSH/lib/key-bindings.zsh"
source "$ZSH/lib/directories.zsh"
source "$ZSH/lib/git.zsh"
source "$ZSH/plugins/extract/extract.plugin.zsh"
source "$ZSH/plugins/git/git.plugin.zsh"

source "$HOME/.local/store/zsh-plugins/share/oh-my-zsh/custom/plugins/starship/starship.plugin.zsh"
source "$HOME/.local/store/zsh-plugins/share/oh-my-zsh/custom/plugins/atuin/atuin.plugin.zsh"
source "$ZSH/custom/plugins/zsh-autosuggestions/zsh-autosuggestions.zsh"

source "$XDG_CONFIG_HOME/zsh/functions.zsh"
source "$XDG_CONFIG_HOME/zsh/git.zsh"
source "$XDG_CONFIG_HOME/zsh/aliases.zsh"

# Must remain last so every ZLE widget is instrumented.
source "$ZSH/custom/plugins/zsh-syntax-highlighting/zsh-syntax-highlighting.zsh"
