#!/usr/bin/env bash
set -euo pipefail

APP_NAME="taskpop"
APP_ID="com.dsynz.TaskPop"
SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR="$HOME/.local/share/$APP_NAME"
BIN_DIR="$HOME/.local/bin"
VENV_DIR="$APP_DIR/.venv"
DESKTOP_DIR="$HOME/.local/share/applications"
ICON_DIR="$HOME/.local/share/icons/hicolor"

printf 'Installing system dependencies...\n'
sudo apt update
sudo apt install -y python3-venv python3-gi python3-gi-cairo gir1.2-gtk-4.0 rsync

printf 'Installing TaskPop files...\n'
mkdir -p "$APP_DIR" "$BIN_DIR" "$DESKTOP_DIR" "$ICON_DIR"
rsync -a --delete "$SRC_DIR/taskpop/" "$APP_DIR/taskpop/"
cp "$SRC_DIR/requirements.txt" "$APP_DIR/requirements.txt"

printf 'Installing TaskPop icon...\n'
rsync -a "$SRC_DIR/icons/hicolor/" "$ICON_DIR/"

printf 'Creating Python environment...\n'
python3 -m venv --system-site-packages "$VENV_DIR"
"$VENV_DIR/bin/python" -m pip install --upgrade pip
"$VENV_DIR/bin/pip" install -r "$APP_DIR/requirements.txt"

cat > "$BIN_DIR/taskpop" <<EOF
#!/usr/bin/env bash
set -euo pipefail

APP_DIR="$APP_DIR"
VENV_DIR="$VENV_DIR"
MAIN_PATH="\$APP_DIR/taskpop/main.py"
PYTHON_PATH="\$VENV_DIR/bin/python"

kill_existing() {
  mapfile -t pids < <(pgrep -f "\$MAIN_PATH" || true)

  if (( \${#pids[@]} > 0 )); then
    kill "\${pids[@]}" 2>/dev/null || true
    sleep 0.15

    mapfile -t pids2 < <(pgrep -f "\$MAIN_PATH" || true)
    if (( \${#pids2[@]} > 0 )); then
      kill -9 "\${pids2[@]}" 2>/dev/null || true
    fi
    return 0
  fi
  return 1
}

case "\${1:-}" in
  --kill)
    kill_existing || true
    exit 0
    ;;
  --open)
    shift
    exec "\$PYTHON_PATH" "\$MAIN_PATH" "\$@"
    ;;
esac

if kill_existing; then
  exit 0
fi

exec "\$PYTHON_PATH" "\$MAIN_PATH" "\$@"
EOF
chmod +x "$BIN_DIR/taskpop"

rm -f "$DESKTOP_DIR/taskpop.desktop"

cat > "$DESKTOP_DIR/$APP_ID.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=TaskPop
Comment=Fast local-first task popup
Exec=$BIN_DIR/taskpop
Icon=taskpop
Terminal=false
Categories=Utility;GTK;
StartupNotify=false
StartupWMClass=TaskPop
EOF

update-desktop-database "$DESKTOP_DIR" >/dev/null 2>&1 || true
if command -v gtk-update-icon-cache >/dev/null 2>&1; then
  gtk-update-icon-cache -f -t "$ICON_DIR" >/dev/null 2>&1 || true
fi

printf '\nInstalled. Run with: taskpop\n'
printf 'Desktop file: %s\n' "$DESKTOP_DIR/$APP_ID.desktop"
printf 'Icon installed as: taskpop\n'
printf 'To bind Super+T, run: ./install_shortcut_gnome.sh\n'
