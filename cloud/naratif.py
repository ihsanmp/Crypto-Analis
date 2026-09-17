"""Kerangka skor naratif #Kalimasada — kriteria yang BISA diukur kode, dari sumber gratis.

Dari video "Bongkar Naratif Trading di Crypto 2026" (Kalimasada). Slide "Framework Scoring
Naratif" memberi tujuh kriteria berbobot, skor 1-5, lalu skor tertimbang:

    Kekuatan katalis        20%   Ada event atau deadline konkret di 2026?
    Tokenomics (float/FDV)  20%   Float sehat? Jadwal unlock terkendali?
    Ukuran pasar (TAM)      15%   Seberapa besar sektor ini bisa tumbuh?
    Kualitas tim & VC       15%   Didukung fund tier-1 yang kredibel?
    Likuiditas              10%   Cukup dalam untuk masuk dan keluar?
    Timing siklus           10%   Masih early atau sudah mainstream?
    Revenue & user nyata    10%   Ada substansi, atau hanya hype?

    > 3,5 layak dikejar · 2,5-3,5 watchlist · < 2,5 hindari

Transkripnya menyebut kriteria pertama "kekuatan naratif" dan tidak mengucapkan tiga bobot;
yang di atas diambil dari SLIDE-nya langsung, bukan dari pendengaran.

YANG DIUKUR KODE, DAN YANG TIDAK. Tiga kriteria punya data gratis yang bisa diperiksa:
tokenomics (CoinGecko: beredar vs maksimum, mcap vs FDV), likuiditas (volume vs kapitalisasi),
dan revenue (DefiLlama lewat fundamentals.py). Empat sisanya — katalis, TAM, tim & VC, timing —
TIDAK punya sumber gratis yang bisa dinilai kode, jadi dikembalikan sebagai "dinilai" beserta
datanya, bukan diberi angka karangan.

AMBANG 1-5 DI SINI MILIK ALAT INI, BUKAN DARI VIDEO. Mentornya hanya memberi pertanyaan kunci.
Ambangnya ditulis terbuka di bawah supaya bisa diperdebatkan, dan tidak boleh dikutip sebagai
"menurut mentor".

SUMBER — semuanya diuji tanpa bayar dan tanpa kunci (16 Sep 2026):
  CoinGecko coin, trending & tickers · DefiLlama fees/revenue · Santiment dev_activity ·
  GitHub + taksonomi Electric Capital (devkode.py) · Altcoin Season Index (musim.py) ·
  Wikipedia pageviews · Google News RSS.
Yang DITOLAK karena berbayar/berkunci meski dipakai di video: jadwal unlock DefiLlama (402),
Tokenomist, Token Terminal, CryptoRank, Kaito, Dune, dan social volume Santiment — paket
gratisnya menolak rentang terbaru, jadi tidak berguna untuk mindshare SEKARANG.

Pemakaian:
    python cloud/naratif.py HYPE
    python cloud/naratif.py TAO --json
"""

import argparse
import concurrent.futures
import json
import os
import re
import subprocess
import sys
import time
import urllib.parse
from datetime import datetime, timedelta, timezone
import cgkunci  # noqa: E402  kunci Demo CoinGecko, dikirim lewat header

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
UA = "riset-koin/1.0"
BATAS_RSS = 100

KRITERIA = (
    # (kunci, label, bobot, pertanyaan kunci dari slide)
    ("katalis", "Kekuatan katalis", 20, "Ada event atau deadline konkret di 2026?"),
    ("tokenomics", "Tokenomics", 20, "Float sehat? Jadwal unlock terkendali?"),
    ("tam", "Ukuran pasar", 15, "Seberapa besar sektor ini bisa tumbuh?"),
    ("tim_vc", "Tim & VC", 15, "Didukung fund tier-1 yang kredibel?"),
    ("likuiditas", "Likuiditas", 10, "Cukup dalam untuk masuk dan keluar?"),
    ("timing", "Timing siklus", 10, "Masih early atau sudah mainstream?"),
    ("revenue", "Revenue", 10, "Ada substansi, atau hanya hype?"),
)
BOBOT = {k: b for k, _, b, _ in KRITERIA}
AMBANG_LAYAK = 3.5
AMBANG_HINDARI = 2.5


