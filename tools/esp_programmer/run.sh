#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV="$SCRIPT_DIR/venv"

if [[ ! -d "$VENV" ]]; then
    python3 -m venv "$VENV"
    "$VENV/bin/python" -m pip install --upgrade pip
    "$VENV/bin/python" -m pip install PySide6 pyserial esptool
fi

exec "$VENV/bin/python" "$SCRIPT_DIR/esp_programmer.py"
