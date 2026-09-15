"""Pre-generate tour narration as audio files.

The live model cannot reliably time its own speech against actions, so the tour
speaks from cached WAVs instead. Generated once, reused forever.
"""

import base64
import json
import struct
import subprocess
import urllib.request
from pathlib import Path

CACHE = Path.home() / ".cache" / "beckon" / "narration"
MODEL = "gemini-3.1-flash-tts-preview"
VOICE = "Puck"


def _key():
    import os
    k = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if k:
        return k.strip()
    f = Path.home() / ".config" / "beckon" / "api_key"
    return f.read_text().strip() if f.exists() else None


def _wav(pcm, rate=24000):
    """Wrap raw 16-bit mono PCM in a WAV header."""
    return (b"RIFF" + struct.pack("<I", 36 + len(pcm)) + b"WAVEfmt "
            + struct.pack("<IHHIIHH", 16, 1, 1, rate, rate * 2, 2, 16)
            + b"data" + struct.pack("<I", len(pcm)) + pcm)


def generate(text, name, voice=VOICE):
    """Synthesise `text` to CACHE/name.wav if not already there. Returns the path."""
    import hashlib
    CACHE.mkdir(parents=True, exist_ok=True)
    name = f"{name}-{hashlib.sha1(text.encode()).hexdigest()[:8]}"
    out = CACHE / f"{name}.wav"
    if out.exists() and out.stat().st_size > 2000:
        return out

    key = _key()
    if not key:
        return None
    body = json.dumps({
        "contents": [{"parts": [{"text": text}]}],
        "generationConfig": {
            "responseModalities": ["AUDIO"],
            "speechConfig": {"voiceConfig": {
                "prebuiltVoiceConfig": {"voiceName": voice}}},
        },
    }).encode()
    req = urllib.request.Request(
        f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL}:generateContent?key={key}",
        data=body, headers={"Content-Type": "application/json"})
    import time
    for attempt, pause in enumerate((0, 3, 8)):
        if pause:
            time.sleep(pause)      # the TTS endpoint rate-limits bursts
        try:
            d = json.loads(urllib.request.urlopen(req, timeout=90).read())
            part = d["candidates"][0]["content"]["parts"][0]["inlineData"]
            out.write_bytes(_wav(base64.b64decode(part["data"])))
            return out
        except Exception:
            continue
    return None


def duration(path):
    """Length of a WAV in seconds, from its header."""
    try:
        b = Path(path).read_bytes()
        rate = struct.unpack("<I", b[24:28])[0]
        return max(0.4, (len(b) - 44) / (rate * 2))
    except Exception:
        return 3.0


def play(path, block=True):
    p = subprocess.Popen(["paplay", str(path)],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if block:
        p.wait()
    return p
