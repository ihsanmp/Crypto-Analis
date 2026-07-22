#!/usr/bin/env bash
# Pasang bot di server Ubuntu/Debian yang bersih.
# Pemakaian:  bash deploy/setup-server.sh
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
echo ">> Repo: $REPO_DIR"

echo ">> 1/5 Paket dasar (python, git, curl)"
sudo apt-get update -qq
sudo apt-get install -y -qq python3 python3-pip python3-venv git curl

echo ">> 2/5 Node.js 20 (untuk Claude Code CLI & server MCP)"
if ! command -v node >/dev/null 2>&1; then
  curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
  sudo apt-get install -y -qq nodejs
fi
node --version

echo ">> 3/5 Claude Code CLI + server MCP (Node)"
sudo npm install -g @anthropic-ai/claude-code mcp-coinglass @shinzolabs/coinmarketcap-mcp

echo ">> 4/5 Server MCP TradingView (Python)"
pip3 install --break-system-packages -q tradingview-mcp-server || pip3 install -q tradingview-mcp-server

echo ">> 5/5 Cek berkas .env"
if [ ! -f "$REPO_DIR/.env" ]; then
  cat > "$REPO_DIR/.env" <<'ENVEOF'
# Isi nilai di bawah, lalu jalankan ulang bot.
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=
COINMARKETCAP_API_KEY=
CLAUDE_CODE_OAUTH_TOKEN=
# Opsional (sentimen derivatif; boleh dikosongkan)
COINGLASS_API_KEY=
SUBSCRIPTION_LEVEL=Basic
ENVEOF
  chmod 600 "$REPO_DIR/.env"
  echo "   -> Dibuatkan $REPO_DIR/.env . ISI DULU nilainya sebelum menjalankan bot."
else
  echo "   -> .env sudah ada, dilewati."
fi

echo
echo "SELESAI. Langkah berikutnya:"
echo "  1) Isi $REPO_DIR/.env"
echo "  2) Uji jalan langsung:  python3 cloud/bot_daemon.py"
echo "  3) Kalau sudah benar, pasang sebagai service:  bash deploy/install-service.sh"
