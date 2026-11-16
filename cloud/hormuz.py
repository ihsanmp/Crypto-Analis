"""Status Selat Hormuz — penggerak PASOKAN minyak — dari Hormuz Strait Monitor (gratis, tanpa kunci).

Diambil dari skill hormuz-strait (himself65/finance-skills, MIT). ~21% minyak dunia lewat
selat ini; status, lalu lintas kapal, premi asuransi perang, dan tarif tanker adalah data
pasokan yang tidak dimiliki sumber bot lain (makro.py hanya makro AS).

SUMBER PIHAK KETIGA, BELUM DIVERIFIKASI: dasbor publik independen, metodologinya tidak
dipublikasikan, dan sebagian deret nyaris statis (throughput 7 hari: 408 rb lalu 412 rb
enam hari berturut-turut, cek 16 Nov 2026) — kemungkinan estimasi, bukan hitungan kapal. Dipakai sebagai KONTEKS pasokan, dikutip bersama sumbernya; harga minyak
tetap dari market.py (CL=F), BUKAN harga Brent di dasbor ini.

    python cloud/hormuz.py
"""
import json
import sys
import urllib.request
from datetime import datetime, timezone

URL = "https://hormuzstraitmonitor.com/api/dashboard"
UA = {"User-Agent": "Mozilla/5.0 (compatible; riset-pasar/1.0)"}


def ambil():
    with urllib.request.urlopen(urllib.request.Request(URL, headers=UA), timeout=20) as r:
        d = json.loads(r.read().decode())
    if not d.get("success"):
        raise RuntimeError("success=false")
    return d.get("data") or {}


def _deret_tetap(x):
    return isinstance(x, list) and len(x) >= 3 and len(set(x)) == 1


def ringkas(d, sekarang=None):
    sekarang = sekarang or datetime.now(timezone.utc)
    s = d.get("straitStatus") or {}
    kapal = d.get("shipCount") or {}
    tertahan = d.get("strandedVessels") or {}
    asuransi = d.get("insurance") or {}
    arus = d.get("throughput") or {}
    dip = d.get("diplomacy") or {}
    dampak = d.get("globalTradeImpact") or {}
    tanker = d.get("tankerRates") or {}
    keluar = {
        "status": s.get("status"), "sejak": s.get("since"),
        "keterangan": (s.get("description") or "")[:220],
        "kapal_melintas_persen_normal": kapal.get("percentOfNormal"),
        "kapal_24_jam": kapal.get("last24h"), "kapal_normal_per_hari": kapal.get("normalDaily"),
        "kapal_tertahan": {"total": tertahan.get("total"), "tanker": tertahan.get("tankers")},
        "asuransi_perang": {"tingkat": asuransi.get("level"),
                            "kelipatan_vs_normal": asuransi.get("multiplier")},
        "throughput_persen_normal": arus.get("percentOfNormal"),
        "tarif_tanker_vlcc_vs_sebelum_krisis_persen": tanker.get("changePercent"),
        "porsi_minyak_dunia_berisiko_persen": dampak.get("percentOfWorldOilAtRisk"),
        "diplomasi": {"status": dip.get("status"), "judul": (dip.get("headline") or "")[:160],
                      "tanggal": dip.get("date")},
        "berita_terbaru": [{"judul": (n.get("title") or "")[:120], "sumber": n.get("source"),
                            "tanggal": (n.get("publishedAt") or "")[:10]}
                           for n in (d.get("news") or [])[:3]],
    }
    diperbarui = d.get("lastUpdated")
    keluar["diperbarui_utc"] = diperbarui
    try:
        t = datetime.fromisoformat(diperbarui.replace("Z", "+00:00"))
        keluar["umur_jam"] = max(0.0, round((sekarang - t).total_seconds() / 3600, 1))
    except Exception:
        keluar["umur_jam"] = None
    curiga = []
    if _deret_tetap(arus.get("last7Days")):
        curiga.append("throughput 7 hari bernilai identik — kemungkinan estimasi statis")
    if keluar["umur_jam"] is not None and keluar["umur_jam"] > 48:
        curiga.append(f"data berumur {keluar['umur_jam']} jam")
    if curiga:
        keluar["peringatan_mutu"] = curiga
    keluar["cara_pakai"] = (
        "Sumber PIHAK KETIGA (hormuzstraitmonitor.com), metodologi tidak dipublikasikan: sebut "
        "sumbernya, perlakukan sebagai konteks pasokan, cocokkan dengan berita bila bisa. "
        "Harga minyak dari market.py (CL=F), bukan dari dasbor ini. Status 'terbatas' yang "
        "sudah lama bisa SUDAH tercermin di harga — yang menggerakkan adalah PERUBAHAN status "
        "(pembukaan/penutupan, hasil diplomasi), bukan statusnya sendiri.")
    return keluar


def main():
    hasil = {"sumber": "Hormuz Strait Monitor (hormuzstraitmonitor.com), pihak ketiga",
             "generated_utc": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")}
    try:
        hasil.update(ringkas(ambil()))
    except Exception as e:
        hasil["tidak_tersedia"] = f"{type(e).__name__}: {str(e)[:100]}"
    print(json.dumps(hasil, ensure_ascii=False, separators=(",", ":")))


if __name__ == "__main__":
    sys.exit(main())
