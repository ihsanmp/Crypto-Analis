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

import hashlib
import concurrent.futures
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
from datetime import datetime, timedelta, timezone

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
# Claude dijalankan dari root repo supaya path "cloud/indicators.py" di prompt valid
REPO_ROOT = os.path.dirname(BASE_DIR)
ANALISA_PROMPT = os.path.join(BASE_DIR, "prompts", "analisa.md")
# Instruksi cara memanggil script/MCP. HANYA untuk tahap yang punya tool (mode SCAN);
# tahap sintesis dijalankan with_tools=False sehingga isinya mustahil dipakai di sana.
SUMBER_PROMPT = os.path.join(BASE_DIR, "prompts", "analisa_sumber.md")
CHAT_PROMPT = os.path.join(BASE_DIR, "prompts", "chat.md")
NARASI_PROMPT = os.path.join(BASE_DIR, "prompts", "narasi.md")
PASAR_PROMPT = os.path.join(BASE_DIR, "prompts", "analisa_pasar.md")
PERAN_DIR = os.path.join(BASE_DIR, "prompts", "peran")
FOTO_PROMPT = os.path.join(BASE_DIR, "prompts", "foto.md")
MCP_CONFIG = os.path.join(BASE_DIR, ".mcp.cloud.json")

# Set tool DIPISAH menurut tahap, bukan satu daftar untuk semua.
#
# ALASANNYA: claude dijalankan dengan --dangerously-skip-permissions (perlu, karena runner
# tanpa TTY). Kalau Bash dan WebFetch aktif BERSAMAAN, isi halaman web sembarang — yang
# dibaca saat mencari katalis — masuk ke konteks model yang punya akses shell. Halaman
# berbahaya bisa menyisipkan instruksi di situ. Repo ini sudah memindai server MCP pihak
# ketiga lewat mcp-security-scan.yml dengan alasan yang persis sama; jalur WebFetch yang
# belum dijaga.
#
# Pemisahan ini jadi murah setelah data dikumpulkan oleh KODE: tahap yang membaca web tidak
# lagi butuh menjalankan script.
_MCP_PASAR = ["mcp__coinglass__*", "mcp__blockscout__*",
              "mcp__coinmarketcap__*", "mcp__tradingview__*"]

TOOLS_WEB = ",".join(_MCP_PASAR + ["WebSearch", "WebFetch"])   # baca web, TANPA shell
TOOLS_SKRIP = ",".join(_MCP_PASAR + ["Bash"])                  # jalankan script, tanpa web
TOOLS_VISION = TOOLS_WEB + ",Read"                             # mode foto butuh Read
TOOLS_LONGGAR = TOOLS_WEB + ",Bash"                            # cadangan & screening narasi

# Nama lama dipertahankan supaya pemanggil yang belum diubah tetap berjalan.
ALLOWED_TOOLS = TOOLS_LONGGAR
ALLOWED_TOOLS_VISION = TOOLS_VISION

# Maksimal pekerjaan per run. Job GitHub Actions dibatasi 30 menit; satu analisa bisa
# 15 menit -> lebih dari 2 berisiko job dibunuh di tengah jalan dan pesan hilang.
MAX_JOBS_PER_RUN = 2

# --- Penjenjangan model (model tiering) ---------------------------------------
# Analisa KOIN dipecah 2 tahap: model MURAH/CEPAT mengumpulkan data (jalankan
# script + MCP + web — bagian terberat & terbanyak round-trip), model PINTAR
# menafsirkan & menyusun laporan dari data itu. Hemat kuota + lebih cepat.
# Penjenjangan model dipilih dari BEBAN PENALARAN tiap tahap, bukan satu model untuk semua.
# Tahap yang mekanis (menjalankan script lalu menempel JSON) tidak bertambah baik dengan
# model mahal; tahap yang menimbang bukti dan menegakkan aturan kalibrasi jelas bertambah baik.
MODEL_GATHER = os.environ.get("MODEL_GATHER", "claude-haiku-4-5")   # mekanis: ambil & tempel
MODEL_SYNTH = os.environ.get("MODEL_SYNTH", "claude-opus-5")        # analis: empat peran sekaligus
MODEL_NARASI = os.environ.get("MODEL_NARASI", "claude-sonnet-5")    # screening: banyak putaran
MODEL_RINGAN = os.environ.get("MODEL_RINGAN", "claude-sonnet-5")    # sapaan & pertanyaan konsep
NL = "\n"

