#!/usr/bin/env bash
set -euo pipefail
SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ICON_DIR="$HOME/.local/share/icons/hicolor"
DESKTOP_DIR="$HOME/.local/share/applications"
APP_ID="com.dsynz.TaskPop"
mkdir -p "$ICON_DIR" "$DESKTOP_DIR"
rsync -a "$SRC_DIR/icons/hicolor/" "$ICON_DIR/"
if [[ -f "$DESKTOP_DIR/$APP_ID.desktop" ]]; then
  sed -i 's/^Icon=.*/Icon=taskpop/' "$DESKTOP_DIR/$APP_ID.desktop"
fi
if [[ -f "$DESKTOP_DIR/taskpop.desktop" ]]; then
  sed -i 's/^Icon=.*/Icon=taskpop/' "$DESKTOP_DIR/taskpop.desktop"
fi
if command -v gtk-update-icon-cache >/dev/null 2>&1; then
  gtk-update-icon-cache -f -t "$ICON_DIR" >/dev/null 2>&1 || true
fi
echo "TaskPop icon installed. Log out/in if GNOME still shows the old icon."
