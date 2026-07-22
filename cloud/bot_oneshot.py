"""Versi one-shot dari bot (untuk GitHub Actions / cron).

Sekali jalan: ambil pesan Telegram yang tertunda, proses, balas, lalu keluar.

Dua mode berdasarkan isi pesan:
  - "analisa" / "analisa <koin>"  -> analisa lengkap terstruktur (metodologi skor penuh)
  - pesan bebas lain               -> mode NGOBROL (jawaban santai, tetap berbasis data)
  - "/start" / "/help"             -> teks bantuan (tanpa memanggil Claude, hemat)

Catatan: tiap pesan diproses INDEPENDEN — tidak ada memori percakapan antar pesan
(GitHub Actions stateless). Pertanyaan lanjutan sebaiknya menyebut ulang koinnya.

Konfigurasi lewat environment variable (di-set dari GitHub Secrets):
  TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, COINGLASS_API_KEY,
  COINMARKETCAP_API_KEY, CLAUDE_CODE_OAUTH_TOKEN
"""

import json
import os
import re
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
ANALISA_PROMPT = os.path.join(BASE_DIR, "prompts", "analisa.md")
CHAT_PROMPT = os.path.join(BASE_DIR, "prompts", "chat.md")
NARASI_PROMPT = os.path.join(BASE_DIR, "prompts", "narasi.md")
MCP_CONFIG = os.path.join(BASE_DIR, ".mcp.cloud.json")

ALLOWED_TOOLS = ",".join([
    "mcp__coinglass__*",
    "mcp__coinmarketcap__*",
    "mcp__tradingview__*",
    "WebSearch",
    "WebFetch",
    "Bash",          # untuk menjalankan cloud/indicators.py
])

# Maksimal pekerjaan per run. Job GitHub Actions dibatasi 30 menit; satu analisa bisa
# 15 menit -> lebih dari 2 berisiko job dibunuh di tengah jalan dan pesan hilang.
MAX_JOBS_PER_RUN = 2

HELP_TEXT = (
    "🤖 Halo! Aku bot riset crypto. Dua cara pakai aku:\n\n"
    "1) ANALISA LENGKAP (terstruktur, berskor):\n"
    "   • ketik: analisa <koin>   (contoh: analisa sol)\n"
    "   • ketik: analisa          -> aku scan pasar & pilih beberapa koin menarik\n\n"
    "2) CARI KOIN LEWAT NARASI/SEKTOR:\n"
    "   • carikan koin dengan narasi privacy yang menarik\n"
    "     (ganti privacy dengan: AI, RWA, DePIN, gaming, meme, DeFi, L2, storage, dll)\n"
    "   • carikan koin narasi yang menarik   -> aku cari sendiri narasi yang lagi jalan\n"
    "   • narasi apa yang lagi jalan?\n\n"
    "3) NGOBROL SANTAI:\n"
    "   • tanya bebas, misal: bagaimana pendapatmu tentang bitcoin?\n"
    "   • atau: prospek eth jangka menengah gimana?\n\n"
    "Analisa & screening narasi makan waktu beberapa menit. Ngobrol biasanya lebih cepat.\n"
    "📌 Fokusku SPOT saja — tidak memberi saran short/leverage/futures.\n"
    "⚠️ Semua output riset berbasis data, bukan saran keuangan."
)


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
    """Kirim pesan (dipecah kalau melebihi batas Telegram). Return True kalau SEMUA
    potongan benar-benar terkirim — pemanggil wajib memeriksa hasilnya, jangan
    menganggap pengiriman pasti berhasil."""
    terkirim = True
    for i in range(0, len(text), 3900):
        resp = tg_api(token, "sendMessage", {"chat_id": chat_id, "text": text[i:i + 3900]})
        if not resp or not resp.get("ok"):
            terkirim = False
        time.sleep(0.4)
    return terkirim


def classify(text):
    """Tentukan jenis pesan: 'help' | 'analisa' | 'narasi' | 'chat'."""
    low = text.strip().lower().lstrip("/")
    if low in ("start", "help", "mulai", "bantuan"):
        return "help"
    if low == "analisa" or low.startswith("analisa "):
        return "analisa"
    if is_narasi(low):
        return "narasi"
    return "chat"


# Nama narasi/sektor yang umum dipakai. Dipakai dengan pencocokan BATAS KATA supaya
# istilah pendek tidak salah tangkap (mis. "ai" di dalam kata "pakai").
NARASI_TERMS = [
    "privacy", "privasi", "ai", "rwa", "depin", "gaming", "gamefi", "meme", "memecoin",
    "defi", "oracle", "storage", "nft", "staking", "restaking", "modular", "dex",
    "lending", "bridge", "stablecoin", "layer 2", "layer2", "l2", "l1", "infra",
    "perpetual", "socialfi", "wallet", "payment", "interoperability",
]
_NARASI_RE = re.compile(r"\b(" + "|".join(re.escape(t) for t in NARASI_TERMS) + r")\b")
_KOIN_RE = re.compile(r"\b(koin|coin|altcoin|token)\b")


