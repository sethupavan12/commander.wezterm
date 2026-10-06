# Configuration

Everything is optional. With no options the plugin uses OpenAI's `gpt-6-luna`, binds `Cmd+I` (`Ctrl+Shift+I` on Linux), and finds your key in `OPENAI_API_KEY`.

## All options

These are the defaults:

```lua
commander.apply_to_config(config, {
  key = "i",                     -- set to false to bind it yourself (see below)
  mods = "CMD",                  -- "CTRL|SHIFT" on Linux

  model = "gpt-6-luna",
  base_url = nil,                -- nil uses $OPENAI_BASE_URL, then https://api.openai.com/v1
  api_key_env = nil,             -- nil means OPENAI_API_KEY (see "The API key")
  api_key_command = nil,
  api_key = nil,
  reasoning_effort = nil,        -- nil: "none" for gpt-6-luna (fastest), not sent for other models
  timeout = 60,                  -- seconds; raise it for slow local models

  height = 0.4,                  -- drawer height as a fraction of the tab
  screen_context_lines = 0,      -- send this many lines of your pane's output along
  python = nil,                  -- path to python3; nil finds one
  helper = nil,                  -- path to commander.py; nil finds it in the installed plugin
})
```

## The API key

The drawer looks for a key in this order:

1. `api_key` in your plugin options. Works, but it puts the key in your config file.
2. The environment variable named by `api_key_env` (default `OPENAI_API_KEY`).
3. If that's empty: the output of `api_key_command` when you set one, otherwise your login shell. WezTerm started from the macOS Dock doesn't see variables exported in `~/.zshrc`, so the drawer starts your shell once in the background (`$SHELL -l -i -c env`) and reads them from there. `OPENAI_BASE_URL` is picked up the same way. This takes under a second and happens while you're still typing.

Your OpenAI key only goes to OpenAI, or to `$OPENAI_BASE_URL` if you set that, which is the convention the official SDKs follow. If you point `base_url` at another provider, name that provider's key with `api_key_env` or `api_key_command`. The drawer won't quietly send your OpenAI key there. It also refuses to send any key over plain `http://` except to localhost, and it doesn't follow redirects.

If you keep the key in a password manager:

```lua
commander.apply_to_config(config, {
  -- 1Password
  api_key_command = "op read op://Private/OpenAI/credential",
  -- or the macOS keychain: security add-generic-password -s openai -a "$USER" -w
  -- api_key_command = "security find-generic-password -s openai -w",
})
```

## Other providers

Anything that speaks the OpenAI chat completions API works. Point `base_url` at it and pick a model:

```lua
-- Ollama
commander.apply_to_config(config, { base_url = "http://localhost:11434/v1", model = "qwen2.5-coder:7b" })

-- LM Studio
commander.apply_to_config(config, { base_url = "http://localhost:1234/v1", model = "your-loaded-model" })

-- OpenRouter
commander.apply_to_config(config, {
  base_url = "https://openrouter.ai/api/v1",
  model = "openai/gpt-6-luna",     -- any model id OpenRouter lists
  api_key_env = "OPENROUTER_API_KEY",
})
```

Local servers don't need a key. If none is found, the request goes out without one.

Small local models are slower and wrong more often. A 4B model can take close to a minute per answer on a laptop, so raise `timeout` if you go that way.

## Screen context

With `screen_context_lines = 80`, the last 80 lines of the pane you came from go along with your question. Then "fix that error" or "rerun that with sudo" just work. It's off by default because whatever is on your screen, tokens and passwords included, gets sent to the model.

## Your own key binding

```lua
commander.apply_to_config(config, { key = false })

table.insert(config.keys, { key = "k", mods = "CTRL|ALT", action = commander.action() })
```

You can also call `commander.toggle(window, pane)` from your own `action_callback`.

## Every key in the drawer

The bar at the bottom of the drawer always shows the keys that work right now. The full list:

| Key | What it does |
| --- | --- |
| Type, then `Enter` | Ask. Once there's a suggestion, whatever you type is feedback on it ("only .js files", "use rg instead"). |
| `Enter` with nothing typed | Use the suggested command: it's pasted into your pane and you jump back there. If the command comes with a warning, press `Enter` a second time to confirm. |
| `Ctrl+R` | Different command: get another command for the same task. |
| `Ctrl+L` | Start a new chat. |
| `Esc` or `Ctrl+D` | Hide the drawer. While waiting for an answer, `Esc` cancels instead. |
| `Ctrl+C` | Clear what you've typed. With nothing typed, hide the drawer. |
| `Up` / `Down` | Bring back questions you asked before. |
| `Ctrl+A`, `Ctrl+E`, `Ctrl+B`, `Ctrl+F`, `Ctrl+W`, `Ctrl+U`, `Ctrl+K`, `Alt+B`, `Alt+F` | The usual line editing. |

Each pane has its own chat. Hide the drawer, do something else, press the key again, and the conversation is still there. Chats untouched for a day start fresh.

## Updating

Run `wezterm.plugin.update_all()` from the debug overlay (`Ctrl+Shift+L`), then reload your config.
