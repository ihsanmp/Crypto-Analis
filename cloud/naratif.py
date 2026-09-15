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
  CoinGecko coin & trending · DefiLlama fees/revenue · Santiment dev_activity ·
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
import urllib.parse
from datetime import datetime, timedelta, timezone

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
        p = subprocess.run(["curl", "-s", "-L", "--max-time", str(timeout), "-A", UA, url],
                           capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout + 10)
        return p.stdout if p.returncode == 0 else ""
    except Exception:
        return ""


def _json(url):
    try:
        return json.loads(_curl(url) or "{}")
    except json.JSONDecodeError:
        return {}


def coingecko(cg_id):
    d = _json(f"https://api.coingecko.com/api/v3/coins/{cg_id}?localization=false&tickers=false"
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
            "kategori": d.get("categories") or []}


def trending_ids():
    d = _json("https://api.coingecko.com/api/v3/search/trending")
    return {c.get("item", {}).get("id") for c in d.get("coins", [])}


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
def analisa(simbol):
    if BASE_DIR not in sys.path:
        sys.path.insert(0, BASE_DIR)
    import indicators as ind
    cg_id = ind.resolve_cg_id(simbol.upper())
    if not cg_id:
        return {"koin": simbol.upper(), "tidak_tersedia": "koin tidak dikenali CoinGecko"}
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as ex:
        f_cg = ex.submit(coingecko, cg_id)
        f_tr = ex.submit(trending_ids)
        f_dev = ex.submit(dev_activity, cg_id)
        f_rev = ex.submit(revenue_1thn, simbol.upper())
        cg = f_cg.result()
        if not cg:
            return {"koin": simbol.upper(), "tidak_tersedia": "data CoinGecko gagal diambil"}
        f_pv = ex.submit(pageviews, cg["nama"] or simbol)
        f_nw = ex.submit(berita_7_hari, cg["nama"] or simbol)
        trending, dev, rev, pv, berita = (f_tr.result(), f_dev.result(), f_rev.result(),
                                          f_pv.result(), f_nw.result())

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
        "tim_vc": {"skor": None, "dinilai": True,
                   "sumber_disarankan": "cryptorank.io & chainbroker.io (web gratis, API "
                                        "berkunci). Electric Capital untuk tim developer."},
        "timing": {"skor": None, "dinilai": True,
                   "data": {"jarak_dari_ath_persen": round((1 - cg["harga"] / cg["ath"]) * 100, 1)
                            if cg["harga"] and cg["ath"] else None,
                            "ubah_30_hari_persen": round(cg["ubah_30h"], 1) if cg["ubah_30h"] is not None else None,
                            "ubah_1_tahun_persen": round(cg["ubah_1thn"], 1) if cg["ubah_1thn"] is not None else None,
                            "trending_coingecko": cg_id in trending,
                            "wikipedia_pageviews": pv},
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
        "developer_santiment": dev,
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
    "Jadwal unlock tidak punya sumber gratis — sebutkan bahwa itu belum diperiksa.")


def main():
    ap = argparse.ArgumentParser(description="Kriteria skor naratif yang terukur kode")
    ap.add_argument("simbol")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    hasil = analisa(args.simbol)
    print(json.dumps(hasil, indent=None if args.json else 2, ensure_ascii=False))
    return 0 if not hasil.get("tidak_tersedia") else 1


if __name__ == "__main__":
    sys.exit(main())
