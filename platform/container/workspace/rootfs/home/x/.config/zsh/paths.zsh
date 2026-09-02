path=(
  "$HOME/.local/bin"
  /opt/bm/bin
  /nix/var/nix/profiles/default/bin
  "$HOME/.nix-profile/bin"
  /opt/homebrew/opt/ruby/bin
  $path
)
typeset -U path PATH

fpath=(
  /opt/homebrew/completions/zsh
  /opt/bm/share/zsh/site-functions
  /opt/bm/store/zsh-bundle/share/oh-my-zsh/custom/plugins/zsh-completions/src
  /opt/bm/store/zsh-bundle/share/oh-my-zsh/custom/plugins/conda-zsh-completion
  $fpath
)
typeset -U fpath FPATH
