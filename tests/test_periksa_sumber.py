import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "cloud"))
import periksa_sumber as ps  # noqa: E402


def test_status_blok_dan_rahasia_dibersihkan():
    brief = ("[TEKNIKAL (indicators.py)]\n{\"rsi\": 50}\n\n"
             "[SETUP DEVIATION (deviasi.py)]\nGAGAL DIAMBIL — kode keluar bukan 0\n\n"
             "[KEPEMILIKAN (investors.py)]\n{\"error\": \"Gagal untuk 0x1234567890abcdef1234 "
             "https://api.x.com/a?key=RAHASIA\"}\n\n"
             "[KOSONG (x.py)]\n{}")
    blok = {j: ps.nilai_blok(j, isi) for j, isi in ps.pecah_blok(brief)}
    assert blok["TEKNIKAL (indicators.py)"][0] == "OK"
    assert blok["SETUP DEVIATION (deviasi.py)"][0] == "GAGAL"
    st, masalah = blok["KEPEMILIKAN (investors.py)"]
    assert st == "SEBAGIAN" and "0x1234" not in masalah[0] and "RAHASIA" not in masalah[0]
    assert blok["KOSONG (x.py)"][0] == "KOSONG"
