"""Kontak SEC untuk header User-Agent — satu tempat, dibaca dari secret SEC_CONTACT.

KENAPA ADA: SEC mewajibkan setiap permintaan otomatis menyertakan identitas DAN alamat
kontak yang bisa dihubungi (kebijakan fair access). Tanpa itu, permintaan dibalas HTTP 403
— dan 403 itu tidak menjelaskan dirinya sendiri: di stockfund.py ia terbaca persis seperti
"emiten tidak ditemukan". Jadi alamat ini FUNGSIONAL, bukan hiasan.

KENAPA DARI SECRET: repo ini PUBLIK. Alamat yang ditulis di kode terbuka untuk pemanen
alamat, dan sebelumnya alamat pribadi pemilik repo memang tertulis di tiga berkas sekaligus
(konteks.py, sec_tickers.py, stockfund.py). Nilainya kini hanya hidup di lingkungan run.

CATATAN JUJUR: alamat lama tetap ada di RIWAYAT git. Pemindahan ini menghentikan paparan
ke depan, bukan menghapus jejak lama — itu butuh penulisan ulang riwayat.
"""

import os
import re

NAMA_ENV = "SEC_CONTACT"
IDENTITAS = "Crypto-Analis Research bot"
# Bukan validasi email yang ketat (tidak ada yang benar-benar ketat) — hanya menolak nilai
# yang JELAS bukan alamat, karena kontak tak valid berujung 403 yang sama membingungkannya.
_RE_EMAIL = re.compile(r"^[^@\s]+@[^@\s.]+\.[^@\s]+$")


def kontak():
    """Alamat kontak dari secret. "" kalau kosong atau jelas bukan email."""
    nilai = os.environ.get(NAMA_ENV, "").strip().strip('"\'').strip()
    return nilai if _RE_EMAIL.match(nilai) else ""


def header():
    """Header User-Agent untuk SEC. Tanpa kontak, identitasnya tetap dikirim apa adanya —
    SEC akan menolak, dan pemanggil yang memeriksa alasan_kosong() bisa menjelaskannya."""
    alamat = kontak()
    return {"User-Agent": f"{IDENTITAS} {alamat}".strip()}


def alasan_kosong():
    """Pesan siap pakai saat kontaknya belum ada. None kalau semuanya beres."""
    if kontak():
        return None
    return (f"{NAMA_ENV} belum di-set (atau isinya bukan alamat email). SEC mewajibkan "
            "kontak di User-Agent, jadi permintaan akan dibalas HTTP 403 — yang mudah "
            "disalahartikan sebagai emiten tidak ditemukan. Isi secret SEC_CONTACT dengan "
            "alamat email aktif.")
