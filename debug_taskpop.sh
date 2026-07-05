#!/usr/bin/env bash
set -euo pipefail
echo "TaskPop command:"; command -v taskpop || true
echo; echo "Wrapper:"; sed -n '1,140p' "$HOME/.local/bin/taskpop" || true
echo; echo "Config:"; cat "$HOME/.config/taskpop/config.json" 2>/dev/null || true
echo; echo "OAuth files:"; ls -l "$HOME/.config/taskpop" 2>/dev/null || true
echo; echo "Shortcut:"; KEY="/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/taskpop/"; gsettings get org.gnome.settings-daemon.plugins.media-keys.custom-keybinding:"$KEY" binding || true; gsettings get org.gnome.settings-daemon.plugins.media-keys.custom-keybinding:"$KEY" command || true
echo; echo "Processes:"; ps -eo pid,comm,%cpu,%mem,rss,args | grep -i taskpop | grep -v grep || true
