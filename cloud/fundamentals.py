"""Penarik laporan keuangan protokol (fundamental) — deterministik, dihitung dengan kode.

Melengkapi indicators.py (teknikal). Sumber: DefiLlama (gratis, tanpa API key).

Yang dihasilkan:
  - Revenue & fees: total 30d/90d/1thn, rincian 12 BULAN terakhir dan 8 KUARTAL terakhir,
    pertumbuhan MoM / QoQ / YoY, dan run-rate tahunan
  - TVL: nilai sekarang, perubahan 30d/90d, tren bulanan
  - Volume DEX (kalau protokolnya DEX)
  - Rasio valuasi: MC/TVL, P/S dan P/F tahunan

CATATAN JUJUR soal active addresses: DefiLlama TIDAK menyediakannya lewat API publik
(endpoint activeUsers mengembalikan 404). Data itu umumnya berbayar (Token Terminal,
Artemis, Dune). Script ini melaporkannya sebagai "tidak tersedia" alih-alih menebak;
Claude diarahkan mencarinya lewat WebSearch dan mengeluarkannya dari skor bila tak ada.

Pemakaian:
    python cloud/fundamentals.py AAVE
    python cloud/fundamentals.py AAVE --slug aave     (kalau resolusi otomatis meleset)
"""

import argparse
import json
import sys
import urllib.error
import urllib.request
from collections import OrderedDict
from datetime import datetime, timezone

UA = {"User-Agent": "Mozilla/5.0 (compatible; riset-koin/1.0)"}
TIMEOUT = 30
BASE = "https://api.llama.fi"


def http_json(url):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return json.loads(r.read().decode())


def try_json(url):
    try:
        return http_json(url)
    except Exception:
        return None


# ------------------------------------------------------------------ resolusi

def resolve_protocol(ticker, slug_override=None):
    """Cari protokol DefiLlama dari ticker. Return (info, kandidat_slug)."""
    if slug_override:
        return {"slug": slug_override, "name": slug_override}, [slug_override]

    data = try_json(f"{BASE}/protocols")
    if not data:
        return None, []

    hits = [p for p in data if (p.get("symbol") or "").upper() == ticker.upper()]
    if not hits:
        # cadangan: cocokkan nama persis
        hits = [p for p in data if (p.get("name") or "").upper() == ticker.upper()]
    if not hits:
        return None, []

    hits.sort(key=lambda p: -(p.get("tvl") or 0))
    top = hits[0]

    # mcap sering kosong di entri versi (mis. "Aave V3") karena melekat pada token induk.
    # Ambil dari kandidat mana pun yang punya nilai.
    mcap = next((h.get("mcap") for h in hits if h.get("mcap")), None)

    # Slug untuk fees sering memakai nama induk ("aave"), bukan versi ("aave-v3").
    # Kumpulkan kandidat: induk dulu, lalu tiap versi.
    induk = (top.get("name") or "").split()[0].lower().replace(".", "")
    kandidat = [induk] + [h.get("slug") for h in hits if h.get("slug")]
    seen, urut = set(), []
    for s in kandidat:
        if s and s not in seen:
            seen.add(s)
            urut.append(s)

    info = {
        "name": top.get("name"),
        "slug": top.get("slug"),
        "category": top.get("category"),
        "chains": (top.get("chains") or [])[:6],
        "mcap": mcap,
        "tvl_now": top.get("tvl"),
        "versi_lain": max(0, len(hits) - 1),
    }
    return info, urut


# --------------------------------------------------------------- agregasi

def deret_ke_bulanan(chart):
    """[[unix, nilai], ...] harian -> OrderedDict {'YYYY-MM': total}."""
    out = OrderedDict()
    for item in chart or []:
        try:
            ts, val = int(item[0]), float(item[1] or 0)
        except (TypeError, ValueError, IndexError):
            continue
        kunci = datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m")
        out[kunci] = out.get(kunci, 0.0) + val
    return OrderedDict(sorted(out.items()))