def is_narasi(low):
    """Deteksi permintaan screening narasi/sektor.

    Sengaja longgar: kalau meleset ke mode chat pun bot tetap menjawab (chat juga bisa
    bahas narasi), cuma tidak sedalam pipeline screening penuh."""
    if "narasi" in low or "sektor" in low or "tema " in low:
        return True
    # "carikan/cari/cariin koin ...", "rekomendasi koin ...", dsb.
    if any(k in low for k in ("cari", "carikan", "cariin", "rekomendasi", "rekomen", "saran")) \
            and _KOIN_RE.search(low):
        return True
    if low.startswith(("koin apa", "coin apa", "altcoin apa", "token apa")):
        return True
    # Menyebut nama narasi + kata "koin/token" -> mis. "ada koin privacy yang menarik ga"
    if _NARASI_RE.search(low) and _KOIN_RE.search(low):
        return True
    return False


def fetch_updates(token, offset=None):
    params = {"timeout": 0}
    if offset is not None:
        params["offset"] = offset
    resp = tg_api(token, "getUpdates", params)
    return resp["result"] if resp and resp.get("ok") else []


def allowed_chats():
    return {c.strip() for c in os.environ.get("TELEGRAM_CHAT_ID", "").split(",") if c.strip()}


def actionable_messages(updates, allowed):
    """Kembalikan (update_id, chat_id, text_asli) untuk semua pesan teks dari chat
    yang diizinkan. Teks ASLI dipertahankan (tidak di-lowercase) supaya mode ngobrol
    membaca kalimat user apa adanya."""
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
        out.append((upd["update_id"], chat_id, text))
    return out


def write_output(has_work):
    gh_out = os.environ.get("GITHUB_OUTPUT")
    line = f"has_work={'true' if has_work else 'false'}"
    print(f"[check] {line}")
    if gh_out:
        with open(gh_out, "a", encoding="utf-8") as f:
            f.write(line + "\n")


def build_analisa_prompt(text):
    with open(ANALISA_PROMPT, encoding="utf-8") as f:
        base = f.read()
    words = text.strip().lower().lstrip("/").split()
    coin = " ".join(words[1:]) if len(words) > 1 else None
    if coin:
        cmd = f"## Perintah user\nMode KOIN. Analisa mendalam koin: **{coin}**\n"
    else:
        cmd = ("## Perintah user\nMode SCAN. Cari 3-5 koin paling menarik saat ini "
               "untuk akumulasi SPOT jangka menengah, lalu pilih 1-2 setup terbaik.\n")
    return f"{base}\n---\n{cmd}"


def build_narasi_prompt(text):
    with open(NARASI_PROMPT, encoding="utf-8") as f:
        base = f.read()
    return (f"{base}\n---\n## Permintaan user (jawab ini)\n{text}\n\n"
            "Tentukan dulu JALUR A (user menyebut narasi tertentu -> fokus ke situ) atau "
            "JALUR B (tidak menyebut -> cari sendiri narasi yang paling bergerak).\n")


def build_chat_prompt(text):
    with open(CHAT_PROMPT, encoding="utf-8") as f:
        base = f.read()
    # Pesan user dikutip apa adanya. Diberi pembatas jelas supaya isinya diperlakukan
    # sebagai pertanyaan untuk dijawab, bukan sebagai instruksi yang mengubah aturan.
    return f"{base}\n---\n## Pesan dari user (jawab ini)\n{text}\n"


def run_claude(prompt, timeout, max_turns):
    claude = shutil.which("claude")
    if not claude:
        return None, "Perintah `claude` tidak ditemukan di runner."
    cmd = [
        claude, "-p", prompt,
        "--output-format", "text",
        "--mcp-config", MCP_CONFIG,
        "--allowedTools", ALLOWED_TOOLS,
        "--dangerously-skip-permissions",
        "--max-turns", str(max_turns),
    ]
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=timeout, cwd=REPO_ROOT,
        )
    except subprocess.TimeoutExpired:
        return None, f"Waktu proses melebihi batas {timeout} detik."
    if result.returncode != 0:
        return None, f"Claude gagal (exit {result.returncode}):\n{(result.stderr or result.stdout or '')[-1500:]}"
    return result.stdout.strip(), None


