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
# Tanpa MCP sama sekali: dipakai untuk obrolan murni, supaya server MCP tidak perlu
# dipasang maupun dinyalakan. run_claude() ikut membuang --mcp-config sendiri.
TOOLS_SOSIAL = "WebSearch,WebFetch"

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


# Pola rahasia yang TIDAK BOLEH ikut terkirim ke Telegram. Pesan error kadang membawa
# potongan konfigurasi, dan repo ini publik — chat ID pun sengaja di-hash, jadi
# membocorkan token lewat pesan gagal akan membatalkan kehati-hatian itu.
_RAHASIA_RE = re.compile(
    r"(?i)(bot[0-9]{6,}:[A-Za-z0-9_-]{20,}"          # token bot Telegram
    r"|gh[pousr]_[A-Za-z0-9]{20,}"                   # token GitHub
    r"|sk-[A-Za-z0-9_-]{20,}"                        # kunci bergaya sk-
    r"|[A-Za-z0-9_-]{32,}\.[A-Za-z0-9_-]{16,})")    # token bertitik


def tanpa_rahasia(teks):
    """Ganti apa pun yang menyerupai token dengan penanda, sebelum dikirim ke user."""
    return _RAHASIA_RE.sub("[dirahasiakan]", teks or "")


def send_message(token, chat_id, text):
    """Kirim pesan (dipecah kalau melebihi batas Telegram). Return True kalau SEMUA
    potongan benar-benar terkirim — pemanggil wajib memeriksa hasilnya, jangan
    menganggap pengiriman pasti berhasil."""
    # Disaring SEBELUM dipecah. Menyaring tiap potongan secara terpisah membuat token
    # yang kebetulan terbelah di batas 3.900 karakter lolos — kedua belahannya tampak
    # seperti teks biasa dan tidak cocok pola apa pun, padahal begitu digabung kembali
    # di layar user token itu utuh.
    text = tanpa_rahasia(text or "")
    # Teks kosong TIDAK BOLEH dilaporkan berhasil. Perulangan di bawah tidak berjalan
    # sama sekali untuk teks kosong, sehingga fungsi ini dulu mengembalikan True padahal
    # tak satu pun pesan dikirim — persis kebalikan dari janji docstring, dan pemanggil
    # lalu mencatat "TERKIRIM" ke log. Telegram juga menolak pesan berisi spasi saja.
    if not text.strip():
        print("[kirim] teks kosong — tidak ada yang dikirim", file=sys.stderr)
        return False
    terkirim = True
    for i in range(0, len(text), 3900):
        potong = text[i:i + 3900]
        resp = tg_api(token, "sendMessage", {"chat_id": chat_id, "text": potong})
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


# Nama bulan LENGKAP dan SINGKATANNYA. Model kerap menulis "9 Agu 2026" alih-alih
# "9 Agustus 2026" — dan tanpa singkatan di daftar ini tanggalnya tidak dikenali,
# sehingga audit_kesegaran memvonis "angka TANPA satu pun tanggal" lalu memunculkan
# PERINGATAN PALSU. Terlihat langsung di layar user: balasan yang jelas bertanggal
# tetap diberi peringatan seolah disusun dari ingatan.
# Yang panjang ditulis LEBIH DULU supaya regex tidak berhenti di singkatannya
# ("Agustus" jangan sampai cuma tercocok sebagai "Agu").
_BULAN_ID = ("Januari", "Februari", "Maret", "April", "Mei", "Juni", "Juli", "Agustus",
             "September", "Oktober", "November", "Desember",
             "Sept", "Jan", "Feb", "Mar", "Apr", "Jun", "Jul", "Agu", "Ags", "Agt",
             "Sep", "Okt", "Nov", "Des")


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
    r"\b(harga|beli|jual|buy|sell|hold|akumulasi|prospek|pasar|market|tren|trend|level|support|resisten|"
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


# Jenis aset -> blok yang relevan. Dipakai saat kosakata rumpun tidak cocok tapi asetnya
# sudah dikenali dari pesan, supaya tidak jatuh ke gagal-aman "muat semua".
_RUMPUN_JENIS = {
    "crypto": {"institusi", "x-twitter"},
    "forex": {"gold", "makro", "saham-forex"},
    "saham": {"saham-forex", "makro"},
}


def _rumpun_cocok(low):
    """Blok mana yang relevan dengan pesan ini. Kosong = tidak ada rumpun yang cocok."""
    blok = set()
    for kata_kunci, blok_terkait in _RUMPUN.values():
        if any(k in low for k in kata_kunci):
            blok.update(blok_terkait)
    return blok


_PEMICU_PENDEK = 3      # di bawah ini, substring polos terlalu sering salah kena


def _pemicu_cocok(kata, low):
    """Pemicu PENDEK harus jatuh di awal kata; yang panjang tetap substring bebas.

    Substring polos membuat pemicu pendek menyala di tempat yang salah: "ai" cocok di
    dalam "hai" dan "explain" (sapaan "hai bot" ikut membawa 1.486 karakter aturan
    industri AI), dan "ema" cocok di dalam "kemarin" (1.272 karakter peta korelasi untuk
    pertanyaan yang tidak menyinggung EMA sama sekali).

    Tapi batas kata TIDAK boleh dipasang untuk semua pemicu, ke dua arah:

    - di BELAKANG — pemicu ditulis sebagai akar kata, "banding" untuk "bandingkan".
    - di DEPAN — bahasa Indonesia memakai AWALAN. "emas bagus dibeli sekarang?" adalah
      pertanyaan beli, dan pemicunya "beli" berada di tengah "di-beli". Memasang batas
      depan untuk semua pemicu mematikan blok rencana-posisi di situ — regresi yang
      hanya ketahuan karena hasilnya diukur, bukan diasumsikan.

    Jadi batasnya hanya untuk pemicu <= 3 huruf, tempat kesalahannya benar-benar
    terkonsentrasi. Pemicu >= 4 huruf jarang jadi potongan kata lain secara kebetulan.
    """
    if len(kata) > _PEMICU_PENDEK:
        return kata in low
    i = low.find(kata)
    while i != -1:
        if i == 0 or not (low[i - 1].isalnum() or low[i - 1] == "_"):
            return True
        i = low.find(kata, i + 1)
    return False


def _jenis_ticker(tik):
    """Rumpun sebuah simbol, dipakai memilih blok prompt untuk pesan MULTI-ASET.

    aset_dari_pesan() sengaja menolak memilih saat asetnya lebih dari satu, dan itu
    benar — brief perbandingan memang tidak bisa dilayani satu aset. Tapi RUMPUN-nya
    tetap jelas, dan tanpa ini gagal-aman memuat seluruh blok.
    """
    if tik in _FX_SIMBOL or _PASANGAN_FX.match(tik):
        return "forex"
    if tik in _TICKER_UMUM or tik in _KOIN_SIMBOL:
        return "crypto"
    return "saham"      # sisanya hanya bisa datang dari peta ticker SEC


def rakit_chat(teks_prompt, pesan, jenis_aset_terdeteksi=None):
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
            if kata and _pemicu_cocok(kata, low):
                dipakai.add(nama)
                break

    # GAGAL-AMAN BERKELOMPOK. Dulu biner: sentuh satu kata _PASAR_UMUM, SEMUA blok dimuat.
    # Itu terlalu lebar — pertanyaan gold ikut membawa aturan 13F dan riset X, lalu model
    # menjalankan tool yang tidak nyambung. Sekarang hanya blok SERUMPUN yang ditambahkan.
    # Kalau menyentuh kosakata pasar tapi TIDAK ADA rumpun yang cocok, barulah semua blok
    # dimuat — di situ kita memang tidak tahu apa yang dibutuhkan, dan kehilangan aturan
    # lebih merugikan daripada boros. Prinsip lamanya dipertahankan, ambangnya dipersempit.
    # Dipakai pesan_pasar(), bukan _PASAR_UMUM saja: kalimat seperti "di timeframe weekly
    # masih possible turun sampai 55k-58k" jelas soal pasar, tapi tak menyentuh satu pun
    # kata _PASAR_UMUM — sehingga gagal-aman tidak pernah aktif dan blok aturan yang
    # relevan tidak ikut terpasang.
    if pesan_pasar(pesan):
        serumpun = _rumpun_cocok(low)
        # Kalau kosakata rumpun tidak cocok TAPI jenis asetnya sudah dikenali dari pesan,
        # pakai itu. "kalo buy pump di 0.0026" menyentuh kosakata pasar lewat kata "buy",
        # tapi tidak menyebut satu pun kata rumpun — tanpa petunjuk ini gagal-aman memuat
        # SEMUA blok (42 rb karakter) padahal jelas pertanyaan crypto.
        if not serumpun and jenis_aset_terdeteksi:
            serumpun = _RUMPUN_JENIS.get(jenis_aset_terdeteksi, set())
        # Pesan MULTI-ASET ("bandingkan btc dan eth") sengaja tidak memilih satu aset,
        # jadi jenis_aset_terdeteksi kosong dan gagal-aman memuat SELURUH 14 blok:
        # 54.948 karakter, +19 rb dari pertanyaan crypto biasa — di tingkat BERAT yang
        # 40 putaran. Rumpunnya jelas dari aset-aset yang disebut; tidak perlu ditebak.
        if not serumpun:
            # Sekali saja: _semua_aset menyapu peta 10.398 ticker SEC, dan dulu dipanggil
            # dua kali di sini (plus sekali lagi lewat aset_dari_pesan di pemanggil).
            aset = _semua_aset(pesan)
            if aset:
                serumpun = set().union(*(_RUMPUN_JENIS.get(_jenis_ticker(a), set())
                                         for a in aset))
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

# LAPIS KEDUA — hanya saat user MEMINTA melanjutkan. Batas 6 jam di atas disengaja:
# percakapan kemarin yang ikut menempel di pertanyaan baru hari ini lebih sering
# menyesatkan daripada menolong. Tapi "lanjutkan yang kemarin" adalah permintaan
# eksplisit, dan di situ batas itu justru yang menghalangi. Jadi jendelanya dilebarkan
# HANYA di jalur itu, bukan untuk semua pesan.
RIWAYAT_UMUR_LANJUT = 7 * 24 * 3600
RIWAYAT_MAKS_LANJUT = 5

# "lanjutkan", "yang kemarin", "tadi kita bahas apa". Sengaja menuntut kata sambungnya —
# "lanjut" telanjang terlalu sering berarti "teruskan analisanya", bukan "buka lagi
# percakapan lama".
_MINTA_LANJUT = re.compile(
    r"\b(?:lanjutkan|lanjutin|teruskan|terusin|sambung(?:kan)?|balik ke)\b"
    r"[^.]{0,24}\b(?:tadi|kemarin|sebelumnya|yang lalu|obrolan|pembicaraan|diskusi|"
    r"bahasan|topik)\b|"
    r"\b(?:yang|obrolan|pembicaraan|diskusi|bahasan|topik)\s+"
    r"(?:tadi|kemarin|sebelumnya)\b|"
    r"\b(?:tadi|kemarin)\s+kita\b|"
    r"\bcontinue\b[^.]{0,20}\b(?:earlier|previous|conversation)\b",
    re.I)


def minta_lanjut(teks):
    """Apakah user MEMINTA melanjutkan percakapan lama (bukan sekadar pesan lanjutan)."""
    return bool(_MINTA_LANJUT.search(teks or ""))