def bulanan_ke_kuartalan(bulanan):
    out = OrderedDict()
    for ym, val in bulanan.items():
        tahun, bulan = ym.split("-")
        kuartal = f"{tahun}-Q{(int(bulan) - 1) // 3 + 1}"
        out[kuartal] = out.get(kuartal, 0.0) + val
    return OrderedDict(sorted(out.items()))


def tumbuh(baru, lama):
    if lama in (None, 0) or baru is None:
        return None
    return round((baru - lama) / abs(lama) * 100, 1)


def ringkas_deret(chart, label_sekarang):
    """Bangun ringkasan bulanan/kuartalan + pertumbuhan dari deret harian.
    Periode BERJALAN (belum lengkap) dipisah agar tidak mengacaukan perbandingan."""
    bulanan = deret_ke_bulanan(chart)
    if not bulanan:
        return None

    kini_bulan = datetime.now(timezone.utc).strftime("%Y-%m")
    kini_kuartal = f"{kini_bulan[:4]}-Q{(int(kini_bulan[5:7]) - 1) // 3 + 1}"

    bulan_lengkap = OrderedDict((k, v) for k, v in bulanan.items() if k != kini_bulan)
    kuartalan = bulanan_ke_kuartalan(bulanan)
    kuartal_lengkap = OrderedDict((k, v) for k, v in kuartalan.items() if k != kini_kuartal)

    bl = list(bulan_lengkap.items())
    kl = list(kuartal_lengkap.items())
    nilai_bulan = [v for _, v in bl]

    ttm = sum(nilai_bulan[-12:]) if len(nilai_bulan) >= 12 else None
    ttm_sebelum = sum(nilai_bulan[-24:-12]) if len(nilai_bulan) >= 24 else None

    return {
        "berjalan": {"periode": kini_bulan, "usd": round(bulanan.get(kini_bulan, 0.0), 2),
                     "catatan": f"{label_sekarang} bulan berjalan, belum lengkap"},
        "bulanan_12_terakhir": [{"bulan": k, "usd": round(v, 2)} for k, v in bl[-12:]],
        "kuartalan_8_terakhir": [{"kuartal": k, "usd": round(v, 2)} for k, v in kl[-8:]],
        "pertumbuhan_persen": {
            "mom": tumbuh(bl[-1][1], bl[-2][1]) if len(bl) >= 2 else None,
            "qoq": tumbuh(kl[-1][1], kl[-2][1]) if len(kl) >= 2 else None,
            "yoy_ttm": tumbuh(ttm, ttm_sebelum),
        },
        "ttm_usd": round(ttm, 2) if ttm is not None else None,
        "run_rate_tahunan_usd": round(bl[-1][1] * 12, 2) if bl else None,
    }


# ------------------------------------------------------------------ sumber

def ambil_fees(kandidat, data_type):
    """dataType: dailyRevenue atau dailyFees. Coba tiap slug sampai ada yang berisi."""
    for slug in kandidat:
        d = try_json(f"{BASE}/summary/fees/{slug}?dataType={data_type}")
        if d and d.get("totalDataChart"):
            return d, slug
    return None, None


def ambil_dex_volume(kandidat):
    for slug in kandidat:
        d = try_json(f"{BASE}/summary/dexs/{slug}")
        if d and d.get("totalDataChart"):
            return d, slug
    return None, None


def ambil_tvl(kandidat):
    for slug in kandidat:
        d = try_json(f"{BASE}/protocol/{slug}")
        if d and d.get("tvl"):
            return d, slug
    return None, None


def ringkas_tvl(d):
    deret = [(int(x["date"]), float(x["totalLiquidityUSD"] or 0))
             for x in (d.get("tvl") or []) if x.get("date")]
    if not deret:
        return None
    deret.sort()
    sekarang = deret[-1][1]

    def nilai_x_hari_lalu(n):
        target = deret[-1][0] - n * 86400
        cocok = [v for t, v in deret if t <= target]
        return cocok[-1] if cocok else None

    bulanan = OrderedDict()
    for t, v in deret:  # TVL itu stok, bukan aliran -> pakai nilai AKHIR bulan
        bulanan[datetime.fromtimestamp(t, tz=timezone.utc).strftime("%Y-%m")] = v

    return {
        "sekarang_usd": round(sekarang, 2),
        "perubahan_30d_persen": tumbuh(sekarang, nilai_x_hari_lalu(30)),
        "perubahan_90d_persen": tumbuh(sekarang, nilai_x_hari_lalu(90)),
        "akhir_bulan_6_terakhir": [{"bulan": k, "usd": round(v, 2)}
                                   for k, v in list(bulanan.items())[-6:]],
    }


