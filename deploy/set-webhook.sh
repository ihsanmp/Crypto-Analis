#!/usr/bin/env bash
# Daftarkan (atau hapus) webhook Telegram ke Cloudflare Worker.
#
# Pemakaian:
#   bash deploy/set-webhook.sh https://xxx.workers.dev  RAHASIA_ACAK
#   bash deploy/set-webhook.sh --status
#   bash deploy/set-webhook.sh --delete        # kembali ke mode polling
#
# Token bot dibaca dari .env (TELEGRAM_BOT_TOKEN) supaya tidak perlu ditempel di
# baris perintah — jadi tidak tersimpan di riwayat shell.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if [ -f "$REPO_DIR/.env" ]; then
  TOKEN="$(grep -E '^TELEGRAM_BOT_TOKEN=' "$REPO_DIR/.env" | head -1 | cut -d= -f2- | tr -d '"'"'"' ')"
fi
TOKEN="${TOKEN:-${TELEGRAM_BOT_TOKEN:-}}"

if [ -z "${TOKEN:-}" ]; then
  echo "ERROR: TELEGRAM_BOT_TOKEN tidak ketemu."
  echo "Buat file .env berisi TELEGRAM_BOT_TOKEN=..., atau export dulu variabelnya."
  exit 1
fi

API="https://api.telegram.org/bot${TOKEN}"

case "${1:-}" in
  --status)
    echo "== Status webhook saat ini =="
    curl -s "${API}/getWebhookInfo"; echo
    ;;
  --delete)
    echo "== Menghapus webhook (kembali ke mode polling) =="
    curl -s "${API}/deleteWebhook?drop_pending_updates=false"; echo
    ;;
  "")
    echo "Pemakaian: bash deploy/set-webhook.sh <URL_WORKER> <RAHASIA>"
    echo "           bash deploy/set-webhook.sh --status | --delete"
    exit 1
    ;;
  *)
    URL="$1"
    SECRET="${2:-}"
    if [ -z "$SECRET" ]; then
      echo "ERROR: rahasia (secret_token) wajib diisi, harus SAMA dengan TELEGRAM_SECRET di Worker."
      exit 1
    fi
    echo "== Mendaftarkan webhook ke: $URL =="
    curl -s -X POST "${API}/setWebhook" \
      -d "url=${URL}" \
      -d "secret_token=${SECRET}" \
      -d "allowed_updates=[\"message\"]"; echo
    echo
    echo "== Verifikasi =="
    curl -s "${API}/getWebhookInfo"; echo
    ;;
esac
