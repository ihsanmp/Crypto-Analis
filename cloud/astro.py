"""Mesin astronomi untuk analisa astro-trading — pustaka standar Python saja, gratis.

KENAPA DITULIS SENDIRI. Runner bot tidak memasang pustaka astronomi apa pun, dan dua
pilihan yang biasa dipakai sama-sama bermasalah untuk repo ini:
  - pyswisseph (dipakai pyAstroTrader) berlisensi AGPL/komersial;
  - kode pyAstroTrader sendiri TIDAK berlisensi, dan jesse-astrology-trading-strategy
    AGPL-3.0 — keduanya tidak boleh disalin ke repo ini.
Yang dipakai di sini adalah data publik NASA/JPL: "Keplerian Elements for Approximate
Positions of the Major Planets" (E.M. Standish, Tabel 1, berlaku 1800–2050), dan deret
utama teori Bulan dari Meeus (Astronomical Algorithms, bab 47). Ketelitiannya ~0,1–0,3°,
jauh lebih kecil dari orb aspek (beberapa derajat) — cukup untuk astro-trading harian.

KETELITIANNYA DIBUKTIKAN, BUKAN DIANGGAP. tests/test_astro.py mencocokkan keluaran modul
ini dengan peristiwa langit yang tanggalnya sudah pasti: konjungsi besar Jupiter–Saturnus
21 Des 2020, stasiun retrograde Merkurius 2024, retrograde Mars 2022–23 dan Venus 2023,
gerhana matahari 8 Apr 2024, ekuinoks Maret. Kalau satu elemen orbit salah ketik,
tanggal-tanggal itu bergeser dan tesnya gagal.

ZODIAK TROPIS. Elemen JPL mengacu ke ekliptika J2000; astrologi memakai ekuinoks tanggal
berjalan. Selisihnya presesi ~1,397°/abad, ditambahkan ke semua bujur. Untuk ASPEK
(selisih dua planet) presesi saling meniadakan — hanya posisi zodiaknya yang terpengaruh.

Pemakaian:
    python cloud/astro.py                 # posisi hari ini + peristiwa 30 hari ke depan
    python cloud/astro.py --tanggal 2026-10-01 --hari 60 --json
"""

import argparse
import datetime as dt
import json
import math

# --- Elemen orbit JPL (Standish), Tabel 1: 1800 M – 2050 M ------------------------------
# (a au, e, I°, L°, bujur perihelion°, bujur simpul naik°) dan lajunya per abad.
_ELEMEN = {
    "Merkurius": ((0.38709927, 0.20563593, 7.00497902, 252.25032350, 77.45779628, 48.33076593),
                  (0.00000037, 0.00001906, -0.00594749, 149472.67411175, 0.16047689, -0.12534081)),
    "Venus": ((0.72333566, 0.00677672, 3.39467605, 181.97909950, 131.60246718, 76.67984255),
              (0.00000390, -0.00004107, -0.00078890, 58517.81538729, 0.00268329, -0.27769418)),
    "Bumi": ((1.00000261, 0.01671123, -0.00001531, 100.46457166, 102.93768193, 0.0),
             (0.00000562, -0.00004392, -0.01294668, 35999.37244981, 0.32327364, 0.0)),
    "Mars": ((1.52371034, 0.09339410, 1.84969142, -4.55343205, -23.94362959, 49.55953891),
             (0.00001847, 0.00007882, -0.00813131, 19140.30268499, 0.44441088, -0.29257343)),
    "Jupiter": ((5.20288700, 0.04838624, 1.30439695, 34.39644051, 14.72847983, 100.47390909),
                (-0.00011607, -0.00013253, -0.00183714, 3034.74612775, 0.21252668, 0.20469106)),
    "Saturnus": ((9.53667594, 0.05386179, 2.48599187, 49.95424423, 92.59887831, 113.66242448),
                 (-0.00125060, -0.00050991, 0.00193609, 1222.49362201, -0.41897216, -0.28867794)),
    "Uranus": ((19.18916464, 0.04725744, 0.77263783, 313.23810451, 170.95427630, 74.01692503),
               (-0.00196176, -0.00004397, -0.00242939, 428.48202785, 0.40805281, 0.04240589)),
    "Neptunus": ((30.06992276, 0.00859048, 1.77004347, -55.12002969, 44.96476227, 131.78422574),
                 (0.00026291, 0.00005105, 0.00035372, 218.45945325, -0.32241464, -0.00508664)),
}
BENDA = ["Matahari", "Bulan", "Merkurius", "Venus", "Mars", "Jupiter", "Saturnus",
         "Uranus", "Neptunus"]
