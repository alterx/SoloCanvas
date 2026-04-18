#!/usr/bin/env bash
# ============================================================
#  SoloCanvas - Launch Script (Linux)
# ============================================================

set -euo pipefail

echo "============================================================"
echo " SoloCanvas - Launch Script"
echo "============================================================"
echo

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="$SCRIPT_DIR/.venv"

# ── 1. Locate Python 3 ───────────────────────────────────────
SYSTEM_PYTHON=""
for candidate in python3 python; do
    if command -v "$candidate" &>/dev/null; then
        ver=$("$candidate" --version 2>&1 | awk '{print $2}')
        major=$(echo "$ver" | cut -d. -f1)
        if [ "$major" = "3" ]; then
            SYSTEM_PYTHON="$candidate"
            echo "Found Python $ver  ($SYSTEM_PYTHON)"
            break
        fi
    fi
done

if [ -z "$SYSTEM_PYTHON" ]; then
    echo "[ERROR] Python 3 not found."
    echo
    echo "Install it with your package manager, for example:"
    echo "  sudo apt install python3 python3-venv   # Debian / Ubuntu"
    echo "  sudo dnf install python3                # Fedora"
    echo "  sudo pacman -S python                   # Arch"
    exit 1
fi

# ── Helper: detect package manager and install venv/pip ──────
install_venv_deps() {
    if command -v apt-get &>/dev/null; then
        PKG_MGR="apt-get"
        PACKAGES="python3-venv python3-pip"
    elif command -v dnf &>/dev/null; then
        PKG_MGR="dnf"
        PACKAGES="python3-pip"
    elif command -v pacman &>/dev/null; then
        PKG_MGR="pacman"
        PACKAGES="python-pip"
    elif command -v zypper &>/dev/null; then
        PKG_MGR="zypper"
        PACKAGES="python3-pip"
    else
        echo
        echo "[ERROR] Could not detect a supported package manager."
        echo "Please install Python venv/pip support manually, then re-run ./launch.sh."
        echo
        echo "  Debian/Ubuntu:  sudo apt install python3-venv python3-pip"
        echo "  Fedora/RHEL:    sudo dnf install python3-pip"
        echo "  Arch:           sudo pacman -S python-pip"
        echo "  openSUSE:       sudo zypper install python3-pip"
        exit 1
    fi

    echo
    echo "[INFO] Python's 'venv' module is not fully available on this system."
    echo
    echo "  SoloCanvas uses a virtual environment to install its Python"
    echo "  dependencies without touching your system Python installation."
    echo "  The following system package(s) are needed to set this up:"
    echo
    echo "    $PACKAGES"
    echo
    echo "  This requires administrator (sudo) access via $PKG_MGR."
    echo "  No other changes will be made to your system."
    echo
    read -rp "Install now? (y/N): " answer
    case "$answer" in
        [Yy]*)
            case "$PKG_MGR" in
                apt-get) sudo apt-get install -y $PACKAGES ;;
                dnf)     sudo dnf install -y $PACKAGES ;;
                pacman)  sudo pacman -S --noconfirm $PACKAGES ;;
                zypper)  sudo zypper install -y $PACKAGES ;;
            esac
            ;;
        *)
            echo
            echo "Cannot continue. To install manually:"
            echo "  $PACKAGES  (using $PKG_MGR)"
            echo "Then run ./launch.sh again."
            exit 1
            ;;
    esac
}

# ── 2. Create virtual environment if needed ──────────────────
if [ ! -f "$VENV_DIR/bin/python" ] || [ ! -f "$VENV_DIR/bin/pip" ]; then
    # Clean up any partial venv from a previous failed attempt
    rm -rf "$VENV_DIR"
    echo "Creating virtual environment..."
    if ! "$SYSTEM_PYTHON" -m venv "$VENV_DIR" 2>/dev/null; then
        install_venv_deps
        echo
        echo "Retrying virtual environment creation..."
        "$SYSTEM_PYTHON" -m venv "$VENV_DIR"
    fi
    echo "  [OK] Virtual environment created at .venv/"
    echo
fi

PYTHON="$VENV_DIR/bin/python"
PIP="$VENV_DIR/bin/pip"

# ── 3. Check / install required packages ─────────────────────
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

check_pkg "PyQt6"       "PyQt6"
check_pkg "qtawesome"   "qtawesome"
check_pkg "markdown"    "markdown"
check_pkg "markdownify" "markdownify"
check_pkg "PyMuPDF"     "pymupdf"

if [ "$MISSING" -eq 1 ]; then
    echo
    echo "Installing missing packages into virtual environment..."
    "$PIP" install --quiet -r "$SCRIPT_DIR/requirements.txt"
    echo "  [OK] All packages installed."
fi

echo

# ── 4. Launch app ────────────────────────────────────────────
echo "Launching SoloCanvas..."

"$PYTHON" "$SCRIPT_DIR/main.py"

echo
read -rp "Press Enter to close..." _
