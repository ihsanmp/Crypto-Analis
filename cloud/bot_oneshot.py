"""Versi one-shot dari bot (untuk GitHub Actions / cron).

Beda dengan bot.py (yang jalan terus di laptop), file ini:
  - Tidak long-polling. Sekali jalan: ambil pesan Telegram yang tertunda,
    proses perintah "analisa", balas, lalu keluar. Cocok dipanggil cron.
  - Tidak pakai TradingView Desktop (tidak ada GUI di cloud). Teknikal lewat
    MCP tradingview versi data (atilaahmettaner) + OHLC CoinGecko.

Mode:
  python bot_oneshot.py --check   -> cuma ngintip: ada perintah analisa baru?
                                     tulis has_work=true/false ke $GITHUB_OUTPUT.
                                     TIDAK menandai pesan sebagai terbaca.
  python bot_oneshot.py           -> proses semua perintah analisa yang tertunda.

Semua konfigurasi lewat environment variable (di-set dari GitHub Secrets):
  TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, COINGLASS_API_KEY, CLAUDE_CODE_OAUTH_TOKEN
"""

import json
import os
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
# Claude dijalankan dari root repo supaya path "cloud/indicators.py" di prompt valid
REPO_ROOT = os.path.dirname(BASE_DIR)
PROMPT_FILE = os.path.join(BASE_DIR, "prompts", "analisa.md")
MCP_CONFIG = os.path.join(BASE_DIR, ".mcp.cloud.json")

ALLOWED_TOOLS = ",".join([
    "mcp__coinglass__*",
    "mcp__coinmarketcap__*",
    "mcp__tradingview__*",
    "WebSearch",
    "WebFetch",
    "Bash",          # untuk menjalankan cloud/indicators.py
])

# Maksimal analisa per run. Job GitHub Actions dibatasi 30 menit, satu analisa bisa
# 15 menit — lebih dari 2 berisiko job dibunuh di tengah jalan dan pesan hilang.
MAX_JOBS_PER_RUN = 2


def tg_api(token, method, params=None, timeout=60):
    url = f"https://api.telegram.org/bot{token}/{method}"
    data = urllib.parse.urlencode(params or {}).encode()
    req = urllib.request.Request(url, data=data)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        print(f"[telegram] HTTP {e.code} di {method}: {e.read().decode(errors='replace')}", file=sys.stderr)
    except Exception as e:
        print(f"[telegram] error di {method}: {e}", file=sys.stderr)
    return None


def send_message(token, chat_id, text):
    for i in range(0, len(text), 3900):
        tg_api(token, "sendMessage", {"chat_id": chat_id, "text": text[i:i + 3900]})
        time.sleep(0.4)


def is_analisa(text):
    low = (text or "").strip().lower().lstrip("/")
    return low == "analisa" or low.startswith("analisa ")


def fetch_updates(token, offset=None):
    params = {"timeout": 0}
    if offset is not None:
        params["offset"] = offset
    resp = tg_api(token, "getUpdates", params)
    return resp["result"] if resp and resp.get("ok") else []


def allowed_chats():
    return {c.strip() for c in os.environ.get("TELEGRAM_CHAT_ID", "").split(",") if c.strip()}


def relevant_messages(updates, allowed):
    """Kembalikan (update_id, chat_id, text) untuk pesan analisa dari chat yang diizinkan.

    update_id ikut dikembalikan supaya kita bisa meng-ack HANYA sampai pesan yang
    benar-benar diproses run ini — sisanya tetap mengantre untuk run berikutnya."""
    out = []
    for upd in updates:
        msg = upd.get("message") or {}
        chat_id = str(msg.get("chat", {}).get("id", ""))
        text = (msg.get("text") or "").strip()
        if not chat_id or not text:
            continue
        if chat_id not in allowed:      # fail-closed: hanya chat yang terdaftar
            print(f"[skip] chat tak terdaftar: {chat_id}")
            continue
        if is_analisa(text):
            out.append((upd["update_id"], chat_id, text.lower().lstrip("/")))
    return out


def write_output(has_work):
    gh_out = os.environ.get("GITHUB_OUTPUT")
    line = f"has_work={'true' if has_work else 'false'}"
    print(f"[check] {line}")
    if gh_out:
        with open(gh_out, "a", encoding="utf-8") as f:
            f.write(line + "\n")


