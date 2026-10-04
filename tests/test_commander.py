"""Tests for plugin/commander.py. Standard library only: python3 -m unittest discover -s tests"""

import base64
import json
import os
import re
import stat
import sys
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "plugin"))

import commander as c  # noqa: E402

ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]|\x1b\][^\x07]*\x07")


def plain(text):
    return ANSI.sub("", text)


def user_vars(text):
    found = {}
    for name, value in re.findall(r"\x1b\]1337;SetUserVar=([^=]+)=([^\x07]*)\x07", text):
        found[name] = base64.b64decode(value).decode()
    return found


class ParseReplyTest(unittest.TestCase):
    def test_plain_json(self):
        s = c.parse_reply('{"command": "ls -la", "explanation": "", "warning": ""}')
        self.assertEqual((s.command, s.explanation, s.warning), ("ls -la", "", ""))

    def test_fenced_json_with_think_block(self):
        text = '<think>hmm, find?</think>\n```json\n{"command": "find . -size +1G", "explanation": "x"}\n```'
        s = c.parse_reply(text)
        self.assertEqual(s.command, "find . -size +1G")
        self.assertEqual(s.explanation, "x")

    def test_json_with_surrounding_prose(self):
        s = c.parse_reply('Sure! {"command": "du -sh *", "warning": "none"} Hope that helps.')
        self.assertEqual(s.command, "du -sh *")
        self.assertEqual(s.warning, "none")

    def test_code_fence_fallback(self):
        s = c.parse_reply("Use this:\n```bash\ngit log --oneline\n```\nShows history.")
        self.assertEqual(s.command, "git log --oneline")
        self.assertIn("Shows history.", s.explanation)

    def test_bare_text_fallback(self):
        self.assertEqual(c.parse_reply("  pwd \n").command, "pwd")

    def test_list_and_null_fields(self):
        s = c.parse_reply('{"command": "a", "explanation": ["one", "two"], "warning": null}')
        self.assertEqual(s.explanation, "one\ntwo")
        self.assertEqual(s.warning, "")

    def test_braces_inside_command(self):
        s = c.parse_reply('{"command": "awk \'{print $1}\' f", "explanation": ""}')
        self.assertEqual(s.command, "awk '{print $1}' f")


class SanitizeTest(unittest.TestCase):
    INJECT = "\x1b]1337;SetUserVar=wezterm_commander_event=eyJ9\x07\x1b[2J\u202eevil\x9b31m"

    def test_reply_fields_lose_control_characters(self):
        reply = json.dumps({"command": "ls" + self.INJECT, "explanation": "x" + self.INJECT, "warning": self.INJECT})
        s = c.parse_reply(reply)
        for field in (s.command, s.explanation, s.warning):
            self.assertNotRegex(field, "[\x1b\x07\x9b\u202e]")
        rendered = c.render_suggestion(s, 80)
        self.assertNotIn("SetUserVar", rendered.replace("SetUserVar=wezterm", ""))  # text survives, escapes do not
        self.assertNotIn("\x1b]", rendered)

    def test_newlines_and_tabs_survive(self):
        self.assertEqual(c.sanitize("a\tb\nc\x00"), "a\tb\nc")

    def test_errors_and_user_text_are_sanitized(self):
        self.assertNotIn("\x1b]", c.render_error("bad \x1b]0;title\x07", 80))
        self.assertNotIn("\x1b]", c.render_user("hi \x1b]0;title\x07"))


