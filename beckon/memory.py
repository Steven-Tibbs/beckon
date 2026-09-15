"""Small, bounded, persistent memory for the voice agent.

Two kinds of entry, both hard-capped so the file can never grow past a few KB:

  preferences  key -> value      "email" -> "https://mail.google.com"
  notes        short facts       "working on the checkout flow"

The whole thing is rendered into the system prompt at session start (last 15
notes only), so the model starts every session already knowing your habits.
"""

import json
import time
from pathlib import Path

FILE = Path.home() / ".config" / "beckon" / "memory.json"
MAX_PREFS, MAX_NOTES, MAX_LEN, PROMPT_NOTES = 40, 30, 200, 15


def _load():
    try:
        d = json.loads(FILE.read_text())
        return {"preferences": dict(d.get("preferences", {})), "notes": list(d.get("notes", []))}
    except (OSError, json.JSONDecodeError):
        return {"preferences": {}, "notes": []}


def _save(d):
    """Write atomically and 0600 -- this file is a record of the user's habits."""
    FILE.parent.mkdir(parents=True, exist_ok=True)
    FILE.write_text(json.dumps(d, indent=2))
    FILE.chmod(0o600)


def _clip(s):
    s = " ".join(str(s).split())
    return s[:MAX_LEN]


def remember(key, value):
    d = _load()
    key = _clip(key).lower()[:40]
    d["preferences"][key] = _clip(value)
    if len(d["preferences"]) > MAX_PREFS:          # drop the oldest-inserted
        for k in list(d["preferences"])[: len(d["preferences"]) - MAX_PREFS]:
            del d["preferences"][k]
    _save(d)
    return f"remembered {key} = {d['preferences'][key]}"


def note(text):
    d = _load()
    text = _clip(text)
    d["notes"] = [n for n in d["notes"] if n.get("text") != text]  # no duplicates
    d["notes"].append({"ts": time.strftime("%Y-%m-%d"), "text": text})
    d["notes"] = d["notes"][-MAX_NOTES:]
    _save(d)
    return f"noted ({len(d['notes'])}/{MAX_NOTES})"


def recall(query=""):
    d = _load()
    q = _clip(query).lower()
    prefs = {k: v for k, v in d["preferences"].items() if not q or q in k or q in v.lower()}
    notes = [n for n in d["notes"] if not q or q in n["text"].lower()]
    return {"preferences": prefs, "notes": [n["text"] for n in notes[-10:]]}


def forget(target):
    d = _load()
    t = _clip(target).lower()
    before = (len(d["preferences"]), len(d["notes"]))
    d["preferences"] = {k: v for k, v in d["preferences"].items() if t not in k}
    d["notes"] = [n for n in d["notes"] if t not in n["text"].lower()]
    _save(d)
    gone = (before[0] - len(d["preferences"])) + (before[1] - len(d["notes"]))
    return f"forgot {gone} item(s)" if gone else "nothing matched"


def clear():
    _save({"preferences": {}, "notes": []})


def render():
    """Compact block for the system prompt. Empty string when nothing is stored."""
    d = _load()
    if not d["preferences"] and not d["notes"]:
        return ""
    lines = ["WHAT YOU KNOW ABOUT THIS USER (from memory; use it without being asked):"]
    for k, v in d["preferences"].items():
        lines.append(f"- {k}: {v}")
    for n in d["notes"][-PROMPT_NOTES:]:
        lines.append(f"- note ({n['ts']}): {n['text']}")
    return "\n".join(lines)


def status():
    d = _load()
    size = FILE.stat().st_size if FILE.exists() else 0
    return {"preferences": len(d["preferences"]), "notes": len(d["notes"]), "bytes": size,
            "caps": {"preferences": MAX_PREFS, "notes": MAX_NOTES}}
