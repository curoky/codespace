ENV_PATHS=(
  # "$HOMEBREW_PREFIX/opt/ruby/bin"
  "/opt/sb/bin"
  "/nix/var/nix/profiles/default/bin"
)
for p in "${ENV_PATHS[@]}"; do
  [[ -d $p ]] && export PATH=$p:$PATH
done

ENV_PATHS=(
  "$HOME/.local/bin"
  "$HOME/.nix-profile/bin"

  "/opt/conda/condabin"
  # "/opt/pipx/bin"
  "/opt/rust/cargo/bin"

  # "$HOME/app/conda/condabin"
  # "$HOME/app/conda/pipx/bin"
  "$HOMEBREW_PREFIX/opt/ruby/bin"

  # "$HOME/.npm-global/bin"
  "$HOME/devspace/tools"

  # "/nix/var/nix/profiles/default/lib/ruby/gems/2.7.0/bin"
  # "$HOMEBREW_PREFIX/lib/ruby/gems/3.1.0/bin"
  # "$HOME/.cargo/bin" # already source in ~/.zshenv
)
for p in "${ENV_PATHS[@]}"; do
  [[ -d $p ]] && export PATH=$PATH:$p
done

ENV_FPATHS=(
  "$HOMEBREW_PREFIX/completions/zsh"

  "/opt/sb/share/zsh/site-functions"
  "/opt/sb/store/zsh-bundle/share/oh-my-zsh/custom/plugins/zsh-completions/src"
  "/opt/sb/store/zsh-bundle/share/oh-my-zsh/custom/plugins/conda-zsh-completion"
)

for p in "${ENV_FPATHS[@]}"; do
  [[ -d $p ]] && fpath=($p $fpath)
done

ENV_PATHS=(
)

for p in "${ENV_PATHS[@]}"; do
  [[ -d $p ]] && export PYTHONPATH=$p:$PYTHONPATH
done