def vonis(skor):
    if skor is None:
        return None
    if skor > AMBANG_LAYAK:
        return "LAYAK DIKEJAR"
    if skor >= AMBANG_HINDARI:
        return "WATCHLIST"
    return "HINDARI"


def skor_tertimbang(skor_per_kriteria):
    """Skor tertimbang dari 7 kriteria. None kalau ada yang kosong — skor sebagian yang
    dibaca sebagai skor akhir adalah salah baca yang paling mudah terjadi."""
    if any(skor_per_kriteria.get(k) is None for k in BOBOT):
        return None
    return round(sum(skor_per_kriteria[k] * b for k, b in BOBOT.items()) / 100, 2)


# --- Ambang milik alat ini (lihat docstring) --------------------------------------------
def skor_tokenomics(float_persen):
    """Float = beredar / maksimum. Float rendah = pasokan besar masih menunggu dilepas."""
    if float_persen is None:
        return None
    for batas, s in ((80, 5), (60, 4), (40, 3), (20, 2)):
        if float_persen >= batas:
            return s
    return 1


def skor_likuiditas(volume_usd, mcap_usd):
    if not volume_usd or not mcap_usd:
        return None
    if volume_usd < 1_000_000:
        return 1                         # masuk-keluar posisi berarti menggerakkan harga
    rasio = volume_usd / mcap_usd * 100
    for batas, s in ((10, 5), (5, 4), (2, 3), (1, 2)):
        if rasio >= batas:
            return s
    return 1


def skor_revenue(revenue_1thn_usd):
    if revenue_1thn_usd is None:
        return None
    for batas, s in ((100e6, 5), (10e6, 4), (1e6, 3)):
        if revenue_1thn_usd >= batas:
            return s
    return 2 if revenue_1thn_usd > 0 else 1


def tingkat_kapitalisasi(mcap_usd, peringkat):
    """Slide langkah 3: leader = mayoritas porsi, mid-cap = porsi kecil, long-tail = sangat
    kecil. Batasnya milik alat ini."""
    if not mcap_usd:
        return None
    if (peringkat and peringkat <= 50) or mcap_usd >= 5e9:
        return "leader (porsi mayoritas)"
    if mcap_usd >= 300e6:
        return "mid-cap (porsi kecil)"
    return "long-tail (porsi sangat kecil, exit ketat)"


# --- Pengambil data ---------------------------------------------------------------------
def _curl(url, timeout=35):
    try:
        p = subprocess.run(["curl", "-s", "-L", "--max-time", str(timeout), "-A", UA,
                            *cgkunci.argumen_curl(url), url],
                           capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout + 10)
        return p.stdout if p.returncode == 0 else ""
    except Exception:
        return ""


# CoinGecko paket gratis membalas 429 saat permintaan per menit terlampaui. Di GitHub
# Actions itu hampir pasti: saat naratif.py mulai, belasan skrip lain sudah menembak
# CoinGecko duluan. Diukur 17 Sep 2026, run 35177796577: naratif.py GAGAL dalam 3,7 detik
# di runner, sementara di laptop jalan normal dalam 14 detik. 429 bersifat sementara,
# jadi yang benar adalah menunggu lalu mencoba lagi — bukan membuang seluruh blok.
#
# Jedanya (15, 45) = 60 detik, SATU jendela kuota per menit penuh. Versi pertama memakai
# (8, 20) = 28 detik, dan di run 35178956460 ketiga percobaannya tetap ditolak: 28 detik
# belum melewati jendelanya. Dengan COINGECKO_DEMO_KEY (lihat cgkunci.py) 429 seharusnya
# jarang terjadi sama sekali; jeda ini lapisan cadangan untuk run tanpa kunci.
JEDA_ULANG_429 = (15, 45)


def _kena_batas(d):
    st = d.get("status") if isinstance(d, dict) else None
    return isinstance(st, dict) and st.get("error_code") == 429


def _json(url, jeda=JEDA_ULANG_429):
    """JSON dari url. {} kalau gagal. Permintaan ke CoinGecko diulang saat kena 429 atau
    balasan kosong; sumber lain tidak, karena kegagalan mereka bukan soal kuota."""
    ulang = jeda if "coingecko.com" in url else ()
    for i in range(len(ulang) + 1):
        teks = _curl(url)
        try:
            d = json.loads(teks) if teks else None
        except json.JSONDecodeError:
            d = None
        if d is not None and not _kena_batas(d):
            return d
        if i < len(ulang):
            time.sleep(ulang[i])
    return {}


