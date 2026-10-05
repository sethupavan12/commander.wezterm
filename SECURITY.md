# Security policy

## Reporting a vulnerability

Please don't open a public issue. Use GitHub's private reporting instead: the **Security** tab of this repository, then **Report a vulnerability**. You'll get a reply within a week.

## What counts

commander.wezterm sits between a language model and your shell, so these matter most:

- Getting text pasted into a pane, or a pasted command executed, without the user pressing Enter in the drawer.
- Escape sequences from a model reply, a server error or a file name reaching the terminal.
- Leaking the API key: sending it to a host other than the configured one, over plain http, or writing it to disk.
- Making a non-drawer pane act as a drawer.

Wrong or dangerous suggestions from the model are not vulnerabilities on their own. The drawer shows every command before it's used and never runs anything. Still, if you find a prompt that reliably produces a destructive command without a warning, an issue is welcome.
