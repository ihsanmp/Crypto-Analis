"""Kalibrasi skor 0-100 panggilan bot — DIDAFTARKAN SEBELUM DIJALANKAN (16 Okt 2026).

Pertanyaan: apakah panggilan berskor tinggi LEBIH SERING benar daripada yang berskor
rendah, dan kalau ya, berapa peluang benar untuk skor tertentu?

ATURAN (ditetapkan sebelum melihat hasil):
  1. Unit sampel = EPISODE, bukan panggilan. Panggilan aset yang sama dalam 72 jam adalah
     analisa ulang atas keadaan yang sama (rapor 9 Agu 2026: NVDA tiga kali di harga yang
     sama; 30 Sep: SOL dua kali dalam 13 menit) — hasilnya berkorelasi, jadi satu episode
     diwakili panggilan PERTAMA-nya (pandangan awal, bebas dari tinjauan ulang).
  2. "Benar" = rapor._benar (sadar arah: HINDARI/KURANGI benar bila tertinggal dari pasar).
  3. Hubungan skor-hasil diuji dengan korelasi peringkat + uji permutasi 5.000x (satu sisi).
  4. TERKALIBRASI hanya bila episode yang sudah dinilai >= 60 DAN p < 0,05 DAN korelasi > 0.
     Baru saat itu skor dipetakan ke peluang benar lewat regresi logistik.
  5. Selama belum terkalibrasi, bot DILARANG menyajikan skor sebagai peluang atau tingkat
     keyakinan terukur (catatan ini masuk brief lewat rapor.catatan_untuk_brief).
  Kalibrasi tetap keputusan MANUSIA: berkas ini tidak mengubah ambang di analisa.md.

    python cloud/kalibrasi_skor.py
"""
import json
import math
import os
import random
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import rapor  # noqa: E402

JENDELA_EPISODE_JAM = 72
EPISODE_MINIMUM = 60
P_MAKS = 0.05
PERMUTASI = 5000
BENIH = 20261016


def _waktu(e):
    return datetime.strptime(e["tanggal_utc"], "%Y-%m-%d %H:%M").replace(tzinfo=timezone.utc)


def episode(entri, jam=JENDELA_EPISODE_JAM):
    """[[panggilan,...], ...] — aset sama & selisih <= `jam` dari panggilan pertama."""
    urut = sorted((e for e in entri if e.get("tanggal_utc")), key=_waktu)
    kelompok, terakhir = [], {}
    for e in urut:
        k = (e.get("aset_asli") or e.get("aset"), e.get("jenis"))
        i = terakhir.get(k)
        if i is not None and _waktu(e) - _waktu(kelompok[i][0]) <= timedelta(hours=jam):
            kelompok[i].append(e)
        else:
            terakhir[k] = len(kelompok)
            kelompok.append([e])
    return kelompok


def wilson(benar, n, z=1.96):
    if not n:
        return None
    p = benar / n
    pusat = (p + z * z / (2 * n)) / (1 + z * z / n)
    lebar = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return round(max(0, pusat - lebar) * 100), round(min(1, pusat + lebar) * 100)


def _peringkat(x):
    urut = sorted(range(len(x)), key=lambda i: x[i])
    r = [0.0] * len(x)
    i = 0
    while i < len(urut):
        j = i
        while j + 1 < len(urut) and x[urut[j + 1]] == x[urut[i]]:
            j += 1
        for k in range(i, j + 1):
            r[urut[k]] = (i + j) / 2
        i = j + 1
    return r


def _korelasi(a, b):
    ra, rb = _peringkat(a), _peringkat(b)
    n = len(a)
    ma, mb = sum(ra) / n, sum(rb) / n
    kov = sum((x - ma) * (y - mb) for x, y in zip(ra, rb))
    va = math.sqrt(sum((x - ma) ** 2 for x in ra))
    vb = math.sqrt(sum((y - mb) ** 2 for y in rb))
    return kov / (va * vb) if va and vb else 0.0


def kalibrasi(entri, sekarang=None):
    sekarang = sekarang or datetime.now(timezone.utc)
    eps = episode(entri)
    wakil = [ep[0] for ep in eps]
    dinilai = [(e["skor"], 1 if rapor._benar(e) else 0) for e in wakil
               if e.get("skor") is not None and rapor._benar(e) is not None]
    hasil = {"panggilan": len(entri), "episode": len(eps), "episode_dinilai": len(dinilai),
             "aturan": f"terkalibrasi bila >= {EPISODE_MINIMUM} episode dinilai, p < {P_MAKS}"}
    per_pita = {}
    for s, b in dinilai:
        per_pita.setdefault(rapor._kelompok_skor(s), []).append(b)
    hasil["per_rentang_skor"] = {
        k: {"episode": len(v), "benar_persen": round(sum(v) / len(v) * 100),
            "selang_95": wilson(sum(v), len(v))} for k, v in sorted(per_pita.items())}
    skor_set = sorted({s for s, _ in dinilai})
    hasil["rentang_skor_teramati"] = [skor_set[0], skor_set[-1]] if skor_set else None
    if len(dinilai) >= 5 and len({b for _, b in dinilai}) == 2:
        s, b = [x[0] for x in dinilai], [x[1] for x in dinilai]
        r = _korelasi(s, b)
        rng = random.Random(BENIH)
        lebih = 0
        for _ in range(PERMUTASI):
            acak = b[:]
            rng.shuffle(acak)
            if _korelasi(s, acak) >= r:
                lebih += 1
        hasil["korelasi_skor_hasil"] = round(r, 3)
        hasil["p_permutasi"] = round((lebih + 1) / (PERMUTASI + 1), 4)
    lolos = (len(dinilai) >= EPISODE_MINIMUM and hasil.get("p_permutasi", 1) < P_MAKS
             and hasil.get("korelasi_skor_hasil", 0) > 0)
    hasil["status"] = "TERKALIBRASI" if lolos else "BELUM TERKALIBRASI"
    if lolos:
        import model_kuant as mk
        a, b_ = mk.logistik([x[0] / 100 for x in dinilai], [x[1] for x in dinilai])
        hasil["peta_peluang_benar"] = {str(s): round(mk.sigmoid(a + b_ * s / 100) * 100)
                                       for s in (30, 45, 60, 75, 90)}
    else:
        # Laju episode baru -> perkiraan kapan sampel cukup (hanya perkiraan kasar).
        if eps:
            mulai = _waktu(eps[0][0])
            bulan = max((sekarang - mulai).days / 30.4, 0.5)
            laju = len(eps) / bulan
            kurang = max(EPISODE_MINIMUM - len(dinilai), 0)
            hasil["laju_episode_per_bulan"] = round(laju, 1)
            hasil["perkiraan_bulan_lagi"] = round(kurang / laju, 1) if laju else None
    return hasil


def catatan_brief(entri):
    """Satu baris untuk brief selama skor belum terkalibrasi. None bila sudah."""
    k = kalibrasi(entri)
    if k["status"] == "TERKALIBRASI":
        return ("SKOR 0-100 TERKALIBRASI: peluang benar menurut skor "
                + ", ".join(f"{s}->{p}%" for s, p in k["peta_peluang_benar"].items()))
    return (f"SKOR 0-100 BELUM TERKALIBRASI ({k['episode_dinilai']} dari {EPISODE_MINIMUM} "
            "episode independen yang dibutuhkan). Jangan sajikan skor sebagai peluang atau "
            "tingkat keyakinan terukur; sebut sebagai penilaian kualitatif.")


def main():
    print(json.dumps(kalibrasi(rapor._muat()), indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