def build_prompt(coin):
    with open(PROMPT_FILE, encoding="utf-8") as f:
        base = f.read()
    if coin:
        cmd = f"## Perintah user\nMode KOIN. Analisa mendalam koin: **{coin}**\n"
    else:
        cmd = ("## Perintah user\nMode SCAN. Cari 3-5 koin paling menarik saat ini "
               "untuk spot/futures jangka menengah, lalu pilih 1-2 setup terbaik.\n")
    return f"{base}\n---\n{cmd}"


def run_analysis(prompt, timeout):
    claude = shutil.which("claude")
    if not claude:
        return None, "Perintah `claude` tidak ditemukan di runner."
    cmd = [
        claude, "-p", prompt,
        "--output-format", "text",
        "--mcp-config", MCP_CONFIG,
        "--allowedTools", ALLOWED_TOOLS,
        "--dangerously-skip-permissions",
        "--max-turns", "60",
    ]
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=timeout, cwd=REPO_ROOT,
        )
    except subprocess.TimeoutExpired:
        return None, f"Analisa melebihi batas waktu {timeout} detik."
    if result.returncode != 0:
        return None, f"Claude gagal (exit {result.returncode}):\n{(result.stderr or result.stdout or '')[-1500:]}"
    return result.stdout.strip(), None


def process(token, chat_id, low):
    words = low.split()
    coin = " ".join(words[1:]) if len(words) > 1 else None
    label = f"koin {coin.upper()}" if coin else "scan pasar"
    send_message(token, chat_id, f"⏳ Oke, mulai riset {label} (dari cloud). Tunggu beberapa menit ya...")

    timeout = int(os.environ.get("ANALYSIS_TIMEOUT", "900"))
    output, err = run_analysis(build_prompt(coin), timeout)
    if err:
        send_message(token, chat_id, f"❌ {err}")
    elif not output:
        send_message(token, chat_id, "❌ Analisa selesai tapi output kosong. Coba lagi.")
    else:
        send_message(token, chat_id, output)


def config_problem():
    """Cek konfigurasi wajib. Return pesan error, atau None kalau beres."""
    if not os.environ.get("TELEGRAM_BOT_TOKEN", "").strip():
        return "TELEGRAM_BOT_TOKEN kosong — isi GitHub Secret dengan token dari @BotFather."
    if not allowed_chats():
        return ("TELEGRAM_CHAT_ID kosong — isi GitHub Secret dengan chat ID kamu. "
                "Bot sengaja menolak melayani semua chat demi keamanan: tanpa daftar ini, "
                "siapa pun yang menemukan bot bisa menghabiskan kuota Claude-mu.")
    return None


def main():
    check_only = "--check" in sys.argv[1:]

    problem = config_problem()
    if problem:
        # Jangan bikin workflow gagal tiap 5 menit (spam notifikasi). Cukup laporkan
        # jelas di log lalu berhenti dengan tenang.
        print(f"[konfigurasi] {problem}", file=sys.stderr)
        if check_only:
            write_output(False)
        return

    token = os.environ["TELEGRAM_BOT_TOKEN"].strip()
    allowed = allowed_chats()
    updates = fetch_updates(token)

    if check_only:
        # Cuma ngintip — JANGAN ack, biar run berikutnya masih lihat pesannya.
        write_output(bool(relevant_messages(updates, allowed)))
        return

    if not updates:
        print("[run] tidak ada update.")
        return

    jobs = relevant_messages(updates, allowed)
    if not jobs:
        # Tidak ada perintah analisa: ack semua supaya antrean tidak menumpuk.
        fetch_updates(token, offset=max(u["update_id"] for u in updates) + 1)
        print("[run] tidak ada perintah analisa.")
        return

    # Batasi jumlah analisa per run supaya total waktu tetap di bawah timeout job.
    # Sisanya TIDAK di-ack, jadi tetap mengantre dan dikerjakan run berikutnya.
    batch = jobs[:MAX_JOBS_PER_RUN]
    fetch_updates(token, offset=batch[-1][0] + 1)   # ack sampai job terakhir yang diproses

    sisa = len(jobs) - len(batch)
    print(f"[run] memproses {len(batch)} perintah analisa"
          + (f" ({sisa} sisanya menunggu run berikutnya)." if sisa else "."))
    for _, chat_id, low in batch:
        process(token, chat_id, low)


if __name__ == "__main__":
    main()
