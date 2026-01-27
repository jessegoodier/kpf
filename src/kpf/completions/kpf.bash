#!/bin/bash

#compdef kpf

_kpf_completion() {
    local cur prev words cword
    _get_comp_words_by_ref -n : cur prev words cword

    # Define KPF options
    local kpf_opts="--namespace -n --all -A --all-ports -l --check -c --debug -d --debug-terminal -t --run-http-health-checks -z --listen-all --prompt-namespace -p --auto-reconnect --auto-select-free-port --capture-usage --multiline-command --reconnect-attempts --reconnect-delay --show-context --show-direct-command --usage-folder --completions --version -v --help -h"

    # Pre-calculate KPF flag matches if current word looks like a flag
    local -a kpf_matches=()
    if [[ "$cur" == -* ]]; then
        kpf_matches=( $(compgen -W "${kpf_opts}" -- ${cur}) )
    fi

    # Delegate to kubectl for resources and other arguments
    if declare -F __start_kubectl >/dev/null; then
        # Store original state
        local original_words=("${COMP_WORDS[@]}")
        local original_cword=$COMP_CWORD
        local original_line="$COMP_LINE"
        local original_point=$COMP_POINT
        
        # 1. Reconstruct COMP_WORDS: kpf -> kubectl port-forward
        local -a new_words=(kubectl port-forward)
        for ((i=1; i < ${#words[@]}; i++)); do
            new_words+=("${words[i]}")
        done
        COMP_WORDS=("${new_words[@]}")
        COMP_CWORD=$((cword + 1))
        
        # 2. Reconstruct COMP_LINE
        # We need to replace the command 'kpf' at the start with 'kubectl port-forward'
        # We'll assume kpf is the first word in the line for simplicity of replacement
        # or use string replacement on the prefix.
        # Find length of "kpf" (or whatever the invoked command was)
        local cmd_len=${#words[0]}
        
        # Take everything after the command
        local suffix="${original_line:$cmd_len}"
        COMP_LINE="kubectl port-forward$suffix"
        
        # 3. Reconstruct COMP_POINT
        # We added "kubectl port-forward" (20) - "kpf" (3) = 17 chars (approx)
        # More accurately: length difference between new prefix and old prefix
        local new_prefix="kubectl port-forward"
        local old_prefix="${words[0]}"
        local diff=$(( ${#new_prefix} - ${#old_prefix} ))
        COMP_POINT=$(( original_point + diff ))

        # Call the delegate
        __start_kubectl

        # Restore state (good practice, though we mostly just return)
        COMP_WORDS=("${original_words[@]}")
        COMP_CWORD=$original_cword
        COMP_LINE="$original_line"
        COMP_POINT=$original_point
        
        # Merge KPF matches with kubectl matches
        # kubectl might have returned some flags or resources
        # We append our kpf-specific flag matches
        if [[ ${#kpf_matches[@]} -gt 0 ]]; then
            COMPREPLY+=("${kpf_matches[@]}")
        fi
    else
        # Fallback if kubectl completion is missing: just show kpf flags
        COMPREPLY=("${kpf_matches[@]}")
    fi

    # If strict kpf flags are mandatory and kubectl doesn't know them, 
    # kubectl completion might have failed to suggest anything if it saw them.
    # But usually it just ignores unknown flags and tries to complete based on position.
    
    return 0
}

complete -F _kpf_completion kpf