HELP_TEXT = (
    "🤖 Halo! Aku bot riset PASAR (crypto/saham/forex) & PERKEMBANGAN AI.\n"
    "Cara pakai aku:\n\n"
    "1) ANALISA LENGKAP (terstruktur, berskor):\n"
    "   • ketik: analisa <koin>   (contoh: analisa sol)\n"
    "   • ketik: analisa          -> aku scan pasar & pilih beberapa koin menarik\n\n"
    "2) ANALISA SAHAM & FOREX:\n"
    "   • analisa saham nvda   (saham luar negeri: NVDA, AAPL, MSFT)\n"
    "   • analisa gold / analisa xauusd / analisa eurusd\n"
    "   • sebut 'saham' di depan supaya tidak tertukar dengan koin\n\n"
    "3) CARI KOIN LEWAT NARASI/SEKTOR:\n"
    "   • carikan koin dengan narasi privacy yang menarik\n"
    "     (ganti privacy dengan: AI, RWA, DePIN, gaming, meme, DeFi, L2, storage, dll)\n"
    "   • carikan koin narasi yang menarik   -> aku cari sendiri narasi yang lagi jalan\n"
    "   • narasi apa yang lagi jalan?\n\n"
    "4) NGOBROL SANTAI:\n"
    "   • tanya bebas, misal: bagaimana pendapatmu tentang bitcoin?\n"
    "   • atau: prospek eth jangka menengah gimana?\n\n"
    "5) KIRIM FOTO/SCREENSHOT:\n"
    "   • kirim gambar (chart, data, pengumuman) + caption pertanyaanmu\n"
    "   • aku baca isinya, cari kaitannya dengan koin/project, dan kasih rekomendasi\n"
    "   • caption boleh pendek atau kosong — aku tetap coba pahami\n\n"
    "6) CEK DOMPET / HOLDER (multi-chain: ETH, BSC, Base, Arbitrum, Solana, dll):\n"
    "   • tempel alamat dompet + tanya, misal: dompet ini isinya apa 0x...\n"
    "   • atau: siapa holder terbesar sol / konsentrasi holder cake di bsc\n\n"
    "7) PERKEMBANGAN AI:\n"
    "   • tanya: perkembangan ai terbaru apa? / rilis model ai terbaru\n"
    "   • aku tarik dari RSS resmi OpenAI, DeepMind, Hugging Face, TechCrunch, dll\n\n"
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
    low = (text or "").strip().lower().lstrip("/")
    if low in ("start", "help", "mulai", "bantuan"):
        return "help"
    # AI sebagai BIDANG didahulukan. Tanpa ini "analisa sektor ai" masuk jalur aset dan
    # dibaca sebagai koin bernama "SEKTOR", sedangkan "analisis sektor ai" tersedot ke
    # screening narasi lalu dijawab dengan daftar koin AI — keduanya bukan yang diminta.
    if topik_ai(low):
        return "chat"
    # "analisis" (ejaan baku) sama sahnya dengan "analisa"; dulu hanya satu yang dikenali
    # sehingga perintah yang sama berperilaku berbeda tergantung ejaan.
    # Screening diperiksa DULU: "analisa sektor rwa" adalah permintaan screening, bukan
    # koin bernama "SEKTOR". is_narasi sudah menuntut penanda screening yang jelas
    # (narasi/sektor/tema atau kata cari + koin), jadi "analisa sol" tidak ikut tertarik.
    if is_narasi(low):
        return "narasi"
    if low in ("analisa", "analisis") or low.startswith(("analisa ", "analisis ")):
        return "analisa"
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
# Sebagian istilah narasi juga kata sehari-hari atau topik lain yang sah. "ai" paling
# parah: AI adalah BIDANG TERSENDIRI bagi bot ini, jadi "analisis sektor ai" ikut tersedot
# ke screening koin dan dijawab dengan daftar koin AI — bukan itu yang diminta user.
_NARASI_AMBIGU = ("ai", "gaming", "storage", "payment", "wallet", "privacy", "privasi",
                  "meme", "infra")
# Penanda bahwa yang dimaksud TOPIK/INDUSTRI, bukan aset yang diperdagangkan.
_TOPIK_RE = re.compile(r"\b(sektor|industri|perkembangan|kabar|berita|teknologi|"
                       r"riset|model|regulasi|tren|topik|dunia|bidang|kecerdasan|"
                       # "ada yang baru di ai?" juga pertanyaan industri, bukan soal koin.
                       r"baru|terbaru|update|rilis|kemajuan|arah)\b")
# Kata yang menandakan MINTA REKOMENDASI (bukan pertanyaan faktual). Dipakai untuk
# membedakan "koin apa yang menarik?" (screening) dari "koin apa saja yang di-hold
# BlackRock?" (pertanyaan fakta -> harus ke mode chat, bukan pipeline screening).
_MINAT_RE = re.compile(
    r"\b(menarik|bagus|prospek|potensi|potensial|worth|layak|rekomendasi|rekomen|saran|"
    r"cuan|murah|undervalued|trending|hype|meledak|naik daun|lagi jalan|lagi rame|"
    r"patut|sebaiknya)\b")


# --- Deteksi jenis aset untuk perintah "analisa" -----------------------------
# Tanpa ini, "analisa nvda" masuk jalur crypto dan memanggil DefiLlama/holder Ethereum/
# whale untuk sebuah SAHAM — hasilnya kosong atau menyesatkan.
_PASANGAN_FX = re.compile(
    r"^(XAU|XAG|EUR|GBP|USD|AUD|NZD|CAD|CHF|JPY)(USD|JPY|EUR|GBP|CHF|CAD|AUD|NZD)$", re.I)
# Emas & perak dipetakan ke kontrak berjangka COMEX — "XAUUSD=X" TIDAK ADA di Yahoo (404).
# JEBAKAN PENTING: ticker "GOLD" di NYSE adalah Barrick Gold Corp (perusahaan TAMBANG),
# bukan logamnya. Tanpa pemetaan ini, "analisa gold" bisa menganalisa saham yang salah.
_ALIAS_FX = {"GOLD": "GC=F", "EMAS": "GC=F", "XAUUSD": "GC=F", "XAU": "GC=F",
             "SILVER": "SI=F", "PERAK": "SI=F", "XAGUSD": "SI=F", "XAG": "SI=F"}


# Kata pengantar yang lazim diketik sebelum nama aset ("analisa KOIN pump"). Bukan nama
# aset, jadi harus dilewati. "saham"/"forex" TIDAK di sini — keduanya penanda jenis yang
# punya penanganan tersendiri di bawah.
_KATA_PENGANTAR = ("koin", "coin", "kripto", "crypto", "token", "aset", "asset",
                   "harga", "chart", "grafik", "si", "untuk", "tentang", "soal", "the",
                   # Ditambah setelah "analisa sektor ai" terbaca sebagai koin "SEKTOR".
                   "sektor", "perkembangan", "industri", "kabar", "berita", "topik")

# Kata yang, bila BERDIRI SENDIRI, berarti permintaan SCAN — bukan nama aset.
# Sengaja jauh lebih sempit dari _KATA_PENGANTAR: sebagian kata di atas ADALAH ticker
# sungguhan (THE = Thena, SI = kontrak perak), jadi "analisa the" harus tetap dibaca
# sebagai koin THE. Kata di sini dipilih yang hampir mustahil jadi ticker yang dimaksud.
_GENERIK_SCAN = ("koin", "coin", "kripto", "crypto", "aset", "asset")


def jenis_aset(sisa):
    """Tentukan (jenis, simbol) dari teks setelah kata 'analisa'.

    Urutan: kata kunci eksplisit -> alias emas/perak -> pola pasangan forex -> default crypto.
    Default sengaja CRYPTO supaya perintah lama tetap berperilaku sama.
    """
    kata = (sisa or "").split()
    if not kata:
        return "crypto", None

    # Buang kata pengantar di depan. Tanpa ini "analisa koin pump" terbaca sebagai koin
    # bernama KOIN — kejadian nyata, dan menyesatkan justru karena ADA koin bernama PUMP
    # sehingga tidak ketahuan sebagai salah ketik. Hanya dibuang bila masih ada kata
    # sesudahnya, supaya "analisa token" tidak berubah jadi perintah kosong.
    while len(kata) > 1 and kata[0].lower() in _KATA_PENGANTAR:
        kata = kata[1:]
    # Kata generik yang berdiri sendiri = permintaan SCAN, bukan koin bernama "KOIN".
    # Dicek terhadap _GENERIK_SCAN yang sempit, BUKAN _KATA_PENGANTAR — sebagian kata
    # pengantar adalah ticker sungguhan (THE = Thena), dan "analisa the" harus tetap
    # dibaca sebagai koin THE.
    if kata[0].lower() in _GENERIK_SCAN:
        return "crypto", None

    depan = kata[0].lower()
    if depan in ("saham", "stock", "stocks") and len(kata) > 1:
        return "saham", kata[1].upper().replace("$", "")
    if depan in ("forex", "fx", "mata") and len(kata) > 1:
        s = kata[1].upper().replace("$", "")
        return "forex", _ALIAS_FX.get(s, s)
    simbol = kata[0].upper().replace("$", "")
    if simbol in _ALIAS_FX:
        return "forex", _ALIAS_FX[simbol]
    if _PASANGAN_FX.match(simbol):
        return "forex", simbol
    return "crypto", simbol


def is_narasi(low):
    """Deteksi permintaan screening narasi/sektor.

    Sengaja longgar: kalau meleset ke mode chat pun bot tetap menjawab (chat juga bisa
    bahas narasi), cuma tidak sedalam pipeline screening penuh."""
    # "sektor"/"tema" SAJA tidak cukup. "analisis sektor ai" berarti INDUSTRI AI, bukan
    # screening koin AI — kejadian nyata yang dilaporkan user. Kata itu baru berarti
    # screening kalau konteksnya memang koin, atau narasinya khas crypto (defi, rwa, dst).
    if "narasi" in low or "sektor" in low or "tema " in low:
        if _KOIN_RE.search(low) or not _NARASI_RE.search(low):
            return True
        return not any(re.search(r"\b" + re.escape(t) + r"\b", low)
                       for t in _NARASI_AMBIGU)
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


def topik_ai(low):
    """Pertanyaan tentang AI sebagai BIDANG, bukan tentang koin bernarasi AI.

    AI adalah satu dari empat bidang bot ini. Tanpa pemisahan ini "analisis sektor ai"
    dijawab dengan daftar koin AI — persis yang dikeluhkan user.
    """
    if not re.search(r"\b(ai|kecerdasan buatan|artificial intelligence)\b", low):
        return False
    if _KOIN_RE.search(low):        # "koin ai"/"token ai" -> memang soal koin
        return False
    return bool(_TOPIK_RE.search(low))


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


_BULAN_ID = ("Januari", "Februari", "Maret", "April", "Mei", "Juni", "Juli",
             "Agustus", "September", "Oktober", "November", "Desember")


def header_waktu():
    """Suntikkan TANGGAL HARI INI ke setiap prompt, deterministik dari Python.

    Tanpa ini model menebak "sekarang" dari pengetahuannya yang sudah tertinggal, lalu
    menyajikan angka lama seolah terkini (kasus nyata: jumlah BTC di ETF BlackRock).
    Dengan tanggal asli di depan mata, model bisa menilai sendiri mana data yang basi.
    """
    utc = datetime.now(timezone.utc)
    wib = utc + timedelta(hours=7)
    tgl = f"{wib.day} {_BULAN_ID[wib.month - 1]} {wib.year}"
    return (
        "## WAKTU SEKARANG — ACUAN KESEGARAN DATA (wajib dipatuhi)\n"
        f"Hari ini: {tgl}, pukul {wib:%H:%M} WIB ({utc:%H:%M} UTC).\n"
        "PENGETAHUAN BAWAANMU SUDAH TERTINGGAL dari tanggal ini. Karena itu:\n"
        "- DILARANG menjawab angka/fakta pasar dari ingatan. Ambil dari tool, script, "
        "MCP, atau WebSearch. Kalau belum diambil, ambil dulu — jangan menebak.\n"
        "- SETIAP angka sebutkan TANGGAL berlakunya (mis. 'per 17 Juli 2026: ...').\n"
        "- Kalau data yang ketemu lebih tua dari beberapa hari, sebutkan tanggalnya apa "
        "adanya dan bilang itu data terakhir yang tersedia — jangan sajikan seolah hari ini.\n"
        "- Kalau sumber saling berbeda, sebutkan RENTANG + tanggal masing-masing, jangan "
        "diam-diam memilih satu seolah pasti.\n"
        "- Hasil WebSearch: cek TANGGAL artikelnya, utamakan yang terbaru; artikel lama "
        "boleh dipakai hanya kalau disebut tanggalnya.\n\n"
    )


def build_analisa_prompt(text):
    # Mode SCAN memanggil tool sendiri, jadi instruksi sumber data WAJIB ikut.
    with open(SUMBER_PROMPT, encoding="utf-8") as f:
        sumber = f.read()
    with open(ANALISA_PROMPT, encoding="utf-8") as f:
        base = sumber + "\n---\n" + f.read()
    words = text.strip().lower().lstrip("/").split()
    coin = " ".join(words[1:]) if len(words) > 1 else None
    if coin:
        cmd = f"## Perintah user\nMode KOIN. Analisa mendalam koin: **{coin}**\n"
    else:
        cmd = ("## Perintah user\nMode SCAN. Cari 3-5 koin paling menarik saat ini "
               "untuk akumulasi SPOT jangka menengah, lalu pilih 1-2 setup terbaik.\n")
    return f"{header_waktu()}{base}\n---\n{cmd}"


def build_narasi_prompt(text):
    with open(NARASI_PROMPT, encoding="utf-8") as f:
        base = rakit_peran("crypto", ["inti", "analis"]) + f.read()
    return (f"{header_waktu()}{base}\n---\n## Permintaan user (jawab ini)\n{text}\n\n"
            "Tentukan dulu JALUR A (user menyebut narasi tertentu -> fokus ke situ) atau "
            "JALUR B (tidak menyebut -> cari sendiri narasi yang paling bergerak).\n")


# Kosakata pasar umum. Dipakai sebagai PENGAMAN: kalau pesan jelas menyangkut pasar tapi
# tidak ada satu pun blok yang cocok, seluruh blok dimuat. Prinsipnya ragu = muat, karena
# kehilangan aturan jauh lebih merugikan daripada boros token.
_PASAR_UMUM = re.compile(
    r"\b(harga|beli|jual|akumulasi|prospek|pasar|market|tren|trend|level|support|resisten|"
    r"chart|grafik|analisa|analisis|invest|portofolio|posisi|entry|target|koin|coin|token|"
    r"saham|stock|forex|emas|gold|bursa|rally|koreksi|bullish|bearish|cuan|rugi|profit|"
    r"dompet|wallet|alamat|address|holder|whale|on-chain|onchain|tvl|saldo|supply|mcap|"
    r"volume|funding|likuidasi|unlock|listing|airdrop|staking|narasi|sektor|etf|institusi|"
    r"suku bunga|inflasi|makro|fed|cpi|nfp|yield|dolar|rupiah)\b",
    re.IGNORECASE)
_BLOK_RE = re.compile(
    r"<!-- BLOK: ([\w-]+) \| pemicu: ([^>]*?) -->\n(.*?)\n<!-- /BLOK -->\n?",
    re.DOTALL)


# Gagal-aman BERKELOMPOK. Versi lama biner: begitu pesan menyentuh satu kata _PASAR_UMUM,
# SELURUH blok dimuat. Karena kosakata itu berisi ~60 kata umum ("harga", "gold", "fed"),
# satu pertanyaan gold ikut membawa aturan 13F, riset X, dan ainews.py — lalu model
# menjalankan tool yang tidak ada hubungannya dengan pertanyaannya.
# Sekarang kosakata dipetakan ke rumpun, dan hanya blok serumpun yang dimuat.
_RUMPUN = {
    "makro-fx": (("emas", "gold", "xau", "perak", "xag", "forex", "dolar", "yield", "fed",
                  "cpi", "nfp", "suku bunga", "inflasi", "makro", "rupiah", "fomc"),
                 ("gold", "makro", "saham-forex")),
    "saham": (("saham", "stock", "emiten", "bursa", "earnings", "dividen", "p/e", "nasdaq"),
              ("saham-forex", "makro")),
    "crypto": (("koin", "coin", "token", "tvl", "on-chain", "onchain", "holder", "whale",
                "dompet", "wallet", "staking", "airdrop", "unlock", "listing", "narasi",
                "sektor", "funding", "likuidasi", "mcap", "supply", "etf", "institusi"),
               ("institusi", "x-twitter")),
}


def _rumpun_cocok(low):
    """Blok mana yang relevan dengan pesan ini. Kosong = tidak ada rumpun yang cocok."""
    blok = set()
    for kata_kunci, blok_terkait in _RUMPUN.values():
        if any(k in low for k in kata_kunci):
            blok.update(blok_terkait)
    return blok


def rakit_chat(teks_prompt, pesan):
    """Rakit prompt NGOBROL: bagian inti selalu ikut, blok domain hanya bila relevan.

    chat.md dikirim UTUH tiap pesan (23 rb karakter) padahal blok khusus jarang relevan
    bersamaan — untuk "apa itu RAG?" aturan gold/X/institusi tidak terpakai sama sekali.
    Blok bertanda dimuat hanya bila pemicunya cocok.

    GAGAL-AMAN: kalau pesan menyinggung kosakata pasar tapi tak ada blok yang cocok, SEMUA
    blok dimuat. Lebih baik boros sedikit daripada menjawab tanpa aturan yang seharusnya ada.
    """
    low = (pesan or "").lower()
    blok = _BLOK_RE.findall(teks_prompt)
    if not blok:
        return teks_prompt

    dipakai = set()
    for nama, pemicu, _ in blok:
        for kata in pemicu.split(","):
            kata = kata.strip().lower()
            if kata and kata in low:
                dipakai.add(nama)
                break

    # GAGAL-AMAN BERKELOMPOK. Dulu biner: sentuh satu kata _PASAR_UMUM, SEMUA blok dimuat.
    # Itu terlalu lebar — pertanyaan gold ikut membawa aturan 13F dan riset X, lalu model
    # menjalankan tool yang tidak nyambung. Sekarang hanya blok SERUMPUN yang ditambahkan.
    # Kalau menyentuh kosakata pasar tapi TIDAK ADA rumpun yang cocok, barulah semua blok
    # dimuat — di situ kita memang tidak tahu apa yang dibutuhkan, dan kehilangan aturan
    # lebih merugikan daripada boros. Prinsip lamanya dipertahankan, ambangnya dipersempit.
    if _PASAR_UMUM.search(low):
        serumpun = _rumpun_cocok(low)
        if serumpun:
            dipakai.update(serumpun)
        else:
            dipakai = {nama for nama, _, _ in blok}

    def ganti(m):
        nama, _, isi = m.group(1), m.group(2), m.group(3)
        return (isi + "\n\n") if nama in dipakai else ""

    return _BLOK_RE.sub(ganti, teks_prompt)



RIWAYAT_PATH = os.path.join(BASE_DIR, "data", "percakapan.json")
RIWAYAT_MAKS = 3          # pasang tanya-jawab terakhir yang disertakan
RIWAYAT_UMUR = 6 * 3600   # detik; lebih tua dari ini dianggap topik lain
BALASAN_POTONG = 500      # balasan dipangkas supaya tidak membengkakkan prompt


def _muat_riwayat():
    try:
        with open(RIWAYAT_PATH, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []


def _potong_balasan(teks):
    """Pangkas balasan panjang dengan menyimpan AWAL dan AKHIR-nya.

    Memotong dari depan saja akan membuang bagian paling penting untuk diskusi: pada
    analisa, skor & bias ada di ATAS sementara KESIMPULAN ada di BAWAH. Kalau user
    lalu bertanya "kenapa kamu bilang tunggu dulu?", justru bagian bawah itu yang
    dibutuhkan.
    """
    teks = teks or ""
    if len(teks) <= BALASAN_POTONG:
        return teks
    sisi = BALASAN_POTONG // 2
    return teks[:sisi].rstrip() + "\n[...dipangkas...]\n" + teks[-sisi:].lstrip()


# Pola angka yang benar-benar mengubah keputusan. Sengaja SEMPIT: yang dikejar bukan semua
# angka, melainkan yang biasanya ditanyakan lagi di giliran berikutnya.
_ANGKA_POLA = [
    ("harga", re.compile(r"[$]\s*(\d[\d.,]*)")),
    ("rsi", re.compile(r"RSI\s*(?:14)?\s*(?:di|:|=)?\s*(\d+(?:[.,]\d+)?)", re.I)),
    ("ema", re.compile(r"EMA\s*(\d+)\s*[$]?\s*(\d[\d.,]*)", re.I)),
    ("persen", re.compile(r"(-?\d+(?:[.,]\d+)?\s*%)")),
    ("skor", re.compile(r"(\d+)\s*/\s*100")),
]
_ANGKA_MAKS = 8


def angka_kunci(teks):
    """Tarik angka penting dari balasan supaya giliran berikutnya tidak menarik ulang semua.

    Riwayat memangkas balasan jadi BALASAN_POTONG karakter, jadi angka dari giliran
    sebelumnya memang HILANG — itulah sebab bot menarik ulang seluruh data hanya untuk
    menjawab "jadi gambaranmu bagaimana?". Menyimpan angkanya secara terpisah menutup
    lubang itu tanpa memperbesar potongan balasannya.
    """
    teks = teks or ""
    keluar = []
    for label, pola in _ANGKA_POLA:
        for m in pola.finditer(teks):
            # Buang tanda baca yang ikut tertangkap di ujung ("$4.230." -> "4.230").
            nilai = " ".join(x.strip(" .,;:") for x in m.groups() if x)
            butir = f"{label}={nilai}"
            if butir not in keluar:
                keluar.append(butir)
            if len(keluar) >= _ANGKA_MAKS:
                return keluar
    return keluar


def simpan_riwayat(chat_id, pesan, balasan):
    """Simpan satu pasang tanya-jawab supaya pesan lanjutan punya konteks.

    Tiap run GitHub Actions adalah mesin baru, jadi tanpa ini "lanjutkan dengan acuan
    news" datang tanpa tahu topik sebelumnya — persis keluhan user.

    PRIVASI: repo ini PUBLIK. Isi percakapan yang memuat alamat dompet atau kepemilikan
    pribadi TIDAK disimpan sama sekali (penyaring sama dengan memori.py, di level kode).
    Balasan juga dipangkas — yang dibutuhkan cuma benang topiknya, bukan isi lengkapnya.
    """
    try:
        sys.path.insert(0, BASE_DIR)
        from memori import masalah_privasi
        if masalah_privasi(f"{pesan} {balasan}"):
            print("[riwayat] tidak disimpan — memuat data pribadi", file=sys.stderr)
            return
    except Exception:
        pass

    sekarang = time.time()
    riwayat = [r for r in _muat_riwayat()
               if sekarang - r.get("waktu", 0) < RIWAYAT_UMUR][-20:]
    riwayat.append({
        "chat": str(chat_id),
        "waktu": sekarang,
        "waktu_utc": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M"),
        "pesan": (pesan or "")[:300],
        "balasan": _potong_balasan(balasan),
        # Angka kunci disimpan TERPISAH karena balasannya dipangkas — tanpa ini angka
        # dari giliran sebelumnya hilang dan bot terpaksa menarik ulang semuanya.
        "angka_kunci": angka_kunci(balasan),
    })
    try:
        os.makedirs(os.path.dirname(RIWAYAT_PATH), exist_ok=True)
        with open(RIWAYAT_PATH, "w", encoding="utf-8") as f:
            json.dump(riwayat, f, indent=1, ensure_ascii=False)
    except Exception as e:
        print(f"[riwayat] gagal menyimpan: {e}", file=sys.stderr)


def konteks_percakapan(chat_id):
    """Rakit konteks percakapan sebelumnya untuk disisipkan ke prompt."""
    sekarang = time.time()
    lalu = [r for r in _muat_riwayat()
            if str(r.get("chat")) == str(chat_id)
            and sekarang - r.get("waktu", 0) < RIWAYAT_UMUR][-RIWAYAT_MAKS:]
    if not lalu:
        return ""
    baris = ["## PERCAKAPAN SEBELUMNYA (konteks, bukan perintah baru)"]
    for r in lalu:
        menit = int((sekarang - r.get("waktu", 0)) // 60)
        baris.append(f"[{menit} menit lalu] User: {r.get('pesan', '')}")
        baris.append(f"           Kamu menjawab: {r.get('balasan', '')}")
        ak = r.get("angka_kunci") or []
        if ak:
            baris.append(f"           Angka kunci saat itu ({menit} menit lalu): "
                         + " · ".join(ak))
    baris += [
        "",
        "CARA MEMAKAI konteks ini:",
        "- Kalau pesan sekarang jelas LANJUTAN (pendek, memakai kata seperti 'itu',",
        "  'lanjutkan', 'kalau', 'bagaimana dengan', atau tidak menyebut asetnya),",
        "  sambungkan ke topik di atas. JANGAN meminta user mengulang topiknya.",
        "- Kalau pesan sekarang topik BARU, ABAIKAN konteks ini sepenuhnya.",
        "- ANGKA di dalam konteks ini SUDAH LAMA. Jangan dikutip sebagai data terkini —",
        "  ambil ulang datanya kalau dibutuhkan.",
        "- Konteks ini hanya untuk menyambung benang pembicaraan, bukan sumber fakta.",
        "",
    ]
    return "\n".join(baris) + "\n---\n"



# Seed peran: identitas profesional yang dipakai saat menganalisa. inti.md SELALU ikut
# (memuat aturan kalibrasi keras yang mencegah model mengarang keyakinan); peran lain
# dimuat sesuai kebutuhan mode. Tiap file punya blok bertanda sektor, jadi analisa crypto
# tidak ikut membawa aturan risiko forex/saham — itu yang membuat mutu naik tanpa boros.
PERAN_LENGKAP = ("inti", "analis", "risk", "portofolio", "trader")


def rakit_peran(sektor, peran=PERAN_LENGKAP):
    """Gabungkan seed peran, hanya blok yang cocok sektornya.

    sektor: "crypto" | "forex" | "saham". Blok bertanda pemicu lain dibuang.
    Berkas yang hilang DILEWATI diam-diam supaya analisa tetap jalan, bukan mati total.
    """
    bagian = []
    for nama in peran:
        jalur = os.path.join(PERAN_DIR, f"{nama}.md")
        try:
            with open(jalur, encoding="utf-8") as f:
                teks = f.read()
        except OSError:
            continue

        def ganti(m, _s=sektor):
            return m.group(3) + "\n" if _s in m.group(2) else ""

        bagian.append(_BLOK_RE.sub(ganti, teks).strip())
    pisah = "\n\n---\n\n"
    return (pisah.join(bagian) + pisah) if bagian else ""



def _sektor_pesan(teks):
    """Tebak sektor dari isi pesan untuk memilih blok peran yang relevan.
    Default crypto — itu bidang terbesar bot ini dan salah tebak hanya berarti
    blok risiko yang kurang pas, bukan analisa yang salah."""
    low = (teks or "").lower()
    if any(k in low for k in ("emas", "gold", "xau", "forex", "usd", "eur", "jpy",
                              "dolar", "yield", "fed", "cpi", "nfp", "perak", "xag")):
        return "forex"
    if any(k in low for k in ("saham", "stock", "emiten", "earnings", "nasdaq",
                              "s&p", "bursa", "dividen", "p/e")):
        return "saham"
    return "crypto"


# Penanda tingkat beban pertanyaan ngobrol.
_RINGAN_RE = re.compile(
    r"^(halo|hai|hi|hey|pagi|siang|sore|malam|thanks|thank you|makasih|terima kasih|"
    r"ok|oke|sip|mantap|siap|bagus|wah|hmm)[\s!.?]*$", re.I)
_KONSEP_RE = re.compile(
    r"\b(apa itu|apa sih|apakah maksud|kenapa .* (bekerja|begitu)|bagaimana cara kerja|"
    r"jelaskan istilah|bedanya .* dan|maksudnya apa|kamu bisa apa|siapa kamu)", re.I)
_TAFSIR_RE = re.compile(
    r"\b(jadi (gimana|bagaimana)|menurutmu|artinya apa|gambaranmu|kesimpulannya|"
    r"pendapatmu|bagaimana menurut|jadi kesimpulan)", re.I)
_BERAT_RE = re.compile(
    r"\b(detail|lengkap|panjang|bandingkan|perbandingan|versus|\bvs\b|"
    r"jelaskan lebih|riset|selengkapnya)", re.I)


# Kosakata TEKNIKAL & timeframe. _PASAR_UMUM tidak memuatnya, sehingga "rsi eth di daily
# berapa?" sempat jatuh ke tingkat RINGAN dengan 8 putaran — padahal butuh menjalankan
# indicators.py. Kalau putarannya habis di tengah, balasannya terpotong TANPA error, jadi
# kegagalannya tidak berisik dan sulit disadari.
_TEKNIKAL_RE = re.compile(
    r"\b(rsi|ema|sma|macd|stoch|stochastic|bollinger|atr|supertrend|pivot|fibo|fibonacci|"
    r"daily|weekly|harian|mingguan|4h|1d|1w|candle|timeframe|oversold|overbought|"
    r"golden cross|death cross|divergence|divergensi)", re.I)


def bobot_chat(text, ada_konteks):
    """Tentukan (jatah_detik, model, max_turns) dari BERAT pertanyaannya.

    Dulu cuma dua tingkat, dan adanya riwayat 6 jam terakhir otomatis memberi jatah 600
    detik + model termahal. Praktisnya hampir semua pesan dapat jalur paling lambat.
    Logikanya juga TERBALIK: pertanyaan lanjutan justru sering lebih RINGAN karena
    konteksnya sudah ada — jadi konteks kini menurunkan bobot, bukan menaikkan.
    """
    low = (text or "").strip().lower()

    if _BERAT_RE.search(low):
        return 600, MODEL_SYNTH, 40, "BERAT (diminta detail / perbandingan)"
    if _RINGAN_RE.match(low) or _KONSEP_RE.search(low):
        return 120, MODEL_RINGAN, 8, "RINGAN (sapaan / konseptual)"
    # Penafsiran lanjutan: angka kuncinya sudah ada di konteks, tinggal ditimbang.
    if _TAFSIR_RE.search(low) and ada_konteks:
        return 120, MODEL_RINGAN, 8, "RINGAN (penafsiran dari konteks yang sudah ada)"
    if _PASAR_UMUM.search(low) or _TEKNIKAL_RE.search(low):
        # Satu aset, satu pertanyaan spesifik. Butuh data tapi bukan riset multi-sumber.
        return 300, MODEL_NARASI, 20, "SEDANG (pertanyaan pasar spesifik)"
    return 120, MODEL_RINGAN, 8, "RINGAN (di luar kosakata pasar)"


# Ticker crypto yang lazim ditanyakan. Daftar SENGAJA terbatas: deteksi yang terlalu
# agresif akan menarik data koin untuk pesan yang sebenarnya bukan soal koin, dan itu
# lebih merugikan daripada tidak mendeteksi sama sekali (kalau meleset, perilakunya
# kembali seperti sebelum tugas ini — model mencari sendiri).
_TICKER_UMUM = {
    "BTC", "ETH", "SOL", "BNB", "XRP", "ADA", "AVAX", "DOT", "MATIC", "LINK", "UNI",
    "ATOM", "LTC", "TRX", "NEAR", "APT", "SUI", "TON", "ICP", "FIL", "ARB", "OP",
    "INJ", "TIA", "SEI", "PEPE", "DOGE", "SHIB", "BONK", "WIF", "RNDR", "FET", "TAO",
    "ONDO", "ENA", "JUP", "PYTH", "AAVE", "MKR", "CRV", "LDO", "SNX", "COMP", "GRT",
    "IMX", "SAND", "MANA", "AXS", "HBAR", "XLM", "ALGO", "VET", "STX", "RUNE", "KAS",
}
_KATA_BUKAN_TICKER = {"ADA", "OP", "ATAU", "INI", "ITU", "DAN", "APA", "KE", "DI"}


def _semua_aset(teks):
    """Kumpulan aset berbeda yang disebut dalam satu pesan. Dipakai untuk mendeteksi
    pertanyaan PERBANDINGAN, yang tidak bisa dilayani satu brief."""
    low = (teks or "").lower()
    kata = re.findall(r"[A-Za-z]{2,6}", teks or "")
    ketemu = set()
    for alias, simbol in _ALIAS_FX.items():
        if re.search(r"\b" + alias.lower() + r"\b", low):
            ketemu.add(simbol)
    for k in kata:
        atas = k.upper()
        if _PASANGAN_FX.match(atas):
            ketemu.add(atas)
        elif atas in _TICKER_UMUM and atas not in _KATA_BUKAN_TICKER:
            ketemu.add(atas)
    return ketemu


def aset_dari_pesan(teks):
    """Cari aset yang disebut dalam pesan ngobrol. (jenis, simbol) atau (None, None).

    Dipakai untuk memutuskan apakah data deterministik perlu dikumpulkan lewat KODE.
    SENGAJA konservatif — kalau tidak yakin, kembalikan None dan biarkan model mencari
    sendiri seperti sebelumnya. Salah menarik data jauh lebih merugikan daripada tidak
    menarik: brief yang isinya aset lain akan membuat audit keterlacakan ikut keliru.
    """
    low = (teks or "").lower()
    kata = re.findall(r"[A-Za-z]{2,6}", teks or "")

    # LEBIH DARI SATU aset disebut -> JANGAN kumpulkan apa pun.
    # Kalau dipaksakan, brief hanya berisi aset PERTAMA, lalu angka aset kedua otomatis
    # tertandai "tidak terlacak" oleh audit_angka dan memicu peringatan PALSU ke user.
    # Peringatan yang salah menyala membuat orang berhenti membaca peringatan — lebih
    # merugikan daripada tidak punya brief sama sekali. Pertanyaan perbandingan memang
    # masuk tingkat BERAT (600 detik, 40 putaran), jadi model punya cukup ruang mencari
    # sendiri seperti sebelum brief mode ngobrol ada.
    if len(_semua_aset(teks)) > 1:
        return None, None

    # 1. Emas/perak & pasangan mata uang — paling jelas, dicek lebih dulu.
    for alias, simbol in _ALIAS_FX.items():
        if re.search(r"\b" + alias.lower() + r"\b", low):
            return "forex", simbol
    for k in kata:
        if _PASANGAN_FX.match(k.upper()):
            return "forex", k.upper()

    # 2. "saham NVDA" / "emiten AAPL" — jenisnya disebut eksplisit.
    m = re.search(r"\b(?:saham|emiten|stock)\s+([A-Za-z]{1,5})\b", teks or "", re.I)
    if m:
        return "saham", m.group(1).upper()

    # 3. Ticker crypto dari daftar terbatas. Kata Indonesia yang kebetulan sama
    #    (mis. "ada", "op") dikecualikan supaya tidak salah tangkap.
    for k in kata:
        atas = k.upper()
        if atas in _TICKER_UMUM and atas not in _KATA_BUKAN_TICKER:
            return "crypto", atas
        # "$ADA" ditulis dengan dolar = jelas ticker, pengecualian tidak berlaku.
    for m2 in re.finditer(r"[$]([A-Za-z]{2,6})\b", teks or ""):
        atas = m2.group(1).upper()
        if atas in _TICKER_UMUM:
            return "crypto", atas
    return None, None


def build_chat_prompt(text, chat_id=None, brief=None):
    with open(CHAT_PROMPT, encoding="utf-8") as f:
        base = rakit_chat(f.read(), text)
    # Aturan kalibrasi hanya untuk pertanyaan pasar. Buat "apa itu RAG?" atau sapaan,
    # aturan konviksi & bukti kontra tidak berguna dan cuma menambah beban.
    if _PASAR_UMUM.search((text or "").lower()):
        low = (text or "").lower()
        peran = ["inti"]
        if any(k in low for k in ("risiko", "risk", "rugi", "drawdown", "aman", "bahaya")):
            peran.append("risk")
        if any(k in low for k in ("porto", "alokasi", "ukuran posisi", "modal",
                                  "diversifikasi", "korelasi")):
            peran.append("portofolio")
        base = rakit_peran(_sektor_pesan(text), peran) + base
    # Penegasan lewat KODE, bukan berharap model membaca blok yang tepat. Routing sudah
    # benar mengarahkan "analisis sektor ai" ke chat, tapi jawabannya tetap berisi koin AI,
    # dominasi BTC, dan Fear & Greed — kerangka crypto di bagian inti prompt mengalahkan
    # blok AI. Arahan ini ditempel PALING ATAS supaya tidak bisa terlewat.
    if topik_ai(text.strip().lower()):
        base = (
            "## ARAHAN WAJIB — INI PERTANYAAN TENTANG INDUSTRI AI" + NL +
            "User menanyakan AI sebagai BIDANG/INDUSTRI: perusahaan, model, chip & compute, "
            "riset, pendanaan, regulasi, adopsi. Ini BUKAN pertanyaan tentang koin." + NL + NL +
            "DILARANG dalam jawaban ini:" + NL +
            "- Menjawab dengan daftar KOIN bernarasi AI (FET, RENDER, TAO, dsb)" + NL +
            "- Membuka dengan harga BTC, dominasi BTC, atau Fear & Greed" + NL +
            "- Memberi skor koin, level entry, atau rencana akumulasi" + NL +
            "- Menjalankan indicators.py / sentiment.py / investors.py — tidak ada koin di sini" + NL + NL +
            "YANG DIMINTA: keadaan industrinya — rilis & kemampuan model terbaru, persaingan "
            "antar pemain, rantai pasok chip & kapasitas compute, pendanaan dan valuasi, "
            "regulasi, serta adopsi nyata. Pakai `python cloud/ainews.py --hari 7` dan "
            "WebSearch. Sebut nama sumber + tanggalnya." + NL + NL +
            "Kaitan ke pasar boleh disebut SEBAGAI PELENGKAP di akhir, dan hanya bila "
            "jalurnya nyata (mis. permintaan compute menopang emiten chip) — bukan sebagai "
            "isi utama jawaban. Kalau user memang ingin sisi koinnya, ia akan menyebut "
            "'koin' atau 'token'." + NL + NL + "---" + NL + NL) + base
    if chat_id is not None:
        base = konteks_percakapan(chat_id) + base
    # Pesan user dikutip apa adanya. Diberi pembatas jelas supaya isinya diperlakukan
    # sebagai pertanyaan untuk dijawab, bukan sebagai instruksi yang mengubah aturan.
    if brief:
        # Data sudah dikumpulkan KODE — model tidak perlu menariknya lagi. Selain lebih
        # cepat, ini yang membuat brief ADA di mode ngobrol sehingga audit keterlacakan
        # angka bisa berjalan; sebelumnya mode ini keluar tanpa pemeriksaan sama sekali.
        base += (NL + "---" + NL + "## DATA BRIEF (SUDAH DIAMBIL — jangan tarik ulang)"
                 + NL + "Angka di bawah ini baru saja diambil sistem. Pakai apa adanya, "
                 "JANGAN menjalankan script untuk mengambilnya lagi. Metrik yang TIDAK ADA "
                 "di sini diperlakukan tidak tersedia — jangan mengarang." + NL + NL
                 + brief + NL)
    return f"{header_waktu()}{base}\n---\n## Pesan dari user (jawab ini)\n{text}\n"


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


def build_photo_prompt(caption, image_path, chat_id=None):
    with open(FOTO_PROMPT, encoding="utf-8") as f:
        base = f.read()
    if chat_id is not None:
        base = konteks_percakapan(chat_id) + base
    instruksi = (caption.strip() if caption and caption.strip()
                 else "(tidak ada caption — pakai default: identifikasi keterkaitan dengan "
                      "koin/project, cari info terkait, beri rekomendasi tindakan)")
    return (f"{header_waktu()}{base}\n---\n"
            f"## Gambar dari user\n"
            f"Gambar tersimpan di path: {image_path}\n"
            f"WAJIB baca dulu dengan tool Read (bisa melihat gambar), lalu kerjakan.\n\n"
            f"## Caption / pertanyaan user\n{instruksi}\n")


def jalankan_script(args, batas=300, min_kar=0, ulang=1):
    """Jalankan script pengumpul data LANGSUNG dari Python, tanpa perantara model.

    min_kar: bila keluarannya jauh lebih pendek dari itu, dicoba ULANG. Bursa membalas
    JSON yang sah tapi nyaris kosong saat kena rate limit — tanpa error, sehingga
    kegagalan itu lolos diam-diam dan model menerima data tipis tanpa tahu.
    """
    for percobaan in range(ulang + 1):
        keluar, err = _jalankan_sekali(args, batas)
        if err is None and (min_kar <= 0 or len(keluar) >= min_kar):
            return keluar, err
        if percobaan < ulang:
            if err is None:
                print(f"[data] keluaran tipis ({len(keluar)} < {min_kar} kar) dari "
                      f"{args[0]} — coba ulang", file=sys.stderr)
            time.sleep(2)
    return keluar, err


def _jalankan_sekali(args, batas):
    try:
        r = subprocess.run([sys.executable] + args, capture_output=True, text=True,
                           timeout=batas, cwd=os.path.dirname(BASE_DIR),
                           encoding="utf-8", errors="replace")
        if r.returncode != 0:
            return None, (r.stderr or "kode keluar bukan 0").strip()[:300]
        return (r.stdout or "").strip(), None
    except subprocess.TimeoutExpired:
        return None, f"melebihi {batas} detik"
    except Exception as e:
        return None, f"{type(e).__name__}: {e}"


# Koin asli jaringan — bukan token kontrak, jadi daftar holder & aliran whale berbasis
# kontrak tidak berlaku. Menjalankannya hanya menghasilkan bagian kosong.
_KOIN_NATIF = {"BTC", "ETH", "BNB", "SOL", "XRP", "ADA", "AVAX", "DOT", "ATOM", "LTC",
               "TRX", "NEAR", "APT", "SUI", "TON", "ICP", "FIL", "HBAR", "XLM", "ALGO"}
# Cakupan CoinMetrics Community praktis hanya dua ini; sisanya balas kosong.
_ONCHAIN_ADA = {"BTC", "ETH"}
# Tanpa protokol berpendapatan, fundamentals.py (DefiLlama) tidak punya apa pun.
_TANPA_PROTOKOL = {"BTC", "LTC", "XRP", "DOGE", "SHIB", "PEPE", "BONK", "WIF", "TRUMP"}


def data_mentah_crypto(coin):
    """Kumpulkan data koin dengan KODE, hanya yang RELEVAN untuk koin itu.

    Dijalankan paralel supaya penyaringan tidak mengorbankan kecepatan. Bagian yang
    kosong dibuang dari brief — model tidak perlu membaca blok 'tidak tersedia' yang
    panjang, dan tidak tergoda mengarang isinya.
    """
    t = coin.upper()
    tugas = [("TEKNIKAL (indicators.py)", ["cloud/indicators.py", coin, "--ringkas"], 2500),
             ("INGATAN (memori.py)", ["cloud/memori.py", "cari", coin], 0),
             ("UJI BALIK (backtest.py)", ["cloud/backtest.py", coin, "--ringkas"], 1200),
             ("SENTIMEN (sentiment.py)", ["cloud/sentiment.py", coin], 0)]
    lewat = []
    if t in _TANPA_PROTOKOL:
        lewat.append(f"fundamentals.py ({t} tidak punya protokol berpendapatan)")
    else:
        tugas.append(("FUNDAMENTAL PROTOKOL (fundamentals.py)", ["cloud/fundamentals.py", coin], 0))
    if t in _KOIN_NATIF:
        lewat.append(f"investors.py & whaleflow.py ({t} koin natif, bukan token kontrak)")
    else:
        tugas.append(("KEPEMILIKAN (investors.py)", ["cloud/investors.py", coin], 0))
    if t in _ONCHAIN_ADA:
        tugas.append(("ON-CHAIN (onchain.py)", ["cloud/onchain.py", coin], 0))
    else:
        lewat.append(f"onchain.py (CoinMetrics Community tidak mencakup {t})")

    bagian, gagal = [], []
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        hasil = {pool.submit(jalankan_script, a, 300, mk): l for l, a, mk in tugas}
        kumpul = {}
        for fut in concurrent.futures.as_completed(hasil):
            label = hasil[fut]
            try:
                keluar, err = fut.result()
            except Exception as e:
                keluar, err = None, type(e).__name__
            kumpul[label] = (keluar, err)
    for label, _, _ in tugas:
        keluar, err = kumpul.get(label, (None, "tidak dijalankan"))
        if err:
            gagal.append(f"{label}: {err}")
            bagian.append(f"[{label}]\nGAGAL DIAMBIL — {err}")
        else:
            bagian.append(f"[{label}]\n{keluar}")
    if lewat:
        bagian.append("[SENGAJA TIDAK DIAMBIL]\n" + "\n".join("- " + x for x in lewat)
                      + "\nPerlakukan sebagai tidak berlaku untuk koin ini, BUKAN sebagai "
                        "data yang hilang — jangan menyebutnya kekurangan.")
    for g in gagal:
        print(f"[data] GAGAL {g}", file=sys.stderr)
    print(f"[data] crypto {t}: {len(tugas)} script dijalankan, {len(lewat)} dilewati, "
          f"{sum(len(x) for x in bagian)} karakter", file=sys.stderr)
    return "\n\n".join(bagian)


def data_mentah_pasar(simbol, jenis):
    """Kumpulkan data deterministik saham/forex dengan KODE, bukan lewat model.

    Kenapa: tahap gather pernah mengembalikan brief 759 karakter untuk 'analisa gold'
    (run 31164017822) padahal keempat scriptnya sehat dan menghasilkan ~20 rb karakter.
    Modelnya yang tidak menjalankan langkahnya. Selama pengumpulan data bergantung pada
    KEPATUHAN model, kegagalan diam-diam seperti itu akan terulang.

    Sekarang script dijalankan kode; model gather hanya mengerjakan bagian yang memang
    butuh penilaian (mencari berita & rilis terbaru). Bonus: model tidak perlu lagi
    menyalin ulang 20 rb karakter JSON, jadi lebih hemat sekaligus lebih andal.
    """
    emas = any(k in simbol.upper() for k in ("GC=F", "SI=F", "XAU", "XAG"))
    tugas = [
        ("TEKNIKAL (market.py)", ["cloud/market.py", simbol, "--ringkas"]
         + ([] if jenis == "saham" else ["--forex"])),
        ("INGATAN (memori.py)", ["cloud/memori.py", "cari", simbol]),
        ("UJI BALIK (backtest.py)", ["cloud/backtest.py", simbol, "--ringkas", "--pasar"]
         + (["--makro"] if jenis != "saham" else [])),
    ]
    if jenis == "saham":
        tugas.append(("FUNDAMENTAL (stockfund.py)",
                      ["cloud/stockfund.py", simbol, "--ringkas"]))
        # Konteks pasar & sektor: sebagian besar gerak saham individual berasal dari
        # keduanya, bukan dari emitennya sendiri.
        tugas.append(("KONTEKS PASAR & SEKTOR (konteks.py)",
                      ["cloud/konteks.py", "--untuk", simbol]))
        # Jadwal earnings: padanan aturan "jangan masuk menjelang rilis berdampak kuat"
        # yang sudah lama berlaku untuk emas. Tetap jalan tanpa FINNHUB_API_KEY.
        tugas.append(("EARNINGS & PEER (earnings.py)", ["cloud/earnings.py", simbol]))
    else:
        tugas.append(("MAKRO AS (makro.py, sumber FRED)", ["cloud/makro.py", "--ringkas"]))
        # Konsensus & jadwal rilis — HANYA untuk forex/komoditas. Saham dinilai dari
        # fundamental emitennya, crypto tidak digerakkan kalender ekonomi AS.
        tugas.append(("KONSENSUS & JADWAL RILIS (kalender.py)",
                      ["cloud/kalender.py", "--ringkas"]))

    # Dijalankan paralel seperti jalur crypto. Jalur saham kini punya enam bagian dan
    # berurutan memakan ~70 detik, yang memakan jatah tahap analisa. Pekerja dibatasi 2
    # karena stockfund.py dan konteks.py sama-sama menembak SEC.
    bagian, gagal = [], []
    kumpul = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        antre = {pool.submit(jalankan_script, a): l for l, a in tugas}
        for fut in concurrent.futures.as_completed(antre):
            label = antre[fut]
            try:
                kumpul[label] = fut.result()
            except Exception as e:
                kumpul[label] = (None, type(e).__name__)
    for label, args in tugas:
        keluar, err = kumpul.get(label, (None, "tidak dijalankan"))
        if err:
            gagal.append(f"{label}: {err}")
            bagian.append(f"[{label}]\nGAGAL DIAMBIL — {err}")
        else:
            bagian.append(f"[{label}]\n{keluar}")

    if emas:
        try:
            with open(os.path.join(BASE_DIR, "data", "gold_drivers.md"), encoding="utf-8") as f:
                bagian.append("[ACUAN PENGGERAK EMAS]\n" + f.read())
        except OSError as e:
            gagal.append(f"gold_drivers.md: {e}")

    for g in gagal:
        print(f"[data] GAGAL {g}", file=sys.stderr)
    print(f"[data] terkumpul {len(bagian)} bagian, {sum(len(x) for x in bagian)} karakter"
          f"{' — ADA YANG GAGAL' if gagal else ''}", file=sys.stderr)
    return "\n\n".join(bagian)


def build_gather_pasar(simbol, jenis):
    """TAHAP 1 saham/forex — HANYA berita & rilis ekonomi.

    Angka teknikal, fundamental, makro, uji balik, dan ingatan sudah dikumpulkan
    data_mentah_pasar() lewat kode. Model tidak lagi diminta menjalankan script lalu
    menyalin ulang hasilnya — itu titik gagal yang mengosongkan brief (run 31164017822),
    dan menyalin 20 rb karakter JSON juga pemborosan murni.
    """
    emas = any(k in simbol.upper() for k in ("GC=F", "SI=F", "XAU", "XAG"))
    fokus = ("data ekonomi AS (CPI, NFP, Core PCE, keputusan & pernyataan FOMC) dan arah "
             "dolar/yield" if jenis != "saham" else
             f"emiten {simbol}: laporan keuangan terbaru, guidance, revisi estimasi analis, "
             f"aksi korporasi, dan berita sektornya")
    return (
        f"{header_waktu()}"
        f"Kamu PETUGAS PENCARI BERITA untuk {jenis.upper()} {simbol}. Tugasmu HANYA mencari dan menempel berita/rilis — JANGAN menganalisa, JANGAN memberi skor atau rekomendasi, dan JANGAN menjalankan script apa pun (angkanya sudah dikumpulkan terpisah).\n\n"
        f"1. WebSearch: {fokus}. Untuk TIAP temuan tempel JUDUL, MEDIA, TANGGAL, dan angkanya. Utamakan yang terbaru; artikel lama boleh dipakai asal tanggalnya disebut.\n"
        f"2. Sebutkan rilis besar yang AKAN datang beserta tanggalnya, kalau ada.\n"
        f"3. DILARANG mengarang angka konsensus/forecast. Kalau tidak ketemu, tulis persis: konsensus tidak tersedia.\n"
        + (f"4. Emas: cari juga arah imbal hasil riil, dolar, dan aliran dana ETF emas terbaru.\n" if emas else "")
        + f"\nOUTPUT: satu bagian berlabel [KATALIS] berisi temuan apa adanya (judul, media, tanggal, angka). Kalau tidak menemukan apa pun, tulis: [KATALIS] tidak ada berita relevan yang ditemukan. Tanpa interpretasi."
    )


def build_gather_prompt(coin):
    """TAHAP 1 crypto — HANYA berita & katalis.

    Angka teknikal, fundamental, on-chain, sentimen, uji balik, dan ingatan sudah
    dikumpulkan data_mentah_crypto() lewat kode, dan HANYA yang berlaku untuk koin itu.
    Model tidak lagi diminta menjalankan script lalu menyalin ulang hasilnya — itu titik
    gagal yang mengosongkan brief pada jalur pasar (run 31164017822).
    """
    return (
        f"{header_waktu()}"
        f"Kamu PETUGAS PENCARI BERITA untuk koin {coin}. Tugasmu HANYA mencari dan menempel berita/katalis — JANGAN menganalisa, JANGAN memberi skor, dan JANGAN menjalankan script apa pun (angkanya sudah dikumpulkan terpisah).\n\n"
        f"1. WebSearch berita {coin} TERBARU: pembaruan produk/jaringan, kemitraan, listing, pendanaan, regulasi, insiden keamanan. Tempel JUDUL, MEDIA, TANGGAL, dan angkanya. Utamakan yang terbaru.\n"
        f"2. Cari JADWAL UNLOCK token atau vesting cliff yang akan datang — ini supply shock terjadwal dan sering menentukan. Kalau tidak ketemu, tulis: jadwal unlock tidak ditemukan.\n"
        f"3. Cari sentimen/narasi sektor yang sedang menggerakkan {coin}, kalau ada.\n"
        f"4. DILARANG mengarang angka. Yang tidak ketemu ditulis tidak ditemukan.\n\n"
        f"OUTPUT: satu bagian berlabel [KATALIS] berisi temuan apa adanya (judul, media, tanggal, angka), plus [UNLOCK] bila ada. Kalau tidak menemukan apa pun, tulis: [KATALIS] tidak ada berita relevan yang ditemukan. Tanpa interpretasi."
    )


def build_synth_pasar(simbol, jenis, brief):
    """TAHAP 2 untuk saham/forex. Memakai analisa_pasar.md — memakai analisa.md (crypto)
    di sini akan menuntut TVL/holder/whale yang tidak ada padanannya."""
    with open(PASAR_PROMPT, encoding="utf-8") as f:
        base = rakit_peran("saham" if jenis == "saham" else "forex") + f.read()
    return (
        f"{header_waktu()}{base}\n---\n"
        f"## DATA BRIEF (hasil pengumpulan tahap 1 — SEMUA data ada di sini)\n"
        f"JANGAN memanggil tool apa pun lagi. Kalau ada metrik yang TIDAK ADA di brief, "
        f"perlakukan sebagai tidak tersedia (keluarkan dari penilaian, sebutkan) — "
        f"JANGAN mengarang.\n\n"
        f"{brief}\n\n---\n"
        f"## Perintah user\nAnalisa {jenis.upper()}: **{simbol}** berdasarkan DATA "
        f"BRIEF di atas. Terapkan metodologi & format output di atas sepenuhnya."
    )


def build_synth_prompt(coin, brief):
    """Instruksi TAHAP 2 untuk model pintar: analisa dari DATA BRIEF, tanpa tool lagi."""
    with open(ANALISA_PROMPT, encoding="utf-8") as f:
        base = rakit_peran("crypto") + f.read()
    return (
        f"{header_waktu()}{base}\n---\n"
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


JEJAK_PATH = os.path.join(BASE_DIR, "data", "diproses.json")
JEDA_DUPLIKAT = 180        # detik — batas dianggap duplikat
JEDA_SENYAP = 25           # di bawah ini dilewati diam-diam (dispatch ganda asli)


def token_aktif():
    return os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()


def _sidik(chat_id, text, photo_file_id):
    """Sidik pesan yang STABIL antar-proses.

    WAJIB hashlib, bukan hash() bawaan: hash() string diacak ulang tiap proses Python
    (PYTHONHASHSEED), sehingga pesan yang sama menghasilkan sidik berbeda di run berbeda
    dan pencegahan duplikat sama sekali tidak bekerja.
    """
    inti = f"{chat_id}|{(text or '').strip().lower()}|{photo_file_id or ''}"
    return hashlib.sha256(inti.encode("utf-8")).hexdigest()[:16]


def sudah_diproses(chat_id, text, photo_file_id):
    """Cegah satu pesan diproses dua kali.

    Telegram/Cloudflare kadang mengirim dispatch GANDA untuk satu pesan — terpantau pada
    4 Agustus 2026: dua run terpicu pada 14:12:28 dan 14:12:29 untuk pesan "analisa gold"
    yang sama. Akibatnya user menerima DUA balasan berbeda (yang satu datanya gagal ditarik)
    dan kuota Claude terpakai dua kali.

    Aman dilakukan di sisi bot karena workflow memakai concurrency group: run kedua baru
    mulai setelah run pertama selesai DAN commit jejaknya, sehingga run kedua pasti melihat
    catatan itu saat checkout.

    Jendela sengaja pendek (3 menit): duplikat nyata datang dalam hitungan detik, sedangkan
    user yang benar-benar ingin mengulang perintah yang sama biasanya berjarak lebih lama.
    """
    sidik = _sidik(chat_id, text, photo_file_id)
    sekarang = time.time()
    try:
        with open(JEJAK_PATH, encoding="utf-8") as f:
            jejak = json.load(f)
    except Exception:
        jejak = []

    for j in jejak:
        if j.get("sidik") == sidik and sekarang - j.get("waktu", 0) < JEDA_DUPLIKAT:
            umur = int(sekarang - j["waktu"])
            print(f"[proses] DILEWATI — pesan sama sudah diproses {umur} detik lalu "
                  f"(pencegah dispatch ganda)", file=sys.stderr)
            # Duplikat NYATA datang dalam hitungan detik — itu dilewati diam-diam supaya
            # user tidak menerima pesan tambahan untuk sesuatu yang cuma ia kirim sekali.
            # Tapi kalau jaraknya sudah puluhan detik, kemungkinan besar user memang
            # SENGAJA mengulang. Diam saja di situ membuatnya mengira bot rusak, jadi
            # beri kabar singkat + cara mengulangnya.
            if umur >= JEDA_SENYAP:
                send_message(token_aktif(), chat_id,
                             f"↩️ Perintah yang sama baru saja diproses ({umur} detik lalu), "
                             "jadi tidak aku ulang otomatis.\n"
                             "Kalau memang ingin diulang, tunggu sebentar atau ubah sedikit "
                             "perintahnya (mis. tambahkan kata 'lagi').")
            return True

    jejak = [j for j in jejak if sekarang - j.get("waktu", 0) < 3600][-50:]
    jejak.append({"sidik": sidik, "waktu": sekarang,
                  "waktu_utc": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")})
    try:
        os.makedirs(os.path.dirname(JEJAK_PATH), exist_ok=True)
        with open(JEJAK_PATH, "w", encoding="utf-8") as f:
            json.dump(jejak, f, indent=1)
    except Exception as e:
        print(f"[proses] gagal menulis jejak duplikat: {e}", file=sys.stderr)
    return False


def process(token, chat_id, text, photo_file_id=None):
    if sudah_diproses(chat_id, text, photo_file_id):
        return

    simbol = jenis = simbol_chat = jenis_chat = None   # dipakai pencatat rapor di akhir
    brief = None          # DATA BRIEF tahap-1 (hanya terisi di analisa koin); dipakai
                          # audit keterlacakan angka. Dideklarasikan di sini supaya
                          # SELALU terdefinisi di semua cabang, termasuk mode foto.

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
        output, err = run_claude(build_photo_prompt(text, img, chat_id), timeout, max_turns=45,
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
        # Jalur foto punya pengiriman SENDIRI, sehingga dua pengaman di jalur utama
        # sempat terlewat di sini: stempel waktu dan peringatan audit. Padahal analisa
        # gambar justru rawan — angkanya sering dibaca dari gambar lama tanpa tanggal.
        if not body.startswith("❌"):
            body = pastikan_bertanggal(body)
        kesegaran_foto = audit_kesegaran(body)
        if not body.startswith("❌"):
            catatan_foto = peringatan_audit(None, None, kesegaran_foto)
            if catatan_foto:
                body = sisipkan_peringatan(body, catatan_foto)
                print(f"[audit] peringatan foto DIKIRIM: {catatan_foto[:60]}", file=sys.stderr)
        if send_message(token, chat_id, body):
            print(f"[proses] balasan foto {len(body)} karakter TERKIRIM", file=sys.stderr)
            print(f"[audit] {kesegaran_foto}", file=sys.stderr)
            # Tanpa ini, pertanyaan lanjutan sesudah kirim gambar ("jadi menurutmu
            # gimana?") datang tanpa tahu gambar apa yang barusan dibahas.
            simpan_riwayat(chat_id, text or "(mengirim gambar)", body)
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
        jenis, simbol = jenis_aset(" ".join(words[1:]))
        if simbol and jenis != "crypto":
            # SAHAM / FOREX: jalur terpisah. Script crypto (DefiLlama, holder Ethereum,
            # whale) tidak berlaku dan hanya menghasilkan error atau angka tak nyambung.
            label = "saham" if jenis == "saham" else "forex"
            send_message(token, chat_id,
                         f"⏳ Oke, riset {label} {simbol}. Tahap 1: kumpulkan data...")
            # Data deterministik dikumpulkan KODE (tidak bisa dilewatkan model), berita
            # dicari model karena butuh penilaian. Kalau berita gagal, analisa TETAP jalan
            # dengan data angkanya — sebelumnya satu kegagalan model mengosongkan semuanya.
            mentah = data_mentah_pasar(simbol, jenis)
            berita, err = run_claude(build_gather_pasar(simbol, jenis), min(timeout, 300),
                                     max_turns=20, model=MODEL_GATHER,
                                     tools_override=TOOLS_WEB)
            if err or not berita:
                print(f"[proses] pencarian berita gagal ({str(err)[:120]}) — "
                      f"lanjut dengan data angka saja", file=sys.stderr)
                berita = "[KATALIS]" + NL + "Pencarian berita gagal — tidak ada data berita."
            brief = mentah + NL + NL + berita
            if not mentah.strip():
                print(f"[proses] tahap-1 {label} GAGAL: data mentah kosong", file=sys.stderr)
                output = None
            else:
                print(f"[proses] tahap-1 {label} OK, brief {len(brief)} karakter "
                      f"(kode {len(mentah)} + berita {len(berita)}) -> tahap-2",
                      file=sys.stderr)
                send_message(token, chat_id, "🧠 Tahap 2: analisa & susun laporan...")
                output, err = run_claude(build_synth_pasar(simbol, jenis, brief),
                                         min(timeout, 420), max_turns=12,
                                         model=MODEL_SYNTH, with_tools=False)
        elif simbol:
            coin = simbol
            # DUA TAHAP (model tiering): Haiku kumpulkan data -> Opus menganalisa.
            send_message(token, chat_id, f"⏳ Oke, riset koin {coin}. Tahap 1: kumpulkan data...")
            t_gather = min(timeout, 300)
            mentah = data_mentah_crypto(coin)
            berita, err = run_claude(build_gather_prompt(coin), t_gather, max_turns=20,
                                     model=MODEL_GATHER, tools_override=TOOLS_WEB)
            if err or not berita:
                print(f"[proses] pencarian berita gagal ({str(err)[:120]}) — "
                      f"lanjut dengan data angka saja", file=sys.stderr)
                berita = "[KATALIS]" + NL + "Pencarian berita gagal — tidak ada data berita."
            brief = mentah + NL + NL + berita
            err = None if mentah.strip() else "data mentah kosong"
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
        # Screening narasi memang berat (banyak kandidat), tapi tetap dibatasi supaya
        # tidak memonopoli antrean selama 15 menit.
        # Screening memang butuh web DAN shell sekaligus (cari kandidat lalu hitung
        # indikatornya). Ini kompromi yang disadari, bukan kelalaian — jalur inilah yang
        # paling terbuka terhadap penyisipan lewat halaman web.
        output, err = run_claude(build_narasi_prompt(text), min(timeout, 600), max_turns=70,
                                 model=MODEL_NARASI, tools_override=TOOLS_LONGGAR)
    else:  # chat
        # Bobot ditentukan dari BERAT pertanyaannya, bukan dari ada/tidaknya riwayat.
        # Lihat bobot_chat(): tiga tingkat, dan konteks kini MENURUNKAN bobot.
        ada_konteks = bool(konteks_percakapan(chat_id).strip())
        jatah, model_chat, putaran, tingkat = bobot_chat(text, ada_konteks)
        print(f"[proses] bobot chat: {tingkat} -> {jatah} dtk, {model_chat}, "
              f"{putaran} putaran", file=sys.stderr)

        # Kalau pesannya menyebut ASET, kumpulkan datanya lewat KODE. Cakupannya sudah
        # mengikuti PETA KORELASI dengan sendirinya: data_mentah_pasar tidak menarik script
        # crypto, dan data_mentah_crypto tidak menarik makro/saham.
        # Efek terpenting: brief jadi ADA di mode ngobrol, sehingga audit keterlacakan
        # angka berjalan di sini juga — sebelumnya mode ini keluar tanpa pemeriksaan,
        # padahal justru paling rawan karangan karena model menjawab lebih bebas.
        jenis_chat, simbol_chat = aset_dari_pesan(text)
        if simbol_chat:
            try:
                brief = (data_mentah_crypto(simbol_chat) if jenis_chat == "crypto"
                         else data_mentah_pasar(simbol_chat, jenis_chat))
                print(f"[proses] chat: data {jenis_chat} {simbol_chat} dikumpulkan kode "
                      f"({len(brief)} karakter)", file=sys.stderr)
            except Exception as e:
                # Kegagalan di sini TIDAK boleh menggagalkan balasan — tanpa brief, model
                # kembali mencari sendiri persis seperti sebelum perubahan ini.
                brief = None
                print(f"[proses] chat: pengumpulan data gagal ({type(e).__name__}) — "
                      f"model mencari sendiri", file=sys.stderr)
        # Pesan tunggu hanya untuk yang memang lama. Untuk RINGAN, balasannya datang lebih
        # cepat daripada pesan tunggunya sendiri.
        if jatah > 120:
            send_message(token, chat_id, "💬 Sebentar ya, aku cek datanya dulu...")
        # Kalau data sudah di brief, chat tidak butuh Bash sama sekali — cukup web.
        # Kalau pengumpulan gagal, BOLEH jatuh ke mode longgar (web + shell), tapi itu
        # dicatat supaya ketahuan seberapa sering pengaman ini terpaksa dilonggarkan.
        if brief:
            tools_chat = TOOLS_WEB          # data sudah ada, shell tidak diperlukan
        elif simbol_chat:
            # Aset terdeteksi tapi pengumpulannya gagal — model perlu shell sebagai
            # cadangan. Dicatat supaya ketahuan seberapa sering pengaman terpaksa dilepas.
            tools_chat = TOOLS_LONGGAR
            print("[proses] chat: mode tool LONGGAR (web + shell) karena pengumpulan data "
                  "gagal", file=sys.stderr)
        elif topik_ai(text.strip().lower()):
            # Pertanyaan industri AI memang butuh menjalankan ainews.py.
            tools_chat = TOOLS_LONGGAR
        else:
            # Sapaan & pertanyaan konseptual: tidak ada aset, tidak ada script yang perlu
            # dijalankan. Tanpa shell, halaman web yang dibaca tidak bisa berbuat apa-apa.
            tools_chat = TOOLS_WEB
        print(f"[proses] chat: tool = {'WEB' if tools_chat == TOOLS_WEB else 'LONGGAR'}",
              file=sys.stderr)
        output, err = run_claude(build_chat_prompt(text, chat_id, brief),
                                 min(timeout, jatah), max_turns=putaran, model=model_chat,
                                 tools_override=tools_chat)

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

    # Stempel waktu hanya untuk balasan berisi data. Menempelkannya pada pesan error
    # membuat kegagalan terlihat seolah "data per jam sekian" — membingungkan.
    if not body.startswith("❌"):
        body = pastikan_bertanggal(body)

    # Audit dijalankan SEBELUM pengiriman supaya vonisnya bisa ikut ke user. Sebelumnya
    # ketiganya berjalan setelah send_message, jadi hasilnya tidak mungkin sampai.
    kesegaran = audit_kesegaran(body)
    jejak = audit_angka(brief, body)
    asal = audit_sumber(brief)
    if not body.startswith("❌"):
        catatan = peringatan_audit(jejak, asal, kesegaran)
        if catatan:
            body = sisipkan_peringatan(body, catatan)
            print(f"[audit] peringatan DIKIRIM ke user: {catatan[:70]}", file=sys.stderr)

    if send_message(token, chat_id, body):
        print(f"[proses] balasan {len(body)} karakter TERKIRIM ke Telegram", file=sys.stderr)
        # Vonis lengkap tetap dicetak utuh ke log, bukan hanya yang terparah.
        print(f"[audit] {kesegaran}", file=sys.stderr)
        simpan_riwayat(chat_id, text, body)
        # Catat PANGGILAN (bias + level) supaya bisa dinilai belakangan. Diekstraksi oleh
        # kode dari teks balasan, jadi tidak bisa dilewatkan dan tidak menambah biaya
        # giliran. DIBUNGKUS try/except: pencatatan rapor tidak boleh menggagalkan apa pun —
        # balasannya sendiri sudah terkirim di baris atas.
        try:
            aset_rapor = simbol if kind == "analisa" else simbol_chat
            jenis_rapor = jenis if kind == "analisa" else jenis_chat
            if aset_rapor:
                sys.path.insert(0, BASE_DIR)
                from rapor import catat as catat_rapor
                rid = catat_rapor(body, aset_rapor, jenis_rapor, kind)
                if rid:
                    print(f"[rapor] panggilan dicatat: {rid}", file=sys.stderr)
        except Exception as e:
            print(f"[rapor] gagal mencatat ({type(e).__name__}) — diabaikan", file=sys.stderr)
        if jejak:
            print(f"[audit] {jejak}", file=sys.stderr)
        if asal:
            print(f"[audit] {asal}", file=sys.stderr)
    else:
        print(f"[proses] GAGAL KIRIM ke Telegram ({len(body)} karakter hilang). "
              "Penyebab tersering: TELEGRAM_BOT_TOKEN salah/kedaluwarsa/sudah di-revoke.",
              file=sys.stderr)


_TGL_RE = re.compile(
    r"\b\d{1,2}\s+(" + "|".join(_BULAN_ID) + r")\s+\d{4}\b|"   # 17 Juli 2026
    r"\b(" + "|".join(_BULAN_ID) + r")\s+\d{4}\b|"             # Juli 2026
    r"\b\d{4}-\d{2}-\d{2}\b",                                  # 2026-07-17
    re.IGNORECASE)


def peringatan_audit(jejak, asal, kesegaran):
    """Ubah hasil audit jadi MAKSIMAL SATU baris peringatan untuk user, atau None.

    Ketiga audit sudah menghitung vonis nyata sejak lama, tapi hasilnya hanya dicetak ke
    stderr — dan itu SETELAH balasan dikirim. Artinya kalau sebagian besar angka tidak bisa
    dilacak ke data mentah, user tetap menerima analisa itu tanpa tanda apa pun, sementara
    vonisnya terkubur di log Actions yang tidak pernah dibuka.

    Hanya SATU yang ditampilkan, yang paling parah. Menumpuk tiga peringatan membuat orang
    berhenti membacanya, dan peringatan yang diabaikan sama saja dengan tidak ada.

    Vonis PERIKSA (15-35% tidak terlacak) sengaja TIDAK memicu peringatan: level turunan
    seperti target dan invalidasi memang wajar tidak muncul persis di data mentah, jadi
    memperingatkannya akan sering dan membuat peringatan ini kehilangan arti.
    """
    asal = asal or ""
    jejak = jejak or ""
    kesegaran = kesegaran or ""

    if "CLOSE-ONLY" in asal:
        return ("⚠️ Sebagian data hanya harga penutupan — ATR, SuperTrend, dan Pivot di atas "
                "tidak sahih.")
    if "MENCURIGAKAN" in jejak:
        return ("⚠️ Sebagian angka di atas tidak bisa kulacak ke data mentah — periksa ulang "
                "sebelum dipakai.")
    if "DATA BASI" in asal:
        return ("⚠️ Candle terakhir sudah lebih dari 48 jam — untuk crypto ini tidak wajar, "
                "perlakukan levelnya sebagai perkiraan.")
    if "BURUK" in kesegaran:
        return ("⚠️ Balasan ini memuat angka tanpa satu pun tanggal — ada kemungkinan sebagian "
                "berasal dari ingatan, bukan data baru.")
    return None


def sisipkan_peringatan(body, peringatan):
    """Tempel peringatan sebagai baris terakhir SEBELUM disclaimer.

    Disclaimer selalu jadi penutup; peringatan yang ditaruh sesudahnya akan terbaca seperti
    catatan kaki dan kehilangan bobotnya.
    """
    if not peringatan:
        return body
    baris = body.rstrip().split("\n")
    for i in range(len(baris) - 1, -1, -1):
        if baris[i].lstrip().startswith(("⚠️ Riset", "⚠️ Bukan saran", "⚠️ Ini bukan")):
            baris.insert(i, peringatan)
            baris.insert(i + 1, "")
            return "\n".join(baris)
    return body.rstrip() + "\n\n" + peringatan


def pastikan_bertanggal(teks):
    """Sisipkan stempel waktu data kalau balasan sama sekali tidak memuat tanggal.

    Format output MEWAJIBKAN baris "🕒 Data per ...", tapi kepatuhan model tidak bisa
    diandalkan — pernah hilang begitu daftar indikator bertambah panjang. Angka pasar
    tanpa waktu itu menyesatkan (pembaca tak tahu ini seumur jam atau sebulan), jadi
    dijamin di sini lewat kode. Data memang ditarik saat run ini, sehingga stempelnya sahih.
    """
    if _TGL_RE.search(teks):
        return teks
    wib = datetime.now(timezone.utc) + timedelta(hours=7)
    stempel = f"🕒 Data per {wib.day} {_BULAN_ID[wib.month - 1]} {wib.year}, {wib:%H:%M} WIB"
    return f"{stempel}\n\n{teks}"


_SUMBER_RE = re.compile(r'\b(?:source|sumber)\b"?\s*[:=]\s*"?([A-Za-z][\w .()>-]{2,40})', re.I)
_KUALITAS_RE = re.compile(r'\bquality\b"?\s*[:=]\s*"?(\w+)', re.I)
_CANDLE_RE = re.compile(r'\b(?:last_candle_utc|candle[ _]terakhir)\b"?\s*[:=]\s*"?([\d-]{10}[ T][\d:]{5})', re.I)


def audit_sumber(brief):
    """Catat DARI MANA data OHLC berasal dan seberapa segar candle terakhirnya.

    Tanpa ini mustahil memeriksa apakah sebuah analisa memakai data terbaru atau jatuh ke
    sumber cadangan yang lebih miskin. Kualitas 'approx_close_only' berarti hanya harga
    penutupan (tanpa high/low asli) — indikator berbasis rentang jadi tidak sahih.
    """
    if not brief:
        return None
    # Nama sumber boleh mengandung spasi ("coingecko (agregasi harian->mingguan)"), jadi
    # polanya longgar dan bisa terlanjur menelan kata kunci berikutnya pada penulisan
    # sebaris ("source=kraken quality=native"). Potong di kata kunci tersebut.
    def bersih(x):
        return re.split(r"\s+(?:quality|kualitas|last_candle|candle)\b", x, 1)[0].strip(" |,;")

    sumber = sorted({bersih(x) for x in _SUMBER_RE.findall(brief) if bersih(x)})
    kualitas = sorted(set(_KUALITAS_RE.findall(brief)))
    candle = sorted(set(_CANDLE_RE.findall(brief)))
    if not (sumber or kualitas or candle):
        return None
    bagian = []
    if sumber:
        bagian.append("sumber=" + ", ".join(sumber))
    if kualitas:
        bagian.append("kualitas OHLC=" + ",".join(kualitas))

    # Umur candle diperiksa terhadap waktu run. Analisa yang datanya tertinggal berhari-hari
    # menyesatkan meski sumbernya benar, jadi keterlambatan harus terlihat — bukan diasumsikan
    # segar hanya karena sumbernya bursa asli.
    tanda = " ⚠️ ADA DATA CLOSE-ONLY (ATR/SuperTrend/Pivot tidak sahih)" if "approx_close_only" in kualitas else ""
    if candle:
        terbaru = max(candle)
        bagian.append("candle terakhir=" + terbaru + " UTC")
        try:
            t = datetime.strptime(terbaru.replace("T", " ")[:16], "%Y-%m-%d %H:%M").replace(tzinfo=timezone.utc)
            umur_jam = (datetime.now(timezone.utc) - t).total_seconds() / 3600
            bagian.append(f"umur={umur_jam:.1f} jam")
            if umur_jam > 48:
                tanda += " ⚠️ DATA BASI (>48 jam)"
        except Exception:
            pass
    return "sumber data: " + " · ".join(bagian) + tanda


_ANGKA_RE = re.compile(r"\d[\d.,]*")


def _digit(s):
    """Sisakan digitnya saja: '1.864,32' dan '1864.32194' sama-sama jadi '186432...'."""
    return re.sub(r"\D", "", s).lstrip("0")


def _cocok_angka(d, r):
    """Apakah digit d (dari balasan) berasal dari digit r (dari data mentah)?

    Prefiks menangani PEMOTONGAN (35853160 -> "358"), tapi penulis laporan lazimnya
    MEMBULATKAN: 35.853.160 ditulis "35,9 juta" -> "359". Tanpa penanganan ini angka
    yang sebenarnya sah ikut tertandai dan menutupi karangan yang asli.
    """
    if r.startswith(d) or d.startswith(r):
        return True
    if len(r) > len(d) and d.isdigit():
        potong = r[:len(d)]
        if int(r[len(d)]) >= 5:                     # dibulatkan ke atas
            naik = str(int(potong) + 1)
            if len(naik) == len(potong) and d == naik:
                return True
    return False


def audit_angka(brief, balasan):
    """Periksa apakah angka di balasan BISA DILACAK ke data mentah (DATA BRIEF).

    Ini penangkal karangan yang bekerja di level KODE, bukan sekadar imbauan di prompt:
    kalau model menyebut angka yang tidak ada di brief, angka itu bukan berasal dari data.

    Pencocokan sengaja LONGGAR (prefiks digit) supaya pembulatan tetap terhitung cocok —
    '1.864' cocok dengan '1864.32194406'. Karena itu angka yang TIDAK cocok patut dicurigai.
    Turunan yang sah (persentase, rasio, selisih) juga bisa ikut tak cocok, jadi hasilnya
    dilaporkan sebagai SINYAL untuk ditelusuri, bukan vonis otomatis.
    """
    if not brief:
        return None
    ref = {_digit(m.group(0)) for m in _ANGKA_RE.finditer(brief)}
    ref = {d for d in ref if len(d) >= 2}
    if not ref:
        return None

    # Bagian RENCANA & KESIMPULAN berisi level TURUNAN (zona entry, target, invalidasi)
    # yang memang dihitung dari Fibonacci/support — wajar tidak ada persis di brief.
    # Bagian itu dikecualikan supaya sinyal ini tajam: yang tersisa adalah klaim FAKTUAL
    # (harga, indikator, fundamental, kepemilikan) — di situlah karangan benar-benar bahaya.
    potong = re.split(r"🧭\s*RENCANA SPOT|✅\s*KESIMPULAN", balasan)
    faktual = potong[0] if len(potong) > 1 else balasan
    # Baris "Level kunci: support/resisten" juga berisi level TURUNAN (dihitung dari
    # swing/Fibonacci), bukan angka mentah dari sumber — buang agar tidak jadi derau.
    faktual = re.sub(r"(?im)^.*\b(level kunci|support|resisten|resistance)\b.*$", "", faktual)
    # Tiga sumber DERAU SISTEMATIS yang tidak mungkin ada di data mentah, dan karena itu
    # dulu selalu terhitung "tidak terlacak":
    #   1. baris stempel waktu — tahunnya (2026) bukan angka pasar
    #   2. penyebut skor ("62/100") — angka 100 tidak pernah ada di brief
    #   3. baris disclaimer
    # Pada analisa panjang derau ini terencerkan, tapi di mode NGOBROL briefnya kecil
    # sehingga tiga angka ini saja bisa mendorong vonis ke MENCURIGAKAN dan memunculkan
    # PERINGATAN PALSU ke user. Peringatan yang salah menyala membuat orang berhenti
    # membaca peringatan — persis yang berusaha dicegah oleh peringatan itu sendiri.
    faktual = re.sub(r"(?m)^\s*🕒.*$", "", faktual)
    faktual = re.sub(r"(?m)^\s*⚠️.*$", "", faktual)
    faktual = re.sub(r"(?i)(SKOR\s*\d{1,3}\s*)/\s*100", r"\1", faktual)
    # Tahun 19xx/20xx adalah TANGGAL, bukan angka pasar. Kesegarannya sudah diperiksa
    # terpisah oleh audit_kesegaran, jadi di sini hanya menjadi derau.
    faktual = re.sub(r"\b(19|20)\d{2}\b", "", faktual)

    dicek, tak_terlacak = 0, []
    for m in _ANGKA_RE.finditer(faktual):
        d = _digit(m.group(0))
        if len(d) < 3:          # angka 1-2 digit terlalu umum untuk dinilai
            continue
        dicek += 1
        if not any(_cocok_angka(d, r) for r in ref):
            tak_terlacak.append(m.group(0))
    if not dicek:
        return None

    persen = round(len(tak_terlacak) / dicek * 100)
    contoh = ", ".join(tak_terlacak[:6])
    if persen <= 15:
        vonis = "BAIK"
    elif persen <= 35:
        vonis = "PERIKSA"
    else:
        vonis = "MENCURIGAKAN"
    return (f"keterlacakan angka (bagian faktual): {vonis} — {dicek - len(tak_terlacak)}/{dicek} "
            f"angka terlacak ke DATA BRIEF ({persen}% tidak terlacak"
            + (f"; contoh: {contoh}" if tak_terlacak else "") + ")")


def audit_kesegaran(teks):
    """Ukur apakah balasan MENANGGALI angkanya — tanpa menuliskan isi balasan ke log.

    Dipakai sebagai sinyal mutu: jawaban berisi angka pasar tapi tanpa satu pun tanggal
    biasanya berarti model menjawab dari ingatan, bukan dari data yang baru diambil.
    """
    tanggal = len(set(m.group(0) for m in _TGL_RE.finditer(teks)))
    angka_besar = len(re.findall(r"\b\d[\d.,]{3,}\b", teks))
    if tanggal == 0 and angka_besar > 0:
        return (f"kesegaran: BURUK — {angka_besar} angka TANPA satu pun tanggal "
                "(indikasi jawaban dari ingatan, bukan data baru)")
    if tanggal == 0:
        return "kesegaran: tidak ada angka & tidak ada tanggal (jawaban naratif)"
    return f"kesegaran: OK — {tanggal} tanggal berbeda disebut, {angka_besar} angka"


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
