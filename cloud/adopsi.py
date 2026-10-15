"""Data Adoption Clock — A1/A2 arus ETF, A3 13F, A4 treasury korporasi.

  A1/A2  Arus harian ETF spot BTC AS dari Farside (tabel "All Data", US$ juta, sejak
         11 Jan 2024). SoSoValue (~300 hari) dipakai sebagai CEK SILANG, sesuai checklist
         rancangan. Farside menolak UA peramban palsu dengan tantangan Cloudflare; UA riset
         yang jujur dilayani. Tantangan TIDAK dicoba ditembus — kalau muncul, pakai salinan.
         Salinan ada di cloud/data/etf_arus_farside.json, diperbarui workflow mingguan.
  A3     Ringkasan 13F per kuartal dari etf_13f.py (cloud/data/etf_13f.json). Tanggal
         tersedia = akhir kuartal + 45 hari (batas filing), BUKAN akhir kuartal.
  A4     Total BTC treasury perusahaan publik (CoinGecko, gratis). Sumber gratis hanya
         memberi angka HARI INI, jadi riwayatnya dibangun dari arsip mingguan
         cloud/data/treasury_arsip.jsonl. Skornya baru ada setelah arsip cukup panjang.

    python cloud/adopsi.py --perbarui     # tarik Farside + arsipkan treasury
    python cloud/adopsi.py --cek-silang   # Farside vs SoSoValue
"""
import argparse
import json
import os
import re
import sys
import urllib.request
from datetime import date, datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
FARSIDE = "https://farside.co.uk/bitcoin-etf-flow-all-data/"
FARSIDE_PATH = os.path.join(BASE_DIR, "data", "etf_arus_farside.json")
TREASURY = "https://api.coingecko.com/api/v3/companies/public_treasury/bitcoin"
TREASURY_PATH = os.path.join(BASE_DIR, "data", "treasury_arsip.jsonl")
F13_PATH = os.path.join(BASE_DIR, "data", "etf_13f.json")
UA = {"User-Agent": "riset-pasar/1.0 (research; contact via github)"}
TIMEOUT = 40
# BTC milik GBTC saat dikonversi jadi ETF (10 Jan 2024). ETF lain mulai dari ~nol, jadi
# kepemilikan ETF ~ angka ini + jumlah (arus USD / harga hari itu). Dipakai untuk
# menormalkan A1 sepanjang riwayat; SoSoValue memberi total aset asli untuk 300 hari terakhir.
GBTC_AWAL_BTC = 619_220
BULAN = {m: i for i, m in enumerate(
    ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"), 1)}


def _get(url):
    import cgkunci
    req = urllib.request.Request(url, headers={**UA, **cgkunci.header_untuk(url)})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return r.read().decode("utf-8", errors="replace")


def _angka_farside(t):
    t = t.replace(",", "").strip()
    if t in ("", "-"):
        return None
    neg = t.startswith("(") and t.endswith(")")
    v = float(t.strip("()"))
    return -v if neg else v


def urai_farside(html):
    """[(tanggal ISO, total US$ juta)] — baris tanggal saja, hari tanpa data dibuang."""
    if "Just a moment" in html[:3000]:
        raise ValueError("Farside membalas tantangan Cloudflare")
    keluar = []
    for baris in re.findall(r"<tr[^>]*>(.*?)</tr>", html, re.S):
        sel = [re.sub(r"<[^>]+>", "", c).strip()
               for c in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", baris, re.S)]
        m = re.fullmatch(r"(\d{1,2}) (\w{3}) (\d{4})", sel[0]) if sel else None
        if not m or m.group(2) not in BULAN:
            continue
        try:
            total = _angka_farside(sel[-1])
        except ValueError:
            continue
        # Hari berjalan muncul sebagai deretan "-" dengan total 0,0 — belum ada data.
        if total is None or all(s.strip() == "-" for s in sel[1:-1]):
            continue
        tgl = date(int(m.group(3)), BULAN[m.group(2)], int(m.group(1)))
        keluar.append((tgl.isoformat(), total))
    if len(keluar) < 100:
        raise ValueError(f"tabel Farside hanya {len(keluar)} baris — bentuk halaman berubah?")
    return keluar


def _muat(path, bawaan):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return bawaan


def arus_etf(perbarui=False):
    """(baris [(tgl, juta USD)], sumber, error). Salinan dipakai kalau tarikan gagal."""
    salinan = _muat(FARSIDE_PATH, {})
    if perbarui:
        try:
            baris = urai_farside(_get(FARSIDE))
            os.makedirs(os.path.dirname(FARSIDE_PATH), exist_ok=True)
            with open(FARSIDE_PATH, "w", encoding="utf-8", newline="\n") as f:
                json.dump({"ditarik_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                           "satuan": "US$ juta, total semua ETF spot BTC AS",
                           "baris": baris}, f, separators=(",", ":"))
            return baris, "farside (baru ditarik)", None
        except Exception as e:
            err = f"Farside gagal ({type(e).__name__}: {str(e)[:80]})"
            if salinan.get("baris"):
                return salinan["baris"], f"salinan {salinan.get('ditarik_utc')}", err
            return None, None, err
    if salinan.get("baris"):
        return salinan["baris"], f"salinan Farside {salinan.get('ditarik_utc', '')[:10]}", None
    return None, None, "salinan Farside belum ada (jalankan --perbarui)"


def cek_silang(baris_farside, baris_soso):
    """Selisih harian Farside vs SoSoValue pada tanggal yang sama (US$ juta)."""
    soso = {b["date"]: b["totalNetInflow"] / 1e6 for b in baris_soso
            if b.get("date") and b.get("totalNetInflow") is not None}
    pas = [(v, soso[t]) for t, v in baris_farside if t in soso]
    if not pas:
        return {"tidak_tersedia": "tidak ada tanggal yang sama"}
    selisih = sorted(abs(a - b) for a, b in pas)
    return {"hari_dibandingkan": len(pas),
            "selisih_median_juta_usd": round(selisih[len(selisih) // 2], 1),
            "hari_selisih_lebih_50_juta": sum(1 for x in selisih if x > 50),
            "jumlah_farside_juta": round(sum(a for a, _ in pas)),
            "jumlah_sosovalue_juta": round(sum(b for _, b in pas))}


def kepemilikan_btc(baris, harga):
    """Estimasi BTC yang dipegang ETF per hari: GBTC awal + jumlah(arus / harga)."""
    btc, keluar = GBTC_AWAL_BTC, {}
    for t, juta in baris:
        p = harga.get(t)
        if p:
            btc += juta * 1e6 / p
        keluar[t] = btc
    return keluar


# ------------------------------------------------------------------ A4 treasury
def arsipkan_treasury():
    """Tambah satu baris snapshot (paling sering sekali per 6 hari)."""
    arsip = seri_treasury()
    hari_ini = datetime.now(timezone.utc).date()
    if arsip and (hari_ini - date.fromisoformat(arsip[-1]["tanggal"])).days < 6:
        return arsip[-1], "sudah ada snapshot < 6 hari"
    d = json.loads(_get(TREASURY))
    baris = {"tanggal": hari_ini.isoformat(),
             "total_btc": round(float(d["total_holdings"]), 2),
             "perusahaan": len(d.get("companies") or [])}
    with open(TREASURY_PATH, "a", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(baris) + "\n")
    return baris, None


def seri_treasury():
    try:
        with open(TREASURY_PATH, encoding="utf-8") as f:
            return [json.loads(x) for x in f if x.strip()]
    except OSError:
        return []


# ------------------------------------------------------------------ A3 13F
def seri_13f():
    """[(tanggal_tersedia, ringkasan kuartal)] dari etf_13f.json, terurut."""
    d = _muat(F13_PATH, {})
    keluar = []
    for q in d.get("kuartal") or []:
        try:
            akhir = date.fromisoformat(q["akhir_kuartal"])
        except (KeyError, ValueError):
            continue
        keluar.append((akhir + timedelta(days=45), q))
    return sorted(keluar, key=lambda t: t[0])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--perbarui", action="store_true", help="tarik Farside & arsip treasury")
    ap.add_argument("--cek-silang", dest="cek", action="store_true")
    a = ap.parse_args()
    if a.perbarui:
        baris, sumber, err = arus_etf(perbarui=True)
        print(f"farside: {len(baris or [])} hari · {sumber} · {err or 'ok'}")
        try:
            snap, cat = arsipkan_treasury()
            print(f"treasury: {snap['tanggal']} {snap['total_btc']:.0f} BTC · {cat or 'baru'}")
        except Exception as e:
            print(f"treasury gagal: {type(e).__name__}")
    if a.cek:
        import sosovalue
        soso, err = sosovalue.historis_etf("us-btc-spot")
        baris, _, e2 = arus_etf()
        print(json.dumps(cek_silang(baris or [], soso or []) if not (err or e2)
                         else {"gagal": err or e2}, ensure_ascii=False))


if __name__ == "__main__":
    main()