def _muat_riwayat():
    """Riwayat percakapan. [] kalau belum ada — TAPI kegagalan lain dicatat.

    Berkas yang belum ada memang wajar dan diam-diam saja. Berkas yang RUSAK tidak:
    tanpa jejak, ingatan percakapan lenyap selamanya dan tidak ada yang tahu — bot
    cuma terlihat pelupa. Membedakan keduanya harganya satu baris.
    """
    try:
        with open(RIWAYAT_PATH, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return []
    except Exception as e:
        print(f"[riwayat] {RIWAYAT_PATH} tidak terbaca ({type(e).__name__}) — "
              f"percakapan dimulai dari kosong", file=sys.stderr)
        return []


def _buang_ekor_boilerplate(teks):
    """Buang disclaimer & peringatan audit di UJUNG balasan sebelum dipangkas.

    Keduanya sama untuk setiap balasan, jadi tidak menambah konteks apa pun saat dibaca
    ulang di giliran berikutnya — tapi keduanya MEMAKAN jatah ekor. Sejak peringatan audit
    ditambahkan, blok "KESIMPULAN" terdorong keluar dari potongan yang disimpan, padahal
    mempertahankan kesimpulan itulah alasan potongan dua-ujung ini dibuat.
    """
    baris = (teks or "").rstrip().split("\n")
    while baris and (not baris[-1].strip() or baris[-1].lstrip().startswith("⚠️")):
        baris.pop()
    return "\n".join(baris)


def _potong_balasan(teks):
    """Pangkas balasan panjang dengan menyimpan AWAL dan AKHIR-nya.

    Memotong dari depan saja akan membuang bagian paling penting untuk diskusi: pada
    analisa, skor & bias ada di ATAS sementara KESIMPULAN ada di BAWAH. Kalau user
    lalu bertanya "kenapa kamu bilang tunggu dulu?", justru bagian bawah itu yang
    dibutuhkan.
    """
    teks = _buang_ekor_boilerplate(teks)
    if len(teks) <= BALASAN_POTONG:
        return teks
    sisi = BALASAN_POTONG // 2
    return teks[:sisi].rstrip() + "\n[...dipangkas...]\n" + teks[-sisi:].lstrip()


# Pola angka yang benar-benar mengubah keputusan. Sengaja SEMPIT: yang dikejar bukan semua
# angka, melainkan yang biasanya ditanyakan lagi di giliran berikutnya.
# Pola angka kunci. Tiap pola BERJANGKAR pada labelnya, bukan sekadar mencari "$".
# Versi lama memungut angka dolar apa pun sehingga yang tersimpan justru MCAP, VOLUME,
# dan harga BTC dari baris pasar — sementara harga koin yang dianalisa tenggelam di
# urutan bawah atau terpotong batas 8. RSI pun tertangkap sebagai "4" dari "RSI 4H".
# Ini berbahaya karena MODE PENDAPAT bersandar pada angka-angka ini saat menjawab
# pertanyaan lanjutan — angka yang salah di sini menjadi jawaban yang salah di situ.
# Kata "harga" boleh di mana saja dalam kalimat, tidak harus di awal baris: mode
# ngobrol menulisnya inline ("harga 4H terakhir $0,002683"). Yang penting kata itu
# ADA di dekatnya — itulah yang membedakannya dari mcap & volume.
_RE_AK_HARGA = re.compile(r"harga[^$\n]{0,26}[$]\s*(\d[\d.,]*)", re.I)
# Cadangan: kalau tak ada kata "harga" sama sekali, ambil nilai dolar PERTAMA yang
# jelas BUKAN mcap/volume/kapitalisasi.
_RE_AK_DOLAR = re.compile(r"(?<!mcap )(?<!volume )[$]\s*(\d[\d.,]*)", re.I)
_LABEL_BUKAN_HARGA = ("mcap", "market cap", "volume", "kapitalisasi", "fdv", "tvl")
_RE_AK_EMA = re.compile(r"EMA\s*(\d{1,3})[^$\n]{0,16}[$]\s*(\d[\d.,]*)", re.I)
_RE_AK_RSI = re.compile(r"RSI\s*(?:14)?\s*(?:harian|daily|mingguan|weekly|4H|1D|1W|D1|H4)?\s*[:=]?\s*(\d{1,3}(?:[.,]\d+)?)\b(?!\s*[Hh]\b)", re.I)
_RE_AK_SKOR = re.compile(r"SKOR\s*(\d{1,3})\s*/\s*100", re.I)
_RE_AK_INVALID = re.compile(r"Invalid(?:asi)?\s*[$]?\s*(\d[\d.,]*)", re.I)

_ANGKA_MAKS = 8


def angka_kunci(teks):
    """Tarik angka penting dari balasan supaya giliran berikutnya tidak menarik ulang semua.

    Riwayat memangkas balasan jadi BALASAN_POTONG karakter, jadi angka dari giliran
    sebelumnya memang HILANG — itulah sebab bot menarik ulang seluruh data hanya untuk
    menjawab "jadi gambaranmu bagaimana?".

    Tiap angka diambil dari LABELNYA, dan yang tidak masuk akal dibuang: RSI di luar
    0-100 bukan RSI. Urutannya juga penting — harga & level dulu, baru sisanya, supaya
    batas 8 tidak habis oleh angka pelengkap.
    """
    teks = teks or ""
    keluar = []

    def tambah(butir):
        if butir not in keluar and len(keluar) < _ANGKA_MAKS:
            keluar.append(butir)

    m = _RE_AK_HARGA.search(teks)
    if m:
        tambah(f"harga={m.group(1).strip(' .,;:')}")
    else:
        # Tidak ada kata "harga" — ambil nilai dolar pertama dari baris yang tidak
        # membicarakan mcap/volume/TVL, supaya yang tersimpan tetap harga aset.
        for baris in teks.split("\n"):
            if any(k in baris.lower() for k in _LABEL_BUKAN_HARGA):
                continue
            md = _RE_AK_DOLAR.search(baris)
            if md:
                tambah(f"harga={md.group(1).strip(' .,;:')}")
                break
    for m in _RE_AK_INVALID.finditer(teks):
        tambah(f"invalid={m.group(1).strip(' .,;:')}")
    for m in _RE_AK_EMA.finditer(teks):
        tambah(f"ema{m.group(1)}={m.group(2).strip(' .,;:')}")
    for m in _RE_AK_RSI.finditer(teks):
        nilai = m.group(1).replace(",", ".")
        try:
            if 0 <= float(nilai) <= 100:      # di luar itu bukan RSI
                tambah(f"rsi={m.group(1)}")
        except ValueError:
            pass
    m = _RE_AK_SKOR.search(teks)
    if m:
        tambah(f"skor={m.group(1)}")
    return keluar

def bersihkan_id():
    """Ubah chat ID polos di riwayat lama menjadi hash. Sekali jalan.

    Dipakai setelah _id_chat() diperkenalkan: entri yang sudah tersimpan masih memuat chat
    ID apa adanya. Riwayat GIT-nya tetap memuat yang polos — membersihkan itu menuntut
    force-push yang menulis ulang sejarah bersama, dan sengaja TIDAK dilakukan di sini.
    """
    try:
        with open(RIWAYAT_PATH, encoding="utf-8") as f:
            riwayat = json.load(f)
    except OSError:
        print("[bersihkan] tidak ada riwayat untuk dibersihkan")
        return
    diubah = 0
    for r in riwayat:
        chat = str(r.get("chat", ""))
        if chat.isdigit():          # masih polos
            r["chat"] = _id_chat(chat)
            diubah += 1
    with open(RIWAYAT_PATH, "w", encoding="utf-8") as f:
        json.dump(riwayat, f, indent=1, ensure_ascii=False)
    print(f"[bersihkan] {diubah} dari {len(riwayat)} entri disamarkan")


def _id_chat(chat_id):
    """Samarkan chat ID sebelum disimpan — repo ini PUBLIK.

    memori.py sudah menolak alamat dompet & saldo di level kode, tapi chat ID lolos padahal
    itu identifier akun Telegram. Di-hash dengan GARAM dari token bot supaya tidak bisa
    dibalik dengan mencoba semua angka: chat ID hanya ~10 digit, jadi sha256 tanpa garam
    praktis sama dengan menyimpannya polos.

    Konsekuensi yang disadari: kalau token bot diganti, garamnya berubah dan riwayat lama
    tidak lagi cocok. Riwayatnya jadi terlihat kosong — mengganggu, tapi jauh lebih ringan
    daripada membocorkan identifier akun di repo publik.

    CATATAN: riwayat git yang LAMA tetap memuat chat ID polos. Membersihkannya menuntut
    force-push yang menulis ulang sejarah bersama, dan itu di luar cakupan tugas ini.
    """
    garam = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    return hashlib.sha256(f"{garam}|{chat_id}".encode()).hexdigest()[:16]


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
    # Disimpan mengikuti jendela TERPANJANG. Dulu dipangkas di 6 jam, jadi arsip untuk
    # "lanjutkan yang kemarin" tidak akan pernah terkumpul — dibuang sebelum sempat
    # dipakai. Yang menentukan berapa yang DIPAKAI tetap konteks_percakapan().
    riwayat = [r for r in _muat_riwayat()
               if sekarang - r.get("waktu", 0) < RIWAYAT_UMUR_LANJUT][-40:]
    riwayat.append({
        "chat": _id_chat(chat_id),
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


def _jenis_terakhir(chat_id, panjang=False):
    """Rumpun aset dari giliran sebelumnya. None kalau memang belum ada.

    Pesan LANJUTAN sering tidak menyebut asetnya lagi: "menurutku justru masih bisa turun"
    tidak punya satu pun petunjuk rumpun, sehingga gagal-aman memuat SELURUH blok — 63 rb
    karakter untuk satu kalimat. Padahal rumpunnya sudah diketahui satu giliran lalu, dan
    riwayatnya memang sudah dibaca untuk keperluan lain.
    """
    if not chat_id:
        return None
    sekarang = time.time()
    lalu = [r for r in _muat_riwayat()
            if str(r.get("chat")) == _id_chat(chat_id)
            and sekarang - r.get("waktu", 0) < (RIWAYAT_UMUR_LANJUT if panjang
                                                else RIWAYAT_UMUR)]
    for r in reversed(lalu):
        jenis = aset_dari_pesan(r.get("pesan") or "")[0]
        if jenis:
            return jenis
    return None


def _usia_terbaca(detik):
    """"1800 menit lalu" tidak terbaca sebagai "kemarin". Umur harus berbicara."""
    menit = int(detik // 60)
    if menit < 90:
        return f"{menit} menit lalu"
    if menit < 36 * 60:
        return f"{menit / 60:.0f} jam lalu"
    return f"{menit / 1440:.0f} hari lalu"


def _masih_nyambung(pesan, entri):
    """Apakah giliran lama masih relevan dengan pesan sekarang — dinilai KODE.

    Ukurannya ASET yang disebut: pesan hari ini menyebut SOL dan giliran kemarin juga
    tentang SOL. Tegas, murah, dan tidak menuntut model menilai apa pun.

    Kesamaan kata biasa sengaja TIDAK dipakai. "gimana", "sekarang", "menurutmu" muncul
    di hampir semua pesan, jadi ambang berbasis kata akan menyeret percakapan lama yang
    tidak ada hubungannya — persis alasan batas 6 jam dipasang sejak awal.
    """
    aset = _semua_aset(pesan or "")
    if not aset:
        return False
    lama = (_semua_aset(entri.get("pesan") or "")
            | _semua_aset(entri.get("balasan") or ""))
    return bool(aset & lama)


def konteks_percakapan(chat_id, panjang=False, pesan=None):
    """Rakit konteks percakapan sebelumnya untuk disisipkan ke prompt.

    `panjang` = user MEMINTA melanjutkan percakapan lama, jadi jendelanya dibuka 7 hari
    dan pasangannya lebih banyak. Di luar itu tetap 6 jam: percakapan kemarin yang ikut
    menempel di pertanyaan baru hari ini lebih sering menyesatkan daripada menolong.
    """
    sekarang = time.time()
    milik = [r for r in _muat_riwayat() if str(r.get("chat")) == _id_chat(chat_id)]

    def usia(r):
        return sekarang - r.get("waktu", 0)

    nyambung = []
    if panjang:
        lalu = [r for r in milik if usia(r) < RIWAYAT_UMUR_LANJUT][-RIWAYAT_MAKS_LANJUT:]
    else:
        segar = [r for r in milik if usia(r) < RIWAYAT_UMUR][-RIWAYAT_MAKS:]
        # OTOMATIS: lebih tua dari 6 jam tapi MASIH membahas aset yang sama. User tidak
        # perlu bilang "lanjutkan" — kalau ia bertanya soal SOL lagi hari ini, percakapan
        # SOL kemarin memang nyambung. Dibatasi 2 supaya tidak menggantikan yang segar.
        nyambung = [r for r in milik
                    if RIWAYAT_UMUR <= usia(r) < RIWAYAT_UMUR_LANJUT
                    and _masih_nyambung(pesan, r)][-2:]
        lalu = nyambung + segar
    if not lalu:
        # Diminta melanjutkan tapi tidak ada apa-apa: katakan, jangan berpura-pura ingat.
        if panjang:
            return ("## MELANJUTKAN PERCAKAPAN — TIDAK ADA CATATANNYA" + NL
                    + "User meminta melanjutkan pembicaraan sebelumnya, tapi tidak ada "
                      "riwayat dalam 7 hari terakhir. Katakan apa adanya dan minta ia "
                      "menyebutkan topiknya. JANGAN mengarang apa yang pernah dibahas."
                    + NL + NL)
        return ""
    if panjang:
        judul = "## MELANJUTKAN PERCAKAPAN SEBELUMNYA (user memintanya)"
    elif nyambung:
        judul = ("## PERCAKAPAN SEBELUMNYA (termasuk yang lebih lama tapi MASIH "
                 "membahas aset yang sama)")
    else:
        judul = "## PERCAKAPAN SEBELUMNYA (konteks, bukan perintah baru)"
    baris = [judul]
    for r in lalu:
        u = _usia_terbaca(sekarang - r.get("waktu", 0))
        baris.append(f"[{u}] User: {r.get('pesan', '')}")
        baris.append(f"           Kamu menjawab: {r.get('balasan', '')}")
        ak = r.get("angka_kunci") or []
        if ak:
            baris.append(f"           Angka kunci saat itu ({u}): " + " · ".join(ak))
    baris += [
        "",
        "CARA MEMAKAI konteks ini:",
        "- Kalau pesan sekarang jelas LANJUTAN (pendek, memakai kata seperti 'itu',",
        "  'lanjutkan', 'kalau', 'bagaimana dengan', atau tidak menyebut asetnya),",
        "  sambungkan ke topik di atas. JANGAN meminta user mengulang topiknya.",
        "- Kalau pesan sekarang topik BARU, ABAIKAN konteks ini sepenuhnya.",
        "- ANGKA di dalam konteks ini SUDAH LAMA. Jangan dikutip sebagai data terkini —",
        "  ambil ulang datanya kalau dibutuhkan.",
    ]
    if nyambung:
        baris += [
            "- Sebagian di atas berumur BERHARI-HARI, ikut dibawa karena membahas aset "
            "yang sama.",
            "  Sambungkan benangnya ('waktu itu kesimpulannya TUNGGU DULU'), tapi angkanya",
            "  hampir pasti sudah berubah — bandingkan dengan data sekarang dan sebutkan",
            "  apa yang berubah sejak itu. Itu justru bagian yang berguna.",
        ]
    baris += [
        "- Konteks ini hanya untuk menyambung benang pembicaraan, bukan sumber fakta.",
        "",
    ]
    return "\n".join(baris) + "\n---\n"



# Seed peran: identitas profesional yang dipakai saat menganalisa. inti.md SELALU ikut
# (memuat aturan kalibrasi keras yang mencegah model mengarang keyakinan); peran lain
# dimuat sesuai kebutuhan mode. Tiap file punya blok bertanda sektor, jadi analisa crypto
# tidak ikut membawa aturan risiko forex/saham — itu yang membuat mutu naik tanpa boros.
PERAN_LENGKAP = ("inti", "analis", "risk", "portofolio", "trader", "prediktor")

# Pertanyaan yang MEMINTA proyeksi: target harga, arah ke depan, atau perkiraan hasil
# rilis data. Dipakai untuk memuat seed FORECASTER pada mode ngobrol — di analisa penuh
# seed itu selalu ikut karena analisa memang berujung pada target dan skenario.
_MINTA_PROYEKSI = re.compile(
    r"(?:target|proyeksi|prediksi|forecast|ramal|potensi|berpotensi|bisa (?:naik|turun|"
    r"tembus|sampai)|akan (?:naik|turun)|sampai (?:harga|level|\$)|ke \$|outlook|"
    r"bakal|kapan|berapa lama|sejauh mana|seberapa (?:jauh|tinggi)|bullish|bearish|"
    # "performa X seminggu kedepan" adalah pertanyaan proyeksi yang paling wajar,
    # dan sempat jatuh ke jalur RINGAN tanpa data sama sekali. "kedepan" ditulis
    # tanpa spasi jauh lebih sering daripada "ke depan".
    r"performa|kinerja|ke ?depan|mendatang|"
    r"predict|projection|where will|how (?:high|low|far)|next (?:week|month|quarter|year)|"
    r"dampak(?:nya)?|efek(?:nya)?|hasil(?:nya)? (?:cpi|nfp|fomc))", re.I)


# Pertanyaan SEBAB: "kenapa BTC naik minggu ini". Wajib ada kata tanya sebab DAN kata
# gerakan — tanpa keduanya, "kenapa staking bekerja begitu" ikut tertangkap, padahal
# itu pertanyaan konsep yang jalurnya ringan dan tidak butuh data pasar sama sekali.
_MINTA_SEBAB = re.compile(
    r"(?:kenapa|mengapa|apa (?:yang )?(?:penyebab|sebab|bikin|membuat)|kok|why)"
    r"[^?.!]{0,60}?"
    r"(?:naik|turun|anjlok|jatuh|reli|rally|melonjak|pump|dump|melemah|menguat|"
    r"drop|crash|terbang|ambles)", re.I)


def data_sebab(jenis, simbol):
    """Bahan dekomposisi sebab — dijalankan KODE, bukan diminta ke model.

    Tanpa ini, "kenapa naik" dijawab dengan daftar berita yang kebetulan terbit pekan
    itu. Itu koinsidensi yang disusun rapi, bukan sebab: kalau seluruh pasar naik dengan
    besaran serupa, berita itu penumpang, bukan penggerak."""
    keluar, err = _jalankan_terukur("SEBAB (sebab.py)",
                                    ["cloud/sebab.py", simbol, "--jenis", jenis])
    judul = "### DEKOMPOSISI SEBAB (sebab.py)" + chr(10)
    if err:
        return (judul + f"tidak tersedia: {err}. Katakan apa adanya — JANGAN "
                        "menggantinya dengan daftar berita pekan ini seolah itu sebabnya.")
    return judul + keluar


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


# Niat transaksi + harga konkret. Gabungan keduanya berarti user sedang menimbang
# keputusan nyata, dan itu tidak boleh dijawab dari angka giliran sebelumnya.
_NIAT_TRANSAKSI = re.compile(
    r"\b(buy|beli|jual|sell|masuk|entry|entri|akumulasi|average|dca|cut|tp|take profit)",
    re.I)
# Harga bisa ditulis desimal ("0.002551"), berdolar ("$2400"), atau bulat begitu saja
# ("masuk eth di 2400"). Bentuk terakhir sempat lolos sehingga pertanyaan transaksi
# dengan harga bulat tetap jatuh ke tingkat RINGAN tanpa data.
_HARGA_KONKRET = re.compile(r"\d+[.,]\d+|[$]\s*\d|\b\d{3,}\b")


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
    # RISET TELEGRAM. Diukur di produksi: memverifikasi belasan klaim terhadap data
    # bukan pekerjaan 120 detik / 8 putaran. Run pertama jatuh ke RINGAN dan tidak
    # akan pernah sempat selesai — bahannya saja 3 rb karakter di atas prompt 31 rb.
    if minta_telegram(text):
        return 420, MODEL_NARASI, 24, "RISET TELEGRAM (verifikasi klaim terhadap data)"
    # Keputusan TRANSAKSI dengan harga konkret selalu butuh data segar, walau kalimatnya
    # terdengar seperti minta pendapat. "kalo buy pump di 0.002551 bagaimana menurutmu?"
    # sempat jatuh ke tingkat RINGAN — 8 putaran, tanpa shell, tanpa brief — sehingga
    # jawabannya bersandar pada angka giliran SEBELUMNYA untuk sebuah keputusan beli.
    if _NIAT_TRANSAKSI.search(low) and _HARGA_KONKRET.search(low):
        return 300, MODEL_NARASI, 20, "SEDANG (keputusan transaksi dengan harga konkret)"
    # Penafsiran lanjutan: angka kuncinya sudah ada di konteks, tinggal ditimbang.
    if _TAFSIR_RE.search(low) and ada_konteks:
        return 120, MODEL_RINGAN, 8, "RINGAN (penafsiran dari konteks yang sudah ada)"
    # Predikat yang sama dipakai untuk memuat aturan kalibrasi — SATU sumber kebenaran.
    # Sebelumnya baris ini hanya menguji _PASAR_UMUM/_TEKNIKAL_RE, sehingga "btc masih bisa
    # turun ke 55k?" — menyebut aset DAN target harga — jatuh ke tingkat RINGAN dengan label
    # "di luar kosakata pasar": 8 putaran, model ringan, tanpa data segar.
    if pesan_pasar(text):
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
# Nama panjang. Tanpa ini "solana berpotensi naik sampai $200?" tidak dikenali sama sekali
# (aset None -> bukan pertanyaan pasar -> tanpa aturan kalibrasi), padahal "sol" dikenali.
# Orang menulis nama panjang justru saat TIDAK memakai perintah, yaitu di mode ngobrol.
_ALIAS_KOIN = {
    "bitcoin": "BTC", "ethereum": "ETH", "solana": "SOL", "cardano": "ADA",
    "ripple": "XRP", "dogecoin": "DOGE", "polkadot": "DOT", "avalanche": "AVAX",
    "chainlink": "LINK", "polygon": "MATIC", "litecoin": "LTC", "cosmos": "ATOM",
    "arbitrum": "ARB", "optimism": "OP", "injective": "INJ", "celestia": "TIA",
    "aptos": "APT", "toncoin": "TON", "hedera": "HBAR", "stellar": "XLM",
    "algorand": "ALGO", "render": "RNDR", "bittensor": "TAO", "uniswap": "UNI",
    "shiba inu": "SHIB", "binance coin": "BNB", "tron": "TRX", "filecoin": "FIL",
}
_KATA_BUKAN_TICKER = {"ADA", "OP", "ATAU", "INI", "ITU", "DAN", "APA", "KE", "DI",
                      # "MANA" adalah ticker Decentraland SEKALIGUS kata tanya Indonesia.
                      # "bagusan mana sol atau eth" sempat terbaca menyebut tiga aset.
                      # Bentuk "$MANA" tetap dikenali lewat jalur dolar di bawah.
                      "MANA"}

# Kata Indonesia yang KEBETULAN terdaftar sebagai ticker saham AS di berkas SEC. Peta SEC
# memuat 10.398 ticker termasuk "DAN", "VS", "MANA", "GOLD" — mencocokkannya mentah ke
# kalimat Indonesia akan menghasilkan aset palsu di hampir setiap pertanyaan.
# Diturunkan sekali di impor, bukan dihitung ulang tiap pesan.
_FX_SIMBOL = frozenset(_ALIAS_FX.values())
_KOIN_SIMBOL = frozenset(_ALIAS_KOIN.values())

_BUKAN_TICKER_SAHAM = {
    "DAN", "VS", "MANA", "ATAU", "INI", "ITU", "APA", "KE", "DI", "YANG", "JADI", "BUAT",
    "PADA", "DARI", "AKAN", "BISA", "LAGI", "SAJA", "JUGA", "TAPI", "ANTARA", "SAMA",
    "LEBIH", "BAGUS", "MASIH", "SUDAH", "BELUM", "NANTI", "SAAT", "KALAU", "ADA", "AKU",
    "KAMU", "SAYA", "GIMANA", "KENAPA", "BERAPA", "HARGA", "PASAR", "KOIN", "BELI", "JUAL",
}
# Kata yang lazim MENGIKUTI kata kerja transaksi tapi jelas bukan nama aset.
# Tanpa daftar ini, "beli banyak" terbaca sebagai koin BANYAK, "entry lagi" jadi koin
# LAGI, dan "buy the dip" jadi koin THE — bot lalu mengumpulkan data untuk aset yang
# tidak ada. Ini kelas kesalahan yang sama dengan "analisa koin pump" yang dulu sudah
# diperbaiki, muncul kembali di tempat baru karena polanya ditulis ulang.
_SETELAH_TRANSAKSI_BUKAN_ASET = {
    "BANYAK", "SEDIKIT", "LAGI", "DULU", "AJA", "SAJA", "TERUS", "SEMUA", "SISA",
    "SEBAGIAN", "SEKARANG", "NANTI", "BESOK", "KAPAN", "BERAPA", "HARGA", "POSISI",
    "PELAN", "CEPAT", "PENUH", "THE", "DIP", "MORE", "NOW", "SOME", "ALL", "AGAIN",
    "BACK", "IN", "OUT", "PADA", "SAAT", "KALAU", "KALO", "WAKTU", "SAMPAI", "SETELAH",
    "SEBELUM", "BIAR", "SUPAYA", "MUMPUNG", "BARENG", "JUGA", "MASIH", "BELUM", "SUDAH",
}


# Niat MEMBANDINGKAN. Dipakai dua tempat: membuka pencocokan ticker SEC (yang terlalu
# berisiko dibuka untuk kalimat bebas) dan menandai pesan yang butuh brief perbandingan.
_BANDING_RE = re.compile(
    r"(?:banding|bandingkan|perbandingan|dibanding|dibandingkan|"
    r"\bvs\b|versus|lebih (?:baik|bagus)|bagusan|mendingan|pilih mana|mana yang)", re.I)


def _semua_aset(teks):
    """Kumpulan aset berbeda yang disebut dalam satu pesan. Dipakai untuk mendeteksi
    pertanyaan PERBANDINGAN, yang tidak bisa dilayani satu brief."""
    low = (teks or "").lower()
    kata = re.findall(r"[A-Za-z]{2,6}", teks or "")
    ketemu = set()
    for alias, simbol in _ALIAS_FX.items():
        if re.search(r"\b" + alias.lower() + r"\b", low):
            ketemu.add(simbol)
    for nama, tik in _ALIAS_KOIN.items():
        if re.search(r"\b" + re.escape(nama) + r"\b", low):
            ketemu.add(tik)
    for k in kata:
        atas = k.upper()
        if _PASANGAN_FX.match(atas):
            ketemu.add(atas)
        elif atas in _TICKER_UMUM and atas not in _KATA_BUKAN_TICKER:
            ketemu.add(atas)

    # Saham: dicocokkan ke peta ticker SEC, dengan penyaring kata Indonesia. Tanpa ini,
    # "bandingkan nvda dan amd" tidak terdeteksi sebagai perbandingan sama sekali.
    if not ketemu or len(ketemu) < 2:
        try:
            from sec_tickers import peta_ticker
            hasil = peta_ticker()
            peta = hasil[0] if isinstance(hasil, tuple) else hasil
        except Exception:
            peta = {}
        # KATA UTUH saja. `kata` dibuat tanpa batas kata, jadi "sekarang" terpotong jadi
        # "sekara"+"ng" — dan "NG" adalah ticker SEC yang sah (Northrop Grumman). Akibatnya
        # "harga btc berapa sekarang" terbaca menyebut DUA aset, brief-nya batal dikumpulkan,
        # dan pertanyaan satu koin kehilangan datanya. Peta SEC berisi 10 ribu ticker pendek,
        # jadi pencocokan potongan kata pasti menghasilkan aset palsu.
        # Kata yang SUDAH punya arti lain tidak boleh dicocokkan ulang ke SEC. "gold" alias
        # emas sekaligus ticker Barrick; "rsi" indikator sekaligus ticker Rush Street.
        sudah_punya_arti = ({a.upper() for a in _ALIAS_FX} | {a.upper() for a in _ALIAS_KOIN}
                            | set(_TICKER_UMUM))
        # Peta SEC berisi 10.398 ticker pendek, jadi mencocokkannya ke kalimat Indonesia
        # bebas akan SELALU menemukan aset palsu — sudah terbukti pada "sekarang" (NG),
        # "gold" (Barrick), dan "rsi" (Rush Street). Daftar pengecualian tidak akan pernah
        # selesai. Karena itu jalur ini hanya dibuka saat konteksnya memang menuntutnya:
        # ada niat MEMBANDINGKAN, kata "saham" disebut, atau tickernya ditulis KAPITAL.
        petunjuk = bool(re.search(r"\b(saham|stock|emiten|ticker)\b", low)
                        or _BANDING_RE.search(low))
        for k in re.findall(r"\b[A-Za-z]{2,6}\b", teks or ""):
            atas = k.upper()
            if (atas in peta and atas not in _BUKAN_TICKER_SAHAM
                    and atas not in _KATA_BUKAN_TICKER
                    and atas not in sudah_punya_arti
                    and (petunjuk or k.isupper())):
                ketemu.add(atas)
    return ketemu


# Kata Indonesia yang sering muncul di pertanyaan pasar dan TIDAK boleh dikirim ke
# pencarian koin. resolve_ticker sudah konservatif (menuntut kecocokan persis DAN
# peringkat market cap), tapi menembakkan kata umum ke jaringan tetap pemborosan yang
# bisa dicegah tanpa biaya.
_KATA_UMUM_BUKAN_KOIN = {
    "PERFORMA", "KINERJA", "SEMINGGU", "SEBULAN", "KEDEPAN", "DEPAN", "BAGAIMANA",
    "GIMANA", "SEKARANG", "MINGGU", "BULAN", "TAHUN", "HARI", "PROSPEK", "KONDISI",
    "SITUASI", "UPDATE", "PANTAU", "ANALISA", "ANALISIS", "TARGET", "HARGA", "PASAR",
    "UNTUK", "DENGAN", "SAMPAI", "SUDAH", "BELUM", "MASIH", "AKAN", "BISA",
    # Sapaan & basa-basi. HALO, PING, dan OKE semuanya nama koin sungguhan di CoinGecko —
    # tanpa baris ini, "halo" mengembalikan analisa aset.
    "HALO", "HAI", "PAGI", "SIANG", "SORE", "MALAM", "OKE", "OKEY", "SIP", "PING",
    "THANKS", "MAKASIH", "TERIMA", "KASIH", "MAAF", "TOLONG", "COBA", "LAGI",
}


def aset_dari_pesan(teks, dalam=False):
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

    # 2b. Pola "buy/beli/jual <TOKEN>" — niat transaksi menyebut asetnya secara eksplisit,
    #     jadi cukup aman diambil walau tickernya di luar daftar terbatas. Tanpa ini, koin
    #     yang tidak masuk daftar tidak pernah mendapat brief sama sekali.
    m2 = re.search(r"\b(?:buy|beli|jual|sell|entry|masuk|akumulasi)\s+([A-Za-z]{2,6})\b",
                   teks or "", re.I)
    if m2:
        atas = m2.group(1).upper()
        if (atas not in _KATA_BUKAN_TICKER
                and atas not in _SETELAH_TRANSAKSI_BUKAN_ASET
                and atas not in ("DARI", "UNTUK", "DENGAN")):
            return "crypto", atas

    # 2c. Nama panjang ("solana", "bitcoin"). Dicek sebelum daftar ticker karena kata
    #     panjang tidak tertangkap oleh pemindaian 2-6 huruf di atas.
    for nama, tik in _ALIAS_KOIN.items():
        if re.search(r"\b" + re.escape(nama) + r"\b", low):
            return "crypto", tik

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

    # 4. PENCARIAN DALAM — hanya kalau pemanggilnya meminta.
    #
    # _TICKER_UMUM cuma 55 nama. ASTER, HYPE, dan SKYAI TIDAK ada di dalamnya, padahal
    # ketiganya sudah pernah dianalisa dan tercatat di rapor.jsonl — mereka hanya lolos
    # lewat perintah "analisa X" yang memakai jenis_aset, fungsi lain yang menerima
    # ticker apa pun. Lewat pertanyaan biasa, koin di luar daftar itu TIDAK PERNAH
    # mendapat brief sama sekali, dan seluruh data yang dikumpulkan bot ini jadi tidak
    # ikut menjawab.
    #
    # `dalam` default False karena pesan_pasar() memanggil fungsi ini untuk SETIAP pesan,
    # termasuk "halo". Pencarian jaringan di sana berarti tiap sapaan menembak CoinGecko.
    # Hanya pengumpul data — yang jalan SESUDAH pesannya terklasifikasi sebagai pertanyaan
    # pasar — yang meminta pencarian dalam.
    if not dalam:
        return None, None
    # LAPIS PENGAMAN 1: pesannya harus memang soal pasar. Tanpa ini "halo" mengembalikan
    # koin HALO — yang benar-benar ada — dan sapaan berubah jadi analisa aset.
    # Rekursinya cuma satu tingkat: pesan_pasar memanggil balik fungsi ini dengan
    # dalam=False, dan cabang itu tidak pernah memanggil pesan_pasar lagi.
    # Pertanyaan PEMANTAUAN ("update aster", "kondisi skyai") tidak selalu lolos
    # pesan_pasar — kosakatanya berbeda — padahal justru butuh brief. Diterima keduanya;
    # _KATA_UMUM_BUKAN_KOIN yang menahan "ada update?" dan "kondisi pasar gimana", karena
    # seluruh katanya ada di daftar itu sehingga tidak ada kandidat tersisa.
    if not (pesan_pasar(teks) or _MINTA_PANTAU.search(low)):
        return None, None
    try:
        from indicators import resolve_ticker
    except Exception:
        return None, None
    dicoba = 0
    # KATA UTUH, bukan `kata`. Pemindaian di atas memakai [A-Za-z]{2,6} TANPA batas kata,
    # jadi "bagaimana" terpotong jadi "bagaim" + "ana" — dan "ana" adalah koin sungguhan.
    # Ini persis kelas kesalahan yang dulu membuat "sekaraNG" dibaca sebagai saham NG.
    # Pencarian dangkal aman karena daftarnya tertutup; pencarian dalam bertanya ke
    # CoinGecko, jadi potongan kata bisa mengembalikan koin yang tidak pernah disebut.
    utuh = re.findall(r"\b[A-Za-z]{3,6}\b", teks or "")
    for k in utuh:
        atas = k.upper()
        if len(atas) < 3 or atas in _KATA_BUKAN_TICKER or atas in _BUKAN_TICKER_SAHAM:
            continue
        if atas in _SETELAH_TRANSAKSI_BUKAN_ASET or atas in _KATA_UMUM_BUKAN_KOIN:
            continue
        if dicoba >= 2:            # batas keras: dua panggilan jaringan per pesan
            break
        dicoba += 1
        try:
            tik, _cid, _nama = resolve_ticker(k)
        except Exception:
            continue
        if tik:
            print(f"[aset] pencarian dalam: {k} -> {tik}", file=sys.stderr)
            return "crypto", tik
    return None, None


def pesan_pasar(text):
    """Apakah pesan ini menyangkut pasar — penentu apakah aturan kalibrasi dimuat.

    Sengaja lebih longgar dari _PASAR_UMUM: menyebut indikator, aset, atau niat transaksi
    berharga konkret sudah cukup. Sapaan dan pertanyaan konseptual tetap dikecualikan
    supaya "apa itu RSI?" tidak menyeret seluruh berkas peran.
    """
    low = (text or "").strip().lower()
    # Urutan mengikuti bobot_chat. Permintaan detail/perbandingan sudah dinilai BERAT di
    # sana, jadi tidak boleh gugur di saringan konseptual — "bandingkan btc dan eth secara
    # detail" sempat dianggap bukan pertanyaan pasar karenanya.
    if _BERAT_RE.search(low):
        return True
    if _RINGAN_RE.match(low) or _KONSEP_RE.search(low):
        return False
    return bool(_PASAR_UMUM.search(low)
                or _TEKNIKAL_RE.search(low)
                # Meminta target/proyeksi jelas pertanyaan pasar, walau kalimatnya tidak
                # memakai satu pun kosakata harga: "solana berpotensi naik sampai $200?"
                or _MINTA_PROYEKSI.search(low)
                or (_NIAT_TRANSAKSI.search(low) and _HARGA_KONKRET.search(low))
                or any(aset_dari_pesan(text)))


_SHELL_RE = re.compile(r"<!-- SHELL -->.*?<!-- /SHELL -->", re.S)


def buang_bagian_shell(teks):
    """Buang instruksi menjalankan script kalau shell-nya memang tidak diberikan.

    Jalur chat memakai TOOLS_WEB begitu brief tersedia — tanpa Bash. Mengirim "jalankan
    `python cloud/indicators.py`" ke model yang tidak punya shell adalah beban mati 1,6 rb
    karakter yang diulang di SETIAP putaran (sampai 24), dan lebih buruk dari sekadar
    mahal: ia menyuruh model melakukan sesuatu yang alatnya tidak ada. Persis kekeliruan
    yang sudah terjadi sekali di seed pemeriksa.
    """
    return _SHELL_RE.sub("", teks)


def _lepas_penanda_shell(teks):
    """Penandanya sendiri dibuang saat shell MEMANG diberikan — isinya tetap."""
    return teks.replace("<!-- SHELL -->" + NL, "").replace("<!-- /SHELL -->" + NL, "")


def build_chat_prompt(text, chat_id=None, brief=None):
    with open(CHAT_PROMPT, encoding="utf-8") as f:
        # Jenis aset ikut diberikan supaya pemilihan blok tidak jatuh ke "muat semua"
        # hanya karena kalimatnya tidak memakai kosakata rumpun.
        # Rumpun dari pesan ini; kalau tidak ada, warisi dari giliran sebelumnya.
        # Jendelanya harus SAMA dengan jendela konteks: kalau konteksnya boleh 7 hari
        # tapi pewarisan rumpun berhenti di 6 jam, "lanjutkan yang kemarin" jatuh ke
        # gagal-aman dan memuat SELURUH blok — 63 rb karakter, persis yang baru dihemat.
        _lanjut = minta_lanjut(text)
        base = rakit_chat(f.read(), text,
                          aset_dari_pesan(text)[0] or _jenis_terakhir(chat_id, _lanjut))
    # brief terisi <=> tools_chat = TOOLS_WEB (lihat pemilihan tool di process()). Datanya
    # sudah diambil kode, jadi tidak ada script yang perlu dijalankan model.
    base = buang_bagian_shell(base) if brief else _lepas_penanda_shell(base)
    # Aturan kalibrasi hanya untuk pertanyaan pasar. Buat "apa itu RAG?" atau sapaan,
    # aturan konviksi & bukti kontra tidak berguna dan cuma menambah beban.
    #
    # Dulu gerbangnya HANYA _PASAR_UMUM, padahal bobot_chat menyebut pesan sebagai
    # "pertanyaan pasar spesifik" bila _PASAR_UMUM ATAU _TEKNIKAL_RE cocok. Dua ambang
    # yang berbeda untuk keputusan yang sama, jadi pesan seperti "di timeframe weekly
    # masih possible turun sampai 55k-58k" dinilai pertanyaan pasar TAPI dijawab tanpa
    # inti.md — tanpa aturan konfluensi palsu, base rate, skenario, maupun daftar bias.
    # Sekarang satu predikat dipakai bersama supaya keduanya tidak bisa melenceng lagi.
    # Riset Telegram TIDAK lolos pesan_pasar — "carikan info dari telegram saya" tidak
    # menyebut aset maupun kosakata pasar. Tanpa cabang ini seluruh seed peran, termasuk
    # PEMERIKSA dan inti anti-sikap-manis, tidak pernah dimuat untuk pertanyaan itu.
    if pesan_pasar(text) or minta_telegram(text):
        low = (text or "").lower()
        peran = ["inti"]
        if any(k in low for k in ("risiko", "risk", "rugi", "drawdown", "aman", "bahaya")):
            peran.append("risk")
        if any(k in low for k in ("porto", "alokasi", "ukuran posisi", "modal",
                                  "diversifikasi", "korelasi")):
            peran.append("portofolio")
        # Seed FORECASTER hanya ikut kalau memang diminta proyeksi. Isinya berat (lima syarat
        # + protokol per pasar), dan tidak berguna untuk "harga btc berapa sekarang".
        if _MINTA_PROYEKSI.search(low):
            peran.append("prediktor")
        # PEMERIKSA hanya ikut kalau memang ada bahan grup yang harus diperiksa.
        # Isinya panjang dan tidak berguna untuk pertanyaan lain.
        if minta_telegram(text):
            peran.append("pemeriksa")
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
        base = konteks_percakapan(chat_id, panjang=_lanjut, pesan=text) + base
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
        base = konteks_percakapan(chat_id, pesan=caption) + base
    instruksi = (caption.strip() if caption and caption.strip()
                 else "(tidak ada caption — pakai default: identifikasi keterkaitan dengan "
                      "koin/project, cari info terkait, beri rekomendasi tindakan)")
    return (f"{header_waktu()}{base}\n---\n"
            f"## Gambar dari user\n"
            f"Gambar tersimpan di path: {image_path}\n"
            f"WAJIB baca dulu dengan tool Read (bisa melihat gambar), lalu kerjakan.\n\n"
            f"## Caption / pertanyaan user\n{instruksi}\n")


# Ciri "aset tidak ada": seluruh bursa/sumber gagal pada permintaan yang sama.
_SEMUA_SUMBER_GAGAL = re.compile(
    r'gagal ambil candle[^"]{0,200}?okx:'
    r'|tidak ditemukan di daftar emiten'
    r'|symbol tidak dikenal', re.I)


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
        # Keluaran tipis KARENA ASET TIDAK ADA tidak akan membaik dengan diulang.
        # Cirinya khas: SELURUH sumber gagal sekaligus. Rate limit biasanya menyisakan
        # sebagian sumber. Tanpa pembedaan ini, satu salah ketik ticker memakan 40 detik
        # dari jatah 300 detik hanya untuk mengulang sesuatu yang pasti gagal lagi.
        if err is None and keluar and _SEMUA_SUMBER_GAGAL.search(keluar):
            print(f"[data] {args[0]}: semua sumber gagal — aset kemungkinan tidak ada, "
                  f"tidak diulang", file=sys.stderr)
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


def _jalankan_terukur(label, args, min_kar=0):
    """Jalankan script sambil mencatat durasinya.

    Timing per-script sempat HILANG saat pengumpulan data diparalelkan — padahal itulah
    yang dulu membongkar makro.py 65 detik dan stockfund.py 58 detik di runner. Tanpa
    angka ini, script yang melambat tidak bisa dikenali dari log sama sekali.
    """
    t0 = time.time()
    keluar, err = jalankan_script(args, 300, min_kar)
    print(f"[data] {label}: {time.time() - t0:.1f} detik"
          f"{' — GAGAL' if err else ''}", file=sys.stderr)
    return keluar, err


# Script bisa "berhasil" (keluar 0, keluaran cukup panjang) sambil melaporkan bahwa
# datanya tidak ada. Menghitungnya sebagai berhasil membuat kelengkapan membaca 100%
# padahal dua sumber kosong — persis angka menyenangkan-tapi-palsu yang blok ini
# dibuat untuk mencegah.
_KOSONG_RE = re.compile(r'"tidak_tersedia"|semua sumber gagal|tidak ditemukan', re.I)


def _blok_kelengkapan(jumlah_tugas, gagal, bagian=None):
    """Berapa banyak sumber yang benar-benar tiba — dinyatakan, bukan disimpulkan.

    Sebelum ini daftar `gagal` hanya dicetak ke stderr, jadi model tidak pernah tahu
    sumber mana yang mati. Ia cuma melihat brief yang lebih pendek, dan tetap
    mengeluarkan SKOR dengan arsitektur bobot yang sama seperti saat semua data lengkap.
    Skor 72 di atas 5 dari 11 sumber dan skor 72 di atas 11 dari 11 jadi tak terbedakan —
    padahal keyakinan seharusnya dibatasi oleh mutu buktinya.

    `lewat` SENGAJA tidak ikut dihitung: itu bagian yang memang tidak berlaku untuk aset
    ini (koin natif tidak punya kontrak), bukan data yang hilang.
    """
    kosong = []
    for teks in (bagian or []):
        if not _KOSONG_RE.search(teks):
            continue
        judul = teks.split(chr(10), 1)[0].strip("[]# ")
        if judul:
            kosong.append(judul[:48])
    berhasil = jumlah_tugas - len(gagal) - len(kosong)
    persen = round(max(berhasil, 0) / jumlah_tugas * 100) if jumlah_tugas else 0
    baris = [f"{max(berhasil, 0)} dari {jumlah_tugas} sumber berisi data ({persen}%)."]
    if kosong:
        baris.append("JALAN TAPI KOSONG: " + " · ".join(kosong)
                     + " — scriptnya sukses, datanya yang tidak ada. Perlakukan sebagai "
                       "HILANG, bukan sebagai netral.")
    if gagal:
        baris.append("GAGAL: " + " · ".join(gagal))
        baris.append("Keyakinan dibatasi mutu bukti: sebut kelengkapan ini saat memberi "
                     "SKOR, dan JANGAN memberi skor tinggi di atas data yang tipis. "
                     "Yang hilang harus disebut sebagai HILANG, bukan diam-diam "
                     "diperlakukan sebagai netral.")
    return "[KELENGKAPAN DATA]" + chr(10) + chr(10).join(baris)


# Pertanyaan PEMANTAUAN: user ingin tahu apa yang sedang terjadi, bukan sedang menimbang
# transaksi. Kesimpulan bergaya "MASUK SEKARANG / TUNGGU DULU" salah alamat di sini —
# ia menjawab pertanyaan yang tidak diajukan, dan memaksa pembacanya menolak saran yang
# tidak diminta sebelum bisa memakai isinya.
# Diperluas setelah pertanyaan nyata "kalo secara fundamental di X apakah ada informasi
# yang menarik pada koin eden?" dijawab dengan "Belum punya: LEWATI / Sudah pegang:
# TAHAN". Itu pertanyaan INFORMASI, bukan transaksi — dan menjawabnya dengan format
# keputusan memaksa pembacanya menolak saran yang tidak diminta sebelum bisa memakai
# isinya. Aman diperluas: mode ini hanya mengubah GAYA kesimpulan, tidak mengubah data
# yang dikumpulkan maupun jalur routingnya.
_MINTA_PANTAU = re.compile(
    r"\b(update|market update|kondisi|situasi|keadaan|perkembangan|pantau|pantauan|"
    r"apa yang terjadi|lagi (?:gimana|bagaimana)|sekarang (?:gimana|bagaimana)|"
    r"weekly|mingguan|kabar|terpantau|"
    # Bentuk "apakah ada informasi/berita/sesuatu yang menarik" — pertanyaan temuan.
    r"ada (?:informasi|info|berita|kabar|sesuatu|hal)|"
    r"(?:informasi|info|berita) (?:menarik|penting|baru|terbaru)|"
    r"apa saja yang|narasi(?:nya)?|"
    # Sisi Inggris dari pertanyaan yang sama. "what's happening with btc"
    # adalah pertanyaan pemantauan, bukan permintaan rencana beli.
    r"what.?s (?:happening|going on|up) (?:with|on)|anything new|any(?:thing)? (?:news|update)|"
    r"monitor|watch(?:ing)? |current (?:state|condition|situation)|"
    r"fundamental(?:nya)? (?:gimana|bagaimana|apa))" + '\\b', re.I)


# Riset grup hanya jalan kalau user MENYEBUT "telegram" atau "tele" secara utuh.
# "grup", "channel", dan "kanal" sengaja DIBUANG: kata-kata itu terlalu sering muncul
# dalam pertanyaan yang tidak ada hubungannya ("ada apa di grup ini", "kanal berita"),
# dan membaca grup pribadi user karena salah tangkap jauh lebih buruk daripada
# sesekali harus menyebut kata pemicunya.
#
# Batas kata penting: tanpa itu "telepon" dan "televisi" ikut cocok dengan "tele".
_TG_TEMPAT = re.compile(r"\b(?:telegram|tele)\b", re.I)
_TG_NIAT = re.compile(
    r"cari|carikan|nyari|informasi|info|menarik|riset|rangkum|ringkas|"
    r"apa yang|ada apa|kabar|bahas|pantau|"
    # Mencari lowongan adalah niat riset tersendiri — user punya grup khusus untuk itu.
    r"lowongan|hiring|rekrut|"
    # User mencampur dua bahasa dalam satu kalimat, dan sisi Inggrisnya sempat kosong
    # sama sekali: "anything interesting on my telegram" tidak menyalakan apa pun,
    # sementara "info menarik dari telegram" menyala. Gerbang yang hanya mengerti satu
    # bahasa terasa seperti bot yang rusak sesekali, dan itu lebih buruk daripada
    # gerbang yang lebar — kata "telegram"/"tele" tetap wajib ada di sisi tempat.
    r"find|search|look|check|read|scan|"
    r"anything|what.?s new|whats new|any (?:news|update|alpha)|update|"
    r"summar|recap|digest|interesting|"
    r"job|vacanc|opening|career", re.I)


def _seed(nama):
    """Muat satu seed peran. String kosong kalau tidak ada — jangan mematikan alurnya."""
    try:
        with open(os.path.join(BASE_DIR, "prompts", "peran", nama + ".md"),
                  encoding="utf-8") as f:
            return f.read()
    except OSError as e:
        print(f"[seed] {nama}.md tidak terbaca ({type(e).__name__})", file=sys.stderr)
        return ""


def saring_telegram(mentah):
    """Pungut & pilih klaim dari tumpukan pesan grup, pakai model MURAH tanpa tool.

    KENAPA ADA TAHAP INI. Pertanyaan Telegram jatuh ke tingkat RINGAN — sonnet, 8
    putaran — sementara isinya bisa 200 pesan (~40 rb karakter). Mahal sekaligus tidak
    cukup: 8 putaran tidak akan sempat memverifikasi apa pun kalau separuhnya habis
    untuk membaca. Tahap ini memangkas 40 rb karakter jadi belasan klaim, sehingga model
    yang memeriksa hanya membayar untuk yang memang layak diperiksa.

    TANPA TOOL — dan itu bukan penghematan, itu keamanan. Ini titik PERTAMA teks grup
    yang tidak dipercaya bertemu sebuah model. Model tanpa tool tidak bisa menjalankan
    apa pun walau teksnya memuat perintah; ia cuma bisa menghasilkan teks.
    """
    if not mentah:
        return None
    prompt = (_seed("pemulung") + chr(10) * 2 + _seed("kurator") + chr(10) * 2
              + "# BAHAN" + chr(10)
              + "Kerjakan berurutan: pungut dulu (PEMULUNG), lalu pilih (KURATOR). "
              + "Keluarkan HANYA daftar hasil kurasi." + chr(10) * 2 + mentah)
    keluar, err = run_claude(prompt, 180, 3, model=MODEL_GATHER, with_tools=False)
    if err or not keluar:
        print(f"[telegram] penyaringan gagal ({err}) — dipakai mentahnya",
              file=sys.stderr)
        return None
    print(f"[telegram] {len(mentah)} -> {len(keluar)} karakter setelah disaring",
          file=sys.stderr)
    return keluar


# Berapa aset yang datanya diambil untuk verifikasi. Tiap aset ~2 rb karakter; lebih
# dari tiga membuat bahan verifikasi lebih besar daripada klaimnya sendiri.
ASET_VERIFIKASI_MAKS = 3


def _angkat_bagian_kembar(mentah):
    """Angkat field JSON yang isinya SAMA untuk semua aset, supaya dikirim sekali saja.

    Script data menyisipkan catatan cara membaca ke dalam keluarannya — `wajib_dibaca`
    milik derivatif.py sendiri 612 karakter, lebih dari separuh keluarannya, dan isinya
    identik untuk BTC maupun ETH. Dengan tiga aset ia dibayar tiga kali, di SETIAP putaran
    dari 24. Yang diulang bukan datanya melainkan penjelasannya, jadi tidak ada yang
    hilang dengan mengangkatnya ke atas.
    """
    per_label = {}
    for sim, potong in mentah.items():
        for label, isi in potong:
            try:
                per_label.setdefault(label, {})[sim] = json.loads(isi)
            except (ValueError, TypeError):
                return "", mentah                 # bukan JSON: biarkan apa adanya

    umum, buang = [], {}
    for label, per_sim in per_label.items():
        if len(per_sim) < 2:
            continue
        acuan = next(iter(per_sim.values()))
        if not isinstance(acuan, dict):
            continue
        for k, v in acuan.items():
            # Hanya yang panjang: mengangkat "generated_utc" tidak menghemat apa pun
            # dan justru mengaburkan bahwa tiap aset punya stempel waktunya sendiri.
            if len(str(v)) < 200 or not isinstance(v, str):
                continue
            if all(isinstance(d, dict) and d.get(k) == v for d in per_sim.values()):
                umum.append(f"[{label}] {k}: {v}")
                buang.setdefault(label, set()).add(k)
    if not umum:
        return "", mentah

    rapi = {}
    for sim, potong in mentah.items():
        baru = []
        for label, isi in potong:
            kunci = buang.get(label)
            if kunci:
                d = json.loads(isi)
                isi = json.dumps({k: v for k, v in d.items() if k not in kunci},
                                 ensure_ascii=False)
            baru.append((label, isi))
        rapi[sim] = baru
    kepala = ("### CARA MEMBACA (berlaku untuk SEMUA aset di bawah)" + chr(10)
              + chr(10).join(umum))
    return kepala, rapi


def data_verifikasi(teks_klaim):
    """Ambil data untuk aset yang DISEBUT di daftar klaim, supaya bisa diperiksa.

    KENAPA LEWAT KODE. Seed pemeriksa menyuruh memverifikasi dengan kategori.py,
    derivatif.py, dan coinalyze.py — tapi jalur chat memberi TOOLS_WEB tanpa shell,
    jadi model itu diminta melakukan sesuatu yang alatnya tidak ada. Terbukti di run
    produksi pertama.

    Memberi shell BUKAN jawabannya: itu menaruh model yang sedang membaca teks tidak
    dipercaya di lingkungan yang bisa menjalankan perintah — persis yang dihindari
    seluruh rancangan ini. Jadi kode yang mengambil datanya lebih dulu, dan model cuma
    membandingkan. Prinsip yang sama dengan seluruh bot ini.

    Yang diambil sengaja RINGKAS: harga & pasokan, funding & OI, likuidasi. Itu yang
    dipakai membantah klaim grup; analisa teknikal lengkap tidak diminta siapa pun.
    """
    aset = [a for a in sorted(_semua_aset(teks_klaim or "")) if a]
    # _semua_aset bersandar pada daftar 55 ticker. Koin yang sedang ramai di grup justru
    # sering yang BELUM masuk daftar itu — HYPE, ASTER, SKYAI semuanya lolos begitu saja.
    # Kandidat tambahan diambil dari kata BERHURUF BESAR (cara ticker ditulis di grup),
    # lalu diperiksa ke CoinGecko dengan batas keras supaya tidak menembak berkali-kali.
    if len(aset) < ASET_VERIFIKASI_MAKS:
        try:
            from indicators import resolve_ticker
            dicoba = 0
            for k in re.findall(r"\b[A-Z]{3,6}\b", teks_klaim or ""):
                if dicoba >= 4 or len(aset) >= ASET_VERIFIKASI_MAKS:
                    break
                if k in aset or k in _KATA_BUKAN_TICKER or k in _KATA_UMUM_BUKAN_KOIN:
                    continue
                dicoba += 1
                tik, _c, _n = resolve_ticker(k)
                if tik and tik not in aset:
                    aset.append(tik)
        except Exception as e:
            print(f"[verifikasi] pencarian aset dalam dilewati ({type(e).__name__})",
                  file=sys.stderr)
    if not aset:
        return None
    aset = aset[:ASET_VERIFIKASI_MAKS]
    mentah = {}
    for sim in aset:
        for label, args in (("pasar", ["cloud/kategori.py", "--koin", sim]),
                            ("derivatif", ["cloud/derivatif.py", sim, "--ringkas"]),
                            ("likuidasi", ["cloud/coinalyze.py", sim, "--ringkas"])):
            keluar, err = _jalankan_terukur(f"VERIFIKASI {sim} ({label})", args)
            if not err and keluar:
                mentah.setdefault(sim, []).append((label, keluar))
    if not mentah:
        return None
    bersama, mentah = _angkat_bagian_kembar(mentah)
    bagian = [f"### DATA {sim}" + chr(10)
              + chr(10).join(f"[{lab}] {isi}" for lab, isi in potong)
              for sim, potong in mentah.items()]
    if bersama:
        bagian.insert(0, bersama)
    kepala = ("[DATA UNTUK MEMERIKSA KLAIM]" + chr(10)
              + f"Aset yang disebut di daftar klaim: {chr(44).join(aset)}. Angka di bawah "
              + "diambil KODE, bukan dari grup. Pakai ini untuk memvonis tiap klaim. "
              + "Aset yang TIDAK ada datanya di sini berarti tidak bisa diperiksa — "
              + "katakan begitu, jangan menebak.")
    return kepala + chr(10) * 2 + (chr(10) * 2).join(bagian)


def data_telegram():
    """Baca hasil pembaca Telegram dari BERKAS. None kalau tidak ada.

    Lewat berkas, bukan dengan memanggil tgbaca.py dari sini. Itu bukan kerumitan yang
    sia-sia: memanggilnya di proses ini berarti TELEGRAM_SESSION harus ada di environment
    proses yang JUGA menjalankan model — dan seluruh gunanya pemisahan ini adalah supaya
    injeksi prompt dari isi grup tidak berada di ruangan yang sama dengan kredensial yang
    memberi akses penuh ke akun.
    """
    jalur = os.environ.get("BERKAS_TELEGRAM", "").strip()
    if not jalur or not os.path.exists(jalur):
        return None
    try:
        with open(jalur, encoding="utf-8", errors="replace") as f:
            isi = f.read().strip()
    except OSError as e:
        return ("[ISI GRUP TELEGRAM — TIDAK TERBACA]" + chr(10)
                + f"Berkasnya ada tapi gagal dibaca ({type(e).__name__}). Katakan apa "
                  "adanya; JANGAN mengarang isi grup.")
    return isi or None


# Kategori grup yang relevan dengan pertanyaannya. Dua grup forex dan satu grup lowongan
# di daftar user memang hanya berguna untuk pertanyaan tertentu — membacanya di tiap
# pertanyaan kripto cuma menghabiskan jatah pesan tanpa menambah apa pun.
_TG_FOREX = re.compile(r"forex|emas|gold|xau|dxy|dolar|usd|eur|jpy|gbp|komoditas", re.I)
_TG_KERJA = re.compile(r"lowongan|kerja|job|karier|karir|hiring|rekrut|freelance|"
                       r"vacanc|opening|career|recruit|intern", re.I)


def kategori_telegram(teks):
    """Kategori grup yang perlu dibaca untuk pertanyaan ini. Selalu memuat "crypto"."""
    low = (teks or "").lower()
    kat = ["crypto"]
    if _TG_FOREX.search(low):
        kat.append("forex")
    if _TG_KERJA.search(low):
        kat.append("kerja")
    return kat


# Pengecualian: pesan yang MENGOPERASIKAN Telegram, bukan meriset grupnya. Gerbang niat
# dilebarkan ke sisi Inggris (find/check/update/summarize), dan kata-kata itu juga muncul
# di kalimat soal pipa botnya sendiri — 'kirim update ke telegram', 'check telegram bot
# status', 'update webhook telegram'. Salah tangkap di sini mahal: ia membaca grup
# PRIBADI user tanpa diminta. Lebih baik sesekali harus mengulang perintah.
_TG_BUKAN_RISET = re.compile(
    r"webhook|bot ?token|\b(?:telegram|tele) bot\b|\bbot telegram\b|"
    # "notifikasi" polos terlalu lebar: "rangkum notifikasi penting di telegram"
    # adalah permintaan riset yang sah. Yang dikecualikan hanya konteks MENGATUR.
    r"telegram api|api telegram|"
    r"(?:set|atur|ubah|aktifkan|matikan|nyalakan)\s[^.]{0,24}(?:notif|notification)|"
    # "kirim ... KE telegram" adalah mengirim, bukan membaca. "DARI telegram" tetap riset.
    r"\b(?:ke|to|via)\s+(?:telegram|tele)\b", re.I)

# Nama grup yang DISEBUT user: "dari grup cokri", "grup lighter". Diekstrak di step
# pengintip yang tidak punya kredensial apa pun — yang tahu daftar grup sebenarnya cuma
# pembaca, jadi di sini hanya potongan namanya yang diambil, pencocokannya di sana.
_GRUP_SEBUT = re.compile(
    r"\b(?:grup|group|grub|channel|kanal)\s+"
    r"([A-Za-z0-9][\w .&'-]{0,30})", re.I)
# Kata yang mengikuti "grup" tapi BUKAN nama grup. "grup telegram saya" berarti seluruh
# grup, bukan grup bernama Telegram.
_BUKAN_NAMA_GRUP = {"telegram", "tele", "saya", "aku", "kamu", "ini", "itu",
                    "mana", "apa", "yang", "yg"}
# Ekor kalimat yang ikut tertangkap dan harus dipangkas.
_EKOR_GRUP = re.compile(
    r"\s+(?:saya|aku|kamu|ini|itu|dong|ya|yg|yang|gimana|gmn|apa|aja|saja|"
    r"tadi|kemarin|hari|minggu|bulan|terakhir|terbaru|sekarang|barusan|dan|atau)\b.*$",
    re.I)


# OBROLAN MURNI: sapaan, ucapan terima kasih, dan pertanyaan tentang jawaban SEBELUMNYA.
# Giliran seperti ini tidak pernah menyentuh server MCP, tapi tetap membayar
# pemasangannya (~45 detik diukur dari run produksi) dan tetap menunggu keempatnya siap.
#
# DAFTAR PUTIH, bukan tebakan. Ragu = BUKAN obrolan murni, jadi jalurnya yang sekarang
# yang dipakai. Salah menganggap sesuatu obrolan murni berarti mencabut alat yang
# mungkin dibutuhkan; salah ke arah sebaliknya cuma lebih lambat.
_OBROLAN_MURNI = re.compile(
    r"^(?:halo|hai|hi|hello|hallo|pagi|siang|sore|malam|assalam|p)\b|"
    r"\b(?:makasih|terima kasih|thanks|thank you|sip|mantap|oke|okay|siap|noted)\b|"
    r"\b(?:kamu bisa apa|bisa apa aja|kemampuanmu|help|bantuan)\b|"
    # Pertanyaan tentang jawaban sebelumnya — datanya sudah ada di riwayat.
    r"\b(?:maksudnya|maksud kamu|jelaskan lagi|jelasin lagi|ulangi|"
    r"kok beda|kenapa kamu bilang|tadi katanya|kurang paham|gak paham|"
    r"nggak paham|bingung|gimana maksudnya)\b", re.I)


def obrolan_murni(teks):
    """Giliran sosial/meta yang tidak butuh MCP maupun data baru.

    Dipakai untuk MELEWATI pemasangan server MCP di workflow dan menjalankan Claude
    tanpa --mcp-config. Sengaja sempit: yang tidak cocok tetap lewat jalur biasa.
    """
    low = (teks or "").strip().lower()
    if not low or not _OBROLAN_MURNI.search(low):
        return False
    # Pagar terakhir: menyebut aset atau kosakata pasar berarti BUKAN obrolan murni,
    # sekalipun kalimatnya diawali sapaan ("halo, btc gimana?").
    return not pesan_pasar(teks) and not _semua_aset(teks)


# Harga BTC dari grup hanya ditarik kalau memang ditanyakan. Bloknya cuma ~250
# karakter, tapi ia ikut di SETIAP permintaan Telegram kalau tidak digerbangi —
# dan sebagian besar permintaan tidak menanyakan harga sama sekali.
_MINTA_HARGA_BTC = re.compile(
    r"\b(?:harga|price|berapa|rate|kurs)\b[^.]{0,30}\b(?:btc|bitcoin)\b|"
    r"\b(?:btc|bitcoin)\b[^.]{0,30}\b(?:harga|price|berapa|sekarang|now|terbaru)\b", re.I)


def minta_harga_btc(teks):
    """Apakah user menanyakan harga BTC (jadi grup pemberi harga perlu dibaca)."""
    return bool(_MINTA_HARGA_BTC.search(teks or ""))


def grup_diminta(teks):
    """Nama grup yang disebut user, atau None kalau ia tidak menyebut satu pun.

    None berarti "baca sesuai kategori seperti biasa" — BUKAN "tidak ada grup". Bedanya
    menentukan: menganggapnya sebagai nama grup kosong akan membuat pembaca menyaring ke
    nol grup dan melaporkan tidak ada apa-apa.
    """
    m = _GRUP_SEBUT.search(teks or "")
    if not m:
        return None
    nama = _EKOR_GRUP.sub("", m.group(1)).strip(" .,?!:;-" + chr(39) + chr(34))
    if not nama or nama.lower() in _BUKAN_NAMA_GRUP:
        return None
    return nama


def minta_telegram(teks):
    """Apakah user meminta riset dari grup Telegram-nya sendiri."""
    low = (teks or "").lower()
    if _TG_BUKAN_RISET.search(low):
        return False
    return bool(_TG_TEMPAT.search(low) and _TG_NIAT.search(low))


# Rentang waktu yang DISEBUT user, mengalahkan penanda batas baca. "seminggu terakhir"
# berarti seminggu — termasuk yang sudah pernah dilaporkan — karena kalau penandanya tetap
# berlaku, jawabannya nyaris kosong dan permintaannya jadi tak berarti.
#
# Ditulis serangkai di bahasa Indonesia ("seminggu", "sebulan", "sehari"), jadi "se" harus
# ikut jadi kata bilangan dan spasinya opsional.
_ANGKA_KATA = {"se": 1, "satu": 1, "dua": 2, "tiga": 3, "empat": 4, "lima": 5, "enam": 6,
               "tujuh": 7, "delapan": 8, "sembilan": 9, "sepuluh": 10,
               "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
               "seven": 7, "eight": 8, "nine": 9, "ten": 10}
_SATUAN_JAM = {"jam": 1, "hari": 24, "minggu": 24 * 7, "pekan": 24 * 7, "bulan": 24 * 30,
               "hour": 1, "hours": 1, "day": 24, "days": 24, "week": 24 * 7,
               "weeks": 24 * 7, "month": 24 * 30, "months": 24 * 30}
_RENTANG_ANGKA = re.compile(
    r"(\d{1,3})\s*(jam|hari|minggu|pekan|bulan|hours?|days?|weeks?|months?)\b"
    r"|\b(se|satu|dua|tiga|empat|lima|enam|tujuh|delapan|sembilan|sepuluh|one|two|three|four|five|six|seven|eight|nine|ten)\s*"
    r"(jam|hari|minggu|pekan|bulan|hours?|days?|weeks?|months?)\b", re.I)
# Tanpa bilangan sama sekali. "bulan ini" dan "sebulan" sama-sama wajar diucapkan.
_RENTANG_FRASA = (
    (re.compile(r"\bhari ini\b|\bhari ni\b|\bbarusan\b|\btoday\b|\blast 24 ?h(?:ours?|rs?)?\b"), 24),
    (re.compile(r"\bkemarin\b|\byesterday\b"), 48),
    (re.compile(r"\bminggu ini\b|\bpekan ini\b|\b(?:this|last|past) week\b"), 24 * 7),
    (re.compile(r"\bbulan ini\b|\b(?:this|last|past) month\b"), 24 * 30),
)


def rentang_telegram(teks):
    """Jam ke belakang yang diminta user secara eksplisit, atau None kalau tidak disebut.

    None BUKAN nol: artinya "pakai penanda batas seperti biasa". Membedakan keduanya
    penting — mengembalikan 24 sebagai bawaan akan diam-diam mematikan seluruh mekanisme
    penanda dan mengembalikan duplikasi yang baru saja dihapus.
    """
    low = (teks or "").lower()
    m = _RENTANG_ANGKA.search(low)
    if m:
        angka = int(m.group(1)) if m.group(1) else _ANGKA_KATA[m.group(3).lower()]
        satuan = (m.group(2) or m.group(4)).lower()
        return max(1, angka * _SATUAN_JAM[satuan])
    for pola, jam in _RENTANG_FRASA:
        if pola.search(low):
            return jam
    return None


def mode_pantau(teks):
    """Pemantauan, bukan rekomendasi. False kalau ada niat transaksi atau harga konkret.

    Dua pengecualian itu menentukan: "update btc" adalah pemantauan, tapi "update btc,
    worth masuk di 75k?" adalah pertanyaan rencana yang kebetulan memakai kata update.
    Salah membacanya berarti menahan jawaban yang justru diminta.
    """
    low = (teks or "").lower()
    if _NIAT_TRANSAKSI.search(low) or _HARGA_KONKRET.search(low):
        return False
    return bool(_MINTA_PANTAU.search(low))


# Teks pesan asli, dititipkan supaya pengumpul data bisa tahu GAYA jawaban yang
# diminta tanpa menambah parameter ke seluruh rantai pemanggilan.
PESAN_ASLI = {}


def _sisipkan_pantau(bagian, teks):
    """Ganti gaya kesimpulan jadi PEMANTAUAN — kerangka angkanya tetap.

    Baris BIAS, Harga, Invalidasi, dan Target WAJIB bertahan apa adanya: rapor.py
    menariknya dari teks balasan untuk dinilai belakangan. Menghapusnya berarti jawaban
    jenis ini tidak pernah masuk jejak rekam, tidak pernah terbukti benar atau salah,
    dan seluruh ekspektansi yang dibangun di atasnya jadi buta terhadap separuh keluaran.
    """
    if not mode_pantau(teks):
        return
    bagian.insert(0, "[GAYA KESIMPULAN: PEMANTAUAN]" + chr(10) + (
        "Pertanyaannya MEMANTAU keadaan, bukan menimbang transaksi. Ganti blok "
        "kesimpulan dengan bentuk di bawah, dan JANGAN memakai kata perintah "
        "(MASUK SEKARANG / TUNGGU DULU / LEWATI / KELUAR) — user tidak sedang "
        "bertanya apa yang harus dilakukan." + chr(10) + chr(10) +
        "📌 PEMANTAUAN" + chr(10) +
        "Terpantau  : <apa yang BARU terjadi — struktur, momentum, arus dana. "
        "Sebut timeframe-nya eksplisit: close mingguan, reset stochastic, "
        "perubahan OI. Angka + tanggal.>" + chr(10) +
        "Artinya    : <apa yang itu TUNJUKKAN tentang keadaan pasar — bukan apa "
        "yang harus dilakukan.>" + chr(10) +
        "Skenario   : <kondisi ini bertahan sampai kapan, dan dengan syarat apa. "
        "Sebut horizonnya.>" + chr(10) +
        "Membatalkan: <level atau peristiwa yang membuat pembacaan ini gugur.>" +
        chr(10) + chr(10) +
        "Baris BIAS, Harga, Invalidasi, dan Target TETAP DITULIS seperti biasa — "
        "itu yang dipakai menilai panggilanmu belakangan, dan tanpa itu jawaban ini "
        "tidak pernah masuk jejak rekam. Yang berubah HANYA gaya kesimpulannya. "
        "Klaim seperti \"relatif undervalued\" atau \"dekat bottom\" hanya boleh "
        "ditulis kalau ada angka di brief yang mendukungnya — sebutkan angkanya di "
        "baris yang sama, jangan berdiri sendiri sebagai kesan."))


def _sisipkan_jejak(bagian):
    """Selipkan jejak rekam SENDIRI ke kepala brief, kalau ada yang perlu diperbaiki.

    Rapor selama ini jalan satu arah: panggilan dicatat, lalu tidak pernah dibaca lagi
    saat panggilan berikutnya disusun. Akibatnya cacat yang sama — level dengan risiko
    lebih besar daripada imbalannya — terulang di SELURUH panggilan tanpa pernah sampai
    ke matanya. Hanya muncul saat ada peringatan nyata, jadi biayanya nol di hari biasa.
    """
    try:
        sys.path.insert(0, os.path.join(REPO_ROOT, "cloud"))
        from rapor import catatan_untuk_brief
        t = catatan_untuk_brief()
        if t:
            bagian.insert(0, "[JEJAK REKAM SENDIRI (rapor.py)]" + chr(10) + t)
    except Exception as e:
        print(f"[jejak] dilewati ({type(e).__name__})", file=sys.stderr)


def data_mentah_crypto(coin):
    """Kumpulkan data koin dengan KODE, hanya yang RELEVAN untuk koin itu.

    Dijalankan paralel supaya penyaringan tidak mengorbankan kecepatan. Bagian yang
    kosong dibuang dari brief — model tidak perlu membaca blok 'tidak tersedia' yang
    panjang, dan tidak tergoda mengarang isinya.
    """
    # NAMA PROYEK -> TICKER, sebelum apa pun dijalankan. Tanpa ini "analisa hyperliquid"
    # meneruskan "HYPERLIQUID" ke seluruh script: harga tetap jalan karena CoinGecko
    # mengenali namanya, tapi sisanya rontok — DefiLlama membalas "Protokol untuk
    # HYPERLIQUID tidak ditemukan", kepemilikan gagal, berita gagal, dan balasannya jadi
    # daftar panjang "tidak tersedia". Dengan HYPE, protokolnya ketemu beserta TVL $6,2 M.
    catatan_nama = None
    cg_id = None
    try:
        from indicators import resolve_ticker
        tik, _cid, nama_resmi = resolve_ticker(coin)
        cg_id = _cid
        if tik and tik.upper() != coin.upper():
            catatan_nama = (f"Masukan '{coin}' adalah NAMA PROYEK; tickernya {tik} "
                            f"({nama_resmi}). Seluruh data di bawah diambil untuk {tik}. "
                            "Sebutkan penyesuaian ini sekali saat menjawab.")
            print(f"[data] nama proyek '{coin}' dinormalkan jadi ticker {tik}",
                  file=sys.stderr)
            coin = tik
    except Exception as e:
        print(f"[data] normalisasi ticker dilewati ({type(e).__name__})", file=sys.stderr)

    # MCAP diambil DULU, karena fundamentals.py memerlukannya untuk MC/TVL, P/S, dan P/F.
    # Selama ini tidak pernah dioper: DefiLlama sering mengembalikan mcap kosong (melekat
    # pada token induk), sehingga SEMUA rasio valuasi keluar "n/a" — dan fundamental itu
    # justru bagian yang menentukan. Satu panggilan CoinGecko gratis menutupnya.
    mcap = None
    try:
        sys.path.insert(0, os.path.join(REPO_ROOT, "cloud"))
        from kategori import data_koin
        pasar_koin = data_koin(cg_id or coin)
        mcap = pasar_koin.get("mcap_usd")
    except Exception as e:
        pasar_koin = {"tidak_tersedia": f"{type(e).__name__}"}

    t = coin.upper()
    tugas = [("TEKNIKAL (indicators.py)", ["cloud/indicators.py", coin, "--ringkas"], 2500),
             ("INGATAN (memori.py)", ["cloud/memori.py", "cari", coin], 0),
             ("UJI BALIK (backtest.py)", ["cloud/backtest.py", coin, "--ringkas"], 1200),
             ("SENTIMEN (sentiment.py)", ["cloud/sentiment.py", coin], 0)]
    lewat = []
    if t in _TANPA_PROTOKOL:
        lewat.append(f"fundamentals.py ({t} tidak punya protokol berpendapatan)")
    else:
        arg_f = ["cloud/fundamentals.py", coin]
        if mcap:
            arg_f += ["--mcap", f"{mcap:.0f}"]
        tugas.append(("FUNDAMENTAL PROTOKOL (fundamentals.py)", arg_f, 0))
    if t in _KOIN_NATIF:
        lewat.append(f"investors.py & whaleflow.py ({t} koin natif, bukan token kontrak)")
    else:
        tugas.append(("KEPEMILIKAN (investors.py)", ["cloud/investors.py", coin], 0))
    if t in _ONCHAIN_ADA:
        tugas.append(("ON-CHAIN (onchain.py)", ["cloud/onchain.py", coin], 0))
    else:
        lewat.append(f"onchain.py (CoinMetrics Community tidak mencakup {t})")
    # Sebaran historis + level struktural. Analisa penuh selalu memuat seed FORECASTER, dan
    # tahap sintesisnya berjalan TANPA tool — tanpa angka ini, seed itu memerintahkan
    # menjalankan script yang mustahil dijalankan, lalu targetnya dihitung di kepala.
    # Arus dana ETF spot — KATEGORI SINYAL BARU (institusional), bukan sekadar angka
    # tambahan. Hanya BTC dan ETH yang punya ETF spot AS; koin lain akan mengembalikan
    # penolakan yang sama tiap kali, jadi tidak perlu dijalankan sama sekali.
    if t in ("BTC", "ETH"):
        tugas.append(("ARUS DANA ETF SPOT (etf.py)", ["cloud/etf.py", coin, "--ringkas"], 0))
    else:
        lewat.append(f"etf.py ({t} tidak punya ETF spot AS)")
    tugas.append(("PROYEKSI (proyeksi.py)",
                  ["cloud/proyeksi.py", coin, "--hari", "60", "--ringkas"], 0))
    # Pemisah gerakan koin dari gerakan pasar. Tanpa ini "naik 18% sepekan" terdengar seperti
    # prestasi koinnya, padahal kalau BTC naik 24% di pekan yang sama koin itu TERTINGGAL —
    # dan kesimpulannya berbalik arah.
    tugas.append(("PASAR KESELURUHAN (pasarglobal.py)",
                  ["cloud/pasarglobal.py", "--koin", cg_id or coin], 0))
    # Funding & open interest lintas bursa. Prompt sudah lama menyuruh memakainya, tapi
    # tidak ada yang mengambilnya — hanya ada MCP CoinGlass yang bergantung pada model mau
    # memanggilnya. Bursa langsung (Binance/Bybit/OKX) tidak bisa dipakai: semuanya
    # memblokir datacenter AS, dan runner Actions ada di sana.
    tugas.append(("DERIVATIF (derivatif.py)",
                  ["cloud/derivatif.py", coin, "--ringkas"], 0))
    # Likuidasi, riwayat OI, dan rasio long/short — butuh COINALYZE_API_KEY. derivatif.py
    # tetap jalan tanpa kunci, jadi kalau kunci ini mati atau kena batas laju, funding & OI
    # saat ini masih ada. Dua sumber untuk satu keputusan itu disengaja.
    tugas.append(("LIKUIDASI & OI (coinalyze.py)",
                  ["cloud/coinalyze.py", coin, "--ringkas"], 0))
    # STUDI KEJUTAN CPI TIDAK ikut di jalur crypto. Riwayat harian gratis untuk koin cuma
    # ~1 tahun, jadi irisannya dengan 197 rilis CPI tinggal belasan kejadian dan
    # peringatan_cakupan SELALU menyala — bagian itu melaporkan dirinya sendiri terlalu
    # pendek untuk dibaca arahnya. Membayar 5 rb karakter tiap analisa untuk kesimpulan
    # "tidak bisa dibaca" adalah pemborosan yang sama persis dengan PPI, dan hasil nolnya
    # dicatat statis di seed. FOMC apalagi: seri SF Fed berakhir 2023-12 sementara candle
    # crypto mulai jauh sesudahnya, jadi irisannya praktis nol.
    lewat.append("kejutan.py (riwayat harga crypto terlalu pendek untuk studi rilis)")

    bagian, gagal = [], []
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        hasil = {pool.submit(_jalankan_terukur, l, a, mk): l for l, a, mk in tugas}
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
    # Data pasar koin ditaruh di brief apa adanya — mcap, FDV, volume, pasokan.
    bagian.insert(0, "[DATA PASAR KOIN (kategori.py, CoinGecko)]" + chr(10)
                  + json.dumps(pasar_koin, ensure_ascii=False, indent=1))
    if catatan_nama:
        # Penukaran nama HARUS terlihat. Menormalkan diam-diam berarti user bertanya soal
        # satu hal dan menerima jawaban soal hal lain tanpa pernah diberi tahu.
        bagian.insert(0, "[NAMA DINORMALKAN]" + chr(10) + catatan_nama)
    _sisipkan_jejak(bagian)
    _sisipkan_pantau(bagian, PESAN_ASLI.get("teks"))
    if lewat:
        bagian.append("[SENGAJA TIDAK DIAMBIL]\n" + "\n".join("- " + x for x in lewat)
                      + "\nPerlakukan sebagai tidak berlaku untuk koin ini, BUKAN sebagai "
                        "data yang hilang — jangan menyebutnya kekurangan.")
    bagian.append(_blok_kelengkapan(len(tugas), gagal, bagian))
    for g in gagal:
        print(f"[data] GAGAL {g}", file=sys.stderr)
    print(f"[data] crypto {t}: {len(tugas)} script dijalankan, {len(lewat)} dilewati, "
          f"{sum(len(x) for x in bagian)} karakter", file=sys.stderr)
    return "\n\n".join(bagian)


# Harga yang DIAJUKAN user, mis. "sampai $200", "ke 55k", "target 4.000".
_RE_TARGET = re.compile(
    r"(?:sampai|hingga|ke|target|tembus|menuju|mencapai|capai)\s*[:=]?\s*"
    r"[$]?\s*(\d[\d.,]*)\s*(k|rb|ribu)?\b", re.I)
_RE_TARGET_DOLAR = re.compile(r"[$]\s*(\d[\d.,]*)\s*(k|rb|ribu)?\b", re.I)

# Horizon proyeksi dari kata waktu di pesan. Default 60 hari perdagangan (~3 bulan):
# cukup panjang untuk target yang berarti, cukup pendek untuk masih bisa diperiksa.
_HORIZON_KATA = ((r"\b(?:tahun|setahun|jangka panjang|long term)\b", 250),
                 (r"\b(?:bulan|sebulan|kuartal)\b", 30),
                 (r"\b(?:minggu|pekan|mingguan)\b", 10),
                 (r"\b(?:besok|hari ini|harian|intraday)\b", 5))

# kejutan.py hanya punya nowcast Cleveland Fed untuk empat seri ini. NFP/FOMC TIDAK ada —
# jangan dipancing menjalankannya lalu mengarang, biarkan modelnya bilang tidak tersedia.
_INDIKATOR_KEJUTAN = ((r"\bcore\s*pce\b", "Core PCE"), (r"\bcore\s*cpi\b", "Core CPI"),
                      (r"\bpce\b", "PCE"), (r"\b(?:cpi|inflasi|inflation)\b", "CPI"))


def _ke_angka(teks, akhiran):
    """Ubah '4.000' / '55,5' / '200' jadi float. Ribuan vs desimal dibedakan dari posisinya."""
    t = (teks or "").strip()
    if "," in t and "." in t:
        t = (t.replace(".", "").replace(",", ".") if t.rfind(",") > t.rfind(".")
             else t.replace(",", ""))
    elif "," in t:
        ekor = t.split(",")[-1]
        t = t.replace(",", "") if len(ekor) == 3 else t.replace(",", ".")
    elif t.count(".") == 1 and len(t.split(".")[-1]) == 3 and not t.startswith("0."):
        t = t.replace(".", "")           # "4.000" = empat ribu, bukan empat koma nol
    try:
        n = float(t)
    except ValueError:
        return None
    return n * 1000 if akhiran else n


def target_dari_pesan(teks):
    """Harga yang diajukan user, kalau ada. Inilah yang diuji, bukan yang divalidasi."""
    for pola in (_RE_TARGET, _RE_TARGET_DOLAR):
        m = pola.search(teks or "")
        if m:
            n = _ke_angka(m.group(1), m.group(2))
            if n and n > 0:
                return n
    return None


def horizon_dari_pesan(teks):
    low = (teks or "").lower()
    for pola, hari in _HORIZON_KATA:
        if re.search(pola, low):
            return hari
    return 60


def data_proyeksi(teks, jenis, simbol):
    """Tambahan brief untuk pertanyaan proyeksi — dijalankan KODE, bukan diminta ke model.

    Mode ngobrol memakai TOOLS_WEB (tanpa shell) begitu brief tersedia, jadi seed FORECASTER
    tidak akan pernah bisa menjalankan proyeksi.py sendiri. Kalau angkanya tidak disiapkan di
    sini, model terpaksa menghitung target di kepala — persis sumber angka karangan.
    """
    hari = horizon_dari_pesan(teks)
    target = target_dari_pesan(teks)
    args = ["cloud/proyeksi.py", simbol, "--hari", str(hari), "--ringkas"]
    if jenis != "crypto":
        args.append("--pasar")
    if target:
        args += ["--target", f"{target:g}"]

    bagian = []
    keluar, err = _jalankan_terukur("PROYEKSI (proyeksi.py)", args)
    bagian.append(f"### PROYEKSI (proyeksi.py, horizon {hari} hari)\n"
                  + (keluar if not err else f"tidak tersedia: {err}"))

    # Reaksi historis terhadap rilis data — hanya untuk seri yang datanya memang ada.
    low = (teks or "").lower()
    for pola, ind in _INDIKATOR_KEJUTAN:
        if re.search(pola, low):
            k_args = ["cloud/kejutan.py", "--indikator", ind, "--simbol", simbol,
                      "--rezim", "--ringkas"]
            if jenis != "crypto":
                k_args.append("--pasar")
            keluar2, err2 = _jalankan_terukur(f"KEJUTAN {ind} (kejutan.py)", k_args)
            bagian.append(f"### REAKSI HISTORIS TERHADAP RILIS {ind} (kejutan.py)\n"
                          + (keluar2 if not err2 else f"tidak tersedia: {err2}"))
            break
    return "\n\n".join(bagian)


def jenis_banding(aset):
    """crypto kalau SEMUA aset crypto; selain itu lewat market.py (saham/forex/komoditas)."""
    kripto = set(_TICKER_UMUM) | set(_ALIAS_KOIN.values())
    return "crypto" if all(a in kripto for a in aset) else "pasar"


def data_banding(aset):
    """Brief PERBANDINGAN. Sebelumnya pertanyaan dua aset tidak dapat data sama sekali.

    aset_dari_pesan sengaja mengembalikan None saat lebih dari satu aset disebut, supaya
    brief tidak berisi aset PERTAMA saja lalu angka aset kedua tertandai "tidak terlacak"
    oleh audit. Akibatnya perbandingan dijawab tanpa satu angka pun dari kode — persis
    keadaan yang paling rawan karangan.

    banding.py menutup itu dengan mengukur semua aset lewat SATU jalur yang sama, dan
    keluarannya jauh lebih kecil daripada menempelkan dua brief penuh.
    """
    jenis = jenis_banding(aset)
    args = ["cloud/banding.py"] + list(aset) + ["--hari", "60", "--ringkas"]
    if jenis != "crypto":
        args.append("--pasar")
    keluar, err = _jalankan_terukur(f"BANDING {'+'.join(aset)} (banding.py)", args)
    return ("### PERBANDINGAN ANTAR-ASET (banding.py)\n"
            + (keluar if not err else f"tidak tersedia: {err}"))


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
        # HANYA CPI. FOMC dan NFP dibuang dari jalur saham setelah muatannya diukur: prompt
        # sintesis saham mencapai 110.911 karakter (~27.700 token), 2,5 kali angka yang jadi
        # acuan rencana hemat token. Untuk saham individual, tanggal earnings hampir selalu
        # mengalahkan kejutan makro — seed sudah menyatakan itu — jadi membayar ~10 rb
        # karakter tiap analisa untuk dua studi yang kalah dominan adalah pertukaran buruk.
        # Jalur FOREX tetap membawa ketiganya, karena di sana makro justru penggeraknya.
        # Keduanya masih bisa dijalankan manual: kejutan.py menerima ticker saham apa pun.
        tugas.append(("KEJUTAN CPI (kejutan.py, konsensus pasar)",
                      ["cloud/kejutan.py", "--indikator", "CPI", "--sumber", "sosovalue",
                       "--simbol", simbol, "--pasar", "--rezim", "--ringkas"]))
    else:
        tugas.append(("MAKRO AS (makro.py, sumber FRED)", ["cloud/makro.py", "--ringkas"]))
        # Reaksi historis emas/FX terhadap kejutan CPI — pelengkap kalender.py, yang hanya
        # memberi jadwal & konsensus tanpa memberitahu apa yang BIASANYA terjadi sesudahnya.
        tugas.append(("KEJUTAN CPI (kejutan.py, konsensus pasar)",
                      ["cloud/kejutan.py", "--indikator", "CPI", "--sumber", "sosovalue",
                       "--simbol", simbol, "--pasar", "--rezim", "--ringkas"]))
        # kalender.py (Forex Factory) TIDAK lagi ikut di brief. Konsensus untuk rilis
        # berikutnya kini datang dari baris ber-aktual-kosong di riwayat SoSoValue, dan
        # tanggal resminya dari jadwal.py — menjalankannya berarti membayar 4.028 karakter
        # untuk informasi yang sudah ada. Script-nya tetap dipakai secara terjadwal supaya
        # arsip konsensus independen kita terus tumbuh (lihat arsip.py).
        # Jadwal RESMI + angka aktual NFP/PPI. kalender.py memberi konsensus tapi feednya
        # tidak resmi dan pernah berpindah host; untuk aturan "jangan masuk menjelang
        # rilis", tanggalnya sebaiknya datang dari BLS dan The Fed sendiri.
        tugas.append(("JADWAL RESMI & AKTUAL NFP/PPI/FOMC (jadwal.py)",
                      ["cloud/jadwal.py", "--ringkas"]))
        # Sensitivitas harga terhadap kejutan kebijakan FOMC (SF Fed, Bauer-Swanson).
        # Dipakai varian ORTOGONAL: lebih konservatif karena sudah dibersihkan dari
        # informasi publik sebelum pengumuman. Varian kasar memberi efek lebih besar,
        # tapi sebagiannya cuma mencerminkan hal yang sudah diketahui pasar.
        tugas.append(("SENSITIVITAS KEJUTAN FOMC (kejutan.py)",
                      ["cloud/kejutan.py", "--indikator", "FOMC", "--simbol", simbol,
                       "--pasar", "--rezim", "--ortogonal", "--ringkas"]))
        tugas.append(("KEJUTAN NFP (kejutan.py, konsensus pasar)",
                      ["cloud/kejutan.py", "--indikator", "NFP", "--sumber", "sosovalue",
                       "--simbol", simbol, "--pasar", "--rezim", "--ringkas"]))
    # Berlaku untuk saham maupun forex: sebaran historis + level struktural, supaya seed
    # FORECASTER punya angka untuk dikutip pada tahap sintesis yang berjalan tanpa tool.
    tugas.append(("PROYEKSI (proyeksi.py)",
                  ["cloud/proyeksi.py", simbol, "--hari", "60", "--pasar", "--ringkas"]))

    # Dijalankan paralel seperti jalur crypto. Jalur saham kini punya enam bagian dan
    # berurutan memakan ~70 detik, yang memakan jatah tahap analisa. Pekerja dibatasi 2
    # karena stockfund.py dan konteks.py sama-sama menembak SEC.
    bagian, gagal = [], []
    kumpul = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        antre = {pool.submit(_jalankan_terukur, l, a): l for l, a in tugas}
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

    bagian.append(_blok_kelengkapan(len(tugas), gagal, bagian))
    _sisipkan_jejak(bagian)
    _sisipkan_pantau(bagian, PESAN_ASLI.get("teks"))

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
        "--allowedTools", tools,
        "--dangerously-skip-permissions",
        "--max-turns", str(max_turns),
    ]
    # --mcp-config HANYA kalau ada tool MCP yang benar-benar diizinkan. Sebelumnya selalu
    # dikirim, termasuk ke tahap SINTESIS yang tools-nya kosong — keempat server MCP
    # dinyalakan, ditunggu siap, lalu tidak dipakai sama sekali. Itu biaya start yang
    # dibayar di setiap analisa untuk nol manfaat.
    if "mcp__" in (tools or ""):
        cmd[3:3] = ["--mcp-config", MCP_CONFIG]
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
        mentah = (result.stderr or result.stdout or "")
        # Log dapat detail LENGKAP; user hanya ringkasannya. Dulu 1.500 karakter stderr
        # mentah dikirim apa adanya ke Telegram — selain tak terbaca, keluaran seperti itu
        # bisa memuat potongan token, path, atau isi konfigurasi. Repo ini publik dan
        # chat ID pun sengaja di-hash; mengirim stderr mentah membatalkan kehati-hatian itu.
        print(f"[claude] exit {result.returncode}:\n{mentah[-2000:]}", file=sys.stderr)
        return None, f"Claude gagal (exit {result.returncode}). Detailnya ada di log Actions."
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
        kesegaran_foto = audit_kesegaran(body)      # pada teks ASLI, lihat jalur utama
        if not body.startswith("❌"):
            body = pastikan_bertanggal(body)
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
    # Dititipkan SEKALI di sini, sebelum jalur mana pun bercabang, supaya pengumpul
    # data di kedua jalur melihat teks yang sama persis.
    PESAN_ASLI["teks"] = text

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
        # Normalisasi NAMA PROYEK -> TICKER dilakukan DI SINI, bukan di dalam
        # data_mentah_crypto. Di sana hasilnya cuma variabel lokal, sehingga brief benar
        # tapi rapor.jsonl tetap mencatat "HYPERLIQUID". Satu aset lalu terpecah dua di
        # rekam jejak — dan ekspektansi serta alpha dihitung dari kelompok yang salah.
        if simbol and jenis == "crypto":
            try:
                from indicators import resolve_ticker
                tik, _cid, _nama = resolve_ticker(simbol)
                if tik and tik.upper() != simbol.upper():
                    print(f"[routing] {simbol} -> {tik}", file=sys.stderr)
                    simbol = tik
            except Exception as e:
                print(f"[routing] normalisasi dilewati ({type(e).__name__})", file=sys.stderr)
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
        # Pencarian dalam DI SINI, bukan di pesan_pasar: di sana fungsinya dipanggil
        # untuk setiap pesan termasuk sapaan.
        jenis_chat, simbol_chat = aset_dari_pesan(text, dalam=True)
        # Dua aset atau lebih -> pertanyaan PERBANDINGAN. aset_dari_pesan sengaja menolak
        # memilih salah satu, jadi tanpa cabang ini brief-nya kosong sama sekali.
        aset_banding = sorted(_semua_aset(text)) if len(_semua_aset(text)) >= 2 else []
        if not simbol_chat and aset_banding:
            try:
                brief = data_banding(aset_banding)
                print(f"[proses] chat: perbandingan {'+'.join(aset_banding)} dikumpulkan "
                      f"kode ({len(brief)} karakter)", file=sys.stderr)
            except Exception as e:
                brief = None
                print(f"[proses] chat: perbandingan gagal ({type(e).__name__})",
                      file=sys.stderr)
        elif simbol_chat:
            try:
                brief = (data_mentah_crypto(simbol_chat) if jenis_chat == "crypto"
                         else data_mentah_pasar(simbol_chat, jenis_chat))
                # Pertanyaan proyeksi butuh angka yang tidak ada di brief biasa: sebaran
                # historis, ATR, dan — kalau user menyebut target — pengujian target itu.
                if _MINTA_PROYEKSI.search(text.lower()):
                    brief += "\n\n" + data_proyeksi(text, jenis_chat, simbol_chat)
                # Pertanyaan SEBAB butuh pemisahan berlapis: berapa bagian gerakan ini
                # milik seluruh pasar, berapa milik selera risiko yang lebih luas, dan
                # berapa yang benar-benar khas aset ini.
                if _MINTA_SEBAB.search(text):
                    brief += '\n\n' + data_sebab(jenis_chat, simbol_chat)
                print(f"[proses] chat: data {jenis_chat} {simbol_chat} dikumpulkan kode "
                      f"({len(brief)} karakter)", file=sys.stderr)
            except Exception as e:
                # Kegagalan di sini TIDAK boleh menggagalkan balasan — tanpa brief, model
                # kembali mencari sendiri persis seperti sebelum perubahan ini.
                brief = None
                print(f"[proses] chat: pengumpulan data gagal ({type(e).__name__}) — "
                      f"model mencari sendiri", file=sys.stderr)
        # RISET TELEGRAM BERDIRI SENDIRI. Sebelumnya blok ini berada di dalam
        # "elif simbol_chat", sehingga "carikan info dari telegram saya" — yang tidak
        # menyebut aset apa pun — tidak pernah membacanya. Fiturnya diam-diam tidak
        # melakukan apa-apa untuk bentuk pertanyaan yang paling wajar.
        if minta_telegram(text):
            tg = data_telegram()
            if tg:
                # Disaring model MURAH tanpa tool lebih dulu. Kalau gagal, mentahnya
                # tetap dipakai — bahan berlebih masih jauh lebih baik daripada tidak
                # ada bahan sama sekali.
                ringkas_tg = saring_telegram(tg)
                bahan = ringkas_tg or tg
                brief = (brief + chr(10) * 2 if brief else "") + bahan
                # Data untuk MEMERIKSA klaimnya, diambil kode. Tanpa ini pemeriksa
                # diminta memverifikasi tanpa alat apa pun — jalur chat tidak punya
                # shell, dan memberinya shell justru yang dihindari rancangan ini.
                verif = data_verifikasi(bahan)
                if verif:
                    brief += chr(10) * 2 + verif
                print(f"[proses] chat: bahan Telegram {len(bahan)} karakter"
                      f"{f' + data verifikasi {len(verif)} karakter' if verif else ''}",
                      file=sys.stderr)

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
        elif obrolan_murni(text):
            # Obrolan murni: tidak menyentuh MCP sama sekali. Tanpa --mcp-config, keempat
            # server tidak dinyalakan dan tidak ditunggu — dan workflow melewati
            # pemasangannya (~45 detik diukur dari run produksi).
            tools_chat = TOOLS_SOSIAL
            print("[proses] chat: obrolan murni — MCP dilewati", file=sys.stderr)
        else:
            # Sapaan & pertanyaan konseptual: tidak ada aset, tidak ada script yang perlu
            # dijalankan. Tanpa shell, halaman web yang dibaca tidak bisa berbuat apa-apa.
            tools_chat = TOOLS_WEB
        _nama_tool = {TOOLS_WEB: "WEB", TOOLS_LONGGAR: "LONGGAR",
                      TOOLS_SOSIAL: "SOSIAL (tanpa MCP)"}
        print(f"[proses] chat: tool = {_nama_tool.get(tools_chat, 'LAIN')}",
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
    # Kesegaran diperiksa pada teks ASLI — SEBELUM stempel waktu ditambahkan.
    # pastikan_bertanggal() menyisipkan tanggal buatan kita sendiri, dan kalau auditnya
    # berjalan sesudah itu, ia selalu melihat tanggal dan memvonis OK. Vonis BURUK
    # ("angka tanpa satu pun tanggal") jadi mustahil menyala — padahal justru itu yang
    # menandai jawaban dari ingatan. Terbukti: teks yang sama divonis BURUK sebelum
    # distempel dan OK sesudahnya.
    kesegaran = audit_kesegaran(body)
    if not body.startswith("❌"):
        body = pastikan_bertanggal(body)

    # Audit lain dijalankan SEBELUM pengiriman supaya vonisnya bisa ikut ke user.
    jejak = audit_angka(brief, body)
    asal = audit_sumber(brief)
    imbalan = audit_imbalan(body)
    outlook = audit_outlook(brief, body)
    keyakinan = audit_keyakinan(brief, body)
    if not body.startswith("❌"):
        catatan = peringatan_audit(jejak, asal, kesegaran, imbalan, outlook, keyakinan)
        if catatan:
            body = sisipkan_peringatan(body, catatan)
            print(f"[audit] peringatan DIKIRIM ke user: {catatan[:70]}", file=sys.stderr)
        # Kaki sumber disusun KODE dari brief, bukan diminta ke model: model tidak tahu
        # script mana yang benar-benar berhasil, dan atribusi yang keliru lebih buruk
        # daripada tidak ada atribusi.
        kaki = jejak_sumber(brief, simbol or simbol_chat, jenis or jenis_chat)
        if kaki:
            body = sisipkan_peringatan(body, kaki)
            print(f"[audit] kaki sumber DIKIRIM ke user ({len(kaki)} karakter)",
                  file=sys.stderr)

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


def audit_imbalan(body):
    """Hitung rasio imbalan:risiko dari level yang BARU SAJA ditulis. None kalau tak lengkap.

    analisa.md sudah lama mewajibkan R:R minimal 1:2, dan seluruh 10 panggilan pertama yang
    tercatat melanggarnya — median 0,33. Itu bukan alasan menambah kalimat baru ke prompt:
    aturannya sudah ada dan tetap dilewati. Sesuai prinsip proyek ini, yang bergantung pada
    KEPATUHAN model harus dipindah ke kode.

    Dihitung dari teks balasan, memakai pengurai yang sama dengan rapor.py, supaya angka
    yang diperiksa persis angka yang nanti dinilai.
    """
    try:
        sys.path.insert(0, os.path.join(REPO_ROOT, "cloud"))
        import rapor
        import statistik
        p = rapor.urai_panggilan(body or "")
        if not p:
            return None
        rr = statistik.imbalan_risiko(p.get("harga_saat_panggilan"),
                                      p.get("level_target"), p.get("level_invalid"))
        if not rr:
            return None
        # Vonisnya diputuskan DI SINI, bersama datanya. peringatan_audit tetap fungsi murni
        # yang hanya memilih kalimat, tanpa perlu mengimpor apa pun.
        rr["di_bawah_ambang"] = rr["rasio_imbalan_risiko"] < statistik.RASIO_MINIMUM
        rr["perlu_benar_persen"] = statistik.perlu_benar_persen(rr["rasio_imbalan_risiko"])
        return rr
    except Exception as e:
        print(f"[audit] imbalan dilewati ({type(e).__name__})", file=sys.stderr)
        return None


def audit_outlook(brief, body):
    """Apakah jawaban memuat OUTLOOK, padahal briefnya membawa data proyeksi?

    proyeksi.py jalan di SETIAP analisa dan menghasilkan sebaran p10-p90 ke depan. Sebelum
    ini format outputnya tidak pernah menyebutnya sama sekali, jadi data itu dikumpulkan,
    dibayar tokennya, lalu dibuang — dan kesimpulannya berhenti pada "Target $x" tanpa satu
    pun angka peluang.

    Blok yang dilewatkan tidak bisa dibedakan dari analisa yang memang tidak punya datanya,
    kecuali kalau keduanya diperiksa bersama. Return None kalau tidak ada yang perlu
    dikatakan; "HILANG" kalau datanya ada tapi bloknya tidak.
    """
    if not brief or not body:
        return None
    # Penandanya "proyeksi.py" saja, BUKAN judul lengkap: jalur analisa menulis
    # "PROYEKSI (proyeksi.py)" sedangkan jalur chat menulis
    # "PROYEKSI (proyeksi.py, horizon 60 hari)". Mencocokkan judul penuh berarti separuh
    # jalur tidak pernah terperiksa.
    if "proyeksi.py" not in brief:
        return None                      # tidak ada datanya, jadi tidak ada yang dilewatkan
    if "sebaran_historis" not in brief:
        return None                      # scriptnya jalan tapi gagal mengisi
    return None if "OUTLOOK" in body else "HILANG"


_RE_KELENGKAPAN = re.compile(r"(\d+) dari (\d+) sumber berisi data")

# Di bawah kelengkapan ini, skor tinggi tidak lagi punya dasar yang cukup.
KELENGKAPAN_TIPIS = 70
SKOR_TINGGI = 60


def audit_keyakinan(brief, body):
    """Apakah skornya tinggi padahal datanya tipis? Return dict, atau None.

    Diambil dari agency-agents (msitarzewski), aturan #6: keyakinan harus dinyatakan
    BESERTA mutu bukti di belakangnya. Enam dari delapan aturannya sudah ada di seed sini;
    yang ini belum, dan celahnya nyata — arsitektur SKOR punya bobot dan veto, tapi tidak
    satu pun yang mengaitkannya dengan berapa banyak data yang benar-benar tiba.
    """
    if not brief or not body:
        return None
    m = _RE_KELENGKAPAN.search(brief)
    if not m:
        return None
    berhasil, total = int(m.group(1)), int(m.group(2))
    if not total:
        return None
    persen = round(berhasil / total * 100)
    try:
        sys.path.insert(0, os.path.join(REPO_ROOT, "cloud"))
        import rapor
        p = rapor.urai_panggilan(body)
        skor = (p or {}).get("skor")
    except Exception:
        return None
    if skor is None or persen >= KELENGKAPAN_TIPIS or skor < SKOR_TINGGI:
        return None
    return {"skor": skor, "berhasil": berhasil, "total": total, "persen": persen}


def peringatan_audit(jejak, asal, kesegaran, imbalan=None, outlook=None,
                     keyakinan=None):
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

    # Didahulukan karena ini satu-satunya vonis tentang MUTU SARANNYA, bukan mutu datanya.
    # Data segar yang dipakai menyusun level dengan risiko sepuluh kali imbalannya tetap
    # menghasilkan saran yang merugikan, dan itu tidak akan pernah tertangkap audit lain.
    if imbalan and imbalan.get("di_bawah_ambang"):
        perlu = imbalan["perlu_benar_persen"]
        return (f"⚠️ Risikonya lebih besar daripada imbalannya: turun {imbalan['risiko_persen']}% "
                f"ke level invalidasi vs naik {imbalan['imbalan_persen']}% ke target pertama "
                f"(rasio {imbalan['rasio_imbalan_risiko']}). Setup ini harus benar ~{perlu}% kali "
                "hanya untuk impas.")

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
    # Sebelum vonis kelengkapan tapi sesudah vonis data: skor tinggi di atas data tipis
    # bukan sekadar kurang lengkap — ia menyatakan keyakinan yang tidak dimilikinya.
    if keyakinan:
        return (f"⚠️ Skor {keyakinan['skor']}/100 berdiri di atas {keyakinan['berhasil']} "
                f"dari {keyakinan['total']} sumber ({keyakinan['persen']}%). Perlakukan "
                "keyakinannya sebagai lebih rendah daripada angkanya.")

    # Paling akhir: ini soal KELENGKAPAN, bukan kebenaran. Analisa tanpa outlook tetap sahih,
    # hanya berhenti lebih awal daripada yang datanya izinkan.
    if outlook == "HILANG":
        return ("⚠️ Sebaran 60 hari ke depan sudah dihitung tapi tidak dipakai di jawaban ini — "
                "kesimpulannya berhenti pada level, tanpa peluang.")
    return None


# Modul -> (nama sumber yang dikenali orang, alamat halamannya). Hanya sumber yang punya
# HALAMAN PUBLIK yang masuk: sebagian data kita datang dari API tanpa halaman yang bisa
# dibuka, dan menaruh tautan ke endpoint JSON bukan atribusi, itu cuma terlihat seperti
# atribusi. Yang tidak punya halaman disebut namanya saja di baris hitungan.
_SUMBER_TAUT = (
    ("coinalyze.py", "Coinalyze", "https://coinalyze.net"),
    ("fundamentals.py", "DefiLlama", "https://defillama.com"),
    ("etf.py", "SoSoValue", "https://sosovalue.com"),
    ("stockfund.py", "SEC EDGAR", "https://www.sec.gov/edgar/search/"),
    ("investors.py", "SEC EDGAR", "https://www.sec.gov/edgar/search/"),
    ("makro.py", "FRED", "https://fred.stlouisfed.org"),
    ("kejutan.py", "Cleveland Fed", "https://www.clevelandfed.org/indicators-and-data/inflation-nowcasting"),
    ("sentiment.py", "Fear & Greed", "https://alternative.me/crypto/fear-and-greed-index/"),
)

_URL_RE = re.compile(r"https?://[^\s\"'<>,;)\]}]+")
_GAGAL_RE = re.compile(r"^GAGAL: (.+)$", re.M)

# Batas keras. Telegram memecah di 3.900 karakter, dan kaki jawaban yang lebih panjang
# daripada kesimpulannya sendiri berhenti dibaca.
_TAUT_MAKS = 7
_KAKI_MAKS = 600


def jejak_sumber(brief, simbol=None, jenis=None):
    """Daftar sumber untuk kaki jawaban, disusun KODE dari brief. None kalau tak ada.

    Disusun dari brief, bukan diminta ke model, karena dua alasan. Pertama, model tidak
    tahu script mana yang benar-benar berhasil — ia hanya melihat hasilnya. Kedua, daftar
    sumber yang ditulis model adalah daftar yang bisa keliru, dan atribusi yang keliru
    lebih buruk daripada tidak ada atribusi.

    Sumber yang GAGAL diambil sengaja dikeluarkan: mencantumkannya berarti mengaku memakai
    data yang tidak pernah tiba.
    """
    if not brief:
        return None
    gagal = " ".join(_GAGAL_RE.findall(brief))

    taut, terpakai = [], set()
    if "coingecko" in brief.lower() and "kategori.py" not in gagal:
        cg = (simbol or "").lower()
        taut.append(("CoinGecko", f"https://www.coingecko.com/en/coins/{cg}" if cg
                     else "https://www.coingecko.com"))
        terpakai.add("CoinGecko")
    for modul, nama, url in _SUMBER_TAUT:
        if modul in brief and modul not in gagal and nama not in terpakai:
            taut.append((nama, url))
            terpakai.add(nama)
    if jenis in ("saham", "forex") and simbol:
        taut.append(("Yahoo Finance", f"https://finance.yahoo.com/quote/{simbol}"))
        terpakai.add("Yahoo Finance")

    # Berita & rilis yang MEMANG dibaca — diambil dari brief, bukan dikarang. Satu per
    # domain supaya lima artikel dari satu situs tidak menenggelamkan sumber lainnya.
    berita, domain = [], set()
    for u in _URL_RE.findall(brief):
        d = u.split("/")[2].lower().removeprefix("www.")
        if d in domain or any(d in t[1] for t in taut):
            continue
        domain.add(d)
        berita.append(u.rstrip(".,"))

    if not taut and not berita:
        return None

    baris = [f"{n} {u}" for n, u in taut[:_TAUT_MAKS]]
    sisa = _TAUT_MAKS - len(baris)
    baris += berita[:max(0, sisa)]
    kaki = "🔗 Sumber: " + " · ".join(baris)
    if len(kaki) > _KAKI_MAKS:
        # Dipotong per BARIS UTUH, bukan per karakter: URL yang terpenggal di tengah
        # tetap terlihat seperti tautan tapi menuju ke mana-mana.
        pakai = []
        for b in baris:
            if len("🔗 Sumber: " + " · ".join(pakai + [b])) > _KAKI_MAKS:
                break
            pakai.append(b)
        kaki = "🔗 Sumber: " + " · ".join(pakai)
    total = len(taut) + len(berita)
    if total > len(baris):
        kaki += f" (+{total - len(baris)} lainnya)"
    return kaki


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
    # Bagian RENCANA & KESIMPULAN berisi level TURUNAN (zona entry, target, invalidasi)
    # yang memang dihitung dari Fibonacci/support — wajar tidak ada persis di brief.
    # Judulnya BERBEDA antar prompt: analisa.md menulis "RENCANA SPOT" sedangkan
    # analisa_pasar.md hanya "RENCANA". Pola lama hanya mengenali yang pertama, sehingga
    # pada analisa SAHAM & FOREX seluruh level turunan ikut dinilai dan balasan yang jujur
    # divonis MENCURIGAKAN 83% — lalu memicu peringatan palsu ke user.
    potong = re.split(r"🧭\s*RENCANA|✅\s*KESIMPULAN", balasan)
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
    # Dipakai step pengintip di workflow: menentukan apakah step pembaca Telegram perlu
    # jalan, SEBELUM step yang memegang session dimulai. Logikanya di sini, bukan di YAML,
    # supaya frasa pemicunya tidak terduplikasi di dua tempat lalu menyimpang diam-diam.
    if "--minta-telegram" in sys.argv[1:]:
        teks_tg = os.environ.get("TG_TEXT", "")
        if not minta_telegram(teks_tg):
            sys.exit(1)
        # Baris 1 kategori, baris 2 rentang jam (kosong = pakai penanda batas).
        # Dua baris, bukan satu baris berpemisah: step workflow membacanya dengan `sed -n`
        # dan baris kosong tetap terbaca sebagai "tidak disebut" tanpa perlu ditebak.
        print(",".join(kategori_telegram(teks_tg)))
        jam = rentang_telegram(teks_tg)
        print("" if jam is None else jam)
        # Baris 3: nama grup yang disebut user. Kosong = baca sesuai kategori.
        print(grup_diminta(teks_tg) or "")
        # Baris 4: "1" kalau harga BTC ditanyakan, kosong kalau tidak.
        print("1" if minta_harga_btc(teks_tg) else "")
        sys.exit(0)

    # Dipakai workflow untuk MELEWATI pemasangan server MCP pada giliran sosial/meta.
    # Berdiri sendiri supaya bisa dipanggil sebelum step pemasangan mana pun.
    if "--obrolan-murni" in sys.argv[1:]:
        sys.exit(0 if obrolan_murni(os.environ.get("TG_TEXT", "")) else 1)

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
    # Perintah pemeliharaan sekali jalan, sebelum alur normal.
    if "--bersihkan-id" in sys.argv:
        bersihkan_id()
        sys.exit(0)
    main()
