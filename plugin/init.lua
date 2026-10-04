-- commander.wezterm: press a key, describe what you want, get a shell command.
--
-- The UI lives in commander.py, which runs in a split at the bottom of the tab
-- (the "drawer"). It reports back through an OSC 1337 user var,
-- wezterm_commander_event = JSON {action = "insert" | "hide", text}, and this
-- file pastes the text into the pane the drawer was opened for and focuses it.
--
-- Any program can set user vars, so we only listen to panes we spawned. Drawers
-- are recorded in wezterm.GLOBAL (drawer pane id -> target pane id) and the
-- target always comes from that record, never from the event.
--
-- The drawer always closes by exiting its own process. To close it from here we
-- send it QUIT_SEQUENCE, a private escape sequence it treats as "exit now".

local wezterm = require("wezterm")

local M = {}

local EVENT_VAR = "wezterm_commander_event"
local QUIT_SEQUENCE = "\x1b[9999~"
local is_mac = wezterm.target_triple:find("darwin") ~= nil

M.defaults = {
	-- Hotkey that opens, focuses or hides the drawer.
	key = "i",
	mods = is_mac and "CMD" or "CTRL|SHIFT",

	-- Any OpenAI-compatible chat completions endpoint works.
	model = "gpt-6.1-sol",
	base_url = nil, -- nil: $OPENAI_BASE_URL, else https://api.openai.com/v1
	api_key_env = nil, -- nil: OPENAI_API_KEY, but only sent to OpenAI or $OPENAI_BASE_URL
	api_key_command = nil, -- e.g. "op read op://Private/OpenAI/credential"
	api_key = nil, -- discouraged; prefer api_key_env or api_key_command
	reasoning_effort = nil, -- nil: "low" for the default model, unset for others
	timeout = 60,

	-- Drawer height as a fraction of the tab.
	height = 0.4,

	-- Lines of the current pane's output to send along as context. 0 sends none.
	-- Handy for "fix that error", but whatever is on screen goes to the model.
	screen_context_lines = 0,

	-- Python 3.8+ interpreter. nil picks the first one found.
	python = nil,
}

local function file_exists(path)
	local f = io.open(path, "r")
	if f then
		f:close()
		return true
	end
	return false
end

local function find_helper()
	for _, plugin in ipairs(wezterm.plugin.list()) do
		local path = plugin.plugin_dir .. "/plugin/commander.py"
		if plugin.url:find("commander") and file_exists(path) then
			return path
		end
	end
	for _, plugin in ipairs(wezterm.plugin.list()) do
		local path = plugin.plugin_dir .. "/plugin/commander.py"
		if file_exists(path) then
			return path
		end
	end
	return nil
end

local function find_python(preferred)
	if preferred then
		return preferred
	end
	for _, path in ipairs({
		"/opt/homebrew/bin/python3",
		"/usr/local/bin/python3",
		"/usr/bin/python3",
		"/bin/python3",
	}) do
		if file_exists(path) then
			return path
		end
	end
	return "python3"
end

local function cwd_of(pane)
	local ok, cwd = pcall(function()
		return pane:get_current_working_dir()
	end)
	if not ok or not cwd then
		return nil
	end
	if type(cwd) == "string" then -- older WezTerm returns a file:// URL string
		local path = cwd:gsub("^file://[^/]*", "")
		return (path:gsub("%%(%x%x)", function(hex)
			return string.char(tonumber(hex, 16))
		end))
	end
	return cwd.file_path
end

local function get_pane(id)
	if not id then
		return nil
	end
	local ok, pane = pcall(wezterm.mux.get_pane, tonumber(id))
	if ok then
		return pane
	end
	return nil
end

local function drawers()
	if not wezterm.GLOBAL.commander_drawers then
		wezterm.GLOBAL.commander_drawers = {}
	end
	return wezterm.GLOBAL.commander_drawers
end

-- The pane id this pane is a drawer for, or nil if we did not spawn it. Pane ids
-- start over when the mux server restarts, so also check the pane runs Python.
local function drawer_target(pane)
	local target = drawers()[tostring(pane:pane_id())]
	if not target then
		return nil
	end
	local process = pane:get_foreground_process_name()
	if process and not process:lower():find("python") then
		return nil
	end
	return target
end

local function forget_drawer(pane)
	drawers()[tostring(pane:pane_id())] = nil
