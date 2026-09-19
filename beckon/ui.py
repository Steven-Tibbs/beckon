#!/usr/bin/env python3
"""Local control panel for Beckon.

Serves a single-page UI on 127.0.0.1 only. Handles the API key, settings, voice
selection and testing, the tool list, and the conversation history -- so none of
it has to be edited by hand.
"""

import json
import os
import socket
import subprocess
import sys
import threading
import urllib.error
import urllib.request
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
import tools     # noqa: E402
import memory    # noqa: E402

CONFIG = Path.home() / ".config" / "beckon"
DATA = Path.home() / ".local" / "share" / "beckon"
KEYFILE = CONFIG / "api_key"
SETTINGS = CONFIG / "settings.json"
HISTORY = DATA / "history.jsonl"
CUSTOM = CONFIG / "custom_tools.json"


def memory_view():
    m = memory._load(); st = memory.status()
    return {"preferences": m["preferences"], "notes": m["notes"], "bytes": st["bytes"], "caps": st["caps"]}


def read_custom():
    try:
        return json.loads(CUSTOM.read_text())
    except (OSError, json.JSONDecodeError):
        return []


def write_custom(items):
    import importlib
    CONFIG.mkdir(parents=True, exist_ok=True)
    CUSTOM.write_text(json.dumps(items, indent=2))
    CUSTOM.chmod(0o600)          # these are shell commands the user wrote
    importlib.reload(tools)   # so the panel's tool list reflects it immediately

PORT = int(os.environ.get("BECKON_UI_PORT", "8777"))

DEFAULTS = {
    "model": "gemini-3.8-live",
    "voice": "Puck",
    "text_model": "gemini-3.8-flash",
    "thinking_level": "LOW",     # only used by extended-thinking models
}


def load_settings():
    s = dict(DEFAULTS)
    if SETTINGS.exists():
        try:
            s.update(json.loads(SETTINGS.read_text()))
        except json.JSONDecodeError:
            pass
    return s


def save_settings(new):
    s = load_settings()
    s.update({k: v for k, v in new.items() if k in DEFAULTS})
    CONFIG.mkdir(parents=True, exist_ok=True)
    SETTINGS.write_text(json.dumps(s, indent=2))
    SETTINGS.chmod(0o600)
    return s


# Live models, newest first. Only models the Live API can actually hold a
# session with (supportedGenerationMethods includes bidiGenerateContent) belong
# here -- the text model used for screen reads is a separate setting.
LIVE_MODELS = [
    ("gemini-3.8-live", "fastest, best all-round — recommended"),
    ("gemini-3.8-live-extended-thinking", "reasons harder on multi-step tasks; slower"),
    ("gemini-3.1-flash-live-preview", "previous default"),
    ("gemini-2.5-flash-native-audio-latest", "older, native audio"),
]


def list_models():
    return [{"id": i, "name": f"{i} — {d}"} for i, d in LIVE_MODELS]


LIVE_VOICES = [
    ("Puck", "bright, upbeat"),
    ("Charon", "deep, measured"),
    ("Kore", "warm, even"),
    ("Fenrir", "gravelly"),
    ("Aoede", "light, airy"),
    ("Leda", "youthful"),
    ("Orus", "firm"),
    ("Zephyr", "soft"),
]


def list_voices():
    """Gemini Live prebuilt voices -- synthesis happens server-side now."""
    return [{"id": n, "name": f"{n} — {d}", "engine": "gemini"} for n, d in LIVE_VOICES]


def live_running():
    pid = Path(os.environ.get("XDG_RUNTIME_DIR", "/tmp")) / "beckon" / "live.pid"
    if not pid.exists():
        return False
    try:
        os.kill(int(pid.read_text().strip()), 0)
        return True
    except (ValueError, ProcessLookupError, PermissionError):
        return False


def key_status():
    if not KEYFILE.exists():
        return {"set": False, "bytes": 0, "hint": ""}
    raw = KEYFILE.read_text().strip()
    return {
        "set": bool(raw),
        "bytes": len(raw),
        # the key is never echoed back, not even partially
        "hint": "",
    }


