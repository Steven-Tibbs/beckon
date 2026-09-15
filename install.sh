#!/bin/bash
# Install Beckon into ~/.local/share/beckon with a launcher on PATH.
set -euo pipefail

DEST="$HOME/.local/share/beckon"
BIN="$HOME/.local/bin"
SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/beckon"

echo "Installing Beckon…"

missing=()
for cmd in wtype grim wl-copy; do
  command -v "$cmd" >/dev/null 2>&1 || missing+=("$cmd")
done
for mod in websockets sounddevice google.genai; do
  python3 -c "import $mod" 2>/dev/null || missing+=("python: $mod")
done
if ((${#missing[@]})); then
  echo "Missing dependencies: ${missing[*]}" >&2
  echo "See the Requirements section of the README." >&2
  exit 1
fi

command -v ydotool >/dev/null 2>&1 || echo "note: ydotool not found -- mouse clicks will be unavailable (see README)"
command -v omarchy >/dev/null 2>&1 || echo "note: omarchy CLI not found -- the guided tour's theme switching is Omarchy-only"
for opt in notify-send paplay busctl; do
  command -v "$opt" >/dev/null 2>&1 || echo "note: $opt not found -- some features will be limited"
done
python3 -c "import gi" 2>/dev/null \
  || echo "note: python-gobject not found -- reading a page's full text will be unavailable (see README)"

mkdir -p "$DEST" "$BIN" "$HOME/.config/beckon"
cp "$SRC"/*.py "$SRC"/*.html "$SRC"/*.qml "$DEST/"
install -m 755 "$SRC/setup.sh" "$DEST/setup.sh"

cat > "$BIN/beckon" <<'LAUNCH'
#!/bin/bash
case "${1:-live}" in
  ui)    shift; exec python3 "$HOME/.local/share/beckon/ui.py" "$@" ;;
  setup) shift; exec bash "$HOME/.local/share/beckon/setup.sh" "$@" ;;
  live)  shift; exec python3 "$HOME/.local/share/beckon/live.py" "$@" ;;
  *)     exec python3 "$HOME/.local/share/beckon/live.py" "$@" ;;
esac
LAUNCH
chmod +x "$BIN/beckon"

echo
echo "Installed to $DEST"
echo
echo "Next:"
echo "  1. beckon ui        — open the panel and paste your Gemini API key"
echo "  2. beckon setup     — bind a key (F8 by default; 'beckon setup F7' for another)"
echo "  3. press that key   — or run 'beckon' to start a session in the terminal"
echo
echo "To let it read a whole page or email without scrolling (optional):"
echo "  gsettings set org.gnome.desktop.interface toolkit-accessibility true"
echo "  gsettings set org.gnome.desktop.a11y.applications screen-reader-enabled true"
echo "  echo '--force-renderer-accessibility' >> ~/.config/chrome-flags.conf"
echo "  (then restart Chrome -- it reads that only at startup)"
