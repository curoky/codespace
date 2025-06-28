alias chx='chmod +x'

alias fpath='print -l $fpath | sort'
alias penv='env | sort'

# alias t='task'

alias ls='eza --color-scale -g -H -b --color=always --git'                          # ls -> eza
alias l='eza --color-scale -g -H -b --color=always --git -la'                       # long list, all files
alias la='eza --color-scale -g -H -b --color=always --git -la'                       # long list, all files
alias lsd='eza --color-scale -g -H -b --color=always --git -la --sort=modified'     # sort by date
alias lsn='eza --color-scale -g -H -b --color=always --git -la --sort=name'         # sort by name
alias lss='eza --color-scale -g -H -b --color=always --git -la --sort=size'         # sort by size

alias grep='grep --color'
alias sgrep='grep -R -n -H -C 5 --exclude-dir={.git,.svn,CVS} '

alias t='tail -f'

alias ff='find . -type f -name'

alias rm='rm -i'
alias cp='cp -i'
alias mv='mv -i'

function psgrep() {
  ps aux | grep "${1:-.}" | grep -v grep
}
# Kills any process that matches a regexp passed to it
function killit() {
  ps aux | grep -v "grep" | grep "$@" | awk '{print $2}' | xargs sudo kill
}

# alias l='ls -lFh --git'
# alias la='ls -lFha --git'
# alias ping='ping -c 5'
# alias ping6='ping6 -c 5'
# alias clr='clear; echo Currently logged in on $TTY, as $USERNAME in directory $PWD.'
alias path='print -l $path'
# alias mkdir='mkdir -pv'

# alias ta='tmux attach -t'
# alias tad='tmux attach -d -t'
# alias ts='tmux new-session -s'
# alias tl='tmux list-sessions'
# alias tksv='tmux kill-server'
# alias tkss='tmux kill-session -t'

alias topme='top -U $UID'

alias grep='grep --color'
# alias cat='bat'

alias rm='rm -i'
alias cp='cp -i'
alias mv='mv -i'

alias -s txt=less
alias -s h=less
alias -s hpp=less
alias -s cc=less
alias -s cpp=less
alias -s log=less

alias cfmt='clang-format -style=file -fallback-style=google -sort-includes=1 -i '

alias update="rsync --partial --progress --archive --human-readable --rsh=ssh"
# --checksum --bwlimit=4000
alias mirror="rsync --partial --progress --archive --human-readable --rsh=ssh --delete --delete-excluded"
# alias increment="rsync --partial --progress --archive --human-readable --rsh=ssh"

alias prune_empty_dir="find . -type d -empty -delete"

# alias agf='ag --case-sensitive --word-regexp --hidden --silent -g'
alias agf='rg --files --hidden --no-messages | rg --case-sensitive --word-regexp'


# alias lint="pre-commit run --all-files"

alias ggpf='git push origin "$(git_current_branch)" --force'

alias dctemp="docker run --rm --tty --network=host --interactive --entrypoint /bin/bash"

# https://gist.github.com/elventear/7640982
# alias wget="curl -O --retry 999 --retry-max-time 0 -C -"

# alias py3="conda activate py3"
# alias py2="conda activate py2"

alias gccinfo="gcc -E -xc++ - -v"

alias show_coredump_pattern="sysctl kernel.core_pattern"
