#!/usr/bin/env python3
"""Beckon Live -- realtime voice control for Omarchy via the Gemini Live API.

A persistent WebSocket session: audio streams up continuously, Gemini streams
audio back, and tool calls fire mid-sentence. No record/transcribe/respond
round trip, so it answers while you are still talking.

  beckon live          start a session (Ctrl+C or F8 again to stop)
  beckon live --once   same, but exits after the first reply (for testing)
"""

import asyncio
import inspect
import json
import os
import signal
import sys
import time
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
import tools   # noqa: E402
import memory  # noqa: E402

import sounddevice as sd  # noqa: E402
from google import genai  # noqa: E402
from google.genai import types  # noqa: E402

CONFIG = Path.home() / ".config" / "beckon"
DATA = Path.home() / ".local" / "share" / "beckon"
HISTORY = DATA / "history.jsonl"
STATE = Path(os.environ.get("XDG_RUNTIME_DIR", "/tmp")) / "beckon"
STATE.mkdir(parents=True, exist_ok=True)
# When installed as a package the code lives in /usr/lib and nothing has ever
# created this; without it the very first logged turn raises FileNotFoundError.
DATA.mkdir(parents=True, exist_ok=True)
PIDFILE = STATE / "live.pid"
MUTE = STATE / "mute"   # present while the tour narrates

def setting(key, default):
    """Read a value the panel saved. The panel passes model and voice through
    the environment when IT starts a session, but the bound key launches this
    file directly -- without this, every setting chosen in the panel was
    silently ignored whenever the session was started with the keybind."""
    try:
        return json.loads((CONFIG / "settings.json").read_text()).get(key) or default
    except (OSError, ValueError):
        return default


MODEL = os.environ.get("BECKON_LIVE_MODEL") or setting("model", "gemini-3.8-live")
# By default the mic is gated while the model speaks, so its own voice coming
# back through the speakers can't be mistaken for you interrupting it. Set
# BECKON_BARGE_IN=1 (headphones) to keep the mic open and allow talking over it.
BARGE_IN = os.environ.get("BECKON_BARGE_IN") == "1"
SPEAK_TAIL = 0.4   # seconds to keep the mic closed after playback drains
VOICE = os.environ.get("BECKON_LIVE_VOICE") or setting("voice", "Puck")
# Extended-thinking Live models REFUSE a session that doesn't specify a thinking
# level ("Thinking level must be specified for this model"), and reject MINIMAL.
# Every other model must NOT be sent one. LOW keeps it responsive.
THINKING = (os.environ.get("BECKON_THINKING") or setting("thinking_level", "LOW")).upper()

IN_RATE, OUT_RATE, CHUNK = 16000, 24000, 1024

SYSTEM = """You are Beckon, a desktop agent with real tools that open apps and sites,
move windows, type, and click. You are NOT "just a voice model": when the user
asks you to do something on screen, do it with the tools.

You control a Linux desktop running Omarchy (Hyprland, Wayland).

You are in a live spoken conversation. Act on what the user asks -- do not read
back plans or ask permission for ordinary window management.

MEMORY
- For anything generic -- "open my email", "play some music", "open my notes",
  "my editor" -- use the saved preference from memory. If there is none, ask
  ONE short question ("Gmail, or something else?"), then call remember() with
  the answer so you never ask again, then do it.
- When the user tells you what they are working on, or says "remember this",
  call note() or remember(). Do not announce that you saved it; just carry on.
- Never store secrets, passwords, or full email addresses.

- Call list_windows or current_window first when they name a window, so you act
  on the right one.
- Keep spoken replies to a short sentence. Often a two-word confirmation is
  plenty; if the action is obvious, say almost nothing.
- Never call close_window unless they clearly asked to close something. It will
  refuse to close Claude Desktop or the Beckon panel; when asked to close
  everything, close the rest and mention those two are still open.
- To CLICK something -- "open the first email", "press that button", "select
  that" -- the recipe is always: find_on_screen("<what it is>") to get x,y,
  then move_mouse(x, y), then click(). Never say you can't click; use these.
READING WHAT IS ON SCREEN -- three ways, pick deliberately:
- read_page_text() returns the FULL text of the window, including everything
  scrolled off screen. Reach for this FIRST for an email, an article, a
  document, a chat log: it is instant, exact, and needs no scrolling.
- look_at_screen(question, mode="image") sends a screenshot. Use it for
  anything visual -- layout, colours, a photo, a video, a terminal -- or when
  read_page_text says the window publishes no text.
- look_at_screen(question) sends BOTH the screenshot and the full text. Use it
  when the answer needs how the page looks as well as what it says.
Never ask the user to scroll so you can see more -- read the text instead.
- Anything the user could do with a keyboard shortcut -- terminal, browser, file
  manager, screenshot, emoji picker, clipboard history, workspace switching --
  do with press_keybind(name); use list_keybinds to find the name. These are the
  user's CURRENT bindings, so prefer them over guessing program names.
- "Side by side" is usually toggle_split. "Put it on the TV" is
  move_workspace_to_monitor.
- The laptop screen is eDP-1; other monitors are external.

GUIDED TOUR
If the user asks for a tour or a demo, call guided_tour() ONCE and then say
nothing at all -- not a word -- until they speak to you again. The tour
narrates itself with its own voice on a fixed timeline; anything you say will
talk over it. Do not call other tools while it runs.

The tour ends by typing a post on X. It never presses send; the user does.
"""

