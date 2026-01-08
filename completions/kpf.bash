#!/bin/bash

_kpf_completion() {
    local cur prev
    cur=${COMP_WORDS[COMP_CWORD]}
    prev=${COMP_WORDS[COMP_CWORD-1]}

    # Flags
    case ${cur} in
        -*)
            COMPREPLY=( $(compgen -W "--namespace -n --all -A --all-ports -l --check -c --debug -d --debug-terminal -t --run-http-health-checks -0 --prompt-namespace -pn --auto-reconnect --auto-select-free-port --capture-usage --multiline-command --reconnect-attempts --reconnect-delay --show-context --show-direct-command --usage-folder --version -v --help -h" -- ${cur}) )
            return 0
            ;;
    esac

    # Handle flag arguments
    case ${prev} in
        -n|--namespace)
            # Complete namespaces
            local namespaces=$(kubectl get namespaces -o jsonpath='{range .items[*]}{.metadata.name}{"\n"}{end}' 2>/dev/null)
            COMPREPLY=( $(compgen -W "${namespaces}" -- ${cur}) )
            return 0
            ;;
        --reconnect-attempts|--reconnect-delay)
            # Numeric argument - no completion
            return 0
            ;;
        --usage-folder)
            # Directory completion
            COMPREPLY=( $(compgen -d -- ${cur}) )
            return 0
            ;;
    esac

    # Extract namespace if specified
    local ns_arg=""
    for ((i=1; i<COMP_CWORD; i++)); do
        if [[ "${COMP_WORDS[i]}" == "-n" || "${COMP_WORDS[i]}" == "--namespace" ]]; then
            ns_arg="-n ${COMP_WORDS[i+1]}"
            break
        fi
    done

    # Count non-flag positional arguments
    local pos_count=0
    local first_service=""
    for ((i=1; i<COMP_CWORD; i++)); do
        local word="${COMP_WORDS[i]}"
        # Skip flags and their arguments
        if [[ "$word" == -* ]]; then
            # Skip next word if this is a flag that takes an argument
            if [[ "$word" == "-n" || "$word" == "--namespace" || "$word" == "--reconnect-attempts" || "$word" == "--reconnect-delay" || "$word" == "--usage-folder" ]]; then
                ((i++))
            fi
            continue
        fi
        ((pos_count++))
        if [[ $pos_count -eq 1 ]]; then
            first_service="$word"
        fi
    done

    # First positional argument: complete services
    if [[ $pos_count -eq 0 ]]; then
        local services=$(kubectl get services $ns_arg -o jsonpath='{range .items[*]}{.metadata.name}{"\n"}{end}' 2>/dev/null)
        local svc_completions=()
        while IFS= read -r svc; do
            [[ -z "$svc" ]] && continue
            svc_completions+=("svc/$svc")
        done <<< "$services"
        COMPREPLY=( $(compgen -W "${svc_completions[*]}" -- ${cur}) )
        return 0
    fi

    # Second positional argument: complete ports for the selected service
    if [[ $pos_count -eq 1 ]]; then
        # Strip svc/ prefix if present
        local service_name="${first_service#svc/}"

        # Get ports for the service
        local port_data=$(kubectl get service "$service_name" $ns_arg -o jsonpath='{range .spec.ports[*]}{.port}{"/"}{.protocol}{" "}{.name}{"\n"}{end}' 2>/dev/null)

        local port_completions=()
        while IFS= read -r line; do
            [[ -z "$line" ]] && continue
            local port_proto="${line%% *}"
            local port="${port_proto%%/*}"
            port_completions+=("$port:$port")
        done <<< "$port_data"

        COMPREPLY=( $(compgen -W "${port_completions[*]}" -- ${cur}) )
        return 0
    fi
}

complete -F _kpf_completion kpf