def coingecko(cg_id):
    # tickers=true: bursa tier-1 dibaca dari balasan yang SAMA, bukan permintaan terpisah.
    # Di bawah kuota per menit, satu permintaan lebih sedikit itu berarti.
    d = _json(f"https://api.coingecko.com/api/v3/coins/{cg_id}?localization=false&tickers=true"
              f"&community_data=false&developer_data=false&sparkline=false")
    m = d.get("market_data") or {}
    if not m:
        return None
    usd = lambda k: (m.get(k) or {}).get("usd")
    return {"nama": d.get("name"), "peringkat": d.get("market_cap_rank"),
            "beredar": m.get("circulating_supply"), "maks": m.get("max_supply"),
            "total": m.get("total_supply"), "mcap": usd("market_cap"),
            "fdv": usd("fully_diluted_valuation"), "volume": usd("total_volume"),
            "harga": usd("current_price"), "ath": usd("ath"),
            "ubah_30h": m.get("price_change_percentage_30d"),
            "ubah_1thn": m.get("price_change_percentage_1y"),
            "kategori": d.get("categories") or [],
            "repo": (((d.get("links") or {}).get("repos_url") or {}).get("github") or [])[:3],
            "tickers": d.get("tickers") or []}


def trending_ids():
    """None kalau gagal diambil — BUKAN himpunan kosong. Kosong akan terbaca "tidak
    trending", padahal yang sebenarnya "tidak diketahui"."""
    d = _json("https://api.coingecko.com/api/v3/search/trending")
    koin = d.get("coins")
    if not isinstance(koin, list):
        return None
    return {c.get("item", {}).get("id") for c in koin}


def cari_cg_id(simbol):
    """id CoinGecko dari ticker, lewat _json yang tahan 429. indicators.resolve_cg_id
    menelan 429 sebagai "tidak dikenali" — alasan palsu yang membuat koin besar seperti
    TAO terdengar tidak ada."""
    d = _json("https://api.coingecko.com/api/v3/search?query=" + urllib.parse.quote(simbol))
    koin = d.get("coins") or []
    for c in koin:
        if (c.get("symbol") or "").upper() == simbol.upper():
            return c.get("id")
    return koin[0].get("id") if koin else None


def dev_activity(slug):
    """Santiment dev_activity, mingguan. Paket gratis memberi data terkini untuk metrik ini
    (diuji 16 Sep 2026) — tidak seperti social volume, yang rentang terbarunya ditolak."""
    akhir = datetime.now(timezone.utc)
    awal = akhir - timedelta(days=120)
    q = ('{getMetric(metric:"dev_activity"){timeseriesData(slug:"%s",from:"%s",to:"%s",'
         'interval:"7d"){datetime value}}}' % (slug, awal.strftime("%Y-%m-%dT00:00:00Z"),
                                                akhir.strftime("%Y-%m-%dT00:00:00Z")))
    d = _json("https://api.santiment.net/graphql?query=" + urllib.parse.quote(q))
    try:
        ts = [x["value"] for x in d["data"]["getMetric"]["timeseriesData"]]
    except (KeyError, TypeError):
        return None
    if len(ts) < 8:
        return None
    baru, lama = sum(ts[-4:]) / 4, sum(ts[-16:-4]) / max(len(ts[-16:-4]), 1)
    tren = None
    if lama > 0:
        r = baru / lama
        tren = "melemah" if r < 0.7 else ("menguat" if r > 1.3 else "stabil")
    return {"rata_4_minggu": round(baru, 1), "rata_12_minggu_sebelumnya": round(lama, 1),
            "tren": tren}


