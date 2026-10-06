# How it works

The plugin is two files.

[`plugin/init.lua`](../plugin/init.lua) binds the key and opens a full-width split at the bottom of the tab running [`plugin/commander.py`](../plugin/commander.py). It passes the settings, the target pane's id and its working directory through an environment variable, and remembers in `wezterm.GLOBAL` which panes are drawers and which pane each one belongs to.

`commander.py` is the drawer. It draws the chat, edits your input, pins the key bar to the bottom with a terminal scroll region, and calls the chat completions endpoint with Python's standard library. When you accept a command, it sets an OSC 1337 user var with the command in it. The Lua side catches the `user-var-changed` event, pastes the command into your original pane with `pane:send_paste`, focuses that pane, and sends the drawer a private escape sequence that tells it to exit. The drawer waits for that reply before exiting; on a `unix` mux domain, exiting straight away can tear the pane down before WezTerm delivers the event.

Chats live on disk per pane, so hiding the drawer simply ends the process, and opening it again redraws the conversation.

## Why Python?

Most WezTerm plugins are pure Lua, and this one could have been too: prompt with `PromptInputLine`, call `curl`, show the answer in an `InputSelector`. But those overlays are one-shot dialogs. A chat you can refine, a scrolling history, a line editor and a key bar need a real program in a real pane. Python's standard library has everything that takes (HTTP, JSON, a raw terminal) and is already on nearly every Mac and Linux box, so the plugin stays a one-line install with nothing to download or compile.

## The demo GIFs

The GIFs in the README come from a real WezTerm session against the real model, captured by [`scripts/demo/make-demo.sh`](../scripts/demo/make-demo.sh). It opens a separate WezTerm window with its own home directory and mux socket, types into it at human speed, snapshots the screen contents ten times a second, and redraws each frame. Run it again after UI changes:

```sh
OPENAI_API_KEY=... scripts/demo/make-demo.sh
```
