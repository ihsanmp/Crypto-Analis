"""Uji "konsep elevator" mentor #2 — setelah pemimpin kategori naik, apakah koin besar yang
BELUM bergerak benar-benar menyusul?

Aturan pemimpin & kandidat SAMA PERSIS dengan rotasi.py (pemimpin_dan_kandidat()), supaya
yang diuji adalah yang dipakai bot.

DESAIN (ditetapkan sebelum melihat hasil):
  - Kategori: tema besar yang dipakai mentor + ekosistem Solana (koin asli saja).
  - Data: harga harian CoinGecko 365 hari (batas paket gratis/demo).
  - Tiap minggu (jendela 7 hari tak tumpang tindih): pemimpin = 3 market cap teratas,
    anggota = peringkat 4–15. Minggu itu jadi PERISTIWA bila pemimpin terbaik naik ≥ +10%.
  - Kandidat = anggota yang 7 harinya di [−10%, min(+10%, setengah pemimpin terbaik)).
  - UKURAN UTAMA: pada tiap minggu peristiwa, return 7 hari SESUDAHNYA rata-rata kandidat
    DIKURANGI rata-rata seluruh anggota di minggu yang sama. Rotasi nyata = kandidat
    mengungguli rekan satu narasinya. Pembandingnya di minggu yang sama, jadi arah pasar
    minggu itu tidak ikut terhitung.
  - Signifikansi: bootstrap per minggu peristiwa (5.000 kali).
  - Sekunder: horizon 14 hari.

BATAS YANG DIAKUI: keanggotaan kategori dan peringkat market cap diambil HARI INI
(survivorship) — koin yang tumbang dan keluar dari kategori tidak ada. Bias itu menaikkan
return semua anggota, tapi ukuran utamanya membandingkan anggota dengan anggota di minggu
yang sama, sehingga sebagian besar biasnya saling meniadakan. Satu tahun data = puluhan
minggu peristiwa, bukan ratusan.

Butuh COINGECKO_DEMO_KEY (± 90 permintaan) — dijalankan di runner lewat workflow
"Uji rotasi narasi".
"""

import json
import os
import random
import sys
import time
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import kategori  # noqa: E402
import rotasi  # noqa: E402

KATEGORI_UJI = ["artificial-intelligence", "meme-token", "real-world-assets-rwa",
                "decentralized-finance-defi", "layer-2", "gaming"]
EKOSISTEM_UJI = ("solana-ecosystem", {"solana"})
ANGGOTA_N = 15
HARI = 365
JEDA = 2.2
N_BOOT = 5000
SEED = 7


def _get(url):
    req = urllib.request.Request(url, headers={**kategori.UA,
                                               **kategori.cgkunci.header_untuk(url)})
    for coba in range(3):
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.loads(r.read().decode(errors="replace"))
        except Exception as e:
            if getattr(e, "code", None) == 429 and coba < 2:
                time.sleep(30)
                continue
            return None
    return None


