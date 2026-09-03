if [[ -x /opt/homebrew/bin/brew ]]; then
  eval "$(/opt/homebrew/bin/brew shellenv)"
fi

export ZSH_CONFIG_HOME="${XDG_CONFIG_HOME:-$HOME/.config}/zsh"

source "$ZSH_CONFIG_HOME/environment.zsh"
source "$ZSH_CONFIG_HOME/paths.zsh"
source "$ZSH_CONFIG_HOME/aliases.zsh"
source "$ZSH_CONFIG_HOME/functions.zsh"
source "$ZSH_CONFIG_HOME/git.zsh"

export ZSH="$TOOLS_ROOT/store/zsh-plugins/share/oh-my-zsh"
autoload -Uz compinit
compinit -u -d "$XDG_CACHE_HOME/.zcompdump"

for plugin in \
  "$ZSH/lib/history.zsh" \
  "$ZSH/lib/completion.zsh" \
  "$ZSH/lib/key-bindings.zsh" \
  "$ZSH/lib/directories.zsh" \
  "$ZSH/lib/git.zsh" \
  "$ZSH/plugins/extract/extract.plugin.zsh" \
  "$ZSH/plugins/git/git.plugin.zsh" \
  "$ZSH/custom/plugins/zsh-autosuggestions/zsh-autosuggestions.zsh" \
  "$ZSH/custom/plugins/zsh-syntax-highlighting/zsh-syntax-highlighting.zsh"; do
  [[ -r "$plugin" ]] && source "$plugin"
done
unset plugin

if command -v starship >/dev/null 2>&1; then
  starship init zsh >|"$XDG_CACHE_HOME/starship.plugin.zsh"
  source "$XDG_CACHE_HOME/starship.plugin.zsh"
fi

if command -v atuin >/dev/null 2>&1; then
  atuin init zsh --disable-up-arrow >|"$XDG_CACHE_HOME/atuin.plugin.zsh"
  source "$XDG_CACHE_HOME/atuin.plugin.zsh"
fi

if command -v conda >/dev/null 2>&1; then
  conda shell.zsh hook >|"$XDG_CACHE_HOME/conda.plugin.zsh" 2>/dev/null
  source "$XDG_CACHE_HOME/conda.plugin.zsh"
fi
