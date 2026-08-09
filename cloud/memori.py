"""Ingatan terverifikasi — fakta yang sudah dicek kebenarannya lewat riset internet.

Tiap run GitHub Actions adalah mesin baru, jadi bot TIDAK ingat apa pun antar-pesan.
Script ini memberi ingatan yang bertahan: fakta yang sudah DIVERIFIKASI disimpan ke
cloud/data/memori.jsonl (ikut ter-commit ke repo), lalu bisa dipanggil lagi nanti.

PRINSIP: ingatan itu PETUNJUK, bukan kebenaran abadi. Data crypto basi dengan kecepatan
berbeda, jadi tiap entri diberi JENIS yang menentukan seberapa cepat ia harus dicek ulang:
  - volatil : harga, RSI, funding, OI          -> basi dalam HITUNGAN JAM
  - semi    : TVL, revenue, holder, whale flow -> basi dalam pekan
  - stabil  : tokenomics, tim, jadwal unlock   -> basi dalam bulan
Saat dibaca, tiap entri otomatis diberi vonis SEGAR / PERLU CEK ULANG / KEDALUWARSA
berdasarkan tanggal hari ini.

PRIVASI (repo ini PUBLIK): data pribadi DITOLAK di level kode, bukan sekadar imbauan.
Alamat dompet, saldo/kepemilikan pribadi, dan sejenisnya tidak boleh tersimpan karena
riwayat git bersifat permanen dan bisa dibaca siapa saja.

Pemakaian:
    python cloud/memori.py tambah --topik ONDO --klaim "TVL $2,56 miliar" \
        --status VALID --sumber DefiLlama --jenis semi
    python cloud/memori.py cari ONDO
    python cloud/memori.py daftar --limit 20
"""

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MEMORI_PATH = os.path.join(BASE_DIR, "data", "memori.jsonl")

# Berapa hari sebuah fakta masih layak dipakai tanpa dicek ulang.
UMUR = {"volatil": 1, "semi": 14, "stabil": 180}
STATUS_SAH = ("VALID", "MELESET", "SEBAGIAN", "TIDAK TERVERIFIKASI")

# --- Penyaring privasi (repo PUBLIK) -----------------------------------------
# Ditolak di level KODE supaya tidak bergantung pada kepatuhan model.
_EVM = re.compile(r"\b0x[0-9a-fA-F]{40}\b")
_SOL = re.compile(r"\b[1-9A-HJ-NP-Za-km-z]{32,44}\b")
_MILIK_PRIBADI = re.compile(
    r"\b(saya|aku|gue|gw|punyaku|punyaskau|milikku)\b.{0,30}"
    r"\b(punya|pegang|hold|saldo|portofolio|portfolio|beli|dompet|wallet)\b"
    r"|\b(saldo|portofolio|portfolio|dompet|wallet)\s+(saya|aku|gue|gw|pribadi)\b",
    re.IGNORECASE)


def masalah_privasi(teks):
    """Return alasan penolakan, atau None kalau aman disimpan di repo publik."""
    teks = teks or ""      # dipanggil dari beberapa jalur; jangan pecah pada None
    if _EVM.search(teks):
        return "memuat alamat dompet EVM (0x...)"
    if _MILIK_PRIBADI.search(teks):
        return "memuat kepemilikan/saldo pribadi"
    # Base58 panjang: cek belakangan supaya tidak salah tangkap kata biasa.
    for kandidat in _SOL.findall(teks):
        # Alamat Solana hampir selalu campur huruf besar-kecil + angka.
        if (any(c.isdigit() for c in kandidat)
                and any(c.isupper() for c in kandidat)
                and any(c.islower() for c in kandidat)):
            return "memuat kemungkinan alamat dompet Solana"
    return None


def hari_ini():
    return datetime.now(timezone.utc).date()


def baca_semua():
    if not os.path.exists(MEMORI_PATH):
        return []
    keluar = []
    with open(MEMORI_PATH, encoding="utf-8") as f:
        for baris in f:
            baris = baris.strip()
            if not baris:
                continue
            try:
                keluar.append(json.loads(baris))
            except Exception:
                continue          # baris rusak dilewati, jangan bikin bot mati
    return keluar


def vonis(entri):
    """Beri vonis kesegaran + sisa umur, dihitung terhadap hari ini."""
    try:
        tgl = datetime.strptime(entri.get("tanggal", ""), "%Y-%m-%d").date()
    except Exception:
        return "TANGGAL TIDAK JELAS — WAJIB cek ulang", None
    umur = (hari_ini() - tgl).days
    batas = UMUR.get(entri.get("jenis", "semi"), 14)
    if umur <= batas * 0.5:
        return "SEGAR", umur
    if umur <= batas:
        return "MULAI TUA — sebaiknya cek ulang", umur
    return "KEDALUWARSA — WAJIB cek ulang sebelum dipakai", umur


