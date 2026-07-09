# hyprmon-templates


Easily create templates for [fiffeek/hyprdynamicmonitors](https://github.com/fiffeek/hyprdynamicmonitors)
by autodetecting attached monitors.


## Features:
    - Autodetects attached monitors
    - Paths can be defined via args but are set to the default .config dir
    - Interactive tagging per monitor
    - Position is auto by default but if a tag matches (left|right|up|down) it
      will automatically set the position as auto-(left|right|up|down)
    - Automatically appends the new profile to the config file


## Args:
    - `--config` define the path to config.toml
      (default \"$HOME/.config/hyprdynamicmonitors/config.toml\")
    - `--template-dir` define the path to the template dir (expands `~`)
      (default \"$HOME/.config/hyprdynamicmonitors/templates/\")
    - `--resolve` resolve relative paths to absolute for the above two args

---

## tiny-projects
A collection of tiny projects that are too small to have their own repo, and that took me less than an hour to write.

## Usage
Use branches to switch between projects.

