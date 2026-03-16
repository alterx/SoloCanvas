#!/usr/bin/env bash
# ============================================================
#  SoloCanvas - Launch Script (Linux)
# ============================================================

set -euo pipefail

echo "============================================================"
echo " SoloCanvas - Launch Script"
echo "============================================================"
echo

# ── 1. Locate Python 3 ───────────────────────────────────────
PYTHON=""
for candidate in python3 python; do
    if command -v "$candidate" &>/dev/null; then
        ver=$("$candidate" --version 2>&1 | awk '{print $2}')
        major=$(echo "$ver" | cut -d. -f1)
        if [ "$major" = "3" ]; then
            PYTHON="$candidate"
            echo "Found Python $ver  ($PYTHON)"
            break
        fi
    fi
done

if [ -z "$PYTHON" ]; then
    echo "[ERROR] Python 3 not found."
    echo
    echo "Install it with your package manager, for example:"
    echo "  sudo apt install python3 python3-pip   # Debian / Ubuntu"
    echo "  sudo dnf install python3               # Fedora"
    exit 1
fi

# ── 2. Check / install required packages ─────────────────────
echo "Checking prerequisites..."
echo

MISSING=0

check_pkg() {
    local label="$1"
    local import="$2"
    if "$PYTHON" -c "import $import" &>/dev/null; then
        echo "  [OK]      $label"
    else
        echo "  [MISSING] $label"
        MISSING=1
    fi
}

check_pkg "PyQt6"     "PyQt6"
check_pkg "Pillow"    "PIL"
check_pkg "qtawesome" "qtawesome"

if [ "$MISSING" -eq 1 ]; then
    echo
    echo "[WARNING] Some packages are missing."
    read -rp "Install missing packages now? (y/N): " answer
    case "$answer" in
        [Yy]*)
            echo
            echo "Installing missing packages..."
            "$PYTHON" -m pip install --user PyQt6 Pillow "qtawesome>=1.3.0"
            echo
            echo "All packages installed successfully."
            ;;
        *)
            echo "Aborting launch. Install the missing packages and try again."
            exit 1
            ;;
    esac
else
    echo "All prerequisites satisfied."
fi

# ── 3. Launch app ────────────────────────────────────────────
echo
echo "Launching SoloCanvas..."

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Detach from terminal so the shell prompt returns immediately
nohup "$PYTHON" "$SCRIPT_DIR/main.py" &>/dev/null &
disown
