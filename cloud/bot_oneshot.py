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
FOTO_PROMPT = os.path.join(BASE_DIR, "prompts", "foto.md")
MCP_CONFIG = os.path.join(BASE_DIR, ".mcp.cloud.json")

ALLOWED_TOOLS = ",".join([
    "mcp__coinglass__*",
    "mcp__blockscout__*",
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
                   "harga", "chart", "grafik", "si", "untuk", "tentang", "soal", "the")

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
    kata = sisa.split()
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
        base = f.read()
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

    # GAGAL-AMAN diperketat: begitu pesan menyinggung kosakata pasar, SEMUA blok dimuat —
    # tidak peduli sudah ada blok lain yang cocok. Versi sebelumnya hanya memuat penuh bila
    # TIDAK ADA yang cocok, sehingga satu pemicu lemah bisa mematikannya: "menurutmu pasar
    # gimana" cuma memuat blok data-konten karena kata "menurutmu" kebetulan cocok, padahal
    # pertanyaannya soal pasar. Penghematan tetap besar karena datang dari pertanyaan
    # konseptual & sapaan — di situlah aturan domain memang tidak terpakai.
    if _PASAR_UMUM.search(low):
        dipakai = {nama for nama, _, _ in blok}

    def ganti(m):
        nama, _, isi = m.group(1), m.group(2), m.group(3)
        return (isi + "\n\n") if nama in dipakai else ""

    return _BLOK_RE.sub(ganti, teks_prompt)


def build_chat_prompt(text):
    with open(CHAT_PROMPT, encoding="utf-8") as f:
        base = rakit_chat(f.read(), text)
    # Pesan user dikutip apa adanya. Diberi pembatas jelas supaya isinya diperlakukan
    # sebagai pertanyaan untuk dijawab, bukan sebagai instruksi yang mengubah aturan.
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


def build_photo_prompt(caption, image_path):
    with open(FOTO_PROMPT, encoding="utf-8") as f:
        base = f.read()
    instruksi = (caption.strip() if caption and caption.strip()
                 else "(tidak ada caption — pakai default: identifikasi keterkaitan dengan "
                      "koin/project, cari info terkait, beri rekomendasi tindakan)")
    return (f"{header_waktu()}{base}\n---\n"
            f"## Gambar dari user\n"
            f"Gambar tersimpan di path: {image_path}\n"
            f"WAJIB baca dulu dengan tool Read (bisa melihat gambar), lalu kerjakan.\n\n"
            f"## Caption / pertanyaan user\n{instruksi}\n")


def build_gather_pasar(simbol, jenis):
    """TAHAP 1 untuk SAHAM & FOREX. Sengaja terpisah dari jalur crypto: DefiLlama, holder
    Ethereum, dan whale flow sama sekali tidak berlaku di sini, dan memanggilnya hanya
    menghasilkan error atau angka yang tidak nyambung."""
    if jenis == "forex":
        perintah = f"python cloud/market.py {simbol} --forex"
        khusus = (
            f"3. Kalau simbolnya XAUUSD/XAGUSD (emas/perak): WAJIB baca acuan makro dengan "
            f"Bash `cat cloud/data/gold_drivers.md` dan TEMPEL bagian yang relevan — daftar "
            f"data ekonomi penggerak, arah dampaknya, dan peringkat kekuatannya.\n"
            f"4. WebSearch: rilis data ekonomi AS TERBARU yang sudah keluar (CPI, NFP, Core PCE, "
            f"keputusan FOMC) beserta TANGGAL dan angkanya. Tempel apa adanya. Kalau ada rilis "
            f"besar yang akan datang, sebut tanggalnya.\n"
            f"5. JANGAN mengarang angka forecast/konsensus — kalau tidak ketemu, tulis "
            f"'konsensus tidak tersedia'.\n")
    else:
        perintah = f"python cloud/market.py {simbol}"
        khusus = (
            f"3. Bash: `python cloud/stockfund.py {simbol} --price <harga_dari_langkah_1>` → "
            f"revenue, laba bersih, EPS, margin, aset/liabilitas/ekuitas, arus kas, P/E, P/S, "
            f"kuartalan & tahunan BESERTA perubahan_persen tiap periode. Kalau sebuah "
            f"perubahan_persen bernilai null dengan catatan, TEMPEL catatannya juga — jangan "
            f"dihitung sendiri. Kalau emitennya tidak ada di SEC, tulis 'bukan emiten bursa AS'.\n"
            f"4. WebSearch: berita/katalis terbaru untuk {simbol} (earnings, panduan manajemen, "
            f"regulasi, produk) dengan TANGGAL + nama media.\n")

    return (
        f"{header_waktu()}"
        f"Kamu PETUGAS PENGUMPUL DATA (bukan analis) untuk {jenis.upper()} {simbol}. "
        f"JANGAN menganalisa atau menyimpulkan — jalankan tiap langkah dan TEMPEL hasilnya. "
        f"Sebut jelas yang gagal/kosong.\n\n"
        f"PENTING: ini BUKAN crypto. JANGAN menjalankan fundamentals.py, investors.py, "
        f"whaleflow.py, onchain.py, atau MCP coinmarketcap/coinglass/blockscout — semuanya "
        f"khusus crypto dan tidak berlaku di sini.\n\n"
        f"1. Bash: `{perintah}` → untuk TIAP timeframe (1w/1d/4h) tempel: close, SELURUH isi "
        f"ema (ema13/21/33/50/100/200, tulis n/a bila None), ema_stack.status, ema_signal, "
        f"bollinger, atr14, atr_pct, supertrend, pivot_standar, rsi14, stoch, fib, structure, "
        f"kondisi_pasar (status + keandalan_sinyal_ema), volume, source, quality, last_candle_utc. Tempel juga bagian 'profil' (bursa, mata "
        f"uang, harga terakhir) dan seluruh 'peringatan'.\n"
        f"2. Bash: `python cloud/memori.py cari {simbol}` → ingatan terverifikasi. Tempel apa "
        f"adanya; kalau kosong tulis 'belum ada ingatan'.\n"
        f"{khusus}"
        f"6. Bash: `python cloud/backtest.py {simbol} --ringkas --pasar" + (" --makro" if jenis == "forex" else "") + "` "
        f"→ uji balik sinyal terhadap riwayat aset INI SENDIRI + tolok ukur beli-dan-tahan. Untuk forex/komoditas ada uji makro: besar gerakan pada hari rilis terjadwal (NFP/CPI/Kamis Claims) dibanding hari biasa. Tempel apa adanya, TERMASUK peringatan sampel kecil.\n"
        f"\nWAJIB — STEMPEL WAKTU. Tempel generated_utc dan last_candle_utc apa adanya, plus "
        f"source & quality tiap timeframe. Di bagian [WAKTU DATA] tulis SATU baris berformat "
        f"PERSIS ini per timeframe (dibaca pemeriksa otomatis):\n"
        f"  <tf> source=<isi source> quality=<isi quality> last_candle_utc=<isi last_candle_utc>\n\n"
        f"OUTPUT: satu 'DATA BRIEF' berlabel per bagian ([WAKTU DATA], [INGATAN], [PROFIL], "
        f"[TEKNIKAL 1W/1D/4H], [FUNDAMENTAL] atau [MAKRO], [KATALIS], [TIDAK TERSEDIA]). "
        f"Angka apa adanya, tanpa interpretasi/skor/rekomendasi."
    )


def build_gather_prompt(coin):
    """Instruksi TAHAP 1 untuk model murah: kumpulkan data mentah, JANGAN analisa."""
    return (
        f"{header_waktu()}"
        f"Kamu PETUGAS PENGUMPUL DATA (bukan analis). Kumpulkan data mentah untuk koin "
        f"{coin} untuk analisa SPOT. JANGAN menganalisa, memberi skor, atau menyimpulkan — "
        f"cukup jalankan tiap langkah dan TEMPEL hasil angkanya. Sebut jelas yang gagal/kosong.\n\n"
        f"0. Bash: `python cloud/memori.py cari {coin}` → ingatan fakta yang PERNAH "
        f"diverifikasi (dengan vonis kesegaran). Tempel apa adanya ke bagian [INGATAN]; "
        f"kalau kosong tulis 'belum ada ingatan'. JANGAN menilai — tahap berikutnya yang menilai.\n"
        f"1. Bash: `python cloud/indicators.py {coin} --ringkas` → untuk TIAP timeframe (1w/1d/4h) tempel: "
        f"close, SELURUH isi ema (ema13/21/33/50/100/200 — tulis n/a bila None), ema_stack.status, "
        f"ema_signal, ema_cross_valid, bollinger (basis/atas/bawah/posisi/squeeze), atr14, atr_pct, "
        f"supertrend (arah+level), pivot_standar (P/R1/S1), kondisi_pasar (status + keandalan_sinyal_ema + sebaran_ema_persen), indikator_rentang bila ada, "
        f"rsi14, rsi_divergence, stoch k/d/signal/"
        f"cycle_bottom, fib zone + level penting, structure, volume ratio, source, quality.\n"
        f"2. MCP coinmarketcap `cryptoQuotesLatest` untuk {coin} → harga, market cap, FDV, FDV/MC, "
        f"volume 24h, perubahan 24h/7d/30d (WAJIB ketiganya — dipakai di output), circulating/total supply. Lalu `getCryptoMetadata` → "
        f"kategori + tautan repo GitHub (kalau ada).\n"
        f"3. Bash: `python cloud/fundamentals.py {coin} --mcap <market_cap_dari_langkah_2>` → revenue "
        f"30d/TTM, MoM/QoQ/YoY, TVL + perubahan_30d_persen & perubahan_90d_persen, MC/TVL, P/S, "
        f"P/F, volume DEX. Untuk kuartalan & bulanan TEMPEL juga perubahan_persen tiap "
        f"periode (sudah dihitung script). Kalau error, tulis "
        f"'bukan protokol DefiLlama'.\n"
        f"4. Bash: `python cloud/investors.py {coin}` → jumlah holder, top10%, "
        f"top10_non_bursa_kontrak%, 5 holder teratas (persen + kategori + label). Kalau error, "
        f"tulis 'bukan token Ethereum'.\n"
        f"4b. Bash: `python cloud/backtest.py {coin} --ringkas` → uji balik sinyal terhadap "
        f"riwayat koin INI SENDIRI: golden/death cross, RSI ekstrem, pullback EMA21 "
        f"— tiap sinyal dengan jumlah kejadian, menang_persen, return rata2, dan "
        f"nyeri_maks. Tempel juga tolok_ukur (beli_dan_tahan_persen & "
        f"hari_naik_persen). Kalau ada peringatan sampel kecil, TEMPEL juga.\n"
        f"5. Bash: `python cloud/whaleflow.py` → Whale Index (skor+label) + apakah {coin} masuk "
        f"top-token whale & arahnya (AKUMULASI/DISTRIBUSI/seimbang).\n"
        f"6. MCP coinglass (kalau tersedia) → funding rate, open interest, long/short {coin}. "
        f"Kalau gagal/no key, tulis 'derivatif tidak tersedia'.\n"
        f"7. MCP coinmarketcap `globalMetricsLatest` + `fearAndGreedLatest` → dominasi BTC, "
        f"Fear & Greed. Sebut juga harga BTC terkini.\n"
        f"8. WebSearch → 2-4 katalis/berita/unlock terbaru untuk {coin} (dengan tanggal). "
        f"Untuk institusi/whale sebut nama media + tanggal, bukan link markdown.\n\n"
        f"WAJIB — STEMPEL WAKTU. Tahap berikutnya TIDAK BISA memanggil tool, jadi kalau kamu "
        f"tidak membawa waktunya, angka itu jadi tak bertanggal dan menyesatkan. Karena itu:\n"
        f"- Tempel `generated_utc` dari SETIAP script yang kamu jalankan (indicators, "
        f"fundamentals, investors, whaleflow) apa adanya.\n"
        f"- Untuk indicators sebut juga `source` (bursa asal harga) dan `quality`.\n"
        f"- Tiap katalis/berita dari WebSearch WAJIB bertanggal + nama media. Yang tidak "
        f"jelas tanggalnya, TULIS 'tanggal tidak jelas' — jangan dikarang.\n"
        f"- Data fundamental sebut PERIODENYA (bulan/kuartal apa), bukan cuma '30d'.\n\n"
        f"Di bagian [WAKTU DATA], untuk TIAP timeframe tulis SATU baris berformat PERSIS "
        f"ini (dibaca pemeriksa otomatis — jangan ubah kata kuncinya):\n"
        f"  <tf> source=<isi source> quality=<isi quality> last_candle_utc=<isi last_candle_utc>\n"
        f"Contoh: 1d source=kraken quality=native last_candle_utc=2026-07-27 08:00\n\n"
        f"OUTPUT: satu 'DATA BRIEF' terstruktur berlabel per bagian ([WAKTU DATA], [INGATAN], "
        f"[PASAR], [HARGA/VALUASI], [TEKNIKAL 1W/1D/4H], [FUNDAMENTAL], [KEPEMILIKAN], "
        f"[DERIVATIF], [KATALIS], [TIDAK TERSEDIA]). Bagian [WAKTU DATA] berisi semua "
        f"generated_utc + source/quality. Angka apa adanya, tanpa interpretasi/skor/rekomendasi."
    )


def build_synth_pasar(simbol, jenis, brief):
    """TAHAP 2 untuk saham/forex. Memakai analisa_pasar.md — memakai analisa.md (crypto)
    di sini akan menuntut TVL/holder/whale yang tidak ada padanannya."""
    with open(PASAR_PROMPT, encoding="utf-8") as f:
        base = f.read()
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
        base = f.read()
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
            print(f"[audit] {audit_kesegaran(body)}", file=sys.stderr)
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
            brief, err = run_claude(build_gather_pasar(simbol, jenis), min(timeout, 600),
                                    max_turns=40, model=MODEL_GATHER, with_tools=True)
            if err or not brief:
                print(f"[proses] tahap-1 {label} GAGAL: {str(err)[:200]}", file=sys.stderr)
                output = None
            else:
                print(f"[proses] tahap-1 {label} OK, brief {len(brief)} karakter -> tahap-2",
                      file=sys.stderr)
                send_message(token, chat_id, "🧠 Tahap 2: analisa & susun laporan...")
                output, err = run_claude(build_synth_pasar(simbol, jenis, brief),
                                         min(timeout, 420), max_turns=12,
                                         model=MODEL_SYNTH, with_tools=False)
        elif simbol:
            coin = simbol
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

    body = pastikan_bertanggal(body)
    if send_message(token, chat_id, body):
        print(f"[proses] balasan {len(body)} karakter TERKIRIM ke Telegram", file=sys.stderr)
        print(f"[audit] {audit_kesegaran(body)}", file=sys.stderr)
        jejak = audit_angka(brief, body)
        if jejak:
            print(f"[audit] {jejak}", file=sys.stderr)
        asal = audit_sumber(brief)
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
