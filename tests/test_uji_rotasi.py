"""Tes uji_rotasi.py — logika uji 'konsep elevator' dengan data buatan yang jawabannya
sudah diketahui, sebelum dipakai pada data nyata."""

import os
import sys

AKAR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(AKAR, "cloud"))

import uji_rotasi as U  # noqa: E402


def _seri(harian):
    return {d: p for d, p in enumerate(harian)}


def _dunia(rotasi_nyata):
    """3 pemimpin melonjak +20% tiap 14 hari; 3 anggota diam (kandidat), 3 anggota ikut naik.
    rotasi_nyata=True: kandidat menyusul +15% di minggu sesudahnya."""
    n = 120
    seri = {}
    for i in range(3):                                    # pemimpin
        seri[f"pem{i}"] = _seri([100 * (1.2 ** (d // 14)) for d in range(n)])
    for i in range(3):                                    # sudah ikut naik
        seri[f"ikut{i}"] = _seri([100 * (1.15 ** (d // 14)) for d in range(n)])
    for i in range(3):                                    # kandidat
        if rotasi_nyata:
            seri[f"kand{i}"] = _seri([100 * (1.15 ** ((d + 7) // 14)) for d in range(n)])
        else:
            seri[f"kand{i}"] = _seri([100.0] * n)
    ids = [f"pem{i}" for i in range(3)] + [f"ikut{i}" for i in range(3)] + [f"kand{i}" for i in range(3)]
    return ids, seri


def test_rotasi_nyata_terdeteksi():
    ids, seri = _dunia(rotasi_nyata=True)
    ev = U.peristiwa(ids, seri)
    assert ev, "harus ada minggu peristiwa"
    selisih = [k - s for _, k, s, _, _ in ev]
    assert sum(selisih) / len(selisih) > 0


def test_tanpa_rotasi_kandidat_tidak_unggul():
    ids, seri = _dunia(rotasi_nyata=False)
    ev = U.peristiwa(ids, seri)
    selisih = [k - s for _, k, s, _, _ in ev]
    assert selisih and sum(selisih) / len(selisih) <= 0


def test_koin_baru_listing_tidak_memangkas_data_yang_lain():
    """Versi pertama memakai IRISAN hari semua koin."""
    ids, seri = _dunia(rotasi_nyata=True)
    seri["kand2"] = {d: p for d, p in seri["kand2"].items() if d >= 100}   # baru listing
    assert len(U.peristiwa(ids, seri)) >= 3


def test_minggu_tanpa_data_pemimpin_dilewati():
    ids, seri = _dunia(rotasi_nyata=True)
    penuh = len(U.peristiwa(ids, seri))
    seri["pem0"] = {d: p for d, p in seri["pem0"].items() if d >= 60}
    assert len(U.peristiwa(ids, seri)) < penuh


def test_bootstrap_nol_untuk_selisih_simetris():
    rata, p = U._boot([1.0, -1.0] * 20)
    assert abs(rata) < 1e-9 and p > 0.5
