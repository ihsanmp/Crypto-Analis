"""Penjaga: tes tidak boleh mengubah state produksi di cloud/data/.

Suite ini sudah hermetik terhadap JARINGAN (socket.connect diblokir), tapi tidak
terhadap BERKAS. Sebuah tes yang memanggil process() ujung-ke-ujung menimpa
cloud/data/diproses.json dan menulisi dua cache lain — dan karena alur commit di
proyek ini memakai `git add -A`, state produksi yang rusak itu nyaris ikut ter-commit.
Kerusakannya senyap: tidak ada tes yang merah, hanya isinya yang berubah.

Di sini state-nya disidik sebelum sesi dan diperiksa sesudahnya. Yang berubah
dipulihkan dari git, dan sesinya DIMERAHKAN — dipulihkan diam-diam berarti tes
berikutnya yang menulisi produksi tidak akan pernah ketahuan.
"""
import hashlib
import os
import subprocess

AKAR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(AKAR, "cloud", "data")
_sidik = {}


def _sidik_data():
    hasil = {}
    for akar, _, berkas in os.walk(DATA):
        for b in berkas:
            p = os.path.join(akar, b)
            try:
                with open(p, "rb") as f:
                    hasil[p] = hashlib.sha256(f.read()).hexdigest()
            except OSError:
                pass
    return hasil


def _alihkan_cache_sec():
    """Arahkan cache SEC ke tmp, DISALIN dari yang asli.

    peta_ticker() menulis ulang cache-nya begitu umurnya lewat 7 hari, dan cache itu
    ikut ter-commit. Pemanggilnya bukan cuma satu tes: _semua_aset() memanggilnya untuk
    hampir setiap pesan, jadi tes routing mana pun ikut memicunya begitu fetch ke SEC
    kebetulan berhasil — dan itu membuat CI merah dengan cara yang tidak menunjuk ke
    tes mana pun secara khusus.

    DISALIN, bukan dikosongkan: cache kosong memaksa setiap tes menembak jaringan.
    """
    import shutil
    import tempfile
    d = tempfile.mkdtemp(prefix="cache_sec_")
    for akhiran in (".gz", ""):
        asal = os.path.join(DATA, "sec_tickers_cache.json" + akhiran)
        if os.path.exists(asal):
            shutil.copyfile(asal, os.path.join(d, os.path.basename(asal)))
    os.environ["CACHE_DIR_SEC"] = d


def pytest_sessionstart(session):
    _alihkan_cache_sec()
    _sidik.update(_sidik_data())


def pytest_sessionfinish(session, exitstatus):
    sesudah = _sidik_data()
    berubah = sorted(
        {p for p in set(_sidik) | set(sesudah) if _sidik.get(p) != sesudah.get(p)})
    if not berubah:
        return
    nama = [os.path.relpath(p, AKAR).replace(os.sep, "/") for p in berubah]
    subprocess.run(["git", "checkout", "--"] + nama, cwd=AKAR,
                   capture_output=True, text=True)
    print("")
    print("TES MENULISI STATE PRODUKSI (sudah dipulihkan dari git):")
    for n in nama:
        print("  - " + n)
    print("Arahkan penulisan ke tmp_path/tempfile, jangan ke cloud/data/.")
    session.exitstatus = 1