class KeyDecoderTest(unittest.TestCase):
    def names(self, data, decoder=None):
        decoder = decoder or c.KeyDecoder()
        return [(k.name, k.text) for k in decoder.feed(data)]

    def test_text_and_enter(self):
        self.assertEqual(self.names(b"hi\r"), [("text", "hi"), ("enter", "")])

    def test_arrows_and_editing_keys(self):
        keys = self.names(b"\x1b[A\x1b[B\x1b[C\x1b[D\x1bOH\x1b[3~\x7f\x17\x01\x05\x15\x0b")
        self.assertEqual(
            [n for n, _ in keys],
            ["up", "down", "right", "left", "home", "delete", "backspace", "kill-word", "home", "end",
             "kill-start", "kill-end"],
        )  # fmt: skip

    def test_control_keys(self):
        self.assertEqual([n for n, _ in self.names(b"\x03\x04\x0c\x12")], ["ctrl-c", "ctrl-d", "ctrl-l", "ctrl-r"])

    def test_bare_escape_waits_for_flush(self):
        d = c.KeyDecoder()
        self.assertEqual(d.feed(b"\x1b"), [])
        self.assertEqual([k.name for k in d.flush()], ["esc"])

    def test_escape_sequence_split_across_reads(self):
        d = c.KeyDecoder()
        self.assertEqual(d.feed(b"\x1b"), [])
        self.assertEqual([k.name for k in d.feed(b"[D")], ["left"])

    def test_utf8_split_across_reads(self):
        d = c.KeyDecoder()
        data = "日本".encode()
        self.assertEqual(d.feed(data[:2]), [])
        self.assertEqual([(k.name, k.text) for k in d.feed(data[2:])], [("text", "日本")])

    def test_bracketed_paste(self):
        keys = self.names(b"\x1b[200~line one\nline two\x1b[201~x")
        self.assertEqual(keys, [("paste", "line one\nline two"), ("text", "x")])

    def test_paste_split_across_reads(self):
        d = c.KeyDecoder()
        self.assertEqual(d.feed(b"\x1b[200~abc"), [])
        self.assertEqual([(k.name, k.text) for k in d.feed(b"def\x1b[201~")], [("paste", "abcdef")])

    def test_quit_sequence_from_lua(self):
        self.assertEqual([n for n, _ in self.names(b"\x1b[9999~")], ["quit"])

    def test_alt_word_movement(self):
        self.assertEqual([n for n, _ in self.names(b"\x1bb\x1bf\x1b\x7f")], ["word-left", "word-right", "kill-word"])

    def test_invalid_byte_does_not_stall_input(self):
        self.assertEqual(self.names(b"\xffab"), [("text", "\ufffdab")])

    def test_unknown_csi_is_dropped(self):
        self.assertEqual(self.names(b"\x1b[15~a"), [("text", "a")])


class LineEditorTest(unittest.TestCase):
    def apply(self, editor, *names):
        for name in names:
            editor.handle(c.Key(name))

    def test_insert_and_move(self):
        e = c.LineEditor("hello world")
        self.apply(e, "home", "right")
        e.handle(c.Key("text", "X"))
        self.assertEqual(e.text, "hXello world")

    def test_kill_word_and_lines(self):
        e = c.LineEditor("git commit --amend")
        self.apply(e, "kill-word")
        self.assertEqual(e.text, "git commit ")
        self.apply(e, "word-left", "kill-end")
        self.assertEqual(e.text, "git ")
        self.apply(e, "kill-start")
        self.assertEqual((e.text, e.pos), ("", 0))

    def test_paste_flattens_newlines(self):
        e = c.LineEditor()
        e.handle(c.Key("paste", "a\nb\r\nc\td"))
        self.assertEqual(e.text, "a b c d")

    def test_backspace_and_delete_at_edges(self):
        e = c.LineEditor("ab")
        self.apply(e, "delete")
        self.assertEqual(e.text, "ab")
        self.apply(e, "home", "backspace")
        self.assertEqual(e.text, "ab")

    def test_non_editing_key_is_not_consumed(self):
        self.assertFalse(c.LineEditor().handle(c.Key("enter")))

    def test_view_scrolls_to_keep_cursor_visible(self):
        e = c.LineEditor("abcdefghijklmnopqrstuvwxyz")
        visible, cursor = e.view(10)
        self.assertTrue(visible.startswith("q") or "z" in visible)
        self.assertLessEqual(cursor, 9)
        self.apply(e, "home")
        visible, cursor = e.view(10)
        self.assertEqual((visible, cursor), ("abcdefghij", 0))

    def test_view_is_fast_on_huge_input(self):
        e = c.LineEditor("x" * 100000)
        started = time.time()
        visible, cursor = e.view(80)
        self.assertLess(time.time() - started, 0.05)
        self.assertEqual((len(visible), cursor), (79, 79))

    def test_view_counts_wide_characters(self):
        e = c.LineEditor("日本語日本語")
        visible, cursor = e.view(6)
        self.assertLessEqual(c.text_width(visible), 6)
        self.assertLessEqual(cursor, 5)