def cmd_tambah(args):
    teks_gabungan = f"{args.topik} {args.klaim} {args.sumber} {args.catatan or ''}"
    alasan = masalah_privasi(teks_gabungan)
    if alasan:
        print(json.dumps({
            "ok": False,
            "ditolak": f"DATA PRIBADI TIDAK DISIMPAN — {alasan}.",
            "sebab": ("Repo ini PUBLIK dan riwayat git permanen. Fakta pasar umum boleh "
                      "disimpan; data pribadi (alamat dompet, saldo/kepemilikanmu) tidak."),
        }, indent=2, ensure_ascii=False))
        sys.exit(2)

    if args.status not in STATUS_SAH:
        print(json.dumps({"ok": False, "error": f"status harus salah satu dari {STATUS_SAH}"},
                         ensure_ascii=False))
        sys.exit(2)
    if args.jenis not in UMUR:
        print(json.dumps({"ok": False, "error": f"jenis harus salah satu dari {list(UMUR)}"},
                         ensure_ascii=False))
        sys.exit(2)

    entri = {
        "tanggal": str(hari_ini()),
        "topik": args.topik.upper().replace("$", ""),
        "klaim": args.klaim.strip(),
        "status": args.status,
        "sumber": args.sumber.strip(),
        "jenis": args.jenis,
        "asal": args.asal,
    }
    if args.catatan:
        entri["catatan"] = args.catatan.strip()

    os.makedirs(os.path.dirname(MEMORI_PATH), exist_ok=True)
    with open(MEMORI_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(entri, ensure_ascii=False) + "\n")

    print(json.dumps({"ok": True, "tersimpan": entri,
                      "catatan": f"Akan dianggap kedaluwarsa setelah {UMUR[args.jenis]} hari."},
                     indent=2, ensure_ascii=False))


def cmd_cari(args):
    topik = args.topik.upper().replace("$", "")
    cocok = [e for e in baca_semua() if topik in (e.get("topik", "") + " " + e.get("klaim", "")).upper()]
    cocok.sort(key=lambda e: e.get("tanggal", ""), reverse=True)
    cocok = cocok[:args.limit]

    hasil = []
    for e in cocok:
        v, umur = vonis(e)
        item = dict(e)
        item["kesegaran"] = v
        item["umur_hari"] = umur
        hasil.append(item)

    print(json.dumps({
        "topik": topik,
        "hari_ini": str(hari_ini()),
        "ditemukan": len(hasil),
        "ingatan": hasil,
        "cara_pakai": [
            "Ingatan ini PETUNJUK, BUKAN kebenaran terkini. Jangan langsung dikutip.",
            "SEGAR: boleh dipakai, tetap sebutkan tanggalnya.",
            "MULAI TUA / KEDALUWARSA: WAJIB verifikasi ulang ke sumber live sebelum dipakai.",
            "status MELESET = klaim itu dulu terbukti SALAH; berguna untuk mewaspadai "
            "sumber/klaim serupa, jangan diulang sebagai fakta.",
        ],
    }, indent=2, ensure_ascii=False))


def cmd_daftar(args):
    semua = sorted(baca_semua(), key=lambda e: e.get("tanggal", ""), reverse=True)[:args.limit]
    for e in semua:
        v, umur = vonis(e)
        print(f"{e.get('tanggal')} · {e.get('topik'):10s} · {e.get('status'):18s} · "
              f"{v:38s} · {e.get('klaim', '')[:60]}")
    if not semua:
        print("(ingatan masih kosong)")


def main():
    ap = argparse.ArgumentParser(description="Ingatan terverifikasi bot")
    sub = ap.add_subparsers(dest="cmd", required=True)

    t = sub.add_parser("tambah", help="simpan fakta yang SUDAH diverifikasi")
    t.add_argument("--topik", required=True, help="ticker/nama project, mis. ONDO")
    t.add_argument("--klaim", required=True, help="fakta singkat, mis. 'TVL $2,56 miliar'")
    t.add_argument("--status", required=True, help=f"salah satu dari {STATUS_SAH}")
    t.add_argument("--sumber", required=True, help="dari mana diverifikasi, mis. DefiLlama")
    t.add_argument("--jenis", required=True, help=f"salah satu dari {list(UMUR)}")
    t.add_argument("--asal", default="gambar", help="gambar | chat | analisa")
    t.add_argument("--catatan", default=None)
    t.set_defaults(func=cmd_tambah)

    c = sub.add_parser("cari", help="panggil ingatan tentang sebuah topik")
    c.add_argument("topik")
    c.add_argument("--limit", type=int, default=10)
    c.set_defaults(func=cmd_cari)

    d = sub.add_parser("daftar", help="lihat ingatan terbaru")
    d.add_argument("--limit", type=int, default=20)
    d.set_defaults(func=cmd_daftar)

    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
