"""Guided tour -- a scripted demo that runs on its own timeline.

Letting the live model narrate between tool calls never synced: it talked
over itself, advanced early, and drifted at every step. So the tour owns its
timing. Narration is pre-generated to WAVs once and cached; each step starts
its actions, plays its line over the top, and moves on when both are done.
The model's only job is to trigger it and stay quiet.
"""

import os
import shutil
import socket
import subprocess
import sys
import threading
import time
import urllib.parse
from pathlib import Path

import narrate

MUSIC = ("https://www.youtube.com/watch?v=SXZcd-j882k"
         "&list=RDSXZcd-j882k&start_radio=1&t=0s")
DEMO_THEMES = ["Hackerman", "Catppuccin Latte", "Gruvbox", "Nord", "Matte Black"]
HOME_THEME = "Tokyo Night"

POST_TEXT = ("Posting this from Beckon — an open source voice agent built for "
             "Omarchy users. Gemini 3.1 live voice control for your desktop, and it "
             "can be adapted to other setups. github.com/Steven-Tibbs/beckon")


def _setting(key, default):
    """Read a value the user set in the panel's settings file, else the default.
    Keeps machine-specific things (a dev server URL, a custom line) out of the
    source and in ~/.config/beckon/settings.json, which is never committed."""
    import json
    try:
        got = json.loads((Path.home() / ".config" / "beckon" / "settings.json").read_text())
    except (OSError, ValueError):
        return default
    return got.get(key) or default


DEV_URL = _setting("dev_url", "http://localhost:3000")   # set dev_url in settings.json
DEV_LINE = _setting("dev_line",
                    "I can even open your local dev server and run your tests for you. "
                    "Here's the project you're working on.")
FINAL_LINE = "That's the tour. Ask me to do anything and I'll take care of it."
POST_LINE = ("I'm opening X now, with a post about this already drafted. "
             "Sending it is up to you — I never post on your behalf.")

_running = threading.Event()
STATE = Path(os.environ.get("XDG_RUNTIME_DIR", "/tmp")) / "beckon"
MUTE = STATE / "mute"
PANEL_URL = "http://127.0.0.1:8777/"


def _lua(x):
    return '"' + str(x).replace("\\", "\\\\").replace('"', '\\"') + '"'


def _h(lua):
    return subprocess.run(["hyprctl", "dispatch", lua],
                          capture_output=True, text=True, timeout=8).stdout.strip()


def _sh(*cmd, wait=10):
    return subprocess.run(cmd, capture_output=True, text=True, timeout=wait)


def _focus_class(pattern):
    import json
    try:
        for c in json.loads(_sh("hyprctl", "clients", "-j").stdout):
            if pattern.lower() in (c.get("class", "") + c.get("title", "")).lower():
                _h(f'hl.dsp.focus({{ window = "address:{c["address"]}" }})')
                return True
    except Exception:
        pass
    return False


# --------------------------------------------------------------- step actions

def _panel_open():
    return _focus_class("Beckon") or _focus_class("Beckon")


