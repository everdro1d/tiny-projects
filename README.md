# hyprpaper randomizer
Python script to randomly change my hyprpaper wallpaper to a landscape (ish) image from all files in a directory.
Implements:
- caching to avoid checking every time, checks -> caches match or not -> checks cache first, changes selected image if not match otherwise change wallpaper to selected image
- history to go back up to 10 wallpapers
- follows symlinks
- tab completion via [argcomplete](https://github.com/kislyuk/argcomplete) (bash & zsh)

## Args:
- `--cache-list` : list all caches
- `--cache-init NAME` : initialize a new cache and set it as active
- `--cache-update NAME` : update and prune an existing cache
- `--cache-switch NAME` : switch to a cache, clear history, and apply a wallpaper
- `--cache-delete NAME` : delete a cache (or `all` to delete every cache)
- `--wallpaper-dir PATH` : wallpaper source directory (repeatable, used with `--cache-init`)
- `--max-depth N` : maximum directory depth to scan (used with `--cache-init`, default: 2)
- `--no-populate` : skip initial population when using `--cache-init`
- `--back` : rewind to previous wallpaper using history

## Tab completion

Tab completion is provided via [argcomplete](https://github.com/kislyuk/argcomplete) (bash & zsh).

When installed via the flake, completion scripts are automatically placed in the standard locations (`share/bash-completion/completions/` and `share/zsh/site-functions/`) and will be picked up by any shell that sources system completions — no manual setup required.

When using `nix develop`, completions are activated automatically by the `shellHook`.

`--wallpaper-dir <TAB>` expands directories and `--cache-switch/update/delete <TAB>` suggests existing cache names.

---

## tiny-projects
A collection of tiny projects that are too small to have their own repo, and that took me less than an hour to write.

## Usage
Use branches to switch between projects.
