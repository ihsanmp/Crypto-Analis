#!/usr/bin/env bash
# Pasang bot sebagai service systemd: otomatis hidup lagi kalau crash / server reboot.
# Pemakaian:  bash deploy/install-service.sh
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
USER_NAME="$(whoami)"
PY="$(command -v python3)"

if [ ! -f "$REPO_DIR/.env" ]; then
  echo "ERROR: $REPO_DIR/.env belum ada. Jalankan deploy/setup-server.sh dulu."
  exit 1
fi

sudo tee /etc/systemd/system/crypto-analis.service >/dev/null <<EOF
[Unit]
Description=Bot Riset Koin (Telegram) - Crypto Analis
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$USER_NAME
WorkingDirectory=$REPO_DIR
ExecStart=$PY $REPO_DIR/cloud/bot_daemon.py
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable --now crypto-analis
sleep 3
sudo systemctl status crypto-analis --no-pager -l | head -20

echo
echo "Perintah berguna:"
echo "  lihat log langsung : sudo journalctl -u crypto-analis -f"
echo "  restart            : sudo systemctl restart crypto-analis"
echo "  berhenti           : sudo systemctl stop crypto-analis"
