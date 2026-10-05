# Contributing

Thanks for wanting to help. Bug reports, fixes and small focused features are all welcome. For anything bigger, open an issue first so we can agree on the shape before you write code.

## Ground rules

These keep the plugin installable with one line, so please hold to them:

- `plugin/commander.py` uses the Python standard library only and must run on Python 3.8. macOS ships 3.9 as `/usr/bin/python3`, and that's the floor most people hit.
- `plugin/init.lua` only uses WezTerm APIs available since 20230320, the first release with plugin support.
- Nothing is downloaded or compiled at install time.
- Model output is untrusted. Anything that reaches the terminal goes through `sanitize()`, the Lua side only acts on events from drawer panes it spawned, and nothing containing a newline is ever pasted.

## Setup

```sh
git clone https://github.com/sethupavan12/commander.wezterm
cd commander.wezterm
python3 -m unittest discover -s tests
```

To run your checkout inside WezTerm, load it with `dofile` instead of `wezterm.plugin.require`:

```lua
local commander = dofile("/path/to/commander.wezterm/plugin/init.lua")
commander.apply_to_config(config, { helper = "/path/to/commander.wezterm/plugin/commander.py" })
```

Changes to `commander.py` apply the next time you open the drawer. Changes to `init.lua` need a config reload (save `~/.wezterm.lua` again, or press `Ctrl+Shift+R`).

To work without spending API credits, point `base_url` at a local server such as Ollama or LM Studio.

## Before you open a pull request

```sh
python3 -m unittest discover -s tests
luajit tests/test_init.lua                  # or lua5.1 / lua5.4
uvx ruff check plugin tests && uvx ruff format --check plugin tests
npx @johnnymorganz/stylua-bin --check plugin tests
```

CI runs the same checks on Linux and macOS, on the oldest and newest supported Python.

Also try the change in a real WezTerm window. The unit tests drive the drawer through a fake terminal, which catches logic bugs but not how it looks or how WezTerm delivers events. If you touched how the drawer opens, closes or inserts, test it with a `unix` mux domain too (`config.unix_domains` plus `default_gui_startup_args = { "connect", "unix" }`). Timing there differs from the local domain.

Say in the pull request what you tested and how. A screenshot helps for anything visual.

## Commit messages

Write the subject in the imperative ("Fix insert when the pane closed"). Use the body to explain why, not what. The diff already shows what.
