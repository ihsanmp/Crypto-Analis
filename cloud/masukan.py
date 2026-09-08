"""Masukan user yang BERTAHAN — koreksi cara kerja, bukan fakta pasar.

Bedanya dengan memori.py: memori menyimpan FAKTA yang sudah diverifikasi ("TVL ONDO
$2,56 miliar") dan punya masa basi. Berkas ini menyimpan ATURAN KERJA dari user
("timeframe jam ditulis H4, bukan 4H") yang tidak basi sampai ia sendiri mencabutnya.

KENAPA TIDAK CUKUP DIINGAT MODEL. Tiap run GitHub Actions adalah mesin baru, jadi tanpa
disimpan, koreksi yang user berikan kemarin hilang total hari ini — ia harus mengulang
hal yang sama berkali-kali. Itu keluhan yang wajar, dan menyuruh model "ingat" tidak
menyelesaikannya karena tidak ada tempat mengingat.

DUA TINGKAT, DAN BEDANYA PENTING:
  - PANDUAN  : aturan yang hanya bisa DIIKUTI model ("lebih ringkas", "jangan menggurui").
               Disuntikkan ke prompt; kepatuhannya tidak bisa dibuktikan kode.
  - PAKSAAN  : aturan yang bisa DIPERIKSA KODE ("tulis H4, bukan 4H") karena berbentuk
               "jangan tulis X, tulis Y". Ini yang ditegakkan setelah balasan jadi —
               bukan diharapkan, tapi diperbaiki.
Aturan proyek ini: yang bergantung pada kepatuhan model dipindah ke kode kalau bisa.
Karena itu ekstraksi selalu MENCOBA mengubah masukan jadi bentuk PAKSAAN dulu.

PRIVASI (repo ini PUBLIK): dipakai penyaring yang sama dengan memori.py. Masukan yang
memuat data pribadi TIDAK disimpan sama sekali.

Pemakaian:
    python cloud/masukan.py tambah --aturan "Timeframe jam ditulis H4, bukan 4H" \
        --jangan "4H" --pakai "H4" --sumber teks
    python cloud/masukan.py daftar
    python cloud/masukan.py hapus --id 3
"""

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MASUKAN_PATH = os.path.join(BASE_DIR, "data", "masukan.jsonl")

# Batas jumlah aturan yang ikut ke prompt. Tanpa batas, masukan yang menumpuk berbulan-bulan
# pelan-pelan memakan jendela konteks setiap pesan — biaya yang tidak pernah terlihat
# karena bertambahnya sedikit demi sedikit.
MAKS_AKTIF = 25
# Panjang satu aturan. Masukan yang bertele-tele bukan aturan, itu percakapan.
ATURAN_MAKS = 200


def _sekarang():
    return datetime.now(timezone.utc)


def masalah_privasi(teks):
    """Pakai penyaring memori.py supaya cuma ada SATU definisi 'data pribadi'.

    Dua definisi yang berbeda berarti salah satunya pasti tertinggal saat diperbarui,
    dan yang tertinggal itu tidak akan ketahuan sampai ada yang bocor.
    """
    try:
        sys.path.insert(0, BASE_DIR)
        from memori import masalah_privasi as saring
        return saring(teks)
    except Exception:
        # Gagal memuat penyaring TIDAK boleh berarti "aman". Tanpa pemeriksaan, lebih
        # baik menolak menyimpan daripada menaruh sesuatu yang tak terperiksa ke repo publik.
        return "penyaring privasi tidak bisa dimuat"


def baca_semua():
    if not os.path.exists(MASUKAN_PATH):
        return []
    keluar = []
    with open(MASUKAN_PATH, encoding="utf-8") as f:
        for baris in f:
            baris = baris.strip()
            if not baris:
                continue
            try:
                keluar.append(json.loads(baris))
            except json.JSONDecodeError:
                continue          # satu baris rusak tidak boleh mematikan seluruh berkas
    return keluar


def aktif():
    """Aturan yang masih berlaku, terbaru dulu, dibatasi MAKS_AKTIF."""
    hidup = [m for m in baca_semua() if m.get("aktif", True)]
    return hidup[-MAKS_AKTIF:]


def _sama(a, b):
    """Dua aturan dianggap sama kalau teksnya sama setelah dinormalkan."""
    n = lambda s: re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).strip()
    return n(a) == n(b)