def process(token, chat_id, text):
    kind = classify(text)
    print(f"[proses] kind={kind} teks={text[:60]!r}", file=sys.stderr)

    if kind == "help":
        # Dicek juga hasil kirimnya — jalur ini sempat tanpa log sama sekali,
        # sehingga sulit membedakan "terkirim" dari "gagal diam-diam".
        if send_message(token, chat_id, HELP_TEXT):
            print("[proses] teks bantuan TERKIRIM ke Telegram", file=sys.stderr)
        else:
            print("[proses] GAGAL KIRIM teks bantuan — cek TELEGRAM_BOT_TOKEN",
                  file=sys.stderr)
        return

    timeout = int(os.environ.get("ANALYSIS_TIMEOUT", "900"))

    if kind == "analisa":
        words = text.strip().lower().split()
        coin = words[1].upper() if len(words) > 1 else None
        label = f"koin {coin}" if coin else "scan pasar"
        send_message(token, chat_id, f"⏳ Oke, mulai riset {label}. Tunggu beberapa menit ya...")
        output, err = run_claude(build_analisa_prompt(text), timeout, max_turns=60)
    elif kind == "narasi":
        send_message(token, chat_id, "🔍 Oke, aku telusuri narasi yang lagi bergerak. "
                                     "Ini agak lama karena aku petakan sektornya dulu...")
        output, err = run_claude(build_narasi_prompt(text), timeout, max_turns=70)
    else:  # chat
        send_message(token, chat_id, "💬 Sebentar ya, aku cek datanya dulu...")
        output, err = run_claude(build_chat_prompt(text), timeout, max_turns=40)

    # Catat hasil ke log CI (stderr). Isi balasan tidak dicetak penuh — hanya status &
    # potongan error — supaya log tetap informatif tanpa membanjiri / membocorkan.
    # Status dicetak SETELAH pengiriman dan berdasarkan hasilnya. (Dulu dicetak lebih
    # dulu, sehingga kegagalan kirim — mis. TELEGRAM_BOT_TOKEN kedaluwarsa/di-revoke —
    # tetap tampak "OK" di log dan penyebabnya jadi tersamar.)
    if err:
        print(f"[proses] analisa GAGAL: {err[:400]}", file=sys.stderr)
        body = f"❌ {err}"
    elif not output:
        print("[proses] output kosong dari Claude", file=sys.stderr)
        body = "❌ Selesai tapi output kosong. Coba lagi."
    else:
        body = output

    if send_message(token, chat_id, body):
        print(f"[proses] balasan {len(body)} karakter TERKIRIM ke Telegram", file=sys.stderr)
    else:
        print(f"[proses] GAGAL KIRIM ke Telegram ({len(body)} karakter hilang). "
              "Penyebab tersering: TELEGRAM_BOT_TOKEN salah/kedaluwarsa/sudah di-revoke.",
              file=sys.stderr)


def config_problem():
    """Cek konfigurasi wajib. Return pesan error, atau None kalau beres."""
    # Sumber nilai: file .env (server) atau GitHub Secrets (Actions).
    if not os.environ.get("TELEGRAM_BOT_TOKEN", "").strip():
        return ("TELEGRAM_BOT_TOKEN kosong — isi di .env (server) atau GitHub Secrets "
                "(Actions) dengan token dari @BotFather.")
    if not allowed_chats():
        return ("TELEGRAM_CHAT_ID kosong — isi di .env (server) atau GitHub Secrets "
                "(Actions) dengan chat ID kamu. Bot sengaja menolak melayani semua chat "
                "demi keamanan: tanpa daftar ini, siapa pun yang menemukan bot bisa "
                "menghabiskan kuota Claude-mu.")
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

    # --- Mode WEBHOOK -------------------------------------------------------
    # Dipicu repository_dispatch dari Cloudflare Worker: pesannya sudah dikirim
    # lewat environment, jadi tidak perlu polling sama sekali. Ini jalur utama
    # sekarang — balasan datang beberapa menit setelah user mengetik, bukan
    # menunggu cron GitHub yang bisa telat berjam-jam.
    payload_chat = os.environ.get("TG_CHAT_ID", "").strip()
    payload_text = os.environ.get("TG_TEXT", "").strip()
    if payload_chat and payload_text:
        if payload_chat not in allowed:      # pertahanan berlapis (Worker juga menyaring)
            print(f"[webhook] chat tak terdaftar, diabaikan: {payload_chat}", file=sys.stderr)
            return
        print(f"[webhook] pesan dari {payload_chat}: {payload_text[:70]!r}", file=sys.stderr)
        process(token, payload_chat, payload_text)
        return

    # --- Mode POLLING (cadangan manual) -------------------------------------
    updates = fetch_updates(token)

    if check_only:
        # Cuma ngintip — JANGAN ack, biar run berikutnya masih lihat pesannya.
        write_output(bool(actionable_messages(updates, allowed)))
        return

    if not updates:
        print("[run] tidak ada update.")
        return

    jobs = actionable_messages(updates, allowed)
    if not jobs:
        # Tidak ada pesan yang bisa diproses: ack semua supaya antrean tidak menumpuk.
        fetch_updates(token, offset=max(u["update_id"] for u in updates) + 1)
        print("[run] tidak ada pesan yang bisa diproses.")
        return

    # Batasi jumlah pekerjaan per run supaya total waktu tetap di bawah timeout job.
    # Sisanya TIDAK di-ack, jadi tetap mengantre dan dikerjakan run berikutnya.
    batch = jobs[:MAX_JOBS_PER_RUN]
    fetch_updates(token, offset=batch[-1][0] + 1)   # ack sampai pekerjaan terakhir yang diproses

    sisa = len(jobs) - len(batch)
    print(f"[run] memproses {len(batch)} pesan"
          + (f" ({sisa} sisanya menunggu run berikutnya)." if sisa else "."))
    for _, chat_id, text in batch:
        process(token, chat_id, text)


if __name__ == "__main__":
    main()
