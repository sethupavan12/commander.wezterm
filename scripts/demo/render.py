"""Render frames.jsonl (real WezTerm pane snapshots) into PNG frames that look like the window.

Usage: render.py <frames.jsonl> <outdir> [scale]
Writes outdir/NNNNN.png and outdir/frames.txt, an ffmpeg concat list with real durations.
Needs Pillow: `uv run --with pillow python render.py ...`.

Fonts default to MesloLGS Nerd Font Mono in ~/Library/Fonts; set DEMO_FONT_DIR,
DEMO_FONT and DEMO_FONT_BOLD to use others.
"""

import json
import os
import re
import sys
import unicodedata

from PIL import Image, ImageDraw, ImageFont

FONT_DIR = os.environ.get("DEMO_FONT_DIR", os.path.expanduser("~/Library/Fonts"))
FONT = os.path.join(FONT_DIR, os.environ.get("DEMO_FONT", "MesloLGSNerdFontMono-Regular.ttf"))
FONT_BOLD = os.path.join(FONT_DIR, os.environ.get("DEMO_FONT_BOLD", "MesloLGSNerdFontMono-Bold.ttf"))
FALLBACK = "/System/Library/Fonts/Apple Symbols.ttf"
TITLE = os.environ.get("DEMO_TITLE", "~/demo-app")

SIZE = 32  # render at 2x for crisp text; the scale argument shrinks it at the end
FG, BG, CURSOR = (0xCB, 0xE0, 0xF0), (0x01, 0x14, 0x23), (0x47, 0xFF, 0x9C)
CHROME, CHROME_TEXT, SPLIT, OVERLAY = (0x0A, 0x1E, 0x2E), (0x7B, 0x9A, 0xAA), (0x21, 0x49, 0x69), (0xA2, 0x77, 0xFF)
ANSI = ["#214969", "#E52E2E", "#44FFB1", "#FFE073", "#0FC5ED", "#a277ff", "#24EAF7", "#24EAF7"]
BRIGHT = ["#214969", "#E52E2E", "#44FFB1", "#FFE073", "#A277FF", "#a277ff", "#24EAF7", "#24EAF7"]
PAD_X, PAD_Y, TITLE_H = 40, 24, 56


def rgb(h):
    return tuple(int(h.lstrip("#")[i : i + 2], 16) for i in (0, 2, 4))


ANSI, BRIGHT = [rgb(c) for c in ANSI], [rgb(c) for c in BRIGHT]
regular, bold = ImageFont.truetype(FONT, SIZE), ImageFont.truetype(FONT_BOLD, SIZE)
fallback = ImageFont.truetype(FALLBACK, SIZE) if os.path.exists(FALLBACK) else regular
CELL_W, CELL_H = round(regular.getlength("M")), round(SIZE * 1.2)
glyphs = {}


def font_for(ch, is_bold):
    if (ch, is_bold) not in glyphs:
        primary = bold if is_bold else regular
        try:
            ok = ch.isspace() or primary.getmask(ch).getbbox() is not None
        except Exception:
            ok = False
        glyphs[(ch, is_bold)] = primary if ok else fallback
    return glyphs[(ch, is_bold)]


def blend(a, b, t):
    return tuple(round(x * (1 - t) + y * t) for x, y in zip(a, b))


def apply_sgr(state, params):
    ps = [int(p or 0) for p in re.split("[;:]", params)] or [0]
    i = 0
    while i < len(ps):
        p = ps[i]
        if p == 0:
            state.clear()
        elif p in (1, 2, 7):
            state[{1: "b", 2: "d", 7: "r"}[p]] = True
        elif p == 22:
            state.pop("b", None)
            state.pop("d", None)
        elif p == 27:
            state.pop("r", None)
        elif 30 <= p <= 37 or 90 <= p <= 97:
            state["fg"] = (ANSI if p < 90 else BRIGHT)[p % 10]
        elif 40 <= p <= 47:
            state["bg"] = ANSI[p - 40]
        elif p in (39, 49):
            state.pop("fg" if p == 39 else "bg", None)
        elif p in (38, 48) and i + 2 < len(ps) and ps[i + 1] == 5:
            state["fg" if p == 38 else "bg"] = (ANSI + BRIGHT)[ps[i + 2]] if ps[i + 2] < 16 else FG
            i += 2
        elif p in (38, 48) and i + 4 < len(ps) and ps[i + 1] == 2:
            state["fg" if p == 38 else "bg"] = tuple(ps[i + 2 : i + 5])
            i += 4
        i += 1


