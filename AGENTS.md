# Beckon — notes for coding agents

Read this before installing or modifying Beckon on a user's machine.

## What it is

A voice agent for Omarchy users; it also runs on other Hyprland-based setups with small adjustments. `live.py` holds a Gemini Live API
session (audio both ways over one WebSocket) and executes the tools in
`tools.py` against Hyprland. `ui.py` + `ui.html` is a local control panel on
`127.0.0.1:8777`. `tour.py` is a self-narrating demo; `narrate.py` generates
its audio with the Gemini TTS model.

Independent project built for Omarchy users — not affiliated with Omarchy, Hyprland, or Google.

## Install on Omarchy (verified steps)

1. Dependencies. Everything but the Gemini SDK is in the official repos.
   ```
   sudo pacman -S --needed python-websockets python-sounddevice wtype grim wl-clipboard ydotool libnotify python-gobject at-spi2-core
   yay -S --needed python-google-genai
   ```
   Check: `python3 -c "import websockets, sounddevice, google.genai"` prints nothing.
2. Install. As a package, so pacman owns the files and removal is clean:
   ```
   git clone https://github.com/Steven-Tibbs/beckon.git
   cd beckon/packaging && makepkg -si
   ```
   `makepkg -s` resolves dependencies through pacman, which knows nothing about
   the AUR, so `python-google-genai` must already be installed (step 1).
   Without makepkg, `cd beckon && ./install.sh` installs into `~/.local`.
   Check: `command -v beckon` resolves, and Beckon appears in the app grid.
3. API key. Prefer `beckon setup-api-key --project PROJECT_ID`. It uses the
   user's authenticated Google Cloud CLI to enable the Gemini Developer API,
   create a standard key restricted to `generativelanguage.googleapis.com`,
   save it at `~/.config/beckon/api_key` (0600), and make a non-sensitive
   connection check. It must never create a service-account-bound authorization
   key. Check: its final line is `Gemini API connection confirmed.` A user can
   also paste an existing standard key in `beckon ui` and click Test connection.
4. Keybinding: `beckon setup` (or `beckon setup F7` for another key). It appends
   to `~/.config/hypr/bindings.lua`, backs it up, and refuses a key that is
   already bound. Check `hyprctl configerrors` is empty afterwards.
5. Reading full pages (optional but worth it). Both are required; neither works
   alone, and Chromium reads the state only at startup:
   ```
   gsettings set org.gnome.desktop.interface toolkit-accessibility true
   gsettings set org.gnome.desktop.a11y.applications screen-reader-enabled true
   echo '--force-renderer-accessibility' >> ~/.config/chrome-flags.conf
   ```
   Check: restart Chrome, open a page, then `python3 /usr/lib/beckon/tools.py
   --page-text chrome` prints the page's text.
6. Mouse clicks (optional). `ydotool` needs a daemon with `/dev/uinput`
   access; see the README's *Mouse clicks* section for the system unit.
   Check: `ls -l /tmp/.ydotool_socket` is owned by the user, mode `srw-------`.
7. Smoke test: press the bound key and ask *"how many windows do I have open?"*
   — it should call `list_windows` and answer aloud. With step 5 done, open an
   article and ask it to read the bottom of the page without scrolling.

## How the pieces fit

- **Tool schema** is generated from `tools.py` function signatures and
  docstrings. To add a tool: write a function, list it in `TOOLS` at the
  bottom of the file. Docstrings are what the model reads — keep them exact.
- **Shell tools** live in `~/.config/beckon/custom_tools.json` and are loaded
  by `load_custom_tools()` at import. `{arg}` placeholders are shell-quoted.
- **Hyprland calls** use the Lua dispatcher API via `hyprctl dispatch 'hl.dsp…'`.
  Verified shapes: `hl.dsp.focus({ workspace = "2" })`,
  `hl.dsp.window.move({ workspace = "2", follow = false })`,
  `hl.dsp.window.resize({ x = 50, y = 0, relative = true })`,
  `hl.dsp.workspace.move({ monitor = "r" })`,
  `hl.dsp.cursor.move({ x = 100, y = 100, absolute = true })`.
  Classic `hyprctl dispatch movewindow l` syntax does NOT work here.
- **Coordinates** for `cursor.move` are Hyprland's logical layout coordinates —
  the same ones `hyprctl clients -j` reports in `at`/`size`. Not physical pixels.
- **Mute file.** While `$XDG_RUNTIME_DIR/beckon/mute` exists, `live.py` stops
  sending mic audio and drops the model's audio output. The tour creates it so
  the model can't hear its own narration through the speakers and answer it.
- **Half-duplex gating.** `live.py` stops sending mic audio while model audio
  is queued or playing, plus a 0.4s tail (`SPEAK_TAIL`). Without this, the
  model's voice re-enters through the laptop mic and the Live API's VAD treats
  it as an interruption -- it cuts itself off mid-sentence. `BECKON_BARGE_IN=1`
  disables the gate for headphone users. Start-of-speech VAD sensitivity is
  also set LOW to ignore faint bleed.
