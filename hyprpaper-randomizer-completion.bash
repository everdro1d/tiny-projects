#!/usr/bin/env bash
# Bash tab-completion for hyprpaper-randomizer.py
#
# Installation (choose one):
#   1. System-wide:  copy to /etc/bash_completion.d/hyprpaper-randomizer
#   2. Per-user:     add `source /path/to/hyprpaper-randomizer-completion.bash`
#                    to your ~/.bashrc (or ~/.bash_profile)
#
# Works with both the script invoked as `hyprpaper-randomizer.py` and any
# symlink/alias pointing to it.
#
# NOTE: The cache directory path (~/.cache/hyprpaper-randomizer/caches/) is
# defined as CACHEDIR in the Python script.  If that constant is changed,
# update the path in _hyprpaper_randomizer_caches() below accordingly.

# Returns a space-separated list of existing cache names.
_hyprpaper_randomizer_caches() {
    command ls ~/.cache/hyprpaper-randomizer/caches/*.json 2>/dev/null \
        | xargs -I{} basename {} .json 2>/dev/null
}

_hyprpaper_randomizer() {
    local cur prev
    cur="${COMP_WORDS[COMP_CWORD]}"
    prev="${COMP_WORDS[COMP_CWORD-1]}"

    case "$prev" in
        --wallpaper-dir)
            # Delegate to default directory completion so ~/… and relative
            # paths expand naturally.
            COMPREPLY=( $(compgen -d -- "$cur") )
            return 0
            ;;
        --cache-switch|--cache-update)
            COMPREPLY=( $(compgen -W "$(_hyprpaper_randomizer_caches)" -- "$cur") )
            return 0
            ;;
        --cache-delete)
            COMPREPLY=( $(compgen -W "$(_hyprpaper_randomizer_caches) all" -- "$cur") )
            return 0
            ;;
        --cache-init|--max-depth)
            # Free-form argument; no specific completion.
            return 0
            ;;
    esac

    # Complete flags when the user types a leading '-'.
    COMPREPLY=( $(compgen -W \
        "--cache-list --cache-init --cache-update --cache-switch --cache-delete \
         --wallpaper-dir --max-depth --no-populate --back" \
        -- "$cur") )
}

complete -F _hyprpaper_randomizer hyprpaper-randomizer.py
complete -F _hyprpaper_randomizer hyprpaper-randomizer
