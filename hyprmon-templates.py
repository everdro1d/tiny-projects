#!/usr/bin/env python3
"""
Easily write templates for hyprdynamicmonitors by autodetecting your monitors.

Features:
    - Autodetects monitors
    - Paths can be defined via args but are set to the default .config dir
    - Interactive tagging
    - Position is auto by default but if a tag matches (left|right|up|down) it
      will automatically set the position as auto-(left|right|up|down)
    - Automatically appends the new profile to the config file

Args:
    - `--config` define the path to config.toml
      (default \"$HOME/.config/hyprdynamicmonitors/config.toml\")
    - `--template-dir` define the path to the template dir (expands `~`)
      (default \"$HOME/.config/hyprdynamicmonitors/templates/\")
    - `--resolve` resolve relative paths to absolute for the above two args
"""

from pathlib import Path
import sys
import os
import subprocess
import re
import string
import json

import argparse
try:
    import argcomplete
    from argcomplete.completers import DirectoriesCompleter
except ImportError:
    argcomplete = None
    DirectoriesCompleter = None

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
DEF_PATH = Path.home() / ".config" / "hyprdynamicmonitors"
CONFIG_PATH = DEF_PATH / "config.toml"
TEMPLATE_DIR = DEF_PATH / "templates"

# ---------------------------------------------------------------------------
# Utils
# ---------------------------------------------------------------------------

def san_input(prompt: str) -> str:
    try:
        s = input(prompt)
        re.sub(r"\s+","",s)
        valid_chars = f"-_.{string.ascii_letters}{string.digits}"
        return "".join(c for c in s if c in valid_chars)[:255]

    except EOFError:
        print("\nError: Found EOF in input. Exiting.")
        sys.exit(1)

# ---------------------------------------------------------------------------
# Get data
# ---------------------------------------------------------------------------

def get_profile_name() -> str:
    profile = san_input("Profile Name: ")
    if profile is None or profile == "":
        print("Error: Must name the profile.")
        sys.exit(1)
    return profile

def get_monitor_descriptions():
    try:
        result = subprocess.run(
            ["hyprctl", "monitors", "-j"],
            capture_output=True,
            text=True,
            check=True,
        )
    except Exception:
        return []

    try:
        monitors = json.loads(result.stdout)
    except Exception:
        return []

    if not isinstance(monitors, list):
        return []

    descriptions = []
    for monitor in monitors:
        if not isinstance(monitor, dict):
            continue
        desc = monitor.get("description")
        if isinstance(desc, str) and desc:
            descriptions.append(desc)
    return descriptions

def get_description_tags(descriptions):
    if len(descriptions) < 1:
        print("Error: No monitor descriptions detected.")
        sys.exit(1)

    tags = []
    for desc in descriptions:
        print(f"\n{desc}")
        tag = san_input("Enter monitor tag: ")
        tags.append(tag)

    return tags

def get_template_lines(tags):
    tmpl_lines = []

    # create monitor var
    for tag in tags:
        tmpl_lines.append(f"{{{{- ${tag} := index .MonitorsByTag \"{tag}\" -}}}}\n")

    # spacing
    tmpl_lines.append("\n")

    # create monitor setting
    for index, tag in enumerate(tags):
        # auto position if tag is any of the valid hyprland auto-position values
        auto = "auto"
        if tag in ["left","right","up","down"]:
            auto = f"auto-{tag}"

        tmpl_lines.extend([
            "hl.monitor({\n",
           f"    output = \"desc:{{{{${tag}.Description}}}}\",\n",
            "    mode = \"preferred\",\n",
           f"    position = \"{auto}\",\n",
            "    scale = 1,\n",
            "})\n\n"
        ])

    # spacing
    tmpl_lines.append("\n")

    # create commented workspace rules
    tmpl_lines.append("-- optionally bind workspaces to monitors\n")
    for index, tag in enumerate(tags):
        default = ""
        if index == 0:
            default = ", default = true"

        tmpl_lines.append(
            f"-- hl.workspace_rule({{ workspace = \"{index+1}\", monitor = \"{{{{${tag}.Name}}}}\"{default} }})\n"
        )

    # spacing
    tmpl_lines.append("\n\n")

    # create fallback rule
    tmpl_lines.append("-- fallback assignment for plugging in random monitors\n")
    tmpl_lines.append('hl.monitor({ output = "", mode = "preferred", position = "auto", scale = 1 })')

    return tmpl_lines

