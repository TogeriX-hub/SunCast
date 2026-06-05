#!/bin/bash
# SunCast – Raspberry Pi Setup
# Aufruf: bash install_pi.sh

set -e

REPO_DIR="$(cd "$(dirname "$0")" && pwd)"
CURRENT_USER="$(whoami)"

echo "=== SunCast Pi Setup ==="
echo "Repo:     $REPO_DIR"
echo "Benutzer: $CURRENT_USER"
echo ""

# ── 1. System-Pakete ─────────────────────────────────────────────────────────
echo "[1/4] System-Pakete installieren..."
sudo apt update
sudo apt install -y \
    git \
    python3-pip \
    python3-venv

# ── 2. Python-Abhängigkeiten ─────────────────────────────────────────────────
echo "[2/4] Python-Pakete installieren..."
pip3 install --break-system-packages -r "$REPO_DIR/requirements.txt"

# ── 3. config.yaml vorbereiten ───────────────────────────────────────────────
echo "[3/4] Konfiguration prüfen..."
if grep -q "simulator: true" "$REPO_DIR/config.yaml"; then
    echo ""
    echo "  HINWEIS: config.yaml ist noch im Simulator-Modus."
    echo "  Für Echtbetrieb anpassen:"
    echo "    meshcore.simulator: false"
    echo "    meshcore.host: <IP des Heltec #2>"
    echo "    meshcore.channel_idx: 0"
    echo "    location.default: Stuttgart  (oder dein Ort)"
    echo ""
fi

# ── 4. systemd-Service einrichten ────────────────────────────────────────────
echo "[4/4] systemd-Service einrichten..."

SERVICE_SRC="$REPO_DIR/suncast.service"
SERVICE_TMP="/tmp/suncast.service"

# User und Pfad im Service anpassen
sed "s|/home/pi|/home/$CURRENT_USER|g" "$SERVICE_SRC" > "$SERVICE_TMP"

sudo cp "$SERVICE_TMP" /etc/systemd/system/suncast.service
sudo systemctl daemon-reload
sudo systemctl enable suncast.service

echo "    systemd-Service installiert und aktiviert."

# ── Abschluss ────────────────────────────────────────────────────────────────
echo ""
echo "=== Setup abgeschlossen ==="
echo ""
echo "SunCast manuell testen:"
echo "  cd $REPO_DIR && python3 suncast.py"
echo ""
echo "SunCast als Service starten (Dauerbetrieb):"
echo "  sudo systemctl start suncast"
echo "  sudo systemctl status suncast"
echo "  journalctl -u suncast -f"
echo ""
echo "Dashboard:"
echo "  http://localhost:8081  (lokal auf dem Pi)"
echo "  http://<Pi-IP>:8081    (vom Netzwerk)"