def harga_harian(cid):
    d = _get(f"{kategori.API}/coins/{cid}/market_chart?vs_currency=usd&days={HARI}"
             "&interval=daily")
    time.sleep(JEDA)
    if not d or not d.get("prices"):
        return None
    return {int(ts // 86400000): p for ts, p in d["prices"] if p}


def anggota(kat_id, platform=None, kunci=None, kecuali=()):
    d = _get(f"{kategori.API}/coins/markets?vs_currency=usd&category={kat_id}"
             "&order=market_cap_desc&per_page=100&page=1")
    time.sleep(JEDA)
    out = []
    for c in d or []:
        if c.get("id") in kecuali:
            continue
        if platform is not None and platform.get(c.get("id"), "") not in kunci:
            continue
        k = {"id": c["id"], "simbol": (c.get("symbol") or "").upper(),
             "harga": c.get("current_price"),
             "ubah_7h": c.get("price_change_percentage_7d_in_currency") or 0}
        if rotasi._mirip_stabil(k):
            continue
        out.append(c["id"])
        if len(out) >= ANGGOTA_N:
            break
    return out


def _ret(seri, a, b):
    if a in seri and b in seri and seri[a] > 0:
        return 100 * (seri[b] / seri[a] - 1)
    return None


def peristiwa(ids, seri):
    """[(hari, kandidat_fwd7, semua_fwd7, kandidat_fwd14, semua_fwd14)] tiap minggu peristiwa."""
    # GABUNGAN hari, bukan irisan: satu koin yang baru listing tidak boleh memangkas
    # setahun data milik yang lain jadi beberapa minggu.
    hari_semua = sorted(set().union(*[set(seri[i]) for i in ids if i in seri]))
    if len(hari_semua) < 40:
        return []
    pem_ids = ids[:rotasi.PEMIMPIN]
    out = []
    for d in hari_semua[7:-14:7]:
        # Pemimpin harus LENGKAP minggu itu; kalau tidak, posisinya diam-diam diisi koin
        # berikutnya dan yang diuji bukan lagi pemimpin yang sama.
        if any(_ret(seri.get(i, {}), d - 7, d) is None for i in pem_ids):
            continue
        koin = []
        for urut, i in enumerate(ids):
            r7 = _ret(seri.get(i, {}), d - 7, d)
            if r7 is None:
                continue
            # Volume tidak tersedia historis: saringan likuiditas tidak ikut diuji.
            koin.append({"id": i, "simbol": i, "mcap": 1e12 - urut, "volume": 1e12,
                         "ubah_7h": r7, "ubah_30h": None})
        h = rotasi.pemimpin_dan_kandidat(koin)
        if not h["pemimpin_bergerak"] or not h["kandidat"]:
            continue
        anggota_ids = [k["id"] for k in koin[rotasi.PEMIMPIN:]]
        kand_ids = [k["id"] for k in h["kandidat"]]

        def rata(ids_, maju):
            v = [_ret(seri.get(i, {}), d, d + maju) for i in ids_]
            v = [x for x in v if x is not None]
            return sum(v) / len(v) if v else None

        k7, s7, k14, s14 = rata(kand_ids, 7), rata(anggota_ids, 7), rata(kand_ids, 14), rata(anggota_ids, 14)
        if None not in (k7, s7, k14, s14):
            out.append((d, k7, s7, k14, s14))
    return out


def _boot(selisih):
    if not selisih:
        return None, None
    rata = sum(selisih) / len(selisih)
    rng = random.Random(SEED)
    pusat = [x - rata for x in selisih]          # hipotesis nol: selisih rata-rata 0
    lebih = 0
    for _ in range(N_BOOT):
        s = [rng.choice(pusat) for _ in pusat]
        if abs(sum(s) / len(s)) >= abs(rata):
            lebih += 1
    return rata, (lebih + 1) / (N_BOOT + 1)


def main():
    try:
        import musim
        kecuali = musim.dikecualikan() or set()
    except Exception:
        kecuali = set()
    kelompok = {k: anggota(k, kecuali=kecuali) for k in KATEGORI_UJI}
    platform = rotasi.platform_utama()
    if platform:
        kelompok["solana-ecosystem (asli)"] = anggota(EKOSISTEM_UJI[0], platform,
                                                      EKOSISTEM_UJI[1], kecuali)
    seri, semua = {}, sorted({i for v in kelompok.values() for i in v})
    for i in semua:
        s = harga_harian(i)
        if s:
            seri[i] = s
    hasil, gabung7, gabung14 = {}, [], []
    for nama, ids in kelompok.items():
        ids = [i for i in ids if i in seri]
        ev = peristiwa(ids, seri) if len(ids) >= rotasi.PEMIMPIN + 3 else []
        s7 = [k - s for _, k, s, _, _ in ev]
        s14 = [k - s for _, _, _, k, s in ev]
        gabung7 += s7
        gabung14 += s14
        r7, p7 = _boot(s7)
        hasil[nama] = {"koin": len(ids), "minggu_peristiwa": len(ev),
                       "selisih_7h_rata": None if r7 is None else round(r7, 2),
                       "p_7h": None if p7 is None else round(p7, 3),
                       "minggu_kandidat_unggul": sum(1 for x in s7 if x > 0)}
    r7, p7 = _boot(gabung7)
    r14, p14 = _boot(gabung14)
    print(json.dumps({"per_kelompok": hasil, "gabungan": {
        "minggu_peristiwa": len(gabung7),
        "selisih_7h_rata_poin_persen": None if r7 is None else round(r7, 2), "p_7h": p7 and round(p7, 3),
        "minggu_kandidat_unggul_7h": sum(1 for x in gabung7 if x > 0),
        "selisih_14h_rata_poin_persen": None if r14 is None else round(r14, 2), "p_14h": p14 and round(p14, 3)},
        "koin_berdata": len(seri), "koin_diminta": len(semua)}, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