def bandingkan_santiment(santiment, github):
    """Santiment turun jadi SEKUNDER saat GitHub langsung tersedia, dan DITANDAI bertentangan
    saat ia melaporkan nol sementara GitHub mencatat commit.

    Bukan dugaan. 16 Sep 2026 untuk TAO: Santiment nol, GitHub langsung ~70 commit/minggu di
    RaoFoundation/subtensor — Santiment melacak repo opentensor yang sudah ditinggalkan. Lalu
    di run 35185856360 model tetap mengutip "skor dev Santiment turun 32 -> 0" sebagai PENGUAT
    kesimpulan developer melemah. Instruksi prompt saja tidak mencegahnya; tandanya harus ada
    di datanya.
    """
    if not santiment:
        return santiment
    hasil = dict(santiment)
    if not github:
        return hasil
    hasil["peran"] = "sekunder — GitHub langsung tersedia; kalau berbeda, pakai GitHub"
    commit_gh = github.get("commit_per_minggu_4_minggu") or 0
    if (santiment.get("rata_4_minggu") or 0) == 0 and commit_gh > 0:
        hasil["bertentangan_dengan_github"] = True
        hasil["catatan"] = (f"Santiment melaporkan NOL, padahal GitHub langsung mencatat "
                            f"{commit_gh} commit/minggu. Santiment kemungkinan melacak repo yang "
                            "sudah ditinggalkan. JANGAN dikutip sebagai bukti apa pun.")
    elif santiment.get("tren") and github.get("tren") and santiment["tren"] != github["tren"]:
        hasil["catatan"] = (f"Tren Santiment ({santiment['tren']}) berbeda dari GitHub langsung "
                            f"({github['tren']}). Pakai GitHub.")
    return hasil


def status_invalidasi_developer(github):
    """Status aturan invalidasi ke-3 ("developer pergi"), DIHITUNG KODE dari tren GitHub.

    Kenapa statusnya dihitung di sini, bukan dinilai model: run 35186837828 menulis
    "developer masih aktif (78,8 commit/minggu), jadi invalidasi 'developer pergi' belum
    kena" — tanpa menyebut bahwa trennya melemah 48% (151 -> 79/minggu), dan justru di
    bagian bukti kontra. Bunyi aturan mentor adalah "aktivitas melemah". Model yang
    menilainya sendiri menyajikan satu bukti kontra nyata sebagai kabar baik.

    "TANDA AWAL", bukan "invalidasi terpicu": ambang turunnya milik alat ini, bukan dari
    mentor, jadi statusnya tidak boleh terdengar seperti vonis.
    """
    if not github or not github.get("tren"):
        return None
    baru = github.get("commit_per_minggu_4_minggu")
    lama = github.get("commit_per_minggu_12_minggu_sebelumnya")
    ubah = round((baru / lama - 1) * 100) if lama and baru is not None else None
    try:
        import devkode
        batas_turun = round((1 - devkode.AMBANG_MELEMAH) * 100)
    except Exception:
        batas_turun = 30
    tren = github["tren"]
    return {
        "status": ("TANDA AWAL — aktivitas melemah" if tren == "melemah"
                   else f"tidak ada tanda — aktivitas {tren}"),
        "commit_per_minggu": f"{lama} -> {baru}",
        "perubahan_persen": ubah,
        "aturan": "Invalidasi ke-3 kerangka mentor: developer pergi — aktivitas melemah.",
        "ambang": (f"'melemah' = turun lebih dari {batas_turun}% (rata-rata 4 minggu terakhir "
                   f"vs 12 minggu sebelumnya). Ambang ini milik alat ini, BUKAN dari mentor."),
        "wajib": ("Sebut status, angka commit, dan persen perubahannya. Saat statusnya TANDA "
                  "AWAL, itu bukti kontra: jangan menulis invalidasi 'belum kena' dan jangan "
                  "menyajikannya sebagai kabar baik."),
    }


def pageviews(judul):
    """Wikipedia pageviews — pengganti Google Trends yang menolak akses dari server (429)."""
    akhir = datetime.now(timezone.utc) - timedelta(days=1)
    awal = akhir - timedelta(days=90)
    url = ("https://wikimedia.org/api/rest_v1/metrics/pageviews/per-article/en.wikipedia/"
           f"all-access/user/{urllib.parse.quote(judul.replace(' ', '_'))}/daily/"
           f"{awal:%Y%m%d}/{akhir:%Y%m%d}")
    d = _json(url)
    v = [x.get("views", 0) for x in d.get("items", [])]
    if len(v) < 30:
        return None
    rata7, rata90 = sum(v[-7:]) / 7, sum(v) / len(v)
    return {"rata_7_hari": round(rata7), "rata_90_hari": round(rata90),
            "rasio_7h_vs_90h": round(rata7 / rata90, 2) if rata90 else None}


