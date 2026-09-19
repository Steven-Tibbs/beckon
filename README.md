# Beckon

Voice control for Omarchy, powered by the Gemini Live API.

Press a key, talk normally, and your desktop does what you asked — while
you're still talking. Beckon streams audio both directions over a single
connection, so there is no record-then-wait-then-respond cycle: it answers
mid-sentence and runs actions as it hears them.

> **Independent project.** Beckon is built *for* [Omarchy](https://omarchy.org)
> users but is not affiliated with, endorsed by, or part of Omarchy, its
> maintainers, Hyprland, or Google.

## What it does

Beckon exposes your desktop to Gemini as tools it can call, and chains them
itself:

- **Windows** — focus, move, resize, swap, tile, float, fullscreen, close
- **Workspaces** — switch, send windows between them, move a workspace to another monitor
- **Typing** — type text, press keys, send shortcuts into the focused window
- **Mouse** — move the pointer, click
- **Vision** — screenshot the screen and answer questions about what's on it; a soft orange edge glow shows while it's looking
- **Reading** — pulls the *full text* of a page, email or document straight from the window, including everything scrolled off screen, so it answers without scrolling; it can use the text, the picture, or both ([setup](#reading-page-text))
- **Keyboard shortcuts** — reads your *current* Omarchy keybindings live and can trigger any of them by name (terminal, browser, screenshot, emoji picker...); rebind a key and it follows
- **Clipboard** — read and write
- **System** — volume, brightness, launch apps, open URLs
- **Your own tools** — add any shell command as a voice-callable tool from the panel
- **Memory** — remembers preferences ("email means Gmail") and short notes about
  what you're working on, so it stops asking and gets more useful over time

*"Put Chrome and my editor side by side"*, *"what does this error say?"*,
*"open the weather and read it to me"* all work as single requests.

## Where it runs

Made for **Omarchy** — built and tested on Omarchy 4.0.3.

Omarchy runs on Hyprland, and Beckon drives the desktop through Hyprland's
dispatcher API, so **other Hyprland-based setups can run it too** with a little
adjustment:

- Hyprland has to be underneath. It will not work on GNOME, KDE, X11, or
  other Wayland compositors.
- On a non-Omarchy Hyprland setup, the guided tour's theme switching (which
  uses the `omarchy` CLI) won't apply, and app launching expects `uwsm-app`
  (swap it in `beckon/tools.py` if you don't use uwsm).
- Hyprland builds without the Lua dispatcher API need the calls in
  `beckon/tools.py` adjusted to the classic `hyprctl dispatch` syntax.

## Requirements

| Needed for | Arch package | Notes |
|---|---|---|
| Runtime | `python` 3.11+ | |
| Live API connection | `python-websockets` | official repo |
| Mic and speaker streaming | `python-sounddevice` | official repo (Omarchy also ships it) |
| Gemini SDK | `python-google-genai` | **AUR** |
| Typing and key presses | `wtype` | official repo |
| Screen vision | `grim` | official repo |
| Clipboard | `wl-clipboard` | official repo |
| Mouse clicks *(optional)* | `ydotool` | needs its daemon — see [Mouse clicks](#mouse-clicks) |
| Reading page text *(optional)* | `at-spi2-core`, `python-gobject` | see [Reading page text](#reading-page-text) |
| Notifications | `libnotify` | `notify-send`; already on Omarchy |
| Narration playback | `pipewire-pulse` | `paplay`; already on Omarchy |
| Music control in the tour | `systemd` | `busctl` for MPRIS; already there |
| Theme switching in the tour | `omarchy` CLI | Omarchy only |
| Model access | Gemini API key | automatic setup needs Google Cloud CLI; manual fallback is [AI Studio](https://aistudio.google.com/apikey) |

```bash
sudo pacman -S --needed python-websockets python-sounddevice wtype grim wl-clipboard ydotool libnotify
yay -S --needed python-google-genai
```

## Install

**As a package** (recommended) — pacman then owns the files, `pacman -R
beckon-git` removes them cleanly, and rebuilding picks up the latest commit:

```bash
yay -S python-google-genai   # the one dependency not in the official repos
git clone https://github.com/Steven-Tibbs/beckon.git
cd beckon/packaging && makepkg -si
```

`makepkg -si` builds the package and invokes `pacman -U` itself. If you prefer
to inspect the generated package before installing it, run `makepkg -s` and
then `sudo pacman -U ./beckon-git-*.pkg.tar.zst`.

**Or from source**, if you'd rather not package it:

```bash
git clone https://github.com/Steven-Tibbs/beckon.git
cd beckon && ./install.sh
```

Either way, two more commands:

```bash
beckon ui       # paste your Gemini API key, then hit Test connection
beckon setup    # bind a key — F8 by default, `beckon setup F7` for another
```

Get a key free at [aistudio.google.com/apikey](https://aistudio.google.com/apikey)
— that is the fastest way in, and nothing else is required.

### Already using Google Cloud?

`beckon setup-api-key` creates the key for you instead of pasting one. It signs
in to Google Cloud if needed, enables the Gemini Developer API, creates a
**standard** key restricted to `generativelanguage.googleapis.com`, saves it at
`~/.config/beckon/api_key` with `0600` permissions, and verifies it:

```bash
beckon setup-api-key --project PROJECT_ID          # --rotate replaces an old key
```

It needs the Google Cloud CLI (`yay -S google-cloud-cli`) and a project that
already exists — pass it above, or set it with `gcloud config set project`.
Which pricing tier you land on depends on whether that project has an active
billing account, not on how the key was made, so a project you already pay for
will bill this usage too.

Do not restrict the key only to Vertex AI: it needs the Gemini Developer API.
Keys bound to a service account can also fall under organization policies, which
makes changing their restrictions awkward. The **Test connection** button in
`beckon ui` checks access without ever displaying the key.

`beckon setup` appends the binding to `~/.config/hypr/bindings.lua`, backs the
file up first, and refuses to take a key that is already spoken for. To do it by
hand instead:

```lua
o.bind("F8", "Beckon", "beckon")
```

Press the key once to start listening, again to stop.

### The app icon

Both install methods add **Beckon** to your app grid — clicking it opens the
control panel. The package puts the entry in `/usr/share/applications` and the
icon in `/usr/share/icons/hicolor/scalable/apps`; `install.sh` puts both under
`~/.local/share`.

If it doesn't show up, your launcher is holding a stale cache:

```bash
update-desktop-database ~/.local/share/applications
gtk-update-icon-cache -f -t ~/.local/share/icons/hicolor
```

Some launchers only rescan on login. If you installed Beckon before the icon
existed, reinstall (`makepkg -si` or `./install.sh`) and it appears.

While Beckon is speaking it closes the mic, so its own voice coming out of your
speakers can't register as you interrupting it. That means you can't talk over
it by voice; if you use headphones and want that back, start it with
`BECKON_BARGE_IN=1`.

### Installing with an AI agent

If you use Claude Code, Gemini CLI, or another coding agent, point it at
[`AGENTS.md`](AGENTS.md) — it has the exact steps, the checks that prove each
one worked, and the pitfalls. A prompt that works:

> Install Beckon from https://github.com/Steven-Tibbs/beckon on this Omarchy
> machine by following its AGENTS.md. Verify each step, then open `beckon ui`.

## Use

| | |
|---|---|
| `beckon` | start a live session (or press your bound key) |
| `beckon ui` | control panel: API key, **model**, voice, custom tools, history |
| `beckon setup` | bind a key — `beckon setup F7` to choose another |
| *"give me a guided tour"* | the demo — it narrates itself |

The tour's last step opens a local dev server. Point it at yours by putting
`"dev_url": "http://localhost:3000"` (and optionally `"dev_line"` for what it
says over it) in `~/.config/beckon/settings.json`.

## Models

Beckon runs on `gemini-3.8-live` by default. The panel lists every model the
Live API can hold a session with; pick one and it applies to the next session,
however you start it.

| model | what it's for |
|---|---|
| `gemini-3.8-live` | default — fastest, best all-round |
| `gemini-3.8-live-extended-thinking` | reasons harder on multi-step tasks; speaks a filler first and takes longer to finish |
| `gemini-3.1-flash-live-preview` | previous default |

Extended-thinking models need a thinking level; Beckon sends `LOW`, which you
can change with `thinking_level` in `~/.config/beckon/settings.json`.

## Privacy

Audio goes to Google's Live API; that is what makes the low latency possible.
Nothing is sent anywhere else. Your key lives in `~/.config/beckon/api_key`
with `0600` permissions and is never shown in the UI, not even partially.
Conversation history is local (`~/.local/share/beckon/history.jsonl`) and has
a **clear** button in the panel. It, your memory, your settings and your custom
tools are all written `0600` — readable only by you, even on a shared machine.

## Memory

Beckon keeps a small memory at `~/.config/beckon/memory.json`: **preferences**
(`email → https://mail.google.com`) and **notes** about what you're working on.
It reads them at the start of every session and writes to them when you say
things like *"remember that I use Gmail"* or *"I'm working on the checkout
page."* For anything generic — email, music, notes, your editor — it uses the
saved preference, and if there isn't one it asks once and remembers the answer.

It is hard-capped at 40 preferences and 30 notes of 200 characters each, so the
file stays a few kilobytes forever; oldest entries drop off. Everything in it is
visible and deletable in the panel. It never stores secrets or email addresses.

## Reading page text

Asked *"read me this email"*, Beckon can take the whole thing from the window at
once — including the part below the fold — instead of screenshotting and
scrolling. It reads the accessibility tree the desktop already publishes, which
is faster, exact, and costs no vision call. Two settings turn it on, and both
are needed:

```bash
gsettings set org.gnome.desktop.interface toolkit-accessibility true
gsettings set org.gnome.desktop.a11y.applications screen-reader-enabled true
echo '--force-renderer-accessibility' >> ~/.config/chrome-flags.conf
```

Restart Chrome afterwards — Chromium reads the accessibility state only at
startup. GTK apps work without the Chrome flag. Needs `at-spi2-core` and
`python-gobject`, both in the official repos.

Without this, Beckon still sees the screen; it just sees only what's visible.
Terminals, images and video never publish text, so it falls back to looking.

## Mouse clicks

Hyprland's own synthetic clicks are accepted but never reach applications,
so `click` goes through `ydotool`. Its daemon needs `/dev/uinput`, which is
root-only by default. The simplest setup is a system service whose socket is
owned by you:

```bash
sudo tee /etc/systemd/system/ydotoold.service >/dev/null <<UNIT
[Unit]
Description=ydotool daemon
[Service]
ExecStart=/usr/bin/ydotoold --socket-path=/tmp/.ydotool_socket --socket-own=$(id -u):$(id -g) --socket-perm=0600
Restart=on-failure
[Install]
WantedBy=multi-user.target
UNIT
sudo systemctl enable --now ydotoold
```

Everything else works without it; only `click` needs it.

## Adding your own tools

**From the panel** — *Your own tools* takes a name, a description (this is
what the assistant reads to decide when to use it), a shell command, and
optional arguments. `{arg}` placeholders are filled with shell-quoted values.
They are stored in `~/.config/beckon/custom_tools.json` and picked up when the
next session starts.

**In Python** — add a function to `beckon/tools.py` and list it in `TOOLS` at
the bottom. The docstring becomes the description, the signature becomes the
schema; nothing else to register.

```python
def lock_screen():
    """Lock the screen immediately."""
    return _hypr('hl.dsp.exec_cmd("omarchy-system-lock")')
```

## Contributing

Pull requests are welcome. Fork, branch, open a PR — nothing lands on `master`
without review by the maintainer, and direct pushes are limited to the owner.

## License

MIT