- **Memory** is `memory.py`, backed by `~/.config/beckon/memory.json`. Rendered
  into the system prompt at session start (`memory.render()`), capped at 40
  preferences / 30 notes / 200 chars. Tools: `remember`, `note`, `recall`,
  `forget`. The prompt tells the model to ask once for a generic target
  (email, music) and then `remember()` it. Don't add unbounded memory.
- **Edge glow** is `glow.qml`, a click-through Quickshell overlay started by
  `tools._start_pulse()` during screen reads. Quickshell ships with Omarchy;
  without it the code falls back to pulsing the focused window's border.
- **Keybinds** are read live from `omarchy menu keybindings --print` each call
  (`tools._keybinds()`), never stored. `press_keybind` sends the real chord via
  ydotool because Hyprland's `send_key_state` does NOT fire binds (verified).
  Lock/power/logout/close-all binds require `force=True`.
- **Hot reload.** `guided_tour` in `tools.py` reloads `tour.py` on every call,
  so tour edits apply without restarting the session. Edits to `live.py` or
  `tools.py` need a session restart (press the bound key twice).
- **Narration cache** is `~/.cache/beckon/narration/`, keyed by step name plus
  a hash of the text, so edited lines regenerate automatically.
- **App-grid entry.** `beckon/beckon.desktop` plus `beckon/beckon.svg` ship in
  both install paths: the package installs them under `/usr/share`, `install.sh`
  under `~/.local/share` and rewrites `Exec=` to the launcher's absolute path,
  because a desktop entry is not guaranteed to see `~/.local/bin` on PATH.
  Launching from a grid means it can be clicked twice, so `ui.py` checks whether
  port 8777 is already served and just shows the running panel instead of dying
  on "address already in use"; its browser launch falls back chromium ->
  xdg-open rather than assuming Chrome.
- **Model choice** lives in the panel and is saved to
  `~/.config/beckon/settings.json`. `live.py` reads that file directly, because
  the bound key launches it without the panel's environment -- before that it
  silently ignored every model and voice chosen in the panel. Default is
  `gemini-3.8-live`. Only models whose `supportedGenerationMethods` include
  `bidiGenerateContent` can hold a Live session; list them with
  `GET /v1beta/models`.
- **Extended-thinking models refuse a session without a thinking level**
  ("Thinking level must be specified for this model"), and reject `MINIMAL`.
  `live.py` sends `ThinkingConfig(thinking_level=...)` only when the model name
  contains "thinking"; every other model must NOT be sent one. `LOW` is the
  default and keeps it responsive.
- **3.8 Live dispatches tool calls and then ENDS THE TURN without speaking.**
  The spoken answer arrives in the next turn, after the tool response goes back.
  Code that stops reading at the first `turn_complete` sees a model that runs
  tools and never talks. `live.py` is fine because `receive()` is re-entered in
  a loop -- keep it that way. Measured on this machine: 3.8 Live answers in
  2.4s against 3.45s for 3.1 Flash Live; extended-thinking speaks a filler at
  1.3s but takes ~10s to finish.
- **Page text (no scrolling).** `read_page_text()` and `look_at_screen(..., mode)`
  read a window's FULL text -- including what is scrolled off screen -- from the
  AT-SPI accessibility bus, so a long email never has to be screenshotted in
  pieces. The tree walk lives at the bottom of `tools.py` behind
  `python3 tools.py --page-text`, run as a subprocess so a hung accessibility
  call cannot wedge the voice session, and `gi` is imported lazily so machines
  without python-gobject still load the tool layer. Three modes, and the system
  prompt tells the model to choose: `read_page_text()` for text, `mode="image"`
  for anything visual, default `mode="auto"` for both.
- **Which window gets read.** Hyprland's `activewindow` is the source of truth,
  matched against AT-SPI window names. AT-SPI's own ACTIVE state is unreliable
  here -- unregistered apps (Electron, terminals) leave no active window at all,
  and an earlier version happily read *some other* window instead, which would
  have the agent confidently read out a page the user isn't looking at. If the
  focused window publishes no text it returns an error saying so; it never
  substitutes a different window.
- **Enabling page text** takes two things, and BOTH are required (verified by
  testing each alone -- neither works by itself):
  ```
  gsettings set org.gnome.desktop.interface toolkit-accessibility true
  gsettings set org.gnome.desktop.a11y.applications screen-reader-enabled true
  echo '--force-renderer-accessibility' >> ~/.config/chrome-flags.conf
  ```
  The gsettings values persist in dconf and drive `org.a11y.Status` on the
  session bus; the Chrome flag is read by Arch's `/usr/bin/google-chrome-stable`
  wrapper. Chromium apps read the accessibility state **at startup only**, so
  Chrome must be restarted after enabling, and flipping the bus properties at
  runtime does nothing for an already-running browser. Needs `at-spi2-core` and
  `python-gobject`. GTK apps expose text without the Chrome flag.