def berita_7_hari(nama):
    teks = _curl("https://news.google.com/rss/search?q=" + urllib.parse.quote(f'"{nama}" when:7d')
                 + "&hl=en-US&gl=US&ceid=US:en")
    if not teks:
        return None
    n = len(re.findall(r"<item>", teks))
    # RSS Google News berhenti di 100 butir. 100 berarti "setidaknya 100", bukan 100 —
    # koin besar selalu mentok di sini, jadi angka ini hanya membedakan yang sepi.
    return f">={n} (batas RSS)" if n >= BATAS_RSS else n


# Daftar bursa "tier-1" INI MILIK ALAT INI, bukan dari video. Videonya menyebut "listing
# tier-1" sebagai salah satu sinyal fase distribusi tanpa pernah menyebut bursa mana saja.
# Yang di bawah dipilih dari bursa dengan trust score tertinggi CoinGecko plus bursa berizin
# di pasar besar (Korea, Jepang, AS, Eropa). Nama pengenalnya ikut CoinGecko.
TIER1 = {"binance": "Binance", "gdax": "Coinbase", "coinbase_international": "Coinbase Intl",
         "upbit": "Upbit", "bithumb": "Bithumb", "okex": "OKX", "bybit_spot": "Bybit",
         "kraken": "Kraken", "kucoin": "KuCoin", "bitget": "Bitget", "gate": "Gate",
         "htx": "HTX", "huobi": "HTX", "crypto_com": "Crypto.com", "bitstamp": "Bitstamp",
         "bitflyer": "bitFlyer", "gemini": "Gemini"}


def bursa_tier1(cg_id):
    """Bursa tier-1 tempat koin ini diperdagangkan, dan porsi volumenya.

    BATASNYA HARUS IKUT DIBACA: yang terukur di sini KEBERADAAN listing, bukan KAPAN
    listingnya. Sinyal distribusi di video adalah listing tier-1 yang BARU terjadi
    ("akhirnya masuk Binance" di puncak hype), dan tanggal listing tidak ada di API gratis
    mana pun yang diuji. Jadi koin lama yang sudah bertahun-tahun di Binance akan terlihat
    sama dengan koin yang baru listing kemarin.
    """
    d = _json(f"https://api.coingecko.com/api/v3/coins/{cg_id}/tickers?depth=false")
    return ringkas_tickers((d or {}).get("tickers"))


def ringkas_tickers(tik):
    """Bagian hitungnya dipisah dari pengambilannya supaya bisa diuji tanpa jaringan."""
    if not tik:
        return None
    total = 0.0
    per_bursa = {}
    for t in tik:
        v = (t.get("converted_volume") or {}).get("usd") or 0
        if t.get("is_anomaly") or t.get("is_stale"):
            continue
        ident = (t.get("market") or {}).get("identifier")
        total += v
        if ident in TIER1:
            per_bursa[TIER1[ident]] = per_bursa.get(TIER1[ident], 0) + v
    if not total:
        return None
    vol_t1 = sum(per_bursa.values())
    return {"bursa_tier1": sorted(per_bursa, key=lambda k: -per_bursa[k]),
            "n_bursa_tier1": len(per_bursa),
            "porsi_volume_tier1_persen": round(vol_t1 / total * 100, 1),
            "n_pasar_terbaca": len(tik),
            "catatan": "TANGGAL listing tidak tersedia di sumber gratis — yang terukur hanya "
                       "ADA/TIDAKNYA listing, bukan listing BARU yang jadi sinyal distribusi"}


def data_musim():
    if BASE_DIR not in sys.path:
        sys.path.insert(0, BASE_DIR)
    try:
        import musim
        return musim.musim()
    except Exception:
        return None


def data_devkode(simbol, nama, repo):
    if BASE_DIR not in sys.path:
        sys.path.insert(0, BASE_DIR)
    try:
        import devkode
        return devkode.analisa(simbol, nama=nama, repo_coingecko=repo)
    except Exception:
        return None


