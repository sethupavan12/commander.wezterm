# Troubleshooting

**Nothing happens when I press the key.** Check WezTerm's debug overlay (`Ctrl+Shift+L`) for Lua errors, and that `apply_to_config` runs before you `return config`. If you set `config.keys = {...}` after calling `apply_to_config`, you've overwritten the binding, so call it after.

**"No API key found".** Check that your login shell actually sees the key: `$SHELL -lic 'echo $OPENAI_API_KEY'`. If it prints nothing, export it in `~/.zshrc` (or your shell's equivalent) or use `api_key_command`. See [The API key](configuration.md#the-api-key).

**The drawer flashes and disappears.** Python failed to start. On a fresh Mac this is usually the `/usr/bin/python3` stub: run `xcode-select --install`, or `brew install python`. Run `python3 /path/to/commander.py` in a pane to see the error, or set `python` to an interpreter you know works. Plugins live under `~/Library/Application Support/wezterm/plugins/` on macOS and `~/.local/share/wezterm/plugins/` on Linux.

**SSL errors with python.org Python on macOS.** Run its `Install Certificates.command` once, or point `python` at Homebrew's.

**The drawer stays open after I accept, saying the process exited.** You have `exit_behavior = "Hold"`. The drawer closes by exiting, so use `"Close"` or `"CloseOnCleanExit"`.

**"Can't open here: this pane lives on ..."** The pane belongs to an SSH or TLS mux domain, so its shell runs on another machine and the drawer can't be started next to it. Use it from a local pane, or `ssh` from a local pane instead of a mux domain.

**Answers are slow.** With OpenAI, `gpt-6-luna` answers in about a second. Local models are much slower on a laptop; try a smaller one, or raise `timeout`.

Still stuck? [Open an issue](https://github.com/sethupavan12/commander.wezterm/issues/new/choose) with your WezTerm version, OS, and the debug overlay output.