- **Machine-specific tour values** are read from `~/.config/beckon/settings.json`
  (never committed): `dev_url` is the local dev server the tour opens at the end,
  `dev_line` the narration spoken over it. Both fall back to generic defaults, so
  nothing about one user's machine belongs in `tour.py`.

## Packaging

`packaging/PKGBUILD` builds the package, today with `makepkg -si` straight from
a clone and later from the AUR unchanged. `makepkg -s` resolves dependencies
through pacman, which knows nothing about the AUR, so `python-google-genai` --
the only dependency outside the official repos -- has to be installed first.
It is a **VCS package on purpose**:
the repo carries exactly one commit that gets amended and force-pushed, so a
release tarball's checksum would change under every push and a tag would pin a
tree that no longer exists. `pkgver()` derives `r<count>.<short-sha>` from git.

Packaged installs put the code in `/usr/lib/beckon` with a launcher at
`/usr/bin/beckon`. That is why `live.py` creates `~/.local/share/beckon` itself:
nothing else does when the code lives in `/usr`, and the first logged turn used
to die with FileNotFoundError.

`beckon setup` (`beckon/setup.sh`) adds the Hyprland keybinding. It is a command
the user runs, never a pacman post-install step -- those run as root and must
not rewrite someone's dotfiles. Omarchy has no API for adding a keybinding (its
CLI only reads them), so the script appends the line itself, backs up
`bindings.lua`, matches existing binds on the COMMAND rather than the label (so
an upgrade from the manual install isn't double-bound), and refuses a key that
is already taken.

## Environment overrides

Every one of these beats the panel's saved setting, for a one-off run:

| | |
|---|---|
| `BECKON_LIVE_MODEL` | model for this session |
| `BECKON_LIVE_VOICE` | prebuilt voice name |
| `BECKON_THINKING` | thinking level for extended-thinking models (`LOW`/`MEDIUM`/`HIGH`) |
| `BECKON_BARGE_IN=1` | keep the mic open while it speaks (headphones) |
| `BECKON_UI_PORT` | port for the control panel, default 8777 |
| `GEMINI_API_KEY` / `GOOGLE_API_KEY` | key, instead of the file |

## Pitfalls already hit — don't re-learn these

- Hyprland's synthetic `BTN_LEFT` via `send_key_state` returns `ok` but no
  application receives a click. ydotool works, BUT its virtual pointer has its
  own absolute position and Hyprland delivers ydotool's clicks *there*, not at
  a cursor moved by Hyprland. So position with `ydotool mousemove --absolute`
  too. Its absolute space is a fixed multiple of Hyprland's logical coords
  (2x here); `tools._ydo_move` calibrates on first use and self-corrects.
- Live per-window props go through `hl.dsp.window.set_prop({ prop = "active_border_color",
  value = "rgba(..)" })`; `value = "-1"` clears it. `hyprctl setprop` and
  `hyprctl keyword` do not exist under the Lua config. Used for the
  screen-read border pulse.
- YouTube's `k` key *toggles* play/pause and paused videos that had already
  autoplayed. Use MPRIS: `busctl --user call org.mpris.MediaPlayer2.chromium.instanceN /org/mpris/MediaPlayer2 org.mpris.MediaPlayer2.Player Play` (idempotent).
- X's post editor drops characters under fast synthetic typing. Put the text
  on the clipboard with `wl-copy` and paste with Ctrl+V instead of `wtype`-ing it.
- The Gemini TTS endpoint rate-limits bursts; `narrate.generate` retries.
- Do NOT kill Chrome's main process to restart it -- it leaves a stale
  `~/.config/google-chrome/SingletonLock` pointing at the dead PID and every
  later launch then hangs silently with no window and no error. Close the window
  (`hl.dsp.window.close()`) so Chrome exits cleanly; if it is already stuck,
  delete `SingletonLock`, `SingletonCookie` and `SingletonSocket`.
- To open a window for testing without stealing the user's screen, the classic
  rule prefix works through the Lua dispatcher:
  `hl.dsp.exec_cmd("[workspace 5 silent] uwsm-app -- <cmd>")`. It does not work
  for a second window of an already-running Chrome, which routes the request to
  the existing instance.
- If the panel serves stale code, a previous `ui.py` process is still holding
  port 8777. Kill by the PID from `ss -tlnp | grep 8777`, not by name pattern.

- `close_window` refuses to close Claude Desktop (`com.anthropic.Claude`) or
  Beckon's own panel. A user saying "close all the windows" once took out the
  chat they were driving the agent from, then couldn't get it back.

## Don't

- Don't commit `api_key`, `settings.json`, `history.jsonl`, or anything under
  `~/.config/beckon`. `.gitignore` covers the repo; be careful with copies.
- Don't paste the user's API key into a chat, a log, or a commit.
- Don't run the tour or fire test clicks while the user is actively using the
  machine — clicks land wherever the cursor actually is.
- Don't make the tour (or any tool) send posts or messages. It types; the
  user sends.
