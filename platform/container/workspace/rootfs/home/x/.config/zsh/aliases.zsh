alias chx='chmod +x'
alias fpath='print -l $fpath | sort'
alias penv='env | sort'

alias ls='eza-wrapper'
alias l='eza-wrapper -la'
alias la='eza-wrapper -la'
alias lsd='eza-wrapper -la --sort=modified'
alias lsn='eza-wrapper -la --sort=name'
alias lss='eza-wrapper -la --sort=size'

alias grep='grep --color'
alias sgrep='grep -R -n -H -C 5 --exclude-dir={.git,.svn,CVS}'
alias t='tail -f'
alias ff='find . -type f -name'
alias rm='rm -i'
alias cp='cp -i'
alias mv='mv -i'
alias path='print -l $path'
alias topme='top -U $UID'

alias -s txt=less
alias -s h=less
alias -s hpp=less
alias -s cc=less
alias -s cpp=less
alias -s log=less

alias cfmt='clang-format -style=file -fallback-style=google -sort-includes=1 -i'
alias update='rsync --partial --progress --archive --human-readable --rsh=ssh'
alias mirror='rsync --partial --progress --archive --human-readable --rsh=ssh --delete --delete-excluded'
alias prune_empty_dir='find . -type d -empty -delete'
alias agf='rg --files --hidden --no-messages | rg --case-sensitive --word-regexp'
alias ggpf='git push origin "$(git_current_branch)" --force'
alias dctemp='docker run --rm --tty --network=host --interactive --entrypoint /bin/bash'
alias gccinfo='gcc -E -xc++ - -v'
alias show_coredump_pattern='sysctl kernel.core_pattern'