def revenue_1thn(simbol):
    if BASE_DIR not in sys.path:
        sys.path.insert(0, BASE_DIR)
    try:
        import fundamentals as fd
        # Keduanya mengembalikan PASANGAN (data, slug). Versi pertama memperlakukannya sebagai
        # nilai tunggal: tuple selalu truthy, slug-nya jadi sampah, dan galatnya tertelan
        # except di bawah — revenue HYPE diam-diam kosong padahal fundamentals.py menemukannya.
        _info, kandidat = fd.resolve_protocol(simbol)
        if not kandidat:
            return None
        d, _slug = fd.ambil_fees(kandidat, "dailyRevenue")
        if not d:
            return None
        chart = d.get("totalDataChart") or []
        batas = (datetime.now(timezone.utc) - timedelta(days=365)).timestamp()
        return float(sum(v for t, v in chart if t >= batas))
    except Exception:
        return None


# --- Rakitan ------------------------------------------------------------------------------
def hasil_tanpa_coingecko(simbol, alasan, rev=None, musim_alt=None):
    """CoinGecko gagal BUKAN berarti semuanya gagal.

    Versi sebelumnya langsung berhenti, jadi revenue DefiLlama dan musim altcoin — yang
    sama sekali tidak butuh CoinGecko — ikut terbuang, dan model menerima blok kosong.
    Yang tidak bisa diukur tanpa CoinGecko disebut terang-terangan, bukan diberi angka.
    """
    return {
        "koin": simbol, "tidak_tersedia": alasan,
        "catatan": ("Tokenomics, likuiditas, listing tier-1, timing, dan aktivitas developer "
                    "butuh data CoinGecko dan TIDAK terukur di run ini. Jangan menaksirnya "
                    "lalu menyebutnya hasil ukur kode."),
        "kriteria": {"revenue": {"skor": skor_revenue(rev), "bobot": BOBOT["revenue"],
                                 "data": {"revenue_1thn_usd": round(rev) if rev is not None else None}}},
        "sinyal_distribusi": {"musim_altcoin": musim_alt},
        "wajib_dibaca": WAJIB_DIBACA,
    }


