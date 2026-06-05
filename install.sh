#!/bin/bash
# SunCast – Mac Install
# Aufruf: bash install.sh

set -e

echo "=== SunCast Install (Mac) ==="
echo ""

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

# 1. Python prüfen
if ! command -v python3 &>/dev/null; then
    echo "FEHLER: python3 nicht gefunden."
    echo "Installieren: https://www.python.org/downloads/"
    exit 1
fi

PYTHON_VERSION=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
echo "→ Python $PYTHON_VERSION gefunden"

# 2. Python-Pakete installieren
echo "→ Installiere Python-Pakete..."
pip3 install --break-system-packages -r "$SCRIPT_DIR/requirements.txt"

echo ""
echo "✓ Installation abgeschlossen."
echo ""
echo "SunCast starten:"
echo "  cd $SCRIPT_DIR"
echo "  python3 suncast.py"
echo ""
echo "Dashboard öffnen:"
echo "  http://localhost:8081"
