"""Drive the demo WezTerm like a person would and snapshot every pane ~10x per second.

Usage: record.py <scene> <frames.jsonl>     (scenes: hero, tour, warning)

Each line of the output is one snapshot: pane geometry, cursor, the text with escapes,
and the label of the key being pressed (drawn as an overlay by render.py).
"""

import base64
import json
import os
import random
import subprocess
import sys
import threading
import time

ENV = {**os.environ, "WEZTERM_UNIX_SOCKET": os.environ.get("DEMO_SOCKET", "/tmp/cmdr-demo/mux.sock")}
frames = []
overlay = {"label": "", "until": 0.0}
stop = False
t0 = time.time()


def cli(*args):
    return subprocess.run(["wezterm", "cli", *args], capture_output=True, text=True, env=ENV).stdout


def panes():
    return json.loads(cli("list", "--format", "json"))


def capture_loop():
    while not stop:
        started = time.time()
        snap = [{**p, "text": cli("get-text", "--pane-id", str(p["pane_id"]), "--escapes")} for p in panes()]
        now = time.time() - t0
        frames.append({"t": now, "panes": snap, "overlay": overlay["label"] if now < overlay["until"] else ""})
        time.sleep(max(0, 0.1 - (time.time() - started)))


def show_key(label, seconds=0.9):
    overlay["label"], overlay["until"] = label, time.time() - t0 + seconds


def hotkey():
    """Press Cmd+I. The demo config listens for this user var, written straight to the shell's tty."""
    show_key("Cmd+I")
    shell = next(p for p in panes() if p["title"] != "commander")
    with open(shell["tty_name"], "w") as tty:
        tty.write(f"\x1b]1337;SetUserVar=demo_hotkey={base64.b64encode(str(time.time()).encode()).decode()}\x07")


def drawer_id():
    return next((p["pane_id"] for p in panes() if p["title"] == "commander"), None)


def wait_for(cond, timeout=60):
    end = time.time() + timeout
    while time.time() < end:
        value = cond()
        if value:
            return value
        time.sleep(0.05)
    raise SystemExit("timed out waiting")


def send(pane, text):
    subprocess.run(["wezterm", "cli", "send-text", "--pane-id", str(pane), "--no-paste", text], env=ENV)


def type_text(pane, text):
    for ch in text:
        send(pane, ch)
        time.sleep(random.uniform(0.035, 0.075) + (0.12 if ch == " " and random.random() < 0.15 else 0))


def press(pane, seq, label, seconds=0.9):
    show_key(label, seconds)
    time.sleep(0.25)
    send(pane, seq)


def answered(pane, count):
    text = cli("get-text", "--pane-id", str(pane))
    return text.count("$ ") >= count and "thinking" not in text


def hero():
    time.sleep(0.8)
    hotkey()
    d = wait_for(drawer_id)
    time.sleep(0.5)
    type_text(d, "biggest files over 100mb, with sizes")
    time.sleep(0.3)
    press(d, "\r", "Enter")
    wait_for(lambda: answered(d, 1))
    time.sleep(1.8)
    press(d, "\r", "Enter: use it", 1.2)
    wait_for(lambda: drawer_id() is None)
    time.sleep(0.9)
    press(0, "\r", "Enter: run it", 1.2)
    time.sleep(2.4)


def tour():
    time.sleep(1.4)
    hotkey()
    d = wait_for(drawer_id)
    time.sleep(0.9)
    type_text(d, "find files bigger than 100mb")
    time.sleep(0.4)
    press(d, "\r", "Enter")
    wait_for(lambda: answered(d, 1))
    time.sleep(2.2)
    type_text(d, "show human sizes, biggest first")
    time.sleep(0.4)
    press(d, "\r", "Enter")
    wait_for(lambda: answered(d, 2))
    time.sleep(2.8)
    press(d, "\r", "Enter: use it", 1.3)
    wait_for(lambda: drawer_id() is None)
    time.sleep(1.3)
    press(0, "\r", "Enter: run it", 1.3)
    time.sleep(2.6)


def warning():
    time.sleep(1.0)
    hotkey()
    d = wait_for(drawer_id)
    time.sleep(0.8)
    press(d, "\x0c", "Ctrl+L: new chat", 1.2)
    time.sleep(0.6)
    type_text(d, "delete every node_modules folder in here")
    time.sleep(0.4)
    press(d, "\r", "Enter")
    wait_for(lambda: answered(d, 1))
    time.sleep(2.4)
    press(d, "\r", "Enter", 0.9)
    time.sleep(2.2)  # the second-Enter confirmation is on screen now
    press(d, "\x1b", "Esc: hide", 1.2)
    wait_for(lambda: drawer_id() is None)
    time.sleep(1.0)


if __name__ == "__main__":
    scene, out = sys.argv[1], sys.argv[2]
    threading.Thread(target=capture_loop, daemon=True).start()
    try:
        {"hero": hero, "tour": tour, "warning": warning}[scene]()
    finally:
        stop = True
        time.sleep(0.3)
        with open(out, "w") as fh:
            for f in frames:
                fh.write(json.dumps(f) + "\n")
        print(f"{scene}: {len(frames)} frames over {frames[-1]['t']:.1f}s")