def analisa(simbol, cg_id=None):
    """`cg_id` boleh diisi pemanggil yang sudah menemukannya (bot_oneshot.py menemukannya
    saat mengumpulkan data koin). Itu menghemat satu permintaan CoinGecko — dan justru
    permintaan pencarian inilah yang paling dulu kena batas."""
    simbol = simbol.upper()
    with concurrent.futures.ThreadPoolExecutor(max_workers=7) as ex:
        # Yang tidak butuh CoinGecko dimulai DULUAN, supaya tetap ada walau CoinGecko gagal.
        f_rev = ex.submit(revenue_1thn, simbol)
        f_ms = ex.submit(data_musim)
        cg_id = cg_id or cari_cg_id(simbol)
        if not cg_id:
            return hasil_tanpa_coingecko(
                simbol, "id CoinGecko tidak bisa diambil — koin tidak dikenali, ATAU "
                        "CoinGecko menolak karena batas permintaan", f_rev.result(), f_ms.result())
        f_tr = ex.submit(trending_ids)
        f_dev = ex.submit(dev_activity, cg_id)
        cg = coingecko(cg_id)
        if not cg:
            return hasil_tanpa_coingecko(
                simbol, "data koin CoinGecko gagal diambil (kemungkinan batas permintaan)",
                f_rev.result(), f_ms.result())
        f_pv = ex.submit(pageviews, cg["nama"] or simbol)
        f_nw = ex.submit(berita_7_hari, cg["nama"] or simbol)
        f_br = ex.submit(ringkas_tickers, cg.get("tickers"))
        f_dk = ex.submit(data_devkode, simbol, cg["nama"], cg.get("repo"))
        trending, dev, rev, pv, berita = (f_tr.result(), f_dev.result(), f_rev.result(),
                                          f_pv.result(), f_nw.result())
        musim_alt, bursa, devkode_hasil = f_ms.result(), f_br.result(), f_dk.result()

    float_p = (cg["beredar"] / cg["maks"] * 100) if cg["beredar"] and cg["maks"] else None
    mcap_fdv = (cg["mcap"] / cg["fdv"] * 100) if cg["mcap"] and cg["fdv"] else None
    if float_p is None and mcap_fdv is not None:
        float_p = mcap_fdv                      # tanpa pasokan maksimum, mcap/FDV setara
    kr = {
        "tokenomics": {"skor": skor_tokenomics(float_p),
                       "data": {"float_persen": round(float_p, 1) if float_p else None,
                                "mcap_per_fdv_persen": round(mcap_fdv, 1) if mcap_fdv else None},
                       "catatan": "JADWAL UNLOCK tidak punya API gratis — periksa di web "
                                  "(tokenomist.ai / defillama.com/unlocks) sebelum masuk. "
                                  "Aturan video: unlock > 5% supply beredar = tekanan jual."},
        "likuiditas": {"skor": skor_likuiditas(cg["volume"], cg["mcap"]),
                       "data": {"volume_24j_usd": cg["volume"], "mcap_usd": cg["mcap"]}},
        "revenue": {"skor": skor_revenue(rev),
                    "data": {"revenue_1thn_usd": round(rev) if rev is not None else None},
                    "catatan": None if rev is not None else
                    "tidak ada protokol DefiLlama yang cocok — bisa berarti tidak ada revenue, "
                    "bisa berarti resolusi nama meleset. Jangan langsung menyimpulkan nol."},
        "katalis": {"skor": None, "dinilai": True,
                    "data": {"berita_7_hari": berita},
                    "sumber_disarankan": "GENIUS Act, CLARITY Act, persetujuan ETF, kebijakan "
                                         "Fed, jadwal peluncuran/mainnet proyek"},
        "tam": {"skor": None, "dinilai": True, "data": {"kategori_coingecko": cg["kategori"][:5]},
                "sumber_disarankan": "python cloud/kategori.py --cari <sektor> (kapitalisasi "
                                     "sektor, gratis)"},
        # Data developer SENGAJA tidak ditaruh di sini. Versi sebelumnya menaruhnya di
        # tim_vc.data, dan model di run 35185856360 menilai "Tim & VC: 2" hanya dari commit
        # yang melemah — padahal pertanyaan kriteria ini di slide adalah soal PENDUKUNG.
        "tim_vc": {"skor": None, "dinilai": True,
                   "catatan": "Kriteria ini tentang PENDUKUNG: didukung fund tier-1 yang kredibel? "
                              "(slide video). Aktivitas developer BUKAN dasarnya — itu ada di "
                              "developer_github dan dipakai untuk aturan invalidasi ke-3.",
                   "sumber_disarankan": "cryptorank.io & chainbroker.io (web gratis, API "
                                        "berkunci) untuk daftar VC-nya."},
        "timing": {"skor": None, "dinilai": True,
                   "data": {"jarak_dari_ath_persen": round((1 - cg["harga"] / cg["ath"]) * 100, 1)
                            if cg["harga"] and cg["ath"] else None,
                            "ubah_30_hari_persen": round(cg["ubah_30h"], 1) if cg["ubah_30h"] is not None else None,
                            "ubah_1_tahun_persen": round(cg["ubah_1thn"], 1) if cg["ubah_1thn"] is not None else None,
                            "trending_coingecko": (cg_id in trending) if trending is not None else None,
                            "wikipedia_pageviews": pv,
                            "musim_altcoin": musim_alt},
                   "catatan": "Timing tidak diberi angka kode: tidak ada pemetaan teruji dari "
                              "data ini ke 'early' vs 'mainstream'. Baca bersama siklus hidup "
                              "naratif di bawah."},
    }
    for k, v in kr.items():
        v["bobot"] = BOBOT[k]
    terukur = {k: v["skor"] for k, v in kr.items() if v.get("skor") is not None}
    bobot_terukur = sum(BOBOT[k] for k in terukur)
    skor_sebagian = (round(sum(s * BOBOT[k] for k, s in terukur.items()) / bobot_terukur, 2)
                     if bobot_terukur else None)
    return {
        "koin": simbol.upper(), "nama": cg["nama"],
        "tingkat_kapitalisasi": tingkat_kapitalisasi(cg["mcap"], cg["peringkat"]),
        "kriteria": kr,
        "skor_kriteria_terukur": {
            "nilai": skor_sebagian, "cakupan_bobot_persen": bobot_terukur,
            "catatan": f"Rata-rata tertimbang dari {len(terukur)} kriteria yang diukur kode "
                       f"(cakupan {bobot_terukur}% bobot). BUKAN skor akhir — skor akhir butuh "
                       f"ketujuh kriteria."},
        "developer_santiment": bandingkan_santiment(dev, (devkode_hasil or {}).get("github")),
        "developer_github": devkode_hasil,
        "invalidasi_developer": status_invalidasi_developer((devkode_hasil or {}).get("github")),
        "sinyal_distribusi": {
            "listing_tier1": bursa,
            "musim_altcoin": musim_alt,
            "liputan_berita_7_hari": berita,
            "belum_ada_sumbernya": ["saturasi influencer (butuh data X/Twitter berbayar)",
                                    "TANGGAL listing tier-1 (yang ada hanya ada/tidaknya)",
                                    "Google Trends (menolak akses dari server)"],
            "sudah_ada_di_tempat_lain": "funding rate & open interest — derivatif.py dan "
                                        "coinalyze.py, bukan di sini",
        },
        "wajib_dibaca": WAJIB_DIBACA,
    }