def _ensure_server():
    sk = socket.socket(); sk.settimeout(0.5)
    up = sk.connect_ex(("127.0.0.1", 8777)) == 0; sk.close()
    if not up:
        subprocess.Popen([sys.executable, str(Path(__file__).parent / "ui.py"), "--no-open"],
                         start_new_session=True,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(1.5)


def _panel_to_ws2():
    """Go to workspace 2 first, then put the panel there -- opening it in place
    if it isn't running, or pulling it over if it is."""
    _ensure_server()
    _h('hl.dsp.focus({ workspace = "2" })')
    time.sleep(0.4)
    if _panel_open():                       # focuses it, wherever it is
        time.sleep(0.2)
        _h('hl.dsp.window.move({ workspace = "2", follow = true })')
    else:
        _h(f'hl.dsp.exec_cmd("uwsm-app -- google-chrome-stable --app={PANEL_URL}")')
        time.sleep(3.5)
    time.sleep(0.3)
    _h('hl.dsp.focus({ workspace = "2" })')


def _mpris_play():
    """Ask Chrome's media session to play. Idempotent -- unlike the 'k' key,
    which toggles and would pause a video that already autoplayed."""
    r = _sh("busctl", "--user", "list", "--no-pager")
    for line in r.stdout.splitlines():
        name = line.split()[0] if line.strip() else ""
        if name.startswith("org.mpris.MediaPlayer2.chrom"):
            _sh("busctl", "--user", "call", name, "/org/mpris/MediaPlayer2",
                "org.mpris.MediaPlayer2.Player", "Play")
            # YouTube may resume from watch history; seek a full hour back, which
            # clamps to 0:00, so the video always starts from the beginning.
            _sh("busctl", "--user", "call", name, "/org/mpris/MediaPlayer2",
                "org.mpris.MediaPlayer2.Player", "Seek", "x", "-3600000000")


def _click_at(x, y):
    """Position with Hyprland (logical coords, verified), click with ydotool.
    Hyprland's own synthetic BTN_LEFT does not produce a real click."""
    _h(f"hl.dsp.cursor.move({{ x = {int(x)}, y = {int(y)}, absolute = true }})")
    time.sleep(0.25)
    if shutil.which("ydotool"):
        _sh("ydotool", "click", "0xC0", wait=5)
        return True
    return False


def _music():
    _h('hl.dsp.focus({ workspace = "3" })')
    time.sleep(0.4)
    _h(f'hl.dsp.exec_cmd("uwsm-app -- google-chrome-stable --new-window {MUSIC}")')
    time.sleep(6.5)
    _mpris_play()   # no-op if it already autoplayed


def _show_panel():
    _h('hl.dsp.focus({ workspace = "2" })')
    time.sleep(0.8)
    _h('hl.dsp.cursor.move({ x = 700, y = 500, absolute = true })')
    for _ in range(3):
        _sh("wtype", "-k", "Page_Down", wait=5)
        time.sleep(0.9)
    time.sleep(0.4)
    for _ in range(3):
        _sh("wtype", "-k", "Page_Up", wait=5)
        time.sleep(0.8)


def _themes():
    _h('hl.dsp.focus({ workspace = "4" })')
    time.sleep(0.3)
    for t in DEMO_THEMES:
        _sh("omarchy", "theme", "set", t, wait=30)   # ~0.5s: reload + app retints
        time.sleep(0.15)                              # just enough to register the change


CLAUDE_THEME = "Rose Pine"     # shown while typing into Claude
FINAL_THEME = "Matte Black"    # "the ship" -- where the tour leaves you


def _back_to_claude():
    _h('hl.dsp.focus({ workspace = "1" })')
    time.sleep(0.5)
    _focus_class("anthropic.Claude")
    time.sleep(0.5)
    _sh("omarchy", "theme", "set", CLAUDE_THEME, wait=30)   # Claude recolours on screen
    time.sleep(1.2)
    _sh("wtype", "-d", "12", "Hello, World!", wait=15)
    time.sleep(0.3)
    _sh("wtype", "-k", "Return", wait=6)
    time.sleep(1.2)
    _sh("omarchy", "theme", "set", FINAL_THEME, wait=30)


def _post_to_x():
    """Open X's composer with the post pre-filled via the intent URL. No typing,
    no focus games -- the text is already there and the user presses Post."""
    url = "https://x.com/intent/post?text=" + urllib.parse.quote(POST_TEXT, safe="")
    _h(f"hl.dsp.exec_cmd({_lua(f'uwsm-app -- google-chrome-stable --new-window {url}')})")
    time.sleep(6.0)

def _dev_server():
    """Open the user's local dev server in its own window on a fresh workspace."""
    _h('hl.dsp.focus({ workspace = "5" })')
    time.sleep(0.4)
    _h(f"hl.dsp.exec_cmd({_lua(f'uwsm-app -- google-chrome-stable --new-window {DEV_URL}')})")
    time.sleep(5.0)


# (action, narration) -- the line is spoken over the action
SCRIPT = [
    (_panel_to_ws2,
     "Alright, let me show you around. I'm putting my control panel on workspace two."),
    (_music,
     "Let's have some music on. I can open anything and place it exactly where I want it."),
    (_show_panel,
     "This is my control panel. Every tool I have, and a log of everything I've done for you."),
    (None,
     "I can write your emails, launch any app on this machine, change your settings, "
     "read what's on your screen, and type for you. Watch this next part."),
    (_themes,
     "Five different looks. Anything you'd normally dig through settings for, "
     "you can just ask me."),
    (_back_to_claude,
     "Back to Claude. I can recolour your whole desktop on the fly, and type into "
     "any app for you — even this one. Tell me if there's something I haven't thought of."),
]


def prepare(post=False):
    """Pre-generate every narration clip. Safe to call repeatedly (cached)."""
    clips = [narrate.generate(line, f"tour{i}") for i, (_, line) in enumerate(SCRIPT)]
    if post:
        clips.append(narrate.generate(POST_LINE, "tour_post"))
    clips.append(narrate.generate(DEV_LINE, "tour_dev"))
    clips.append(narrate.generate(FINAL_LINE, "tour_final"))
    return clips


def _step(action, clip):
    worker = None
    if action:
        worker = threading.Thread(target=action, daemon=True)
        worker.start()
    if clip:
        narrate.play(clip)            # blocks for the line's duration
    else:
        time.sleep(3)
    if worker:
        worker.join(timeout=60)       # never advance mid-action
    time.sleep(0.5)


def _run(post):
    STATE.mkdir(parents=True, exist_ok=True)
    MUTE.touch()          # the live mic ignores audio while this exists
    try:
        for i, (action, line) in enumerate(SCRIPT):
            _step(action, narrate.generate(line, f"tour{i}"))
        if post:
            _step(_post_to_x, narrate.generate(POST_LINE, "tour_post"))
        _step(_dev_server, narrate.generate(DEV_LINE, "tour_dev"))
        _step(None, narrate.generate(FINAL_LINE, "tour_final"))   # closes on the dev-server page
    finally:
        time.sleep(0.8)   # let the last line's tail clear the speakers
        MUTE.unlink(missing_ok=True)
        _running.clear()


def guided_tour(post_to_x=True):
    """Run the full guided demo tour. It narrates itself on a fixed timeline.

    Call this ONCE when the user asks for a tour or demo, then SAY NOTHING
    until it finishes -- the tour does all the talking. Do not describe it, do
    not narrate alongside it, do not call any other tool while it runs.

    Set post_to_x=True only if the user explicitly asked to post about it.
    """
    if _running.is_set():
        return {"status": "already running"}
    _running.set()
    threading.Thread(target=_run, args=(bool(post_to_x),), daemon=True).start()
    return {"status": "tour started",
            "instruction": "Stay completely silent until it ends. It narrates itself."}
