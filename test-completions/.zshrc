# Enable completion system
autoload -Uz compinit
compinit

# Basic completion options
setopt AUTO_MENU          # Show completion menu on tab
setopt COMPLETE_IN_WORD   # Complete from both ends of word
setopt ALWAYS_TO_END      # Move cursor to end of word after completion

# Case-insensitive completion
zstyle ':completion:*' matcher-list 'm:{a-zA-Z}={A-Za-z}'

# Completion menu styling
zstyle ':completion:*' menu select
zstyle ':completion:*' list-colors ''

# Better directory completion
zstyle ':completion:*' special-dirs true

# Command history
HISTFILE=$HOME/.zsh_history
HISTSIZE=10000
SAVEHIST=10000
setopt SHARE_HISTORY
setopt HIST_IGNORE_DUPS

export PATH=$HOME/.local/bin:$PATH
export fpath=($HOME/completions $fpath)
PROMPT='
kpf-testing # '
