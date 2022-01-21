_bashcompletion_template() {
    local current previous
    local command
    declare -a suggestions

    current="${COMP_WORDS[COMP_CWORD]}"
    previous="${COMP_WORDS[$((COMP_CWORD - 1))]}"

    case "${previous}" in
        -h|--help)
            return
            ;;
        default)
            ;;
    esac


    if (( ${#COMP_WORDS[@]} > 1 )); then
        if [[ "${previous}" == "-"* ]]; then
            command="${COMP_WORDS[*]::${#COMP_WORDS[@]}-2}"
            current="${previous} ${current}"
        else
            command="${COMP_WORDS[*]::${#COMP_WORDS[@]}-1}"
        fi
    else
        command="${COMP_WORDS[*]}"
    fi


    >&2 echo "command=${command}"
    >&2 echo "current=${current}, previous=${previous}, argument=$1"
    >&2 echo "${command} --bash-complete=\"${command} ${current}\""
    # the space in the value is needed for argparse... :S
    # otherwise argument value will be empty, if it starts with --
    suggestions=($(${command} --bash-complete="${command} ${current}" 2>&1))

    COMPREPLY=(${suggestions[*]})
}

complete -F _bashcompletion_template bashcompletion_template