class RenderingTest(unittest.TestCase):
    def test_hard_wrap_prefers_spaces(self):
        rows = c.hard_wrap("find . -type f -exec du -ch {} + | sort -n | head -n 5", 30)
        self.assertTrue(all(c.text_width(r) <= 30 for r in rows))
        self.assertEqual(" ".join(rows), "find . -type f -exec du -ch {} + | sort -n | head -n 5")

    def test_hard_wrap_splits_unbroken_text(self):
        rows = c.hard_wrap("x" * 25, 10)
        self.assertEqual(rows, ["x" * 10, "x" * 10, "x" * 5])

    def test_suggestion_layout(self):
        s = c.Suggestion("rm -rf build", "`-r` recurses into folders.", "Deletes build/ for good.")
        lines = plain(c.render_suggestion(s, 80)).split("\n")
        self.assertEqual(lines[0], "  $ rm -rf build")
        self.assertEqual(lines[1], "    -r recurses into folders.")
        self.assertEqual(lines[2], "    ⚠ Deletes build/ for good.")
        self.assertEqual(lines[3:], ["", ""])

    def test_backticks_are_highlighted(self):
        out = c.render_suggestion(c.Suggestion("ls", "use `-a`"), 80)
        self.assertIn(c.CYAN + "-a" + c.RESET, out)

    def test_empty_suggestion_says_so(self):
        self.assertIn("empty answer", plain(c.render_suggestion(c.Suggestion(), 80)))

    def test_multiline_command(self):
        lines = plain(c.render_suggestion(c.Suggestion("for f in *; do\n  echo $f\ndone"), 80)).split("\n")
        self.assertEqual(lines[:3], ["  $ for f in *; do", "      echo $f", "    done"])

    def test_fit_path(self):
        self.assertEqual(c.fit_path("/a/b/c/d/eeeeee", 11), "…/d/eeeeee")
        self.assertEqual(c.fit_path("/short", 40), "/short")


class ConfigTest(unittest.TestCase):
    def test_defaults(self):
        cfg = c.Config.from_env({"SHELL": "/bin/zsh"})
        self.assertEqual(cfg.model, "gpt-6.1-sol")
        self.assertEqual(cfg.shell, "/bin/zsh")
        self.assertIsNone(cfg.target)
        self.assertTrue(cfg.state_dir.endswith("wezterm-commander"))

    def test_from_lua_json(self):
        data = {"target": "7", "model": "m", "timeout": 5, "process": "/usr/bin/vim"}
        cfg = c.Config.from_env({"WEZTERM_COMMANDER_CONFIG": json.dumps(data), "SHELL": "/bin/bash"})
        self.assertEqual((cfg.target, cfg.model, cfg.timeout), (7, "m", 5.0))
        self.assertEqual(cfg.shell, "/bin/bash")  # vim is not a shell, fall back to $SHELL
        self.assertIsNone(cfg.remote)

    def test_foreground_shell_wins_over_login_shell(self):
        cfg = c.Config.from_env(
            {"WEZTERM_COMMANDER_CONFIG": '{"process": "/opt/homebrew/bin/fish"}', "SHELL": "/bin/zsh"}
        )
        self.assertEqual(cfg.shell, "/opt/homebrew/bin/fish")

    def test_remote_pane(self):
        data = {"process": "/usr/bin/ssh", "cwd": "/home/someone/on-a-server"}
        cfg = c.Config.from_env({"WEZTERM_COMMANDER_CONFIG": json.dumps(data), "SHELL": "/bin/zsh"})
        self.assertEqual((cfg.remote, cfg.remote_cwd, cfg.cwd), ("ssh", "/home/someone/on-a-server", os.getcwd()))
        text = c.describe_environment(cfg)
        self.assertIn("running `ssh`", text)
        self.assertIn("/home/someone/on-a-server", text)
        self.assertNotIn("Files here", text)  # never list the local directory for a remote pane
        self.assertNotIn("macOS", text)

    def test_unknown_cwd_is_not_replaced_by_a_local_listing(self):
        data = {"process": "zsh", "cwd": "/no/such/dir/here"}
        text = c.describe_environment(c.Config.from_env({"WEZTERM_COMMANDER_CONFIG": json.dumps(data)}))
        self.assertIn("/no/such/dir/here (on another machine", text)
        self.assertNotIn("Files here", text)

    def test_session_key_follows_the_mux_socket(self):
        with tempfile.NamedTemporaryFile() as sock:
            key = c.session_key(3, {"WEZTERM_UNIX_SOCKET": sock.name})
        self.assertRegex(key, r"^\d+-3$")
        self.assertEqual(c.session_key(3, {}), "3")

    def test_bad_json_is_ignored(self):
        self.assertEqual(c.Config.from_env({"WEZTERM_COMMANDER_CONFIG": "{nope"}).model, c.DEFAULT_MODEL)


