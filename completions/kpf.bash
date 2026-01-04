#!/bin/bash

_kpf_completion() {
    local cur prev
    cur=${COMP_WORDS[COMP_CWORD]}
    prev=${COMP_WORDS[COMP_CWORD-1]}

    # Flags
    case ${cur} in
        -*)
            COMPREPLY=( $(compgen -W "--namespace -n --all -A --all-ports -l --check -c --debug -d --debug-terminal -t -0 --prompt-namespace -pn --version -v --help -h" -- ${cur}) )
            return 0
            ;;
    esac

    # Handle flag arguments
    case ${prev} in
        -n|--namespace)
            # Complete namespaces
            local namespaces=$(kubectl get namespaces -o jsonpath='{.items[*].metadata.name}' 2>/dev/null)
            COMPREPLY=( $(compgen -W "${namespaces}" -- ${cur}) )
            return 0
            ;;
    esac

    # Positional args (Services/Pods)
    # If we are here, we are not completing a flag or a flag argument
    # We could try to complete services in the current context
    # Use -n if present in the command line
    local ns_arg=""
    for ((i=1; i<COMP_CWORD; i++)); do
        if [[ "${COMP_WORDS[i]}" == "-n" || "${COMP_WORDS[i]}" == "--namespace" ]]; then
            ns_arg="-n ${COMP_WORDS[i+1]}"
            break
        fi
    done

    # Basic resource completion if it looks like a resource or just a name
    # We'll just complete existing service names for simplicity
    local services=$(kubectl get services $ns_arg -o jsonpath='{.items[*].metadata.name}' 2>/dev/null)
    COMPREPLY=( $(compgen -W "${services}" -- ${cur}) )
}

complete -F _kpf_completion kpf
