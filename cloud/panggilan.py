"""Rekam jejak PANGGILAN EKSTERNAL (mis. Astronacci) — dicatat, lalu dinilai oleh data.

KENAPA ADA: materi Astronacci yang dikirim user (24 Sep 2026) memuat panggilan yang
tidak bisa diuji tanpa aturan internal mereka — "Vibrational Date", "Astrology Cycle",
target 98.000/127.000 yang tidak dihasilkan cara ukur baku. Yang BISA dilakukan: mencatat
panggilannya sebelum hasilnya diketahui, lalu menilainya dengan harga yang benar-benar
terjadi. Setelah beberapa bulan, rekam jejak itulah yang menjawab seberapa jauh panggilan
semacam ini layak didengar — bukan keyakinan siapa pun.

Aturan penilaian, ditetapkan sekali:
  - panggilan LEVEL: target mana yang tersentuh lebih dulu dibanding level invalid.
    Invalid berbasis CLOSE harian bila panggilannya berbunyi "selama bertahan di atas",
    berbasis SENTUH bila berupa stop. Hari yang menyentuh keduanya = invalid.
    Panggilan ber-pemicu (buy stop) baru hidup setelah pemicunya tersentuh.
  - panggilan WAKTU (vibrational date): dicatat gerak harga di jendela sesudahnya —
    tanpa vonis benar/salah, karena klaimnya tidak menyebut arah maupun besar gerak.
  - panggilan PERIODE (big bull): dinilai saat jatuh tempo, perubahan harga periodenya.

Rapor ini hanya MENGAMATI, seperti rapor.py — tidak mengubah analisa bot.

Pemakaian:
    python cloud/panggilan.py --ringkas
"""

import argparse
import datetime as dt
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
BERKAS = os.path.join(BASE_DIR, "data", "panggilan_eksternal.json")


def _tgl(ms):
    return dt.datetime.fromtimestamp(ms / 1000, dt.timezone.utc).date()


def _persen(x):
    return f"{x:+.1f}%".replace(".", ",")


def _usd(x):
    return "$" + f"{x:,.0f}".replace(",", ".")


def nilai_level(p, candle):
    """Status panggilan level dari candle harian SESUDAH tanggal panggilan."""
    mulai = dt.date.fromisoformat(p["tanggal"])
    sesudah = [c for c in candle if _tgl(c[0]) > mulai]
    naik = p.get("arah", "naik") == "naik"
    hidup_dari = 0
    if p.get("pemicu"):
        hidup_dari = next((i for i, c in enumerate(sesudah)
                           if (c[2] >= p["pemicu"] if naik else c[3] <= p["pemicu"])), None)
        if hidup_dari is None:
            return {"status": "PEMICU BELUM TERSENTUH", "hari": len(sesudah)}
    kena = []
    for c in sesudah[hidup_dari:]:
        if p.get("invalid_basis") == "sentuh":
            jebol = c[3] <= p["invalid"] if naik else c[2] >= p["invalid"]
        else:
            jebol = c[4] < p["invalid"] if naik else c[4] > p["invalid"]
        baru = [t for t in p["target"] if t not in kena and
                (c[2] >= t if naik else c[3] <= t)]
        if jebol:
            return {"status": "INVALID", "tanggal": str(_tgl(c[0])), "target_kena": kena}
        kena += baru
        if len(kena) == len(p["target"]):
            return {"status": "SEMUA TARGET KENA", "tanggal": str(_tgl(c[0])),
                    "target_kena": kena}
    if kena:
        return {"status": f"TARGET {len(kena)} KENA, sisanya terbuka", "target_kena": kena,
                "hari": len(sesudah)}
    return {"status": "TERBUKA", "hari": len(sesudah)}