# Yang bisa retrograde (Matahari & Bulan tidak pernah).
BISA_MUNDUR = ["Merkurius", "Venus", "Mars", "Jupiter", "Saturnus", "Uranus", "Neptunus"]

# Aspek mayor (dokumen riset user, Bagian A.2) dan orb. Orb DITETAPKAN SEKALI di sini —
# memilih orb sesudah melihat hasil uji adalah cara termudah "menemukan" efek.
ASPEK = {0: "konjungsi", 60: "sextile", 90: "square", 120: "trine", 180: "oposisi"}
ORB = 6.0
PRESESI_PER_ABAD = 1.396971
ZODIAK = ["Aries", "Taurus", "Gemini", "Cancer", "Leo", "Virgo", "Libra", "Scorpio",
          "Sagittarius", "Capricorn", "Aquarius", "Pisces"]


def _jd_utc(t):
    if isinstance(t, dt.date) and not isinstance(t, dt.datetime):
        t = dt.datetime(t.year, t.month, t.day, 12, tzinfo=dt.timezone.utc)
    if t.tzinfo is None:
        t = t.replace(tzinfo=dt.timezone.utc)
    return 2440587.5 + t.timestamp() / 86400.0


def _norm(x):
    return x % 360.0


def _helio(nama, T):
    """Koordinat ekliptika heliosentris J2000 (au) — resep JPL apa adanya."""
    e0, laju = _ELEMEN[nama]
    a, e, I, L, wbar, node = (x + d * T for x, d in zip(e0, laju))
    w = wbar - node
    M = (L - wbar + 180.0) % 360.0 - 180.0
    ed = math.degrees(e)
    E = M + ed * math.sin(math.radians(M))
    for _ in range(12):
        dM = M - (E - ed * math.sin(math.radians(E)))
        dE = dM / (1 - e * math.cos(math.radians(E)))
        E += dE
        if abs(dE) < 1e-8:
            break
    xp = a * (math.cos(math.radians(E)) - e)
    yp = a * math.sqrt(1 - e * e) * math.sin(math.radians(E))
    w, node, I = math.radians(w), math.radians(node), math.radians(I)
    x = ((math.cos(w) * math.cos(node) - math.sin(w) * math.sin(node) * math.cos(I)) * xp
         + (-math.sin(w) * math.cos(node) - math.cos(w) * math.sin(node) * math.cos(I)) * yp)
    y = ((math.cos(w) * math.sin(node) + math.sin(w) * math.cos(node) * math.cos(I)) * xp
         + (-math.sin(w) * math.sin(node) + math.cos(w) * math.cos(node) * math.cos(I)) * yp)
    z = math.sin(w) * math.sin(I) * xp + math.cos(w) * math.sin(I) * yp
    return x, y, z


def _bulan(T):
    """(bujur, lintang) Bulan, ekuinoks tanggal berjalan — suku utama Meeus bab 47."""
    Lp = 218.3164477 + 481267.88123421 * T
    D = math.radians(297.8501921 + 445267.1114034 * T)
    M = math.radians(357.5291092 + 35999.0502909 * T)
    Mp = math.radians(134.9633964 + 477198.8675055 * T)
    F = math.radians(93.2720950 + 483202.0175233 * T)
    lon = (Lp + 6.288774 * math.sin(Mp) + 1.274027 * math.sin(2 * D - Mp)
           + 0.658314 * math.sin(2 * D) + 0.213618 * math.sin(2 * Mp)
           - 0.185116 * math.sin(M) - 0.114332 * math.sin(2 * F)
           + 0.058793 * math.sin(2 * D - 2 * Mp) + 0.057066 * math.sin(2 * D - M - Mp)
           + 0.053322 * math.sin(2 * D + Mp) + 0.045758 * math.sin(2 * D - M)
           - 0.040923 * math.sin(M - Mp) - 0.034720 * math.sin(D)
           - 0.030383 * math.sin(M + Mp))
    lat = (5.128122 * math.sin(F) + 0.280602 * math.sin(Mp + F)
           + 0.277693 * math.sin(Mp - F) + 0.173237 * math.sin(2 * D - F))
    return _norm(lon), lat