class EnvironmentTest(unittest.TestCase):
    def test_system_prompt_mentions_context(self):
        with tempfile.TemporaryDirectory() as tmp:
            os.mkdir(os.path.join(tmp, "src"))
            open(os.path.join(tmp, "package.json"), "w").close()
            cfg = c.Config(cwd=tmp, shell="/bin/zsh", screen="$ make\nerror: missing ;")
            text = c.build_messages(cfg, [{"role": "user", "content": "x"}])[0]["content"]
        self.assertIn("Shell: zsh", text)
        self.assertIn("package.json, src/", text)
        self.assertIn("error: missing ;", text)
        self.assertIn('"command"', text)

    def test_directory_listing_is_capped(self):
        with tempfile.TemporaryDirectory() as tmp:
            for i in range(c.MAX_DIR_ENTRIES + 5):
                open(os.path.join(tmp, f"f{i:03d}"), "w").close()
            self.assertIn("(5 more)", c.list_directory(tmp))

    def test_history_is_trimmed(self):
        history = [{"role": "user", "content": str(i)} for i in range(100)]
        messages = c.build_messages(c.Config(cwd="/"), history)
        self.assertEqual(len(messages), c.MAX_HISTORY_MESSAGES + 1)
        self.assertEqual(messages[-1]["content"], "99")


class StoreTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cfg = c.Config(target=3, state_dir=self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_session_roundtrip_and_clear(self):
        store = c.Store(self.cfg)
        store.save_session([{"role": "user", "content": "hi"}])
        self.assertEqual(c.Store(self.cfg).load_session(), [{"role": "user", "content": "hi"}])
        store.clear_session()
        self.assertEqual(store.load_session(), [])

    def test_sessions_are_per_pane(self):
        c.Store(self.cfg).save_session([{"role": "user", "content": "hi"}])
        self.assertEqual(c.Store(c.Config(target=4, state_dir=self.tmp.name)).load_session(), [])

    def test_stale_session_is_ignored(self):
        store = c.Store(self.cfg)
        store._write(store.session_path, {"updated": time.time() - c.SESSION_TTL_SECONDS - 1, "messages": [{}]})
        self.assertEqual(store.load_session(), [])

    def test_inputs_dedupe_and_order(self):
        store = c.Store(self.cfg)
        for text in ["a", "b", "a"]:
            store.add_input(text)
        self.assertEqual(store.load_inputs(), ["b", "a"])

    def test_state_is_private(self):
        cfg = c.Config(target=3, state_dir=os.path.join(self.tmp.name, "state"))
        store = c.Store(cfg)
        store.add_input("x")
        self.assertEqual(stat.S_IMODE(os.stat(cfg.state_dir).st_mode), 0o700)
        self.assertEqual(stat.S_IMODE(os.stat(store.inputs_path).st_mode), 0o600)

    def test_corrupt_session_is_coerced(self):
        store = c.Store(self.cfg)
        bad = [{"role": "assistant", "content": {"oops": 1}}, {"role": "system", "content": "x"}, "junk"]
        store._write(store.session_path, {"updated": time.time(), "messages": bad})
        messages = store.load_session()
        self.assertEqual([m["role"] for m in messages], ["assistant"])
        c.parse_reply(messages[0]["content"])  # must not raise


class FakeServer:
    """A tiny OpenAI-compatible server running in a thread."""

    def __init__(self, status=200, payload=None, headers=None):
        self.requests = []
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                outer.requests.append({"path": self.path, "headers": dict(self.headers), "body": body})
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                for name, value in (headers or {}).items():
                    self.send_header(name, value)
                self.end_headers()
                default = {"choices": [{"message": {"content": '{"command": "ls"}'}}]}
                self.wfile.write(json.dumps(payload if payload is not None else default).encode())

        self.httpd = HTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.httpd.server_port}/v1"
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()