def nilai_waktu(p, candle):
    t0 = dt.date.fromisoformat(p["tanggal_klaim"])
    acuan = next((c for c in candle if _tgl(c[0]) == t0), None)
    jendela = [c for c in candle
               if t0 < _tgl(c[0]) <= t0 + dt.timedelta(days=p["jendela_hari"])]
    if not acuan or not jendela:
        return {"status": "BELUM ADA DATA JENDELA"}
    turun = min(c[3] for c in jendela) / acuan[4] - 1
    naik = max(c[2] for c in jendela) / acuan[4] - 1
    lengkap = len(jendela) >= p["jendela_hari"]
    return {"status": "TERCATAT" if lengkap else "JENDELA BERJALAN",
            "close_tanggal_klaim": acuan[4], "turun_terdalam_persen": round(100 * turun, 1),
            "naik_tertinggi_persen": round(100 * naik, 1), "hari": len(jendela)}


def nilai_periode(p, candle, hari_ini):
    if hari_ini < dt.date.fromisoformat(p["jatuh_tempo"]):
        return {"status": "BELUM JATUH TEMPO", "jatuh_tempo": p["jatuh_tempo"]}
    a = next((c for c in candle if _tgl(c[0]) >= dt.date.fromisoformat(p["mulai"])), None)
    b = next((c for c in reversed(candle)
              if _tgl(c[0]) <= dt.date.fromisoformat(p["jatuh_tempo"])), None)
    if not a or not b:
        return {"status": "DATA TIDAK CUKUP"}
    return {"status": "DINILAI", "perubahan_persen": round(100 * (b[4] / a[4] - 1), 1)}


def nilai(panggilan, candle, hari_ini=None):
    hari_ini = hari_ini or dt.datetime.now(dt.timezone.utc).date()
    out = []
    for p in panggilan:
        jenis = p.get("jenis", "level")
        if jenis == "waktu":
            h = nilai_waktu(p, candle)
        elif jenis == "periode":
            h = nilai_periode(p, candle, hari_ini)
        else:
            h = nilai_level(p, candle)
        out.append(dict(p, hasil=h))
    return out


def ringkas(hasil):
    b = ["REKAM JEJAK PANGGILAN EKSTERNAL (dicatat sebelum hasilnya diketahui, panggilan.py)"]
    for p in hasil:
        h = p["hasil"]
        baris = f"  [{p['tanggal']}] {p['judul']} — {h['status']}"
        if h.get("tanggal"):
            baris += f" ({h['tanggal']})"
        if h.get("target_kena"):
            baris += " · target kena: " + ", ".join(_usd(t) for t in h["target_kena"])
        if "turun_terdalam_persen" in h:
            # Koma desimal HANYA pada angkanya: .replace pada baris utuh ikut merusak
            # judul ("83.000" → "83,000") — bug yang sama pernah ada di logregresi.py.
            baris += (f" · sesudah {h['hari']} hari: turun terdalam "
                      f"{_persen(h['turun_terdalam_persen'])}, naik tertinggi "
                      f"{_persen(h['naik_tertinggi_persen'])}")
        b.append(baris)
    b.append("  Sebut status ini apa adanya bila materi sumbernya dibahas. Panggilan yang "
             "masih TERBUKA belum terbukti benar maupun salah.")
    return "\n".join(b)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ringkas", action="store_true")
    a = ap.parse_args()
    with open(BERKAS, encoding="utf-8") as f:
        panggilan = json.load(f)
    from indicators import fetch_base, resolve_cg_id
    candle, _s, _k, err = fetch_base("BTC", resolve_cg_id("BTC"), "1d")
    if not candle:
        print(f"REKAM JEJAK PANGGILAN EKSTERNAL: candle harian tidak tersedia ({err}) — "
              "status tidak bisa dinilai.")
        return
    hasil = nilai([p for p in panggilan if p["aset"] == "BTC"], candle)
    if a.ringkas:
        print(ringkas(hasil))
    else:
        print(json.dumps(hasil, indent=2, ensure_ascii=False, default=str))


if __name__ == "__main__":
    main()
