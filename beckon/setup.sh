#!/bin/bash
# beckon setup [KEY] -- bind a key to Beckon in Hyprland.
#
# Deliberately a command the user runs, never something the package does on
# install: a pacman hook runs as root and must not rewrite anyone's dotfiles.
# Omarchy has no API for adding a keybinding (its CLI only reads them), so this
# appends the line itself, backs the file up first, and refuses to touch a key
# that is already spoken for.
set -euo pipefail

KEY="${1:-F8}"
BINDINGS="$HOME/.config/hypr/bindings.lua"
CMD="$(command -v beckon || true)"
[[ -n $CMD ]] || CMD="$HOME/.local/bin/beckon"

die() { echo "beckon setup: $1" >&2; exit 1; }

[[ -f $BINDINGS ]] || die "no $BINDINGS -- this expects Omarchy's Hyprland layout.
  Add this to your Hyprland config by hand instead:
    bind = , $KEY, exec, $CMD"

# Match on the COMMAND, not the label: someone upgrading from the manual
# install has a bind pointing at live.py under whatever name they gave it, and
# binding a second key to the same thing helps nobody.
if grep -qiE 'o\.bind\(.*(beckon|live\.py)' "$BINDINGS"; then
  echo "Already bound:"
  grep -inE 'o\.bind\(.*(beckon|live\.py)' "$BINDINGS" | sed 's/^/  /'
  echo "Nothing to do. Edit $BINDINGS if you want a different key."
  exit 0
fi

# Is the key already taken? Ask Omarchy for the live table when it is available.
if command -v omarchy >/dev/null 2>&1; then
  taken=$(omarchy menu keybindings --print 2>/dev/null | grep -i "^${KEY} " || true)
  if [[ -n $taken ]]; then
    echo "$KEY is already bound to: ${taken#*→}" >&2
    die "pick another key, e.g. 'beckon setup F7'"
  fi
fi

cp "$BINDINGS" "$BINDINGS.bak-$(date +%Y%m%d%H%M%S)"
cat >> "$BINDINGS" <<LUA

-- Beckon: voice control via the Gemini Live API.
-- Press once to start listening, again to end the session.
o.bind("$KEY", "Beckon", "$CMD")
LUA

if command -v hyprctl >/dev/null 2>&1 && hyprctl reload >/dev/null 2>&1; then
  errs=$(hyprctl configerrors 2>/dev/null | grep -v '^no errors' || true)
  [[ -z $errs ]] || echo "warning: Hyprland reported config errors:
$errs" >&2
fi

echo "Bound $KEY to Beckon (backup: $(basename "$BINDINGS").bak-*)."
echo "Press $KEY to start a session. Set your API key first with: beckon ui"