PY_TO_JSON = {int: "INTEGER", float: "NUMBER", bool: "BOOLEAN", str: "STRING"}


def notify(msg, urgency="normal"):
    import subprocess
    subprocess.run(["notify-send", "-a", "Beckon", "-u", urgency, "Beckon", str(msg)[:250]],
                   check=False)


def api_key():
    k = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if k:
        return k.strip()
    f = CONFIG / "api_key"
    return f.read_text().strip() if f.exists() else None


def declarations():
    """Build Gemini function declarations from tools.TOOLS."""
    out = []
    for name, fn in tools.TOOLS.items():
        props, required = {}, []
        for pname, p in inspect.signature(fn).parameters.items():
            kind = int if isinstance(p.default, int) and not isinstance(p.default, bool) else str
            props[pname] = {"type": PY_TO_JSON[kind], "description": pname}
            if p.default is inspect.Parameter.empty:
                required.append(pname)
        d = {"name": name, "description": (fn.__doc__ or name).strip()}
        if props:
            d["parameters"] = {"type": "OBJECT", "properties": props, "required": required}
        out.append(d)
    return out


def log(entry):
    """Append one turn to the local history file.

    The history is a transcript of everything said in this room, so it is
    created 0600 and never leaves the machine. Nothing here is ever uploaded
    or committed -- .gitignore covers it, and the panel can clear it.
    """
    entry["ts"] = datetime.now().isoformat(timespec="seconds")
    entry["via"] = "live"
    fd = os.open(HISTORY, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    with os.fdopen(fd, "a") as f:
        f.write(json.dumps(entry) + "\n")


class Live:
    def __init__(self, once=False):
        self.once = once
        self.stop = asyncio.Event()
        self.out_q = asyncio.Queue()
        self.said, self.heard, self.actions = [], [], []
        self.last_played = 0.0

    def model_speaking(self):
        """True while model audio is queued/playing (plus a short tail)."""
        if BARGE_IN:
            return False
        return (not self.out_q.empty()) or (time.monotonic() - self.last_played < SPEAK_TAIL)

    async def mic(self, session):
        """Stream microphone audio up to Gemini continuously."""
        loop = asyncio.get_running_loop()
        q = asyncio.Queue()

        def cb(indata, frames, time_info, status):
            loop.call_soon_threadsafe(q.put_nowait, bytes(indata))

        with sd.RawInputStream(samplerate=IN_RATE, blocksize=CHUNK, channels=1,
                               dtype="int16", callback=cb):
            while not self.stop.is_set():
                data = await q.get()
                if MUTE.exists() or self.model_speaking():
                    continue  # don't feed the speakers back into the model
                await session.send_realtime_input(
                    audio=types.Blob(data=data, mime_type=f"audio/pcm;rate={IN_RATE}")
                )

    async def speaker(self):
        """Play audio chunks as they arrive -- this is what makes it feel instant."""
        with sd.RawOutputStream(samplerate=OUT_RATE, channels=1, dtype="int16") as out:
            while not self.stop.is_set():
                chunk = await self.out_q.get()
                if chunk is None or MUTE.exists():
                    continue   # never let the model talk over the tour
                await asyncio.to_thread(out.write, chunk)
                self.last_played = time.monotonic()

    async def receive(self, session):
        """Handle everything coming back: audio, transcripts, tool calls."""
        while not self.stop.is_set():
            async for msg in session.receive():
                sc = getattr(msg, "server_content", None)

                if getattr(msg, "data", None) and not MUTE.exists():
                    self.last_played = time.monotonic()   # close the mic the moment audio arrives
                    self.out_q.put_nowait(msg.data)   # dropped while the tour narrates

                if sc:
                    it = getattr(sc, "input_transcription", None)
                    if it and getattr(it, "text", None):
                        self.heard.append(it.text)
                    ot = getattr(sc, "output_transcription", None)
                    if ot and getattr(ot, "text", None):
                        self.said.append(ot.text)

                    if getattr(sc, "interrupted", None):
                        # user talked over the model -- drop queued audio
                        while not self.out_q.empty():
                            self.out_q.get_nowait()

                    if getattr(sc, "turn_complete", None):
                        heard = "".join(self.heard).strip()
                        said = "".join(self.said).strip()
                        if heard or said or self.actions:
                            log({"heard": heard, "reply": said, "actions": self.actions})
                            print(f"  you: {heard}\n  beckon: {said}"
                                  + (f"\n  ran: {[a['tool'] for a in self.actions]}"
                                     if self.actions else ""))
                        self.heard, self.said, self.actions = [], [], []
                        if self.once:
                            self.stop.set()

                tc = getattr(msg, "tool_call", None)
                if tc and getattr(tc, "function_calls", None):
                    responses = []
                    for call in tc.function_calls:
                        fn = tools.TOOLS.get(call.name)
                        try:
                            result = fn(**(call.args or {})) if fn else {"error": "unknown tool"}
                        except Exception as e:
                            result = {"error": f"{type(e).__name__}: {e}"}
                        self.actions.append({"tool": call.name, "args": dict(call.args or {})})
                        responses.append(types.FunctionResponse(
                            id=call.id, name=call.name, response={"result": result}))
                    await session.send_tool_response(function_responses=responses)

    async def run(self):
        key = api_key()
        if not key:
            notify("No API key set — open the Beckon panel", "critical")
            print("no API key", file=sys.stderr)
            return 1

        client = genai.Client(api_key=key)
        try:   # be less trigger-happy about faint bleed-through counting as speech
            vad = types.RealtimeInputConfig(
                automatic_activity_detection=types.AutomaticActivityDetection(
                    start_of_speech_sensitivity=types.StartSensitivity.START_SENSITIVITY_LOW))
        except AttributeError:
            vad = None
        think = None
        if "thinking" in MODEL:
            try:
                think = types.ThinkingConfig(thinking_level=getattr(
                    types.ThinkingLevel, THINKING, types.ThinkingLevel.LOW))
            except AttributeError:
                think = None
        config = types.LiveConnectConfig(
            realtime_input_config=vad,
            thinking_config=think,
            response_modalities=["AUDIO"],
            system_instruction=SYSTEM + ("\n\n" + memory.render() if memory.render() else ""),
            tools=[{"function_declarations": declarations()}],
            speech_config=types.SpeechConfig(
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=VOICE))),
            input_audio_transcription=types.AudioTranscriptionConfig(),
            output_audio_transcription=types.AudioTranscriptionConfig(),
            # let the API manage context instead of us trimming by hand
            context_window_compression=types.ContextWindowCompressionConfig(
                sliding_window=types.SlidingWindow()),
        )

        PIDFILE.write_text(str(os.getpid()))
        MUTE.unlink(missing_ok=True)   # a cancelled tour must not leave us deaf
        notify("Listening — talk to me", "low")
        print(f"Beckon live [{MODEL}, voice {VOICE}] — Ctrl+C to stop\n")

        status = 0
        try:
            async with client.aio.live.connect(model=MODEL, config=config) as session:
                async with asyncio.TaskGroup() as tg:
                    tg.create_task(self.mic(session))
                    tg.create_task(self.speaker())
                    tg.create_task(self.receive(session))
                    await self.stop.wait()
                    raise asyncio.CancelledError
        except* asyncio.CancelledError:
            pass
        except* Exception as eg:
            msg = "; ".join(str(e)[:120] for e in eg.exceptions[:2])
            notify(f"Live error: {msg}", "critical")
            print("error:", msg, file=sys.stderr)
            status = 1
        finally:
            PIDFILE.unlink(missing_ok=True)
            MUTE.unlink(missing_ok=True)
            notify("Session ended", "low")
        return status


def main():
    once = "--once" in sys.argv

    # F8 pressed while a session runs -> stop it
    if PIDFILE.exists() and "--force" not in sys.argv:
        try:
            os.kill(int(PIDFILE.read_text().strip()), signal.SIGTERM)
            PIDFILE.unlink(missing_ok=True)
            notify("Session ended", "low")
            return 0
        except (ValueError, ProcessLookupError):
            PIDFILE.unlink(missing_ok=True)

    live = Live(once=once)

    def bye(*_):
        live.stop.set()
    signal.signal(signal.SIGTERM, bye)
    signal.signal(signal.SIGINT, bye)

    return asyncio.run(live.run())


if __name__ == "__main__":
    sys.exit(main())