def posisi(t):
    """{benda: (bujur tropis°, lintang°)} geosentris pada waktu t (UTC)."""
    T = (_jd_utc(t) - 2451545.0) / 36525.0
    pres = PRESESI_PER_ABAD * T
    bx, by, bz = _helio("Bumi", T)
    hasil = {"Matahari": (_norm(math.degrees(math.atan2(-by, -bx)) + pres),
                          math.degrees(math.atan2(-bz, math.hypot(bx, by))))}
    for nama in BISA_MUNDUR:
        x, y, z = _helio(nama, T)
        gx, gy, gz = x - bx, y - by, z - bz
        hasil[nama] = (_norm(math.degrees(math.atan2(gy, gx)) + pres),
                       math.degrees(math.atan2(gz, math.hypot(gx, gy))))
    hasil["Bulan"] = _bulan(T)
    return {n: hasil[n] for n in BENDA}


def deklinasi(bujur, lintang, t):
    """Deklinasi (°) dari koordinat ekliptika — untuk Out of Bounds (dokumen riset A.2)."""
    T = (_jd_utc(t) - 2451545.0) / 36525.0
    eps = math.radians(23.439291 - 0.0130042 * T)
    lam, bet = math.radians(bujur), math.radians(lintang)
    return math.degrees(math.asin(math.sin(bet) * math.cos(eps)
                                  + math.cos(bet) * math.sin(eps) * math.sin(lam)))


def kemiringan(t):
    T = (_jd_utc(t) - 2451545.0) / 36525.0
    return 23.439291 - 0.0130042 * T


def selisih(a, b):
    """Jarak sudut terpendek 0..180°."""
    d = abs(_norm(a) - _norm(b)) % 360.0
    return 360.0 - d if d > 180 else d


def mundur(nama, t):
    """True kalau bujur geosentrisnya sedang BERKURANG (retrograde)."""
    a = posisi(t - dt.timedelta(hours=12))[nama][0]
    b = posisi(t + dt.timedelta(hours=12))[nama][0]
    return ((b - a + 540.0) % 360.0 - 180.0) < 0


def fase_bulan(t):
    """Elongasi Bulan dari Matahari 0..360° (0 = bulan baru, 180 = purnama)."""
    p = posisi(t)
    return _norm(p["Bulan"][0] - p["Matahari"][0])


