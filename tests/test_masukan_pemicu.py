import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "cloud"))
import bot_oneshot as bot  # noqa: E402


@pytest.mark.parametrize("teks,masukan", [
    # Kosakata PERTANYAAN pasar — dulu memicu ekstraksi aturan di setiap prediksi.
    ("btc 3 bulan ke depan gimana peluangnya?", False),
    ("prediksi eth seminggu ke depan", False),
    ("target selanjutnya berapa?", False),
    ("performa sol kedepan", False),
    # Bentuk INSTRUKSI tetap tertangkap.
    ("ke depannya jangan pakai 4H", True),
    ("selanjutnya tolong lebih singkat", True),
    ("ke depan jangan pakai emoji", True),
    ("mulai sekarang pakai H4", True),
])
def test_ke_depan_dan_selanjutnya_hanya_bentuk_instruksi(teks, masukan):
    assert bot.minta_belajar(teks) is masukan