WAJIB_DIBACA = (
    "Kerangka skor naratif #Kalimasada (slide video): katalis 20, tokenomics 20, TAM 15, tim & "
    "VC 15, likuiditas 10, timing 10, revenue 10; skor 1-5 per kriteria; > 3,5 layak dikejar, "
    "2,5-3,5 watchlist, < 2,5 hindari. Skor tokenomics, likuiditas, dan revenue di sini "
    "DIUKUR KODE — salin apa adanya, jangan dinaikkan. Empat sisanya harus kamu nilai SENDIRI "
    "dan sebutkan dasarnya; kalau datanya tidak ada, katakan tidak bisa dinilai, jangan "
    "mengisi angka tengah. Tuliskan skornya dalam SATU baris persis seperti ini supaya "
    "hitungannya diperiksa kode: 'Kekuatan katalis N · Tokenomics N · Ukuran pasar N · Tim & "
    "VC N · Likuiditas N · Timing siklus N · Revenue N' lalu 'Skor tertimbang X,XX'. "
    "Ambang 1-5 untuk tiga kriteria terukur adalah milik alat ini, BUKAN dari video. "
    "Jadwal unlock tidak punya sumber gratis — sebutkan bahwa itu belum diperiksa. "
    "Aktivitas developer di 'developer_github' (commit GitHub repo ekosistem) dipakai untuk "
    "ATURAN INVALIDASI ke-3 'developer pergi' — BUKAN untuk skor tim & VC, yang menilai "
    "pendukungnya (fund tier-1). Sebutkan repo yang jadi dasarnya. 'developer_santiment' itu "
    "sekunder: kalau bertentangan dengan GitHub, pakai GitHub dan jangan kutip Santiment "
    "sebagai penguat. 'invalidasi_developer' WAJIB dilaporkan dengan status, angka commit, dan "
    "persen perubahannya; saat statusnya TANDA AWAL jangan menulis invalidasi 'belum kena'. "
    "Indeks musim altcoin: angka 90 hari adalah "
    "TERBITAN blockchaincenter, yang 30 hari DIHITUNG SENDIRI — jangan tukar keduanya. "
    "Listing tier-1 hanya menunjukkan ADA/TIDAKNYA listing, bukan listing BARU, jadi ia "
    "belum cukup untuk menyebut fase distribusi sendirian.")


def main():
    ap = argparse.ArgumentParser(description="Kriteria skor naratif yang terukur kode")
    ap.add_argument("simbol")
    ap.add_argument("--cg-id", help="id CoinGecko yang sudah diketahui (menghemat pencarian)")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    hasil = analisa(args.simbol, cg_id=args.cg_id)
    print(json.dumps(hasil, indent=None if args.json else 2, ensure_ascii=False))
    # Selalu 0. Bot membuang SELURUH keluaran skrip yang keluar bukan 0 — termasuk alasan
    # kegagalannya dan data yang tetap berhasil diambil. Kelengkapan data tetap tercatat
    # benar: blok kelengkapan bot mengenali kunci "tidak_tersedia" sebagai sumber kosong.
    return 0


if __name__ == "__main__":
    sys.exit(main())
