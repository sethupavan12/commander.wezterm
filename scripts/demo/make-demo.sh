#!/bin/sh
# Regenerate the README demos from a real WezTerm session against a real model.
#
#   OPENAI_API_KEY=... scripts/demo/make-demo.sh            # writes assets/hero.gif, assets/tour.gif
#   DEMO_API_KEY_COMMAND="op read ..." scripts/demo/make-demo.sh
#
# Opens a separate WezTerm window with its own HOME and mux socket, so your own
# session is never touched. Needs: wezterm, ffmpeg, uv (for Pillow), the MesloLGS
# Nerd Font (or DEMO_FONT_* overrides, see render.py), and about 1 GB of free disk
# for a few large files the demo searches for. Everything is deleted at the end.
set -eu

REPO=$(cd "$(dirname "$0")/../.." && pwd)
HERE="$REPO/scripts/demo"
OUT=${1:-"$REPO/assets"}
WORK=/tmp/cmdr-demo # keep it short: unix socket paths are limited to about 100 bytes
DEMO_HOME="$WORK/home"
APP="$DEMO_HOME/demo-app"
export DEMO_SOCKET="$WORK/mux.sock"

if [ -z "${OPENAI_API_KEY:-}" ] && [ -z "${DEMO_API_KEY_COMMAND:-}" ]; then
	echo "Set OPENAI_API_KEY or DEMO_API_KEY_COMMAND." >&2
	exit 1
fi

cleanup() {
	pkill -f "wezterm-gui --config-file $WORK/demo.lua" 2>/dev/null || true
	for pid in $(pgrep -f "wezterm-mux-server" || true); do
		lsof -p "$pid" 2>/dev/null | grep -q "$DEMO_SOCKET" && kill "$pid" 2>/dev/null || true
	done
	rm -rf "$WORK"
}
trap cleanup EXIT INT TERM
cleanup
mkdir -p "$APP/src/components" "$APP/logs" "$APP/assets/video" "$APP/dist" "$APP/node_modules/.cache" "$APP/scripts"

# A small project with a few genuinely large files (du reports real disk usage, so no sparse files).
(
	cd "$APP"
	printf '{\n  "name": "demo-app",\n  "scripts": { "dev": "vite", "build": "vite build" }\n}\n' >package.json
	echo "# demo-app" >README.md
	touch src/main.ts src/App.tsx src/components/Header.tsx src/components/Footer.tsx scripts/deploy.sh vite.config.ts tsconfig.json
	for spec in assets/video/launch-teaser.mov:412 logs/app.log:236 node_modules/.cache/webpack.pack:182 dist/bundle.js.map:128; do
		dd if=/dev/zero of="${spec%%:*}" bs=1048576 count="${spec##*:}" 2>/dev/null
	done
	git init -q && git add -A && git -c user.name=demo -c user.email=demo@example.com commit -qm init
)
cat >"$DEMO_HOME/.zshrc" <<'EOF'
PROMPT='%F{magenta}%~%f %F{green}❯%f '
unsetopt PROMPT_SP
cd ~/demo-app
EOF

KEY_LINE=""
[ -n "${DEMO_API_KEY_COMMAND:-}" ] && KEY_LINE="api_key_command = [[$DEMO_API_KEY_COMMAND]],"
cat >"$WORK/demo.lua" <<EOF
local wezterm = require("wezterm")
local commander = dofile("$REPO/plugin/init.lua")
local config = wezterm.config_builder()
config.font_dirs = { "${DEMO_FONT_DIR:-$HOME/Library/Fonts}" }
config.font = wezterm.font("MesloLGS Nerd Font Mono")
config.font_size = 16
config.initial_cols = 92
config.initial_rows = 22
config.window_padding = { left = 20, right = 20, top = 12, bottom = 12 }
config.colors = {
	foreground = "#CBE0F0", background = "#011423",
	cursor_bg = "#47FF9C", cursor_border = "#47FF9C", cursor_fg = "#011423",
	ansi = { "#214969", "#E52E2E", "#44FFB1", "#FFE073", "#0FC5ED", "#a277ff", "#24EAF7", "#24EAF7" },
	brights = { "#214969", "#E52E2E", "#44FFB1", "#FFE073", "#A277FF", "#a277ff", "#24EAF7", "#24EAF7" },
}
config.inactive_pane_hsb = { brightness = 0.5 }
config.enable_tab_bar = false
config.unix_domains = { { name = "demo", socket_path = "$DEMO_SOCKET" } }
config.default_gui_startup_args = { "connect", "demo" }
config.window_close_confirmation = "NeverPrompt"
config.set_environment_variables = { ZDOTDIR = "$DEMO_HOME" }
commander.apply_to_config(config, {
	helper = "$REPO/plugin/commander.py",
	height = 0.55,
	$KEY_LINE
})
-- record.py presses the hotkey by writing this user var to the shell's tty.
wezterm.on("user-var-changed", function(window, pane, name)
	if name == "demo_hotkey" then
		commander.toggle(window, pane)
	end
end)
return config
EOF

HOME="$DEMO_HOME" WEZTERM_CONFIG_FILE="$WORK/demo.lua" \
	wezterm --config-file "$WORK/demo.lua" connect demo >"$WORK/gui.log" 2>&1 &
for _ in $(seq 1 40); do
	WEZTERM_UNIX_SOCKET="$DEMO_SOCKET" wezterm cli list >/dev/null 2>&1 && break
	sleep 0.5
done
sleep 2

take() { # take <scene>: fresh chat, `ls` on screen, then record
	export WEZTERM_UNIX_SOCKET="$DEMO_SOCKET"
	[ "$1" != warning ] && rm -rf "$DEMO_HOME/.local/state/wezterm-commander"
	wezterm cli send-text --pane-id 0 --no-paste "$(printf '\025')clear; ls
"
	sleep 1.2
	python3 "$HERE/record.py" "$1" "$WORK/$1.jsonl"
	wezterm cli send-text --pane-id 0 --no-paste "$(printf '\025')"
}
take hero
take tour
take warning

render() { uv run -q --with pillow python "$HERE/render.py" "$@"; }
render "$WORK/hero.jsonl" "$WORK/hero" 0.65
render "$WORK/tour.jsonl" "$WORK/tour" 0.5
render "$WORK/warning.jsonl" "$WORK/warning" 0.5
{
	sed '$d' "$WORK/tour/frames.txt"
	cat "$WORK/warning/frames.txt"
} >"$WORK/full.txt"

gif() { # gif <concat list> <output>
	ffmpeg -y -loglevel error -f concat -safe 0 -i "$1" -vf \
		"fps=15,split[a][b];[a]palettegen=max_colors=128:stats_mode=diff[p];[b][p]paletteuse=dither=bayer:bayer_scale=5:diff_mode=rectangle" "$2"
}
mkdir -p "$OUT"
gif "$WORK/hero/frames.txt" "$OUT/hero.gif"
gif "$WORK/full.txt" "$OUT/tour.gif"
ffmpeg -y -loglevel error -f concat -safe 0 -i "$WORK/full.txt" \
	-vf "fps=30,scale=trunc(iw/2)*2:trunc(ih/2)*2,format=yuv420p" -c:v libx264 -crf 20 -movflags +faststart "$OUT/tour.mp4"
ls -la "$OUT/hero.gif" "$OUT/tour.gif" "$OUT/tour.mp4"
