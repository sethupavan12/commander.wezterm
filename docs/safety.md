# Safety and privacy

commander sits between a language model and your shell, so it is built around one rule: nothing runs unless you run it.

## Nothing runs by itself

Accepting a command pastes it at your prompt. You still press `Enter` in your shell, and you can edit it first.

Only single lines are ever pasted. A newline in a paste is a problem, because shells without bracketed paste (like the bash 3.2 that ships as macOS's `/bin/bash`, or a `python` prompt) run each line the moment it arrives. So the model is asked for one line, and when it sends several anyway the drawer joins them (`for f in *; do echo $f; done`), so what you see is what gets pasted. If joining would change the meaning, as with a heredoc, `Enter` copies the command to your clipboard instead. The Lua side also refuses to paste anything containing a newline, as a second line of defence.

## Dangerous commands ask twice

Every suggestion is checked locally, without asking the model. Anything that deletes recursively, uses `sudo`, pipes a download into a shell, force-pushes, resets or cleans a git tree, kills processes or touches disks gets a warning even if the model gave none, and needs a second `Enter` before it is pasted.

That local check matters because of prompt injection. File names and screen contents can come from anywhere, including a repository you just cloned or a server you're logged into, and someone could name a file to trick the model into suggesting something harmful and leaving the warning out. The model is told to treat that context as data, but the local check doesn't depend on the model behaving.

## Model replies are untrusted text

Before anything is drawn or pasted, control characters, bidi overrides and invisible characters are stripped. A reply can't sneak escape sequences into your terminal, or show you something different from what gets pasted.

The Lua side only accepts events from drawer panes it opened itself. Another program printing the same escape sequence can't make it paste anything.

## What gets sent

Each request carries your question, the conversation so far in that pane, and a short description of the environment: OS and version, shell name, current directory, and up to 60 file names from that directory. Nothing from your screen is sent unless you turn on [`screen_context_lines`](configuration.md#screen-context).

If the pane is running `ssh` (or `mosh`, `docker`, `kubectl` and friends), the drawer says so instead. It tells the model the command runs on another machine with an unknown OS and leaves your local file names out.

The drawer only opens in panes on this machine. In panes from an SSH or TLS mux domain (`ssh_domains`, `tls_clients`), where the shell runs on another host, you get a message instead.

## Your API key

It's sent only to the provider you configured, over https (plain http is allowed only to localhost), and redirects are never followed. It's kept out of the environment of anything the drawer starts, and never written to disk. See [The API key](configuration.md#the-api-key) for where it's read from.

## What's stored

Chats are saved as JSON under `~/.local/state/wezterm-commander/` (or `$XDG_STATE_HOME`), in a folder only you can read. The questions you type are kept there for 30 days, so `Up` can recall them in any pane. Delete the folder to wipe it all.

## Reporting a problem

See [SECURITY.md](../SECURITY.md).
