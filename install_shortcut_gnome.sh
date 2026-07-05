#!/usr/bin/env bash
set -euo pipefail

KEY="/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/taskpop/"
CMD="$HOME/.local/bin/taskpop"

if ! command -v gsettings >/dev/null; then
  echo "gsettings not found. Add the shortcut manually in Settings → Keyboard."
  exit 1
fi

if [[ ! -x "$CMD" ]]; then
  echo "TaskPop command not found or not executable: $CMD"
  echo "Run ./install_ubuntu.sh first."
  exit 1
fi

current="$(gsettings get org.gnome.settings-daemon.plugins.media-keys custom-keybindings)"

new="$(python3 - "$current" "$KEY" <<'PY'
import ast, sys
current, key = sys.argv[1], sys.argv[2]
try:
    items = ast.literal_eval(current.replace("@as ", ""))
    if not isinstance(items, list):
        items = []
except Exception:
    items = []
if key not in items:
    items.append(key)
print("[" + ", ".join(repr(x) for x in items) + "]")
PY
)"

gsettings set org.gnome.settings-daemon.plugins.media-keys custom-keybindings "$new"
gsettings set org.gnome.settings-daemon.plugins.media-keys.custom-keybinding:"$KEY" name 'TaskPop'
gsettings set org.gnome.settings-daemon.plugins.media-keys.custom-keybinding:"$KEY" command "$CMD"
gsettings set org.gnome.settings-daemon.plugins.media-keys.custom-keybinding:"$KEY" binding '<Super>t'

echo "Shortcut installed: Super+T → $CMD"
echo "Press Super+T once to open. Press it again to close."