def test_key():
    """Make a small authenticated Gemini API request without exposing the key."""
    if not KEYFILE.exists():
        return {"ok": False, "error": "No API key is configured."}
    key = KEYFILE.read_text().strip()
    if not key:
        return {"ok": False, "error": "No API key is configured."}
    url = "https://generativelanguage.googleapis.com/v1beta/models"
    request = urllib.request.Request(url, headers={"x-goog-api-key": key})
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            response.read(1)
        return {"ok": True, "message": "Gemini API connection confirmed."}
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")
        if "API_KEY_SERVICE_BLOCKED" in detail:
            message = "This key does not allow the Gemini Developer API. Check its API restrictions."
        elif "SERVICE_DISABLED" in detail or "has not been used" in detail:
            message = "Gemini Developer API is disabled for this project."
        elif "API_KEY_INVALID" in detail:
            message = "The API key is invalid, revoked, or incomplete."
        else:
            message = f"Gemini API rejected the request (HTTP {exc.code})."
        return {"ok": False, "error": message}
    except OSError as exc:
        return {"ok": False, "error": f"Could not reach Gemini API: {exc}"}


def recent_history(n=40):
    if not HISTORY.exists():
        return []
    lines = HISTORY.read_text().splitlines()[-n:]
    out = []
    for line in reversed(lines):
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass  # keep the terminal quiet

    def _send(self, obj, code=200, ctype="application/json"):
        body = obj if isinstance(obj, bytes) else json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", "no-store, must-revalidate")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/":
            html = (HERE / "ui.html").read_bytes()
            return self._send(html, ctype="text/html; charset=utf-8")
        if self.path == "/api/state":
            s = load_settings()
            return self._send({
                "key": key_status(),
                "settings": s,
                "voices": list_voices(),
                "models": list_models(),
                "active_voice": load_settings().get("voice", "Puck"),
                "live_running": live_running(),
                "tools": [
                    {"name": n, "doc": (f.__doc__ or "").strip()}
                    for n, f in sorted(tools.TOOLS.items())
                ],
                "history": recent_history(),
                "custom_tools": read_custom(),
                "memory": memory_view(),
                "windows": tools.list_windows(),
                "monitors": tools.list_monitors(),
            })
        return self._send({"error": "not found"}, 404)

    def _same_origin(self):
        """Only the panel's own page may POST here.

        Every endpoint below changes something, and /api/custom-tools registers a
        shell command the assistant can later run -- so a POST from any page the
        user happens to have open would be a remote hole. Three checks:

        - JSON content type. A cross-site fetch sending application/json must
          pass a CORS preflight first, which nothing here answers. text/plain
          would sail through without one, so that is exactly what we refuse.
        - Host is really us, which is what stops DNS rebinding: a hostile name
          resolving to 127.0.0.1 arrives with its own Host header, not ours.
        - Origin is ours or absent. Same-origin fetches from the panel send our
          origin; cross-site ones send theirs; curl and friends send none.
        """
        ctype = (self.headers.get("Content-Type") or "").split(";")[0].strip().lower()
        if ctype != "application/json":
            return False
        allowed = {f"127.0.0.1:{PORT}", f"localhost:{PORT}"}
        if (self.headers.get("Host") or "").strip().lower() not in allowed:
            return False
        origin = (self.headers.get("Origin") or "").strip()
        if origin and origin.split("//")[-1].lower() not in allowed:
            return False
        return True

    def do_POST(self):
        if not self._same_origin():
            return self._send({"error": "cross-origin request refused"}, 403)
        length = int(self.headers.get("Content-Length", 0))
        try:
            body = json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError:
            return self._send({"error": "bad json"}, 400)

        if self.path == "/api/key":
            key = (body.get("key") or "").strip()
            if len(key) < 20:
                return self._send({"error": "that doesn't look like a key (too short)"}, 400)
            CONFIG.mkdir(parents=True, exist_ok=True)
            KEYFILE.write_text(key)
            KEYFILE.chmod(0o600)
            return self._send({"ok": True, "key": key_status()})

        if self.path == "/api/key-test":
            return self._send(test_key())

        if self.path == "/api/settings":
            return self._send({"ok": True, "settings": save_settings(body)})

        if self.path == "/api/custom-tools":
            items = read_custom()
            if "remove" in body:
                items = [t for t in items if t.get("name") != body["remove"]]
                write_custom(items)
                return self._send({"ok": True, "custom_tools": items})
            add = body.get("add") or {}
            name = str(add.get("name", "")).strip()
            builtin = set(tools.TOOLS) - {t.get("name") for t in items}
            if not name.isidentifier():
                return self._send({"error": "name must be letters, digits and underscores"}, 400)
            if name in builtin:
                return self._send({"error": f"'{name}' is a built-in tool"}, 400)
            if not str(add.get("command", "")).strip():
                return self._send({"error": "command is required"}, 400)
            args = [a for a in add.get("args", []) if str(a).isidentifier()]
            items = [t for t in items if t.get("name") != name] + [{
                "name": name,
                "description": str(add.get("description", "")).strip() or name,
                "command": str(add["command"]).strip(),
                "args": args,
            }]
            write_custom(items)
            return self._send({"ok": True, "custom_tools": items})

        if self.path == "/api/memory":
            if body.get("clear"):
                memory.clear()
            elif body.get("forget"):
                memory.forget(body["forget"])
            return self._send({"ok": True, "memory": memory_view()})

        if self.path == "/api/clear-history":
            DATA.mkdir(parents=True, exist_ok=True)
            HISTORY.write_text("")
            HISTORY.chmod(0o600)
            return self._send({"ok": True})

        if self.path == "/api/live":
            action = body.get("action")
            env = dict(os.environ)
            st = load_settings()
            env["BECKON_LIVE_VOICE"] = st.get("voice", "Puck")
            env["BECKON_LIVE_MODEL"] = st.get("model", DEFAULTS["model"])
            if action == "start" and not live_running():
                subprocess.Popen([sys.executable, str(HERE / "live.py")],
                                 env=env, start_new_session=True,
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            elif action == "stop" and live_running():
                subprocess.Popen([sys.executable, str(HERE / "live.py")],
                                 env=env, start_new_session=True,
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            import time as _t
            _t.sleep(1.2)
            return self._send({"ok": True, "running": live_running()})




        return self._send({"error": "not found"}, 404)


def open_panel(url):
    """Show the panel in an app window. Chrome's --app gives a chromeless
    window, but not everyone has Chrome -- fall back to whatever handles http,
    rather than silently opening nothing."""
    import shutil
    for cmd in (["uwsm-app", "--", "google-chrome-stable", f"--app={url}"],
                ["google-chrome-stable", f"--app={url}"],
                ["chromium", f"--app={url}"],
                ["xdg-open", url]):
        if shutil.which(cmd[0]):
            subprocess.Popen(cmd, start_new_session=True,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return
    print(f"open {url} in a browser")


def main():
    url = f"http://127.0.0.1:{PORT}/"
    # Launched from the app grid, this can be clicked twice. A second process
    # would die on "address already in use"; just show the panel that is up.
    probe = socket.socket()
    probe.settimeout(0.4)
    already = probe.connect_ex(("127.0.0.1", PORT)) == 0
    probe.close()
    if already:
        print(f"Beckon panel already running -> {url}")
        if "--no-open" not in sys.argv:
            open_panel(url)
        return

    srv = HTTPServer(("127.0.0.1", PORT), Handler)
    print(f"Beckon control panel -> {url}   (Ctrl+C to stop)")
    if "--no-open" not in sys.argv:
        threading.Timer(0.6, lambda: open_panel(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")


if __name__ == "__main__":
    main()
