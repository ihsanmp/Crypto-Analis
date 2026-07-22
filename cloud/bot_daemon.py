"""Versi DAEMON — untuk server always-on (VPS), bukan GitHub Actions.

Beda dengan bot_oneshot.py:
  - Long-polling ke Telegram (getUpdates timeout 50 detik) -> pesan diproses BEGITU masuk,
    balasan hitungan detik. Tidak menunggu jadwal cron yang di GitHub bisa telat 1-3 jam.
  - Jalan terus-menerus; dijaga systemd supaya otomatis hidup lagi kalau mati/reboot.
  - Tidak ada batas MAX_JOBS_PER_RUN (tidak ada batas waktu job seperti di Actions).

Seluruh logika mode (analisa / narasi / ngobrol / help), prompt, dan pemanggilan Claude
dipakai ulang dari bot_oneshot.py supaya tidak ada dua sumber kebenaran.

Konfigurasi dibaca dari environment, atau dari file .env di root repo.

Pemakaian:
    python cloud/bot_daemon.py
"""

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from bot_oneshot import (  # noqa: E402
    REPO_ROOT, actionable_messages, allowed_chats, config_problem, process, tg_api,
)


def load_dotenv():
    """Muat .env dari root repo (server tidak punya GitHub Secrets)."""
    path = os.path.join(REPO_ROOT, ".env")
    if not os.path.exists(path):
        return
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            os.environ.setdefault(key.strip(), val.strip().strip('"').strip("'"))


def log(msg):
    print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}", flush=True)


def main():
    load_dotenv()

    problem = config_problem()
    if problem:
        sys.exit(f"Konfigurasi belum lengkap: {problem}")

    token = os.environ["TELEGRAM_BOT_TOKEN"].strip()
    allowed = allowed_chats()

    me = tg_api(token, "getMe")
    if not me or not me.get("ok"):
        sys.exit("Token bot tidak valid / tidak bisa konek ke Telegram.")
    log(f"Bot @{me['result']['username']} jalan. Melayani chat: {', '.join(sorted(allowed))}")

    offset = None
    idle_errors = 0

    while True:
        try:
            params = {"timeout": 50}
            if offset is not None:
                params["offset"] = offset
            # timeout HTTP harus lebih besar dari timeout long-poll Telegram
            resp = tg_api(token, "getUpdates", params, timeout=70)

            if not resp or not resp.get("ok"):
                idle_errors += 1
                # backoff bertahap, maksimal 60 detik, supaya tidak membanjiri saat gangguan
                time.sleep(min(60, 2 ** min(idle_errors, 5)))
                continue
            idle_errors = 0

            updates = resp["result"]
            if not updates:
                continue

            # Ack semua update yang sudah diambil supaya tidak terproses dua kali
            offset = max(u["update_id"] for u in updates) + 1

            for _, chat_id, text in actionable_messages(updates, allowed):
                log(f"pesan dari {chat_id}: {text[:70]!r}")
                try:
                    process(token, chat_id, text)
                except Exception as e:
                    # Satu pesan gagal tidak boleh mematikan bot
                    log(f"ERROR saat memproses: {type(e).__name__}: {e}")
                    tg_api(token, "sendMessage", {
                        "chat_id": chat_id,
                        "text": f"❌ Terjadi error internal: {type(e).__name__}. Coba lagi ya.",
                    })

        except KeyboardInterrupt:
            log("Dihentikan manual.")
            return
        except Exception as e:
            log(f"ERROR di loop utama: {type(e).__name__}: {e}")
            time.sleep(5)


if __name__ == "__main__":
    main()
