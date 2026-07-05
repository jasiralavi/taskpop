#!/usr/bin/env bash
set -euo pipefail
pkill -f "$HOME/.local/share/taskpop/taskpop/main.py" || true
echo "Stopped existing TaskPop instances."