def parse(text, cols, rows):
    """Escaped pane text -> rows x cols grid of (char, fg, bg, bold)."""
    grid = [[(" ", FG, BG, False)] * cols for _ in range(rows)]
    state = {}
    for y, line in enumerate(text.split("\n")[:rows]):
        x = 0
        for tok in re.split(r"(\x1b\[[0-9;:]*m)", re.sub(r"\x1b\([B0]", "", line)):
            m = re.fullmatch(r"\x1b\[([0-9;:]*)m", tok)
            if m:
                apply_sgr(state, m.group(1))
                continue
            for ch in tok:
                if x >= cols:
                    break
                fg, bg = state.get("fg", FG), state.get("bg", BG)
                if state.get("d"):
                    fg = blend(fg, bg, 0.5)
                if state.get("r"):
                    fg, bg = bg, fg
                grid[y][x] = (ch, fg, bg, bool(state.get("b")))
                x += 2 if unicodedata.east_asian_width(ch) in "WF" else 1
    return grid


def render(frame, cols, rows):
    width, height = PAD_X * 2 + cols * CELL_W, TITLE_H + PAD_Y * 2 + rows * CELL_H
    img = Image.new("RGB", (width, height), BG)
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, width, TITLE_H], fill=CHROME)
    for i, color in enumerate([(0xFF, 0x5F, 0x57), (0xFE, 0xBC, 0x2E), (0x28, 0xC8, 0x40)]):
        cx, cy = 28 + i * 40, TITLE_H // 2
        d.ellipse([cx - 12, cy - 12, cx + 12, cy + 12], fill=color)
    small = ImageFont.truetype(FONT, int(SIZE * 0.8))
    d.text(((width - small.getlength(TITLE)) / 2, TITLE_H / 2 - SIZE * 0.45), TITLE, font=small, fill=CHROME_TEXT)

    ox, oy = PAD_X, TITLE_H + PAD_Y
    panes = frame["panes"]
    for p in panes:
        pc, pr = p["size"]["cols"], p["size"]["rows"]
        grid = parse(p["text"], pc, pr)
        dim = not p["is_active"] and len(panes) > 1  # inactive_pane_hsb = { brightness = 0.5 }
        show_cursor = p["is_active"] and p.get("cursor_visibility", "Visible") == "Visible"
        for y in range(pr):
            for x in range(pc):
                ch, fg, bg, is_bold = grid[y][x]
                if dim:
                    fg = blend(fg, (0, 0, 0), 0.5)
                    bg = bg if bg == BG else blend(bg, (0, 0, 0), 0.5)
                if show_cursor and x == p["cursor_x"] and y == p["cursor_y"]:
                    fg, bg = BG, CURSOR
                X, Y = ox + (p["left_col"] + x) * CELL_W, oy + (p["top_row"] + y) * CELL_H
                if bg != BG:
                    d.rectangle([X, Y, X + CELL_W - 1, Y + CELL_H - 1], fill=bg)
                if ch != " ":
                    d.text((X, Y + (CELL_H - SIZE) / 2 - 2), ch, font=font_for(ch, is_bold), fill=fg)
        if p["top_row"] > 0:
            sy = oy + p["top_row"] * CELL_H - CELL_H // 2
            d.line([ox, sy, ox + cols * CELL_W, sy], fill=SPLIT, width=2)

    label = frame.get("overlay")
    if label:
        big = ImageFont.truetype(FONT_BOLD, int(SIZE * 1.1))
        bw, bh = big.getlength(label) + 48, SIZE * 1.1 + 32
        bx, by = width - bw - 36, TITLE_H + PAD_Y + CELL_H * 4.5
        d.rounded_rectangle([bx, by, bx + bw, by + bh], radius=18, fill=OVERLAY)
        d.text((bx + 24, by + 13), label, font=big, fill=BG)
    return img


def main():
    src, outdir = sys.argv[1], sys.argv[2]
    scale = float(sys.argv[3]) if len(sys.argv) > 3 else 0.5
    with open(src) as fh:
        frames = [json.loads(line) for line in fh]
    os.makedirs(outdir, exist_ok=True)
    cols = max(p["left_col"] + p["size"]["cols"] for f in frames for p in f["panes"])
    rows = max(p["top_row"] + p["size"]["rows"] for f in frames for p in f["panes"])
    unique, last = [], None
    for f in frames:  # identical snapshots become one longer frame
        key = json.dumps([f["panes"], f["overlay"]])
        if key != last:
            unique.append(f)
            last = key
    lines = []
    for n, f in enumerate(unique):
        img = render(f, cols, rows)
        if scale != 1:
            img = img.resize((int(img.width * scale), int(img.height * scale)), Image.LANCZOS)
        path = os.path.abspath(os.path.join(outdir, f"{n:05d}.png"))
        img.save(path)
        nxt = unique[n + 1]["t"] if n + 1 < len(unique) else f["t"] + 2.5
        lines.append("file '{}'\nduration {:.3f}".format(path, max(0.04, nxt - f["t"])))
    lines.append(f"file '{path}'")  # ffmpeg's concat demuxer ignores the last duration otherwise
    with open(os.path.join(outdir, "frames.txt"), "w") as fh:
        fh.write("\n".join(lines) + "\n")
    print(f"{src}: {len(unique)} frames at {img.size[0]}x{img.size[1]}")


if __name__ == "__main__":
    main()