def get_profile_lines(template_dir, profile, monitor_descriptions, tags):
    p_lines = []
    # add spacing
    p_lines.append("\n\n\n")

    # define profile
    p_lines.extend([
        f"[profiles.{profile}]\n",
        f"config_file = \"{template_dir}/{profile}.go.tmpl\"\n",
         "config_file_type = \"template\"\n",
        f"[profiles.{profile}.conditions]\n\n"
    ])

    # define required monitors
    # zip is fine here as they must be the same length
    for desc, tag in zip(monitor_descriptions, tags):
        p_lines.extend([
            f"[[profiles.{profile}.conditions.required_monitors]]\n",
            f"description = \"{desc}\"\n",
            f"monitor_tag = \"{tag}\"\n\n"
        ])

    return p_lines


def finish(config, template_dir, profile):
    template = Path(template_dir).expanduser().resolve() / f"{profile}.go.tmpl"
    print(f"\nSuccessfully created profile template: {profile}")
    print(f"Appended profile to config at: {Path(config).expanduser().resolve()}")
    print(f"Created template at: {template}")

    open = san_input("\nWould you like to open the template in $EDITOR? (y/N): ")
    if not open.lower() == "y":
        return
    open_in_editor(template)


def open_in_editor(filepath):
    default_editor = "nano"
    editor = os.getenv("EDITOR", default_editor)

    try:
        subprocess.run([editor, filepath], check=True)
    except FileNotFoundError:
        print(f"Error: Editor \"{editor}\" could not be found on your system.")
    except subprocess.CalledProcessError:
        print(f"Error: Editor \"{editor}\" exited with an error.")

# ---------------------------------------------------------------------------
# Writers
# ---------------------------------------------------------------------------

def write_template(template_dir, profile, tags, resolve):
    template_dir = Path(template_dir).expanduser()
    if resolve:
        template_dir = template_dir.resolve()

    template_dir.mkdir(parents=True, exist_ok=True)

    lines = get_template_lines(tags)

    file = template_dir / f"{profile}.go.tmpl"
    file.write_text("".join(lines), encoding="utf-8")


def append_profile(config, template_dir, profile, monitor_descriptions, tags, resolve):
    config = Path(config).expanduser().resolve()
    if template_dir.startswith("~"):
        template_dir = Path(template_dir).expanduser()
    elif resolve:
        template_dir = Path(template_dir).resolve()

    config.parent.mkdir(parents=True, exist_ok=True)

    lines = get_profile_lines(template_dir, profile, monitor_descriptions, tags)

    with config.open("a", encoding="utf-8") as f:
        f.writelines(lines)

# ---------------------------------------------------------------------------
# Main Run func
# ---------------------------------------------------------------------------

def run(config: str = CONFIG_PATH, template_dir: str = TEMPLATE_DIR, resolve: bool = False):
    c = os.getenv("HY_TMPL_CONFIG")
    t = os.getenv("HY_TMPL_DIR")
    if config == CONFIG_PATH and (c is not None or c != "" ):
        config = c
    if template_dir == TEMPLATE_DIR and (t is not None or t != "" ):
        template_dir = t

    profile = get_profile_name()
    monitor_descriptions = get_monitor_descriptions()
    tags = get_description_tags(monitor_descriptions)

    write_template(template_dir, profile, tags, resolve)
    append_profile(config, template_dir, profile, monitor_descriptions, tags, resolve)

    finish(config, template_dir, profile)

# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------

def parse_args():
    parser = argparse.ArgumentParser(
            description="hyprmon-templates: easily create templates for new monitor configurations",
    )

    config_path_arg = parser.add_argument(
        "--config", metavar="PATH", action="store", dest="config_path",
        help="path to config file (default \"$HOME/.config/hyprdynamicmonitors/config.toml\")")

    template_dir_path_arg = parser.add_argument(
        "--template-dir", metavar="PATH", action="store", dest="template_dir_path",
        help="path to templates directory (default \"$HOME/.config/hyprdynamicmonitors/templates/\")")

    parser.add_argument("--resolve", action="store_true",
        help="resolve relative paths. use this if your templates dir is not in same dir as the config file for example")

    if DirectoriesCompleter is not None:
        d = DirectoriesCompleter()
        config_path_arg.completer = d
        template_dir_path_arg.completer = d

    if argcomplete is not None:
        argcomplete.autocomplete(parser)

    return parser.parse_args()

# ---------------------------------------------------------------------------
# Entry
# ---------------------------------------------------------------------------

def main():
    args = parse_args()

    run(args.config_path, args.template_dir_path, args.resolve)

if __name__ == "__main__":
    main()
