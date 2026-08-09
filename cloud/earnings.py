"""Jadwal & kejutan EARNINGS + emiten sebanding — lubang terbesar di analisa saham.

Untuk emas, prompt sudah tegas: jangan masuk menjelang rilis berdampak kuat. Untuk saham,
padanannya adalah tanggal earnings — dan bot tidak punya datanya sama sekali. Merekomendasikan
akumulasi tanpa tahu earnings-nya lusa adalah cacat serius, bukan sekadar kekurangan data.

Sekaligus menutup satu aturan yang selama ini MUSTAHIL dipenuhi: analisa_pasar.md
memerintahkan "bandingkan dengan sesama emiten di sektor yang sama", tapi tidak ada sumber
daftar peer. Bot hanya bisa mengarang atau mengabaikan aturannya sendiri.

SUMBER: Finnhub tier gratis — 60 panggilan/menit, cakupan AS, daftar earnings 1 bulan,
kejutan EPS 4 kuartal, tanpa kartu kredit.

LISENSI: tier gratis Finnhub hanya untuk PEMAKAIAN PRIBADI NON-KOMERSIAL. Untuk bot Telegram
yang dipakai sendiri itu aman; kalau aksesnya dibuka ke orang lain, statusnya berubah.
ALLOWED_CHAT_IDS di Worker yang menjaga batas itu — pertahankan.

TANPA KUNCI: script TIDAK mati. Bagian ini dilaporkan tidak tersedia dan analisa saham tetap
jalan dengan sumber lain — pola yang sama dengan COINGLASS_API_KEY dan MORALIS_API_KEY.
Daftar gratis di finnhub.io, lalu masukkan sendiri ke GitHub Secrets sebagai FINNHUB_API_KEY.
JANGAN mengirimkan kuncinya lewat chat.

Pemakaian:
    python cloud/earnings.py NVDA
    python cloud/earnings.py NVDA --hanya-jadwal
"""

import argparse
import json
import os
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CACHE_PATH = os.path.join(BASE_DIR, "data", "earnings_cache.json")
CACHE_UMUR = 6 * 3600          # jadwal earnings tidak berubah tiap menit

API = "https://finnhub.io/api/v1"
UA = {"User-Agent": "Crypto-Analis Research bot"}
TIMEOUT = 25


def _kunci():
    return (os.environ.get("FINNHUB_API_KEY") or "").strip()