def creds_for(cfg, environ=None):
    return c.Credentials(cfg, environ if environ is not None else {"SHELL": "/bin/false"}).wait()


class ChatCompletionTest(unittest.TestCase):
    def test_request_shape(self):
        server = FakeServer()
        try:
            cfg = c.Config(base_url=server.url, api_key="sk-1", model="m1", reasoning_effort="low", cwd="/")
            reply = c.chat_completion(cfg, creds_for(cfg), [{"role": "user", "content": "x"}])
        finally:
            server.close()
        self.assertEqual(reply, '{"command": "ls"}')
        request = server.requests[0]
        self.assertEqual(request["path"], "/v1/chat/completions")
        self.assertEqual(request["headers"]["Authorization"], "Bearer sk-1")
        self.assertEqual(request["body"]["model"], "m1")
        self.assertEqual(request["body"]["reasoning_effort"], "low")
        self.assertNotIn("temperature", request["body"])

    def test_no_key_for_local_server_sends_no_auth(self):
        server = FakeServer()
        try:
            cfg = c.Config(base_url=server.url, cwd="/")
            c.chat_completion(cfg, creds_for(cfg), [])
        finally:
            server.close()
        self.assertNotIn("Authorization", server.requests[0]["headers"])

    def test_missing_key_for_openai_is_explained(self):
        cfg = c.Config(cwd="/")
        with self.assertRaisesRegex(c.ApiError, "No API key found"):
            c.chat_completion(cfg, creds_for(cfg), [])

    def test_http_errors_are_readable(self):
        cases = [
            (401, "API key was rejected"),
            (429, "Rate limited"),
            (404, "Model 'gpt-6.1-sol' not found"),
            (500, "HTTP 500: boom model"),
        ]
        for status, expected in cases:
            server = FakeServer(status, {"error": {"message": "boom model"}})
            try:
                cfg = c.Config(base_url=server.url, api_key="k", cwd="/")
                with self.assertRaisesRegex(c.ApiError, re.escape(expected)):
                    c.chat_completion(cfg, creds_for(cfg), [])
            finally:
                server.close()

    def test_key_is_never_sent_over_plain_http_to_other_hosts(self):
        cfg = c.Config(base_url="http://192.0.2.1/v1", api_key="k", cwd="/")
        with self.assertRaisesRegex(c.ApiError, "plain http"):
            c.chat_completion(cfg, creds_for(cfg), [])

    def test_redirects_are_not_followed(self):
        server = FakeServer(302, {"error": {"message": "moved"}}, headers={"Location": "http://127.0.0.1:9/v1"})
        try:
            cfg = c.Config(base_url=server.url, api_key="k", cwd="/")
            with self.assertRaisesRegex(c.ApiError, "HTTP 302"):
                c.chat_completion(cfg, creds_for(cfg), [])
        finally:
            server.close()

    def test_unreachable_server(self):
        cfg = c.Config(base_url="http://127.0.0.1:9/v1", api_key="k", cwd="/", timeout=2)
        with self.assertRaisesRegex(c.ApiError, "Could not reach"):
            c.chat_completion(cfg, creds_for(cfg), [])

    def test_content_parts_are_joined(self):
        server = FakeServer(payload={"choices": [{"message": {"content": [{"text": "a"}, {"text": "b"}]}}]})
        try:
            cfg = c.Config(base_url=server.url, api_key="k", cwd="/")
            self.assertEqual(c.chat_completion(cfg, creds_for(cfg), []), "ab")
        finally:
            server.close()