end

local function find_drawer(tab)
	for _, pane in ipairs(tab:panes()) do
		local target = drawer_target(pane)
		if target then
			return pane, target
		end
	end
	return nil
end

local function close_drawer(drawer)
	forget_drawer(drawer)
	drawer:send_text(QUIT_SEQUENCE)
end

local function open_drawer(window, pane, opts)
	local helper = opts.helper or find_helper()
	if not helper then
		window:toast_notification("commander", "Could not find commander.py in the plugin directory.", nil, 4000)
		return
	end

	local screen = nil
	if opts.screen_context_lines > 0 then
		screen = pane:get_lines_as_text(opts.screen_context_lines)
	end
	local cwd = cwd_of(pane)

	local config = {
		target = pane:pane_id(),
		model = opts.model,
		base_url = opts.base_url,
		api_key = opts.api_key,
		api_key_env = opts.api_key_env,
		api_key_command = opts.api_key_command,
		reasoning_effort = opts.reasoning_effort,
		timeout = opts.timeout,
		cwd = cwd,
		process = pane:get_foreground_process_name(),
		screen = screen,
	}

	local drawer = pane:split({
		direction = "Bottom",
		size = opts.height,
		top_level = true,
		cwd = cwd,
		args = { find_python(opts.python), helper },
		set_environment_variables = {
			WEZTERM_COMMANDER_CONFIG = wezterm.json_encode(config),
		},
	})
	drawers()[tostring(drawer:pane_id())] = pane:pane_id()
end

local function merge(opts)
	local merged = {}
	for k, v in pairs(M.defaults) do
		merged[k] = v
	end
	for k, v in pairs(opts or {}) do
		merged[k] = v
	end
	return merged
end

-- Hotkey behaviour, in order:
--   in the drawer            -> hide it and go back to the original pane
--   drawer open for this pane -> focus it
--   drawer open for another   -> replace it with one for this pane
--   no drawer                 -> open one
function M.toggle(window, pane, opts)
	opts = opts or M.options or merge()
	local target = drawer_target(pane)
	if target then
		local original = get_pane(target)
		if original then
			original:activate()
		end
		close_drawer(pane)
		return
	end

	local drawer, drawer_for = find_drawer(pane:tab())
	if drawer and drawer_for == pane:pane_id() then
		drawer:activate()
		return
	end
	if drawer then
		close_drawer(drawer)
	end
	open_drawer(window, pane, opts)
end

local function on_event(window, pane, value)
	local target_id = drawer_target(pane)
	if not target_id then
		return -- not a drawer we spawned: ignore, whatever it claims
	end
	local ok, event = pcall(wezterm.json_parse, value)
	if not ok or type(event) ~= "table" then
		return
	end
	forget_drawer(pane) -- the drawer exits right after sending an event
	local target = get_pane(target_id)
	local text = type(event.text) == "string"
			and event.text:gsub("[%c]", function(c)
				return (c == "\n" or c == "\t") and c or ""
			end)
		or ""
	if event.action == "insert" and text ~= "" then
		if target then
			-- A paste, so shells with bracketed paste never run it, even if it spans lines.
			target:send_paste(text)
		elseif window then
			window:copy_to_clipboard(text)
			window:toast_notification("commander", "That pane is gone, so the command was copied instead.", nil, 4000)
		end
	end
	if target then
		target:activate()
	end
end

local handler_registered = false

local function register_handler()
	if handler_registered then
		return
	end
	handler_registered = true
	wezterm.on("user-var-changed", function(window, pane, name, value)
		if name == EVENT_VAR then
			on_event(window, pane, value)
		end
	end)
end

--- An action you can bind yourself, e.g. { key = "k", mods = "CTRL|ALT", action = commander.action() }.
function M.action(opts)
	register_handler()
	local merged = merge(opts)
	return wezterm.action_callback(function(window, pane)
		M.toggle(window, pane, merged)
	end)
end

--- Adds the hotkey (unless opts.key is false) and the event handler that inserts commands.
function M.apply_to_config(config, opts)
	local merged = merge(opts)
	M.options = merged
	register_handler()

	if merged.key then
		config.keys = config.keys or {}
		table.insert(config.keys, {
			key = merged.key,
			mods = merged.mods,
			action = M.action(merged),
		})
	end
end

return M