def _muat_cache():
    try:
        with open(CACHE_PATH, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _simpan_cache(c):
    try:
        os.makedirs(os.path.dirname(CACHE_PATH), exist_ok=True)
        with open(CACHE_PATH, "w", encoding="utf-8") as f:
            json.dump(c, f, ensure_ascii=False)
    except Exception as e:
        print(f"[earnings] gagal menyimpan cache: {e}")


def ambil(jalur, params, kunci_cache):
    """Panggil Finnhub dengan cache 6 jam. Return (data, dari_cache, error)."""
    key = _kunci()
    if not key:
        return None, False, "FINNHUB_API_KEY kosong"

    cache = _muat_cache()
    simpan = cache.get(kunci_cache) or {}
    if simpan.get("data") is not None and time.time() - simpan.get("waktu", 0) < CACHE_UMUR:
        return simpan["data"], True, None

    q = dict(params)
    q["token"] = key
    url = f"{API}{jalur}?{urllib.parse.urlencode(q)}"
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=UA),
                                    timeout=TIMEOUT) as r:
            data = json.loads(r.read().decode())
    except Exception as e:
        kode = getattr(e, "code", None)
        pesan = f"{type(e).__name__}" + (f" {kode}" if kode else "")
        if kode == 401:
            pesan += " — kunci ditolak, periksa FINNHUB_API_KEY"
        elif kode == 429:
            pesan += " — batas laju terlampaui (60 panggilan/menit)"
        if simpan.get("data") is not None:
            return simpan["data"], True, f"{pesan} (pakai cache lama)"
        return None, False, pesan

    cache[kunci_cache] = {"data": data, "waktu": time.time(),
                          "waktu_utc": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")}
    _simpan_cache(cache)
    return data, False, None


def jadwal(ticker):
    """Rilis earnings BERIKUTNYA + estimasinya."""
    hari_ini = datetime.now(timezone.utc).date()
    data, cache, err = ambil("/calendar/earnings",
                             {"from": hari_ini.isoformat(),
                              "to": (hari_ini + timedelta(days=90)).isoformat(),
                              "symbol": ticker.upper()},
                             f"cal_{ticker.upper()}")
    if err:
        return {"tidak_tersedia": err}
    entri = (data or {}).get("earningsCalendar") or []
    # Jadwal bisa memuat tanggal yang sudah lewat kalau cache lama dipakai. Menyajikannya
    # sebagai "akan datang" jauh lebih berbahaya daripada mengaku tidak tahu.
    depan = []
    for e in entri:
        try:
            t = datetime.strptime(e.get("date", ""), "%Y-%m-%d").date()
        except ValueError:
            continue
        if t >= hari_ini:
            depan.append((t, e))
    if not depan:
        return {"tidak_ada_jadwal": "tidak ada rilis earnings terjadwal dalam 90 hari ke depan",
                "dari_cache": cache}
    depan.sort(key=lambda x: x[0])
    t, e = depan[0]
    selisih = (t - hari_ini).days
    hasil = {
        "tanggal": t.isoformat(),
        "hari_lagi": selisih,
        "sesi": e.get("hour") or "tidak disebutkan",
        "estimasi_eps": e.get("epsEstimate"),
        "estimasi_revenue": e.get("revenueEstimate"),
        "dari_cache": cache,
    }
    if selisih <= 2:
        hasil["peringatan"] = ("earnings kurang dari 3 hari lagi — gap risk tinggi. "
                               "Untuk yang BELUM punya posisi, bias default TUNGGU DULU.")
    elif selisih <= 7:
        hasil["peringatan"] = ("earnings dalam 7 hari — sebutkan di bagian RISIKO dan "
                               "turunkan keyakinan setup jangka pendek.")
    return hasil


def kejutan(ticker):
    """Kejutan EPS 4 kuartal terakhir: aktual vs estimasi."""
    data, cache, err = ambil("/stock/earnings", {"symbol": ticker.upper(), "limit": 4},
                             f"sur_{ticker.upper()}")
    if err:
        return {"tidak_tersedia": err}
    baris = []
    for e in (data or [])[:4]:
        aktual, estimasi = e.get("actual"), e.get("estimate")
        item = {"periode": e.get("period"), "kuartal": e.get("quarter"),
                "aktual": aktual, "estimasi": estimasi}
        if aktual is not None and estimasi:
            item["kejutan_persen"] = round((aktual - estimasi) / abs(estimasi) * 100, 1)
            item["arah"] = "di atas estimasi" if aktual > estimasi else (
                "di bawah estimasi" if aktual < estimasi else "tepat")
        baris.append(item)
    if not baris:
        return {"tidak_tersedia": "tidak ada riwayat kejutan EPS"}
    lolos = [b for b in baris if b.get("kejutan_persen") is not None
             and b["kejutan_persen"] > 0]
    return {"riwayat": baris, "dari_cache": cache,
            "di_atas_estimasi": f"{len(lolos)} dari {len(baris)} kuartal",
            "arti": ("Yang menggerakkan harga sering bukan angkanya, melainkan SELISIH "
                     "terhadap estimasi dan guidance ke depan. Riwayat melampaui estimasi "
                     "berulang menaikkan ekspektasi — sehingga sekadar 'memenuhi' pun bisa "
                     "dihukum pasar.")}


def peers(ticker):
    """Emiten sebanding — untuk memenuhi aturan 'bandingkan dengan sesama sektor'."""
    data, cache, err = ambil("/stock/peers", {"symbol": ticker.upper()},
                             f"peer_{ticker.upper()}")
    if err:
        return {"tidak_tersedia": err}
    daftar = [p for p in (data or []) if p.upper() != ticker.upper()]
    if not daftar:
        return {"tidak_tersedia": "daftar peer kosong"}
    return {"daftar": daftar[:10], "dari_cache": cache,
            "cara_pakai": ("P/E dan margin HANYA bermakna dibandingkan sesama emiten di "
                           "sektor yang sama. Kalau daftar ini kosong, KATAKAN "
                           "perbandingannya tidak bisa dilakukan — jangan membandingkan "
                           "dengan angka dari ingatan.")}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("ticker")
    ap.add_argument("--hanya-jadwal", action="store_true")
    args = ap.parse_args()

    hasil = {
        "ticker": args.ticker.upper(),
        "generated_utc": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M"),
        "sumber": "Finnhub tier gratis (cakupan AS; lisensi pribadi non-komersial)",
    }
    if not _kunci():
        hasil["tidak_tersedia"] = (
            "FINNHUB_API_KEY belum diisi. Jadwal earnings, kejutan EPS, dan daftar peer "
            "TIDAK tersedia — sampaikan apa adanya, jangan dikarang. Analisa saham tetap "
            "bisa jalan dari market.py, stockfund.py, dan konteks.py.")
        print(json.dumps(hasil, indent=2, ensure_ascii=False))
        return

    hasil["jadwal_berikutnya"] = jadwal(args.ticker)
    if not args.hanya_jadwal:
        hasil["kejutan_eps"] = kejutan(args.ticker)
        hasil["emiten_sebanding"] = peers(args.ticker)
    print(json.dumps(hasil, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