class CredentialsTest(unittest.TestCase):
    def test_precedence(self):
        cfg = c.Config(api_key="explicit")
        self.assertEqual(creds_for(cfg, {"OPENAI_API_KEY": "env"}).api_key, "explicit")
        self.assertEqual(creds_for(c.Config(), {"OPENAI_API_KEY": "env"}).api_key, "env")

    def test_custom_env_name_and_base_url(self):
        creds = creds_for(c.Config(api_key_env="GROQ_KEY"), {"GROQ_KEY": "g", "OPENAI_BASE_URL": "http://x/v1/"})
        self.assertEqual((creds.api_key, creds.base_url), ("g", "http://x/v1"))

    def test_openai_key_is_not_sent_to_a_custom_base_url(self):
        env = {"OPENAI_API_KEY": "sk-openai"}
        creds = creds_for(c.Config(base_url="https://api.example.com/v1"), env)
        self.assertIsNone(creds.api_key)
        explicit = creds_for(c.Config(base_url="https://api.example.com/v1", api_key_env="OPENAI_API_KEY"), env)
        self.assertEqual(explicit.api_key, "sk-openai")
        sdk_style = creds_for(c.Config(), {**env, "OPENAI_BASE_URL": "https://proxy.internal/v1"})
        self.assertEqual((sdk_style.api_key, sdk_style.base_url), ("sk-openai", "https://proxy.internal/v1"))

    def test_key_command(self):
        self.assertEqual(creds_for(c.Config(api_key_command="echo from-cmd")).api_key, "from-cmd")
        creds = creds_for(c.Config(api_key_command="echo nope >&2; exit 3"))
        self.assertIsNone(creds.api_key)
        self.assertIn("nope", creds.error)

    def test_login_shell_fallback(self):
        with tempfile.TemporaryDirectory() as tmp:
            shell = os.path.join(tmp, "fakesh")
            with open(shell, "w") as fh:
                # Behaves like `zsh -l -i -c CMD` whose profile exports the key and prints noise.
                fh.write('#!/bin/sh\necho "noise from rc file"\nOPENAI_API_KEY=from-profile\nexport OPENAI_API_KEY\n'
                         'shift 3\neval "$1"\n')  # fmt: skip
            os.chmod(shell, 0o755)
            creds = creds_for(c.Config(), {"SHELL": shell})
        self.assertEqual(creds.api_key, "from-profile")
        self.assertEqual(creds.base_url, c.DEFAULT_BASE_URL)


class FakeTerminal:
    """Feeds scripted keys to the Drawer and records what it writes."""

    def __init__(self, script):
        self.script = list(script)
        self.out = []
        self.resized = False
        self.fd = None

    def write(self, text):
        self.out.append(text)

    def width(self):
        return 80

    def read(self, decoder, timeout):
        if timeout is not None and timeout < 0.1:  # the spinner polling while a reply is pending
            time.sleep(0.005)
            return []
        if not self.script:
            raise EOFError
        return decoder.feed(self.script.pop(0)) + decoder.flush()

    @property
    def text(self):
        return "".join(self.out)


def typeahead_reader(term, typed):
    """A FakeTerminal.read that delivers `typed` once while a reply is pending."""
    original = term.read
    pending = [typed]

    def read(decoder, timeout):
        if timeout is not None and timeout < 0.1 and pending:
            return decoder.feed(pending.pop())
        return original(decoder, timeout)

    return read


class DrawerTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cfg = c.Config(target=42, state_dir=self.tmp.name, cwd=self.tmp.name, api_key="k", model="test-model")
        self.asked = []

    def tearDown(self):
        self.tmp.cleanup()

    def drawer(self, script, replies=None):
        replies = list(replies or [])

        def ask(messages):
            self.asked.append(messages)
            reply = replies.pop(0)
            if isinstance(reply, Exception):
                raise reply
            return reply

        term = FakeTerminal(script)
        return c.Drawer(self.cfg, term, ask=ask), term

    def test_ask_then_insert(self):
        drawer, term = self.drawer([b"list files\r", b"\r"], ['{"command": "ls -la", "explanation": ""}'])
        self.assertEqual(drawer.run(), 0)
        event = json.loads(user_vars(term.text)["wezterm_commander_event"])
        self.assertEqual((event["action"], event["text"]), ("insert", "ls -la"))
        self.assertIn("$ ls -la", plain(term.text))
        self.assertEqual(self.asked[0][-1], {"role": "user", "content": "list files"})

    def test_refine_keeps_conversation(self):
        replies = ['{"command": "ls"}', '{"command": "ls -t"}']
        drawer, term = self.drawer([b"list\r", b"newest first\r", b"\r"], replies)
        drawer.run()
        roles = [m["role"] for m in self.asked[1]]
        self.assertEqual(roles, ["system", "user", "assistant", "user"])
        self.assertEqual(json.loads(user_vars(term.text)["wezterm_commander_event"])["text"], "ls -t")

    def test_escape_hides_and_session_survives(self):
        drawer, term = self.drawer([b"list\r", b"\x1b"], ['{"command": "ls"}'])
        drawer.run()
        self.assertEqual(json.loads(user_vars(term.text)["wezterm_commander_event"])["action"], "hide")
        reopened, term2 = self.drawer([b"\r"])
        reopened.run()
        self.assertIn("$ ls", plain(term2.text))  # history redrawn
        self.assertEqual(json.loads(user_vars(term2.text)["wezterm_commander_event"])["text"], "ls")

    def test_ctrl_l_starts_over(self):
        drawer, term = self.drawer([b"list\r", b"\x0c", b"\r", b"\x1b"], ['{"command": "ls"}'])
        drawer.run()
        self.assertEqual(drawer.messages, [])
        self.assertEqual(c.Store(self.cfg).load_session(), [])
        self.assertEqual(json.loads(user_vars(term.text)["wezterm_commander_event"])["action"], "hide")

    def test_ctrl_r_asks_for_another(self):
        drawer, term = self.drawer([b"list\r", b"\x12", b"\r"], ['{"command": "ls"}', '{"command": "find ."}'])
        drawer.run()
        self.assertEqual(self.asked[1][-1]["content"], c.ANOTHER_PROMPT)
        self.assertIn("another option", plain(term.text))
        self.assertEqual(json.loads(user_vars(term.text)["wezterm_commander_event"])["text"], "find .")

    def test_error_restores_input(self):
        drawer, term = self.drawer([b"list\r"], [c.ApiError("quota gone")])
        drawer.run()
        self.assertIn("✗ quota gone", plain(term.text))
        self.assertEqual(drawer.editor.text, "list")
        self.assertEqual(drawer.messages, [])

    def test_quit_sequence_exits_silently(self):
        drawer, term = self.drawer([b"\x1b[9999~"])
        self.assertEqual(drawer.run(), 0)
        self.assertNotIn("wezterm_commander_event", user_vars(term.text))

    def test_enter_without_suggestion_does_nothing(self):
        drawer, term = self.drawer([b"\r"])
        drawer.run()
        self.assertNotIn("wezterm_commander_event", user_vars(term.text))
        self.assertEqual(self.asked, [])

    def test_typing_while_waiting_is_kept(self):
        drawer, _ = self.drawer([b"list\r"], ['{"command": "ls"}'])
        slow = drawer.ask

        def ask(messages):
            time.sleep(0.05)
            return slow(messages)

        drawer.ask = ask
        drawer.term.read = typeahead_reader(drawer.term, b"next q")
        drawer.run()
        self.assertEqual(drawer.editor.text, "next q")

    def test_multiline_command_gets_a_note(self):
        drawer, term = self.drawer([b"loop\r"], ['{"command": "for f in *; do\\n  echo $f\\ndone"}'])
        drawer.run()
        self.assertIn("multi-line", plain(term.text))

    def test_up_arrow_recalls_previous_question(self):
        drawer, _ = self.drawer([b"list\r", b"\x1b[A"], ['{"command": "ls"}'])
        drawer.run()
        self.assertEqual(drawer.editor.text, "list")

    def test_ctrl_c_clears_input_then_hides(self):
        drawer, term = self.drawer([b"half typed", b"\x03"])
        drawer.run()
        self.assertEqual(drawer.editor.text, "")
        self.assertNotIn("wezterm_commander_event", user_vars(term.text))
        drawer, term = self.drawer([b"\x03"])
        drawer.run()
        self.assertEqual(json.loads(user_vars(term.text)["wezterm_commander_event"])["action"], "hide")


if __name__ == "__main__":
    unittest.main()