def tambah(aturan, jangan=None, pakai=None, sumber="teks", asal=None):
    """Simpan satu aturan. Return (entri, alasan_gagal)."""
    aturan = (aturan or "").strip()
    if not aturan:
        return None, "aturan kosong"
    if len(aturan) > ATURAN_MAKS:
        aturan = aturan[:ATURAN_MAKS].rstrip() + "…"
    masalah = masalah_privasi(f"{aturan} {jangan or ''} {pakai or ''} {asal or ''}")
    if masalah:
        return None, f"ditolak penyaring privasi: {masalah}"
    # Aturan yang sama persis tidak ditumpuk: user sering mengulang koreksi yang sama,
    # dan menyimpan duplikatnya memakan jatah MAKS_AKTIF tanpa menambah apa pun.
    for m in baca_semua():
        if m.get("aktif", True) and _sama(m.get("aturan"), aturan):
            return m, "sudah ada (tidak diduplikasi)"
    entri = {
        "id": len(baca_semua()) + 1,
        "waktu": _sekarang().timestamp(),
        "waktu_utc": _sekarang().strftime("%Y-%m-%d %H:%M"),
        "aturan": aturan,
        "jangan": (jangan or "").strip() or None,
        "pakai": (pakai or "").strip() or None,
        "sumber": sumber,
        "asal": (asal or "")[:200] or None,
        "aktif": True,
    }
    os.makedirs(os.path.dirname(MASUKAN_PATH), exist_ok=True)
    with open(MASUKAN_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(entri, ensure_ascii=False) + "\n")
    return entri, None


def nonaktifkan(id_):
    """Cabut satu aturan. Barisnya TIDAK dihapus supaya jejaknya tetap ada."""
    semua = baca_semua()
    ketemu = False
    for m in semua:
        if m.get("id") == id_ and m.get("aktif", True):
            m["aktif"] = False
            m["dicabut_utc"] = _sekarang().strftime("%Y-%m-%d %H:%M")
            ketemu = True
    if not ketemu:
        return False
    with open(MASUKAN_PATH, "w", encoding="utf-8") as f:
        for m in semua:
            f.write(json.dumps(m, ensure_ascii=False) + "\n")
    return True


def paksaan():
    """Aturan yang bisa DIPERIKSA KODE: punya `jangan`, dan idealnya `pakai`."""
    return [m for m in aktif() if m.get("jangan")]


def blok_prompt():
    """Teks yang disisipkan ke SETIAP prompt. "" kalau belum ada masukan."""
    hidup = aktif()
    if not hidup:
        return ""
    baris = ["## MASUKAN USER YANG SUDAH BERLAKU (dari percakapan sebelumnya)",
             "Ini koreksi yang PERNAH ia berikan. Ia tidak akan mengulangnya, dan "
             "mengulangi kesalahan yang sama setelah dikoreksi jauh lebih buruk "
             "daripada kesalahan pertamanya."]
    for m in hidup:
        b = "- " + m["aturan"]
        if m.get("jangan") and m.get("pakai"):
            b += f" (tulis \"{m['pakai']}\", JANGAN \"{m['jangan']}\")"
        elif m.get("jangan"):
            b += f" (JANGAN pakai \"{m['jangan']}\")"
        baris.append(b)
    baris.append("")
    return "\n".join(baris) + "\n"


def cmd_tambah(args):
    entri, err = tambah(args.aturan, args.jangan, args.pakai, args.sumber, args.asal)
    if err and not entri:
        print(f"GAGAL: {err}")
        return 1
    print(json.dumps(entri, ensure_ascii=False, indent=2))
    if err:
        print(f"catatan: {err}")
    return 0


def cmd_daftar(args):
    hidup = aktif()
    if not hidup:
        print("(belum ada masukan tersimpan)")
        return 0
    for m in hidup:
        tanda = "[paksaan]" if m.get("jangan") else "[panduan]"
        print(f"{m['id']:>3} {tanda} {m['waktu_utc']} ({m.get('sumber', '?')}) "
              f"{m['aturan']}")
    return 0


def cmd_hapus(args):
    print("dicabut" if nonaktifkan(args.id) else "id tidak ditemukan / sudah dicabut")
    return 0


def main():
    ap = argparse.ArgumentParser(description="Masukan user yang bertahan antar-run")
    sub = ap.add_subparsers(dest="perintah", required=True)
    t = sub.add_parser("tambah")
    t.add_argument("--aturan", required=True)
    t.add_argument("--jangan")
    t.add_argument("--pakai")
    t.add_argument("--sumber", default="teks", choices=("teks", "gambar", "pdf"))
    t.add_argument("--asal")
    t.set_defaults(fn=cmd_tambah)
    d = sub.add_parser("daftar")
    d.set_defaults(fn=cmd_daftar)
    h = sub.add_parser("hapus")
    h.add_argument("--id", type=int, required=True)
    h.set_defaults(fn=cmd_hapus)
    args = ap.parse_args()
    sys.exit(args.fn(args))


if __name__ == "__main__":
    main()
