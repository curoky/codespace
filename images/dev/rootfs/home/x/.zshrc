function mkdir_if_not_exists() {
  if [[ ! -d $1 ]]; then
    mkdir -p $1
  fi
}

export CONFIG_HOME=~/devspace/dotfiles
export ROOTFS_HOME=~/devspace/images/dev/rootfs/home/x
export TOOLS_ROOT=/opt/bm
export WORKSPACE=/workspace
export MY_HOST_NAME=$(hostname)

#=-> XDG
export XDG_CACHE_HOME=$HOME/.cache
export XDG_CONFIG_HOME=$HOME/.config
# just for vscode https://github.com/microsoft/vscode/blob/d2850a427c3f615c7ca94326c801d0fbdb303bad/src/vs/base/parts/ipc/node/ipc.net.ts#L518
export XDG_RUNTIME_DIR=$XDG_CACHE_HOME/runtime
export XDG_DATA_DIR=$XDG_CACHE_HOME/data
mkdir_if_not_exists $XDG_RUNTIME_DIR
mkdir_if_not_exists $XDG_DATA_DIR

#=-> tmp file path
export TMPDIR=$XDG_CACHE_HOME/tmp
mkdir_if_not_exists $TMPDIR

#=-> Path
export PATH=$PATH:$HOME/.local/bin:$HOME/.nix-profile/bin:$HOME/devspace/tools

#=-> FPATH
fpath=(
  "/opt/bm/share/zsh/site-functions"
  "/opt/bm/store/zsh-bundle/share/oh-my-zsh/custom/plugins/zsh-completions/src"
  "/opt/bm/store/zsh-bundle/share/oh-my-zsh/custom/plugins/conda-zsh-completion"
  $fpath
)

source $CONFIG_HOME/zsh/lib/121-apprc.sh
source $CONFIG_HOME/zsh/lib/130-alias.sh
source $CONFIG_HOME/zsh/lib/132-func-git.sh

# kernel config
# https://superuser.com/questions/687094/does-ulimit-su-limit-the-number-of-user-processes-created-in-interactive-logi
# https://github.com/tmux/tmux/issues/1356
ulimit -Sn 1024768

export ZSH=$TOOLS_ROOT/store/zsh-plugins/share/oh-my-zsh
# https://github.com/ohmyzsh/ohmyzsh/blob/7ed475cb589c9e82211f71b3a5d7083b69cea93c/oh-my-zsh.sh#L132
autoload -Uz compinit # zrecompile compaudit
compinit -u -d $XDG_CACHE_HOME/.zcompdump

source ${ZSH}/lib/history.zsh
source ${ZSH}/lib/completion.zsh
source ${ZSH}/lib/key-bindings.zsh
source ${ZSH}/lib/directories.zsh
source ${ZSH}/lib/git.zsh
source ${ZSH}/plugins/extract/extract.plugin.zsh
source ${ZSH}/plugins/git/git.plugin.zsh
source ${ZSH}/custom/plugins/zsh-autosuggestions/zsh-autosuggestions.zsh
source ${ZSH}/custom/plugins/zsh-syntax-highlighting/zsh-syntax-highlighting.zsh

if [[ ! -f $XDG_CACHE_HOME/starship.plugin.zsh ]] && command -v starship >/dev/null 2>&1; then
  starship init zsh >$XDG_CACHE_HOME/starship.plugin.zsh
fi
source $XDG_CACHE_HOME/starship.plugin.zsh

if [[ ! -f $XDG_CACHE_HOME/atuin.plugin.zsh ]] && command -v atuin >/dev/null 2>&1; then
  atuin init zsh --disable-up-arrow >$XDG_CACHE_HOME/atuin.plugin.zsh
fi
source $XDG_CACHE_HOME/atuin.plugin.zsh

if [[ ! -f $XDG_CACHE_HOME/conda.plugin.zsh ]] && command -v conda >/dev/null 2>&1; then
  conda shell.zsh hook 2>/dev/null >$XDG_CACHE_HOME/conda.plugin.zsh
fi

if command -v conda >/dev/null 2>&1; then
  source $XDG_CACHE_HOME/conda.plugin.zsh
fi
