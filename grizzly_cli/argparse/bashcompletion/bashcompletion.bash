_bashcompletion_template() {
    local current previous command
    declare -a suggestions

    current="${COMP_WORDS[COMP_CWORD]}"
    previous="${COMP_WORDS[$((COMP_CWORD - 1))]}"

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


    # the space in the value is needed for argparse... :S
    # otherwise argument value will be empty, if it starts with --
    suggestions=($(${command} --bash-complete="${command} ${current}" 2>&1))

    COMPREPLY=(${suggestions[*]})
}

complete -F _bashcompletion_template -o filenames bashcompletion_template