# -------------------------------------------------------------------- main

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("ticker")
    ap.add_argument("--slug", default=None, help="paksa slug DefiLlama tertentu")
    ap.add_argument("--mcap", type=float, default=None,
                    help="market cap USD (dari CoinMarketCap) untuk menghitung P/S, P/F, MC/TVL")
    args = ap.parse_args()
    ticker = args.ticker.upper().replace("$", "")

    hasil = {
        "symbol": ticker,
        "generated_utc": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M"),
        "sumber": "DefiLlama (gratis, tanpa API key)",
        "catatan": [],
    }

    info, kandidat = resolve_protocol(ticker, args.slug)
    if not info:
        hasil["error"] = (f"Protokol untuk {ticker} tidak ditemukan di DefiLlama. "
                          "Koin ini mungkin bukan protokol (mis. koin meme/L1 murni) "
                          "atau ticker-nya berbeda. Coba --slug <nama-slug>.")
        print(json.dumps(hasil, indent=2, ensure_ascii=False))
        return

    hasil["protokol"] = info

    rev, slug_rev = ambil_fees(kandidat, "dailyRevenue")
    fees, slug_fee = ambil_fees(kandidat, "dailyFees")

    if rev:
        hasil["revenue"] = dict(ringkas_deret(rev["totalDataChart"], "revenue") or {},
                                slug=slug_rev,
                                total_30d_usd=rev.get("total30d"),
                                total_1thn_usd=rev.get("total1y"))
    else:
        hasil["revenue"] = None
        hasil["catatan"].append("Revenue tidak tersedia di DefiLlama untuk protokol ini.")

    if fees:
        hasil["fees"] = dict(ringkas_deret(fees["totalDataChart"], "fees") or {},
                             slug=slug_fee,
                             total_30d_usd=fees.get("total30d"),
                             total_1thn_usd=fees.get("total1y"))
    else:
        hasil["fees"] = None

    tvl_raw, slug_tvl = ambil_tvl(kandidat)
    hasil["tvl"] = dict(ringkas_tvl(tvl_raw) or {}, slug=slug_tvl) if tvl_raw else None

    dex, slug_dex = ambil_dex_volume(kandidat)
    if dex:
        hasil["volume_dex"] = dict(ringkas_deret(dex["totalDataChart"], "volume") or {},
                                   slug=slug_dex, total_30d_usd=dex.get("total30d"))
    else:
        hasil["volume_dex"] = None

    # Rasio valuasi
    mcap = args.mcap or info.get("mcap")
    tvl_now = (hasil["tvl"] or {}).get("sekarang_usd") or info.get("tvl_now")
    rev_ttm = (hasil["revenue"] or {}).get("ttm_usd")
    fee_ttm = (hasil["fees"] or {}).get("ttm_usd")
    hasil["valuasi"] = {
        "mcap_usd": mcap,
        "mc_tvl": round(mcap / tvl_now, 2) if mcap and tvl_now else None,
        "ps_ttm": round(mcap / rev_ttm, 1) if mcap and rev_ttm else None,
        "pf_ttm": round(mcap / fee_ttm, 1) if mcap and fee_ttm else None,
        "catatan": "P/S memakai revenue protokol; P/F memakai total fees (dibayar user).",
    }

    hasil["active_addresses"] = None
    hasil["catatan"].append(
        "Active addresses TIDAK tersedia di API publik DefiLlama (endpoint activeUsers 404). "
        "Cari lewat WebSearch; kalau tidak ketemu, KELUARKAN metrik ini dari skor dan "
        "sebutkan ketidaktersediaannya — jangan mengarang angka.")

    print(json.dumps(hasil, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
