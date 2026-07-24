"""Versi one-shot dari bot (untuk GitHub Actions / cron).

Sekali jalan: ambil pesan Telegram yang tertunda, proses, balas, lalu keluar.

Mode berdasarkan isi pesan:
  - "analisa" / "analisa <koin>"  -> analisa lengkap terstruktur (metodologi skor penuh)
  - permintaan narasi/sektor       -> screening narasi
  - FOTO (dengan/atau caption)     -> mode ANALIS VISUAL: baca gambar, cari kaitan koin/
                                      project, gali info, beri rekomendasi tindakan
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
import tempfile
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
FOTO_PROMPT = os.path.join(BASE_DIR, "prompts", "foto.md")
MCP_CONFIG = os.path.join(BASE_DIR, ".mcp.cloud.json")

ALLOWED_TOOLS = ",".join([
    "mcp__coinglass__*",
    "mcp__coinmarketcap__*",
    "mcp__tradingview__*",
    "WebSearch",
    "WebFetch",
    "Bash",          # untuk menjalankan cloud/indicators.py
])
# Mode foto butuh tool Read (untuk "melihat" gambar yang diunduh).
ALLOWED_TOOLS_VISION = ALLOWED_TOOLS + ",Read"

# Maksimal pekerjaan per run. Job GitHub Actions dibatasi 30 menit; satu analisa bisa
# 15 menit -> lebih dari 2 berisiko job dibunuh di tengah jalan dan pesan hilang.
MAX_JOBS_PER_RUN = 2

# --- Penjenjangan model (model tiering) ---------------------------------------
# Analisa KOIN dipecah 2 tahap: model MURAH/CEPAT mengumpulkan data (jalankan
# script + MCP + web — bagian terberat & terbanyak round-trip), model PINTAR
# menafsirkan & menyusun laporan dari data itu. Hemat kuota + lebih cepat.
MODEL_GATHER = os.environ.get("MODEL_GATHER", "claude-haiku-4-5")   # petugas pengumpul data
MODEL_SYNTH = os.environ.get("MODEL_SYNTH", "claude-opus-4-8")      # analis (sintesis akhir)

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
    "4) KIRIM FOTO/SCREENSHOT:\n"
    "   • kirim gambar (chart, data, pengumuman) + caption pertanyaanmu\n"
    "   • aku baca isinya, cari kaitannya dengan koin/project, dan kasih rekomendasi\n"
    "   • caption boleh pendek atau kosong — aku tetap coba pahami\n\n"
    "5) CEK DOMPET / HOLDER (multi-chain: ETH, BSC, Base, Arbitrum, Solana, dll):\n"
    "   • tempel alamat dompet + tanya, misal: dompet ini isinya apa 0x...\n"
    "   • atau: siapa holder terbesar sol / konsentrasi holder cake di bsc\n\n"
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
# Kata yang menandakan MINTA REKOMENDASI (bukan pertanyaan faktual). Dipakai untuk
# membedakan "koin apa yang menarik?" (screening) dari "koin apa saja yang di-hold
# BlackRock?" (pertanyaan fakta -> harus ke mode chat, bukan pipeline screening).
_MINAT_RE = re.compile(
    r"\b(menarik|bagus|prospek|potensi|potensial|worth|layak|rekomendasi|rekomen|saran|"
    r"cuan|murah|undervalued|trending|hype|meledak|naik daun|lagi jalan|lagi rame|"
    r"patut|sebaiknya)\b")


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
    # "koin apa yang menarik?" -> screening narasi. TAPI pertanyaan FAKTUAL yang kebetulan
    # diawali sama ("koin apa saja yang di-hold BlackRock", "token apa yang dipakai untuk
    # gas") BUKAN screening — biarkan jatuh ke mode chat supaya dijawab dengan riset.
    if low.startswith(("koin apa", "coin apa", "altcoin apa", "token apa")) \
            and (_MINAT_RE.search(low) or _NARASI_RE.search(low)):
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
    """Kembalikan (update_id, chat_id, text_asli, photo_file_id) untuk semua pesan
    teks ATAU foto dari chat yang diizinkan. Untuk foto, text = caption (boleh kosong)
    dan photo_file_id = file_id foto resolusi terbesar."""
    out = []
    for upd in updates:
        msg = upd.get("message") or {}
        chat_id = str(msg.get("chat", {}).get("id", ""))
        photos = msg.get("photo") or []
        photo_id = photos[-1]["file_id"] if photos else None      # resolusi terbesar
        text = (msg.get("caption") if photo_id else msg.get("text")) or ""
        text = text.strip()
        if not chat_id or (not text and not photo_id):
            continue
        if chat_id not in allowed:      # fail-closed: hanya chat yang terdaftar
            print(f"[skip] chat tak terdaftar: {chat_id}")
            continue
        out.append((upd["update_id"], chat_id, text, photo_id))
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


def download_photo(token, file_id):
    """Unduh foto Telegram ke file sementara. Return path absolut atau None."""
    r = tg_api(token, "getFile", {"file_id": file_id})
    if not r or not r.get("ok"):
        return None
    remote = r["result"].get("file_path")
    if not remote:
        return None
    url = f"https://api.telegram.org/file/bot{token}/{remote}"
    ext = os.path.splitext(remote)[1] or ".jpg"
    dest = os.path.join(tempfile.gettempdir(), f"tg_foto_{int(time.time())}{ext}")
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "riset-koin/1.0"})
        with urllib.request.urlopen(req, timeout=60) as resp, open(dest, "wb") as f:
            f.write(resp.read())
        return dest
    except Exception as e:
        print(f"[foto] gagal unduh: {type(e).__name__}: {e}", file=sys.stderr)
        return None


def build_photo_prompt(caption, image_path):
    with open(FOTO_PROMPT, encoding="utf-8") as f:
        base = f.read()
    instruksi = (caption.strip() if caption and caption.strip()
                 else "(tidak ada caption — pakai default: identifikasi keterkaitan dengan "
                      "koin/project, cari info terkait, beri rekomendasi tindakan)")
    return (f"{base}\n---\n"
            f"## Gambar dari user\n"
            f"Gambar tersimpan di path: {image_path}\n"
            f"WAJIB baca dulu dengan tool Read (bisa melihat gambar), lalu kerjakan.\n\n"
            f"## Caption / pertanyaan user\n{instruksi}\n")


def build_gather_prompt(coin):
    """Instruksi TAHAP 1 untuk model murah: kumpulkan data mentah, JANGAN analisa."""
    return (
        f"Kamu PETUGAS PENGUMPUL DATA (bukan analis). Kumpulkan data mentah untuk koin "
        f"{coin} untuk analisa SPOT. JANGAN menganalisa, memberi skor, atau menyimpulkan — "
        f"cukup jalankan tiap langkah dan TEMPEL hasil angkanya. Sebut jelas yang gagal/kosong.\n\n"
        f"1. Bash: `python cloud/indicators.py {coin}` → untuk TIAP timeframe (1w/1d/4h) tempel: "
        f"close, ema13, ema21, ema_signal, ema_cross_valid, rsi14, rsi_divergence, stoch k/d/signal/"
        f"cycle_bottom, fib zone + level penting, structure, volume ratio, source, quality.\n"
        f"2. MCP coinmarketcap `cryptoQuotesLatest` untuk {coin} → harga, market cap, FDV, FDV/MC, "
        f"volume 24h, perubahan 24h/7d/30d, circulating/total supply. Lalu `getCryptoMetadata` → "
        f"kategori + tautan repo GitHub (kalau ada).\n"
        f"3. Bash: `python cloud/fundamentals.py {coin} --mcap <market_cap_dari_langkah_2>` → revenue "
        f"30d/TTM, MoM/QoQ/YoY, kuartalan, TVL, MC/TVL, P/S, P/F, volume DEX. Kalau error, tulis "
        f"'bukan protokol DefiLlama'.\n"
        f"4. Bash: `python cloud/investors.py {coin}` → jumlah holder, top10%, "
        f"top10_non_bursa_kontrak%, 5 holder teratas (persen + kategori + label). Kalau error, "
        f"tulis 'bukan token Ethereum'.\n"
        f"5. Bash: `python cloud/whaleflow.py` → Whale Index (skor+label) + apakah {coin} masuk "
        f"top-token whale & arahnya (AKUMULASI/DISTRIBUSI/seimbang).\n"
        f"6. MCP coinglass (kalau tersedia) → funding rate, open interest, long/short {coin}. "
        f"Kalau gagal/no key, tulis 'derivatif tidak tersedia'.\n"
        f"7. MCP coinmarketcap `globalMetricsLatest` + `fearAndGreedLatest` → dominasi BTC, "
        f"Fear & Greed. Sebut juga harga BTC terkini.\n"
        f"8. WebSearch → 2-4 katalis/berita/unlock terbaru untuk {coin} (dengan tanggal). "
        f"Untuk institusi/whale sebut nama media + tanggal, bukan link markdown.\n\n"
        f"OUTPUT: satu 'DATA BRIEF' terstruktur berlabel per bagian ([PASAR], [HARGA/VALUASI], "
        f"[TEKNIKAL 1W/1D/4H], [FUNDAMENTAL], [KEPEMILIKAN], [DERIVATIF], [KATALIS], [TIDAK TERSEDIA]). "
        f"Angka apa adanya, tanpa interpretasi/skor/rekomendasi."
    )


def build_synth_prompt(coin, brief):
    """Instruksi TAHAP 2 untuk model pintar: analisa dari DATA BRIEF, tanpa tool lagi."""
    with open(ANALISA_PROMPT, encoding="utf-8") as f:
        base = f.read()
    return (
        f"{base}\n---\n"
        f"## DATA BRIEF (hasil pengumpulan tahap 1 — SEMUA data ada di sini)\n"
        f"JANGAN memanggil tool apa pun lagi; seluruh data yang kamu perlukan ada di bawah. "
        f"Kalau ada metrik yang TIDAK ADA di brief, perlakukan sebagai tidak tersedia "
        f"(keluarkan dari skor, renormalisasi) — JANGAN mengarang.\n\n"
        f"{brief}\n\n---\n"
        f"## Perintah user\nMode KOIN. Analisa mendalam koin: **{coin}** berdasarkan DATA BRIEF "
        f"di atas. Terapkan metodologi skoring & format output Telegram sepenuhnya."
    )


def run_claude(prompt, timeout, max_turns, model=None, with_tools=True, tools_override=None):
    claude = shutil.which("claude")
    if not claude:
        return None, "Perintah `claude` tidak ditemukan di runner."
    if tools_override is not None:
        tools = tools_override
    elif with_tools:
        tools = ALLOWED_TOOLS
    else:
        tools = ""   # tahap sintesis tidak butuh tool (data sudah di brief)
    cmd = [
        claude, "-p", prompt,
        "--output-format", "text",
        "--mcp-config", MCP_CONFIG,
        "--allowedTools", tools,
        "--dangerously-skip-permissions",
        "--max-turns", str(max_turns),
    ]
    if model:
        cmd += ["--model", model]
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


def process(token, chat_id, text, photo_file_id=None):
    # --- Mode FOTO (analis visual) -----------------------------------------
    if photo_file_id:
        print(f"[proses] kind=foto caption={text[:60]!r}", file=sys.stderr)
        send_message(token, chat_id, "🖼️ Oke, aku baca gambarnya dan cari kaitannya...")
        img = download_photo(token, photo_file_id)
        if not img:
            send_message(token, chat_id, "❌ Gagal mengunduh gambarnya. Coba kirim ulang ya.")
            return
        timeout = int(os.environ.get("ANALYSIS_TIMEOUT", "900"))
        # Model pintar (vision + penalaran); Read diizinkan untuk 'melihat' gambar.
        output, err = run_claude(build_photo_prompt(text, img), timeout, max_turns=45,
                                 model=MODEL_SYNTH, tools_override=ALLOWED_TOOLS_VISION)
        try:
            os.remove(img)
        except OSError:
            pass
        if err:
            print(f"[proses] foto GAGAL: {err[:300]}", file=sys.stderr)
            body = f"❌ {err}"
        elif not output:
            body = "❌ Selesai tapi output kosong. Coba lagi."
        else:
            body = output
        if send_message(token, chat_id, body):
            print(f"[proses] balasan foto {len(body)} karakter TERKIRIM", file=sys.stderr)
        else:
            print("[proses] GAGAL KIRIM balasan foto — cek TELEGRAM_BOT_TOKEN", file=sys.stderr)
        return

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
        if coin:
            # DUA TAHAP (model tiering): Haiku kumpulkan data -> Opus menganalisa.
            send_message(token, chat_id, f"⏳ Oke, riset koin {coin}. Tahap 1: kumpulkan data...")
            t_gather = min(timeout, 600)
            brief, err = run_claude(build_gather_prompt(coin), t_gather, max_turns=45,
                                    model=MODEL_GATHER, with_tools=True)
            if err:
                print(f"[proses] tahap-1 (gather, {MODEL_GATHER}) GAGAL: {err[:300]}", file=sys.stderr)
                output = None
            elif not brief:
                print("[proses] tahap-1 brief kosong", file=sys.stderr)
                output, err = None, "Pengumpulan data kosong. Coba lagi."
            else:
                print(f"[proses] tahap-1 OK ({MODEL_GATHER}), brief {len(brief)} karakter -> "
                      f"tahap-2 ({MODEL_SYNTH})", file=sys.stderr)
                send_message(token, chat_id, "🧠 Tahap 2: analisa & susun laporan...")
                output, err = run_claude(build_synth_prompt(coin, brief), min(timeout, 420),
                                         max_turns=12, model=MODEL_SYNTH, with_tools=False)
        else:
            # SCAN (tanpa koin) butuh penemuan kandidat -> satu model pintar saja.
            send_message(token, chat_id, "⏳ Oke, scan pasar. Tunggu beberapa menit ya...")
            output, err = run_claude(build_analisa_prompt(text), timeout, max_turns=60,
                                     model=MODEL_SYNTH)
    elif kind == "narasi":
        send_message(token, chat_id, "🔍 Oke, aku telusuri narasi yang lagi bergerak. "
                                     "Ini agak lama karena aku petakan sektornya dulu...")
        output, err = run_claude(build_narasi_prompt(text), timeout, max_turns=70,
                                 model=MODEL_SYNTH)
    else:  # chat
        send_message(token, chat_id, "💬 Sebentar ya, aku cek datanya dulu...")
        output, err = run_claude(build_chat_prompt(text), timeout, max_turns=40,
                                 model=MODEL_SYNTH)

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
    payload_photo = os.environ.get("TG_PHOTO_FILE_ID", "").strip() or None
    if payload_chat and (payload_text or payload_photo):
        if payload_chat not in allowed:      # pertahanan berlapis (Worker juga menyaring)
            print(f"[webhook] chat tak terdaftar, diabaikan: {payload_chat}", file=sys.stderr)
            return
        jenis = "foto" if payload_photo else "teks"
        print(f"[webhook] {jenis} dari {payload_chat}: {payload_text[:70]!r}", file=sys.stderr)
        process(token, payload_chat, payload_text, payload_photo)
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
    for _, chat_id, text, photo_id in batch:
        process(token, chat_id, text, photo_id)


if __name__ == "__main__":
    main()