def zodiak(bujur):
    i = int(_norm(bujur) // 30)
    return f"{_norm(bujur) - 30 * i:.1f}° {ZODIAK[i]}"


def aspek_aktif(t, orb=ORB):
    """Aspek mayor yang sedang dalam orb: [(benda1, benda2, nama_aspek, meleset°)]."""
    p = posisi(t)
    keluar = []
    for i, a in enumerate(BENDA):
        for b in BENDA[i + 1:]:
            s = selisih(p[a][0], p[b][0])
            for sudut, nama in ASPEK.items():
                if abs(s - sudut) <= orb:
                    keluar.append((a, b, nama, round(s - sudut, 2)))
    return keluar


def _t12(d):
    return dt.datetime(d.year, d.month, d.day, 12, tzinfo=dt.timezone.utc)


def peristiwa(mulai, hari=30, tanpa_bulan_aspek=True):
    """Peristiwa langit di [mulai, mulai+hari): stasiun retrograde, aspek eksak antar
    planet, bulan baru/purnama, masuk/keluar Out of Bounds. Resolusi harian (UTC).

    Aspek yang melibatkan Bulan dilewati secara bawaan: Bulan membentuk ~40 aspek eksak
    sebulan, dan daftar sepanjang itu hanya menenggelamkan peristiwa yang jarang.
    """
    keluar = []
    hari_list = [mulai + dt.timedelta(days=i) for i in range(hari + 1)]
    pos = [posisi(_t12(d)) for d in hari_list]
    for i in range(1, len(hari_list)):
        d0, d1 = hari_list[i - 1], hari_list[i]
        p0, p1 = pos[i - 1], pos[i]
        # Stasiun: arah gerak berubah.
        for n in BISA_MUNDUR:
            if i >= 2:
                v0 = (p0[n][0] - pos[i - 2][n][0] + 540) % 360 - 180
                v1 = (p1[n][0] - p0[n][0] + 540) % 360 - 180
                if v0 > 0 >= v1:
                    keluar.append((d0.isoformat(), f"{n} mulai RETROGRADE (stasiun R)"))
                elif v0 < 0 <= v1:
                    keluar.append((d0.isoformat(), f"{n} kembali DIREK (stasiun D)"))
        # Fase bulan.
        e0 = _norm(p0["Bulan"][0] - p0["Matahari"][0])
        e1 = _norm(p1["Bulan"][0] - p1["Matahari"][0])
        if e1 < e0:
            keluar.append((d1.isoformat() if e1 < 360 - e0 else d0.isoformat(), "Bulan baru"))
        if e0 < 180 <= e1:
            keluar.append((d1.isoformat() if e1 - 180 < 180 - e0 else d0.isoformat(),
                           "Bulan purnama"))
        # Aspek eksak antar planet (termasuk Matahari).
        for a_i, a in enumerate(BENDA):
            for b in BENDA[a_i + 1:]:
                if tanpa_bulan_aspek and "Bulan" in (a, b):
                    continue
                s0, s1 = selisih(p0[a][0], p0[b][0]), selisih(p1[a][0], p1[b][0])
                for sudut, nama in ASPEK.items():
                    if (s0 - sudut) * (s1 - sudut) <= 0 and s0 != s1:
                        dekat = d0 if abs(s0 - sudut) <= abs(s1 - sudut) else d1
                        keluar.append((dekat.isoformat(), f"{a} {nama} {b}"))
        # Out of Bounds (hanya planet; Bulan terlalu sering).
        eps = kemiringan(_t12(d1))
        for n in ["Merkurius", "Venus", "Mars"]:
            dk0 = abs(deklinasi(*p0[n], _t12(d0)))
            dk1 = abs(deklinasi(*p1[n], _t12(d1)))
            if dk0 <= eps < dk1:
                keluar.append((d1.isoformat(), f"{n} masuk Out of Bounds"))
            elif dk0 > eps >= dk1:
                keluar.append((d1.isoformat(), f"{n} keluar Out of Bounds"))
    keluar.sort()
    # Buang duplikat (aspek yang tercatat di dua hari berurutan karena pembulatan).
    unik, lihat = [], set()
    for tgl, ket in keluar:
        if ket.startswith(("Bulan baru", "Bulan purnama")):
            kunci = (ket, tgl[:7] + str(int(tgl[8:]) // 3))
        else:
            kunci = (ket, tgl[:7])
        if kunci not in lihat:
            lihat.add(kunci)
            unik.append((tgl, ket))
    return unik


def fitur_harian(d):
    """Fitur numerik satu hari untuk uji & model (dokumen riset Bagian C):
    sin/cos bujur (data sirkular), flag aspek aktif, flag retrograde."""
    t = _t12(d)
    p = posisi(t)
    f = {}
    for n in BENDA:
        r = math.radians(p[n][0])
        f[f"{n}_sin"], f[f"{n}_cos"] = math.sin(r), math.cos(r)
    for a, b, nama, _ in aspek_aktif(t):
        if "Bulan" not in (a, b):
            f[f"{a}_{nama}_{b}"] = 1
    for n in ("Merkurius", "Venus", "Mars"):
        f[f"{n}_retrograde"] = 1 if mundur(n, t) else 0
    return f


# --- Blok brief: kalender WAKTU untuk setiap analisa -------------------------------------
#
# Permintaan user (24 Sep 2026): ilmu astro dipakai di SETIAP analisa, tanpa kata kunci.
# Hasil ujinya (cloud/data/astro_trading.md) null di semua lini — jadi yang masuk brief
# adalah KALENDER beserta status buktinya, dan status itu ikut di blok yang sama supaya
# tidak pernah terpisah dari tanggal-tanggalnya.

# Peristiwa yang ditampilkan: yang memang diperhatikan trader astro, bukan setiap aspek.
# Aspek Matahari/Merkurius/Venus antar sesamanya terjadi hampir tiap minggu.
_LAMBAT = {"Mars", "Jupiter", "Saturnus", "Uranus", "Neptunus"}
MAKS_PERISTIWA = 14
STATUS_BUKTI = (
    "STATUS BUKTI (cloud/data/astro_trading.md, BTC 2012–2026): dari 123 aspek & "
    "retrograde, TIDAK SATU PUN lolos uji — volatilitas maupun arah 5 hari (5 fitur "
    "p<0,05, padahal 6,2 diharapkan karena kebetulan; lolos FDR: 0). Merkurius "
    "retrograde: p=0,73. Sinyal jesse-astrology di luar sampel 47,6% (klaimnya 60%); "
    "metode pyAstroTrader tanpa kebocoran data 51,7% vs baseline 51,4%. Sajikan sebagai "
    "KALENDER yang diperhatikan trader astro, BUKAN titik balik atau sinyal.")


def _penting(ket):
    if "stasiun" in ket or ket.startswith(("Bulan baru", "Bulan purnama")):
        return True
    if "Out of Bounds" in ket:
        return True
    kata = ket.split()
    return len(kata) >= 3 and kata[0] in _LAMBAT and kata[-1] in _LAMBAT


def ringkas(mulai, hari=60):
    """Blok DATA BRIEF: posisi yang sedang retrograde + kalender peristiwa penting."""
    t = _t12(mulai)
    mundur_kini = [n for n in BISA_MUNDUR if mundur(n, t)]
    semua = [(tg, k) for tg, k in peristiwa(mulai, hari) if _penting(k)]
    tampil = semua[:MAKS_PERISTIWA]
    baris = [
        f"KALENDER WAKTU ASTRO — {mulai.isoformat()} s.d. "
        f"{(mulai + dt.timedelta(days=hari)).isoformat()} (dihitung kode, astro.py)",
        "Sedang retrograde: " + (", ".join(mundur_kini) if mundur_kini else "tidak ada"),
        f"Fase bulan hari ini: {fase_bulan(t):.0f}° (0 = baru, 180 = purnama)",
        "Peristiwa:",
    ]
    baris += [f"  {tg}  {k}" for tg, k in tampil] or ["  (tidak ada peristiwa penting)"]
    if len(semua) > len(tampil):
        baris.append(f"  … dan {len(semua) - len(tampil)} peristiwa lain sesudahnya")
    baris += ["", STATUS_BUKTI]
    return "\n".join(baris)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tanggal", default=None, help="YYYY-MM-DD (UTC), bawaan hari ini")
    ap.add_argument("--hari", type=int, default=30)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--ringkas", action="store_true", help="blok brief untuk analisa")
    a = ap.parse_args()
    d = (dt.date.fromisoformat(a.tanggal) if a.tanggal
         else dt.datetime.now(dt.timezone.utc).date())
    if a.ringkas:
        print(ringkas(d, a.hari))
        return
    t = _t12(d)
    p = posisi(t)
    data = {
        "tanggal": d.isoformat(),
        "posisi": {n: {"bujur": round(p[n][0], 2), "zodiak": zodiak(p[n][0]),
                       "retrograde": mundur(n, t) if n in BISA_MUNDUR else False}
                   for n in BENDA},
        "fase_bulan_derajat": round(fase_bulan(t), 1),
        "aspek_aktif": [f"{x} {n} {y} ({m:+.1f}°)" for x, y, n, m in aspek_aktif(t)
                        if "Bulan" not in (x, y)],
        "peristiwa": [{"tanggal": tg, "peristiwa": k} for tg, k in peristiwa(d, a.hari)],
    }
    if a.json:
        print(json.dumps(data, indent=2, ensure_ascii=False))
        return
    print(f"Posisi {d} (tropis, geosentris):")
    for n, v in data["posisi"].items():
        print(f"  {n:10} {v['zodiak']:>18}{'  R' if v['retrograde'] else ''}")
    print("Peristiwa:")
    for e in data["peristiwa"]:
        print(f"  {e['tanggal']}  {e['peristiwa']}")


if __name__ == "__main__":
    main()
