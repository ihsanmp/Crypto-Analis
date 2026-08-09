"""Rapor rekomendasi — mencatat PANGGILAN bot lalu menilainya kemudian.

KENAPA ADA: bot memberi vonis tegas (bias, level invalidasi, target), lalu TIDAK ADA apa pun
yang mencatatnya dan menilainya belakangan. memori.jsonl mencatat FAKTA, bukan PANGGILAN.
backtest.py menguji sinyal generik terhadap riwayat harga, bukan menguji apa yang bot
rekomendasikan. Akibatnya ambang skor di analisa.md tidak akan pernah bisa dikalibrasi —
README sendiri mengakui ambang itu "titik awal wajar yang sebaiknya dikalibrasi ulang",
tanpa jalan untuk melakukannya. Setelah setahun berjalan, tidak akan ketahuan apakah skor
75/100 dari bot berarti sesuatu dibanding 45/100.

CATATAN PENTING: rapor hanya MENGAMATI. Ia tidak mengubah logika analisa, tidak menyetel
ambang, dan tidak boleh dipakai bot untuk menyesuaikan rekomendasinya sendiri secara
otomatis. Agent yang menyetel ambangnya sendiri dari hasil jangka pendek akan mengejar
derau — itu overfitting yang berjalan otomatis dan susah dideteksi. Kalibrasi adalah
keputusan manusia; berkas ini cuma menyediakan bahannya.

Pemakaian:
    python cloud/rapor.py nilai              # perbarui status panggilan yang masih terbuka
    python cloud/rapor.py ringkas [--hari 90]
"""

import argparse
import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
RAPOR_PATH = os.path.join(BASE_DIR, "data", "rapor.jsonl")

BIAS_SAH = ("AKUMULASI", "TAHAN", "KURANGI", "HINDARI", "TUNGGU")

# Horizon pengukuran return setelah panggilan.
HORIZON = (7, 30, 90)
# Di bawah ini, angka keberhasilan tidak bermakna secara statistik.
SAMPEL_MINIMUM = 10


# ------------------------------------------------------------- penguraian

def _angka(t):
    """'4.399,7' dan '4399.70' sama-sama jadi float. Format Indonesia & Inggris."""
    t = (t or "").strip().replace("$", "").replace(" ", "")
    if not t:
        return None
    # Titik sebagai pemisah ribuan bila diikuti tepat 3 digit dan ada koma desimal,
    # atau bila tidak ada koma sama sekali dan polanya 1.234.567
    if "," in t and "." in t:
        t = t.replace(".", "").replace(",", ".")
    elif "," in t:
        t = t.replace(",", ".")
    elif re.match(r"^\d{1,3}(\.\d{3})+$", t):
        t = t.replace(".", "")
    try:
        return float(t)
    except ValueError:
        return None


_RE_SKOR = re.compile(r"SKOR\s*(\d{1,3})\s*/\s*100", re.I)
_RE_BIAS = re.compile(r"BIAS(?:\s+SPOT)?\s*:\s*([A-Za-z]+)", re.I)
_RE_INVALID = re.compile(r"Invalid(?:asi)?\s*\$?\s*([\d.,]+)", re.I)
_RE_TARGET = re.compile(r"Target\s*:?\s*([$\d.,\s→>-]+)", re.I)
_RE_HARGA = re.compile(r"(?:^|\n)\s*Harga\s*\$?\s*([\d.,]+)", re.I)


def urai_panggilan(balasan):
    """Tarik panggilan dari teks balasan. Return dict, atau None kalau tidak layak dicatat.

    Diekstraksi oleh KODE, bukan dengan bertanya ke model — supaya tidak bisa dilewatkan
    dan tidak menambah biaya giliran.
    """
    teks = balasan or ""
    m = _RE_BIAS.search(teks)
    bias = m.group(1).upper() if m else None
    if bias not in BIAS_SAH:
        # "TUNGGU DULU" muncul di baris kesimpulan, bukan di baris BIAS.
        if re.search(r"TUNGGU\s+DULU", teks, re.I):
            bias = "TUNGGU"
        else:
            return None

    harga = _angka(_RE_HARGA.search(teks).group(1)) if _RE_HARGA.search(teks) else None
    invalid = _angka(_RE_INVALID.search(teks).group(1)) if _RE_INVALID.search(teks) else None

    target = []
    mt = _RE_TARGET.search(teks)
    if mt:
        for potong in re.findall(r"[\d.,]+", mt.group(1)):
            n = _angka(potong)
            if n:
                target.append(n)

    skor = None
    ms = _RE_SKOR.search(teks)
    if ms:
        try:
            s = int(ms.group(1))
            skor = s if 0 <= s <= 100 else None
        except ValueError:
            pass

    # ATURAN KEJUJURAN: panggilan tanpa harga ATAU tanpa satu pun level TIDAK BISA dinilai.
    # Memaksakannya masuk hanya akan mengisi rapor dengan entri yang selamanya
    # MASIH_TERBUKA dan mengaburkan angka yang sebenarnya bermakna.
    if harga is None or (invalid is None and not target):
        return None

    return {"bias": bias, "skor": skor, "harga_saat_panggilan": harga,
            "level_invalid": invalid, "level_target": target[:3]}


# ------------------------------------------------------------- pencatatan

def _muat():
    keluar = []
    try:
        with open(RAPOR_PATH, encoding="utf-8") as f:
            for baris in f:
                baris = baris.strip()
                if baris:
                    try:
                        keluar.append(json.loads(baris))
                    except json.JSONDecodeError:
                        continue
    except OSError:
        pass
    return keluar


def _tulis_semua(entri):
    """Ditulis ulang HANYA untuk memperbarui status hasil penilaian.

    Isi panggilannya sendiri tidak pernah diubah — rapor bersifat append-only untuk
    ISI; koreksi dilakukan dengan entri baru yang merujuk id lama.
    """
    os.makedirs(os.path.dirname(RAPOR_PATH), exist_ok=True)
    with open(RAPOR_PATH, "w", encoding="utf-8") as f:
        for e in entri:
            f.write(json.dumps(e, ensure_ascii=False) + "\n")


def catat(balasan, aset, jenis, mode="analisa"):
    """Simpan satu panggilan. Return id, atau None kalau tidak layak dicatat.

    Kegagalan di sini TIDAK BOLEH menggagalkan pengiriman balasan ke user — pemanggil
    membungkusnya dengan try/except.
    """
    p = urai_panggilan(balasan)
    if not p or not aset:
        return None
    sekarang = datetime.now(timezone.utc)
    entri = {
        "id": f"{aset}-{sekarang.strftime('%Y%m%d%H%M%S')}",
        "tanggal_utc": sekarang.strftime("%Y-%m-%d %H:%M"),
        "aset": aset,
        "jenis": jenis,
        "mode": mode,
        "status": "TERBUKA",
        **p,
    }
    os.makedirs(os.path.dirname(RAPOR_PATH), exist_ok=True)
    with open(RAPOR_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(entri, ensure_ascii=False) + "\n")
    return entri["id"]


# -------------------------------------------------------------- penilaian

def _riwayat_harga(aset, jenis):
    """Ambil candle harian. MEMAKAI ULANG penarik yang sudah ada — jangan menulis baru."""
    try:
        sys.path.insert(0, BASE_DIR)
        if jenis == "crypto":
            from indicators import fetch_base, resolve_cg_id
            c, _, _, err = fetch_base(aset, resolve_cg_id(aset), "1d")
        else:
            from market import tarik
            c, _, err = tarik(aset, "2y", "1d")
        return (c or []), err
    except Exception as e:
        return [], f"{type(e).__name__}: {e}"


def _sejak(candles, tanggal_utc):
    """Candle yang terjadi SETELAH panggilan dibuat."""
    try:
        batas = datetime.strptime(tanggal_utc, "%Y-%m-%d %H:%M").replace(tzinfo=timezone.utc)
    except Exception:
        return []
    keluar = []
    for c in candles:
        try:
            t = datetime.fromtimestamp(c[0] / 1000, timezone.utc)
        except Exception:
            continue
        if t >= batas:
            keluar.append((t, c))
    return keluar


def nilai_satu(entri):
    """Tentukan hasil satu panggilan. Mengembalikan dict pembaruan, atau None."""
    candles, err = _riwayat_harga(entri["aset"], entri.get("jenis", "crypto"))
    if err or not candles:
        return {"catatan_penilaian": f"harga tidak bisa diambil: {err or 'kosong'}"}

    jalan = _sejak(candles, entri["tanggal_utc"])
    if not jalan:
        return None                       # belum ada candle baru, biarkan apa adanya

    awal = entri["harga_saat_panggilan"]
    invalid = entri.get("level_invalid")
    target = entri.get("level_target") or []
    target1 = target[0] if target else None

    # Naik atau turun? BIAS menentukan arah yang diharapkan. Untuk spot, semua bias
    # bertaruh harga NAIK (atau setidaknya tidak jatuh) — kecuali HINDARI/KURANGI yang
    # justru "benar" kalau harga turun. Itu dicatat, bukan dinilai dengan aturan berbeda.
    hasil, kena_pada = "MASIH_TERBUKA", None
    terdalam = 0.0
    for t, c in jalan:
        tinggi, rendah = c[2], c[3]
        turun = (rendah - awal) / awal * 100
        terdalam = min(terdalam, turun)
        if invalid is not None and rendah <= invalid:
            hasil, kena_pada = "INVALID_KENA", t.strftime("%Y-%m-%d")
            break
        if target1 is not None and tinggi >= target1:
            hasil, kena_pada = "TARGET_KENA", t.strftime("%Y-%m-%d")
            break

    kembali = {"status": hasil, "mae_persen": round(terdalam, 2)}
    if kena_pada:
        kembali["tanggal_hasil"] = kena_pada

    # Return per horizon + TOLOK UKUR beli-dan-tahan. Tanpa pembanding ini angkanya
    # menyesatkan: bot yang bilang AKUMULASI di pasar naik 40% bukan sedang hebat.
    for h in HORIZON:
        sampai = [x for x in jalan
                  if x[0] <= datetime.strptime(entri["tanggal_utc"], "%Y-%m-%d %H:%M")
                  .replace(tzinfo=timezone.utc) + timedelta(days=h)]
        if len(sampai) >= 2:
            akhir = sampai[-1][1][4]
            kembali[f"return_{h}h_persen"] = round((akhir - awal) / awal * 100, 2)
    kembali["tolok_ukur_beli_tahan_persen"] = kembali.get(
        f"return_{HORIZON[-1]}h_persen", kembali.get("return_7h_persen"))
    kembali["dinilai_utc"] = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")
    return kembali


def perintah_nilai():
    entri = _muat()
    terbuka = [e for e in entri if e.get("status") == "TERBUKA"]
    if not terbuka:
        print(json.dumps({"pesan": "tidak ada panggilan berstatus TERBUKA",
                          "total_entri": len(entri)}, indent=2, ensure_ascii=False))
        return
    diperbarui = 0
    for e in entri:
        if e.get("status") != "TERBUKA":
            continue
        ubah = nilai_satu(e)
        if ubah:
            e.update(ubah)
            diperbarui += 1
    _tulis_semua(entri)
    print(json.dumps({"dinilai": len(terbuka), "diperbarui": diperbarui,
                      "total_entri": len(entri)}, indent=2, ensure_ascii=False))


# ---------------------------------------------------------------- laporan


# Bias yang bertaruh harga NAIK vs yang bertaruh SEBALIKNYA. Ini menentukan cara membaca
# hasilnya, dan mengabaikannya membuat angka keberhasilan menyesatkan: panggilan HINDARI
# pada aset yang lalu turun 60% adalah panggilan yang BENAR, bukan kalah — padahal secara
# mekanis level invalidasinya memang tertembus.
_BIAS_NAIK = ("AKUMULASI", "TAHAN", "TUNGGU")
_BIAS_TURUN = ("HINDARI", "KURANGI")


def _benar(e):
    """Apakah panggilan ini terbukti benar? None kalau belum bisa dinilai."""
    bias = e.get("bias")
    if bias in _BIAS_TURUN:
        # Menghindar terbukti benar kalau harganya memang turun setelah itu.
        r = e.get("return_30h_persen")
        if r is None:
            r = e.get("return_7h_persen")
        return None if r is None else r < 0
    if e.get("status") == "TARGET_KENA":
        return True
    if e.get("status") == "INVALID_KENA":
        return False
    return None                       # MASIH_TERBUKA


def _kelompok_skor(s):
    if s is None:
        return "tanpa skor"
    if s <= 40:
        return "0-40"
    if s <= 60:
        return "41-60"
    if s <= 80:
        return "61-80"
    return "81-100"


def _hitung(kelompok):
    """Ringkasan satu kelompok. Selalu sertakan penanda sampel kecil."""
    n = len(kelompok)
    vonis = [(e, _benar(e)) for e in kelompok]
    selesai = [e for e, b in vonis if b is not None]
    benar = [e for e, b in vonis if b is True]
    ret = [e.get("return_30h_persen") for e in kelompok
           if e.get("return_30h_persen") is not None]
    mae = [e.get("mae_persen") for e in kelompok if e.get("mae_persen") is not None]
    h = {
        "panggilan": n,
        "sudah_bisa_dinilai": len(selesai),
        "terbukti_benar": len(benar),
        "menang_persen": round(len(benar) / len(selesai) * 100, 1) if selesai else None,
        "return_30h_rata2_persen": round(sum(ret) / len(ret), 2) if ret else None,
        "nyeri_maks_rata2_persen": round(sum(mae) / len(mae), 2) if mae else None,
    }
    if n < SAMPEL_MINIMUM:
        h["peringatan"] = (f"SAMPEL KECIL ({n} panggilan) — angka ini TIDAK bermakna secara "
                           "statistik. Jangan dipakai mengubah ambang apa pun.")
    return h


def perintah_ringkas(hari):
    entri = _muat()
    batas = datetime.now(timezone.utc) - timedelta(days=hari)
    dipakai = []
    for e in entri:
        try:
            t = datetime.strptime(e["tanggal_utc"], "%Y-%m-%d %H:%M").replace(
                tzinfo=timezone.utc)
        except Exception:
            continue
        if t >= batas:
            dipakai.append(e)

    keluar = {
        "generated_utc": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M"),
        "rentang_hari": hari,
        "total_panggilan": len(dipakai),
    }
    if not dipakai:
        keluar["pesan"] = "belum ada panggilan tercatat pada rentang ini"
        print(json.dumps(keluar, indent=2, ensure_ascii=False))
        return

    keluar["keseluruhan"] = _hitung(dipakai)
    for label, kunci in (("per_bias", "bias"), ("per_jenis", "jenis")):
        kel = {}
        for e in dipakai:
            kel.setdefault(e.get(kunci) or "?", []).append(e)
        keluar[label] = {k: _hitung(v) for k, v in sorted(kel.items())}

    # INI TUJUAN UTAMANYA: kalau panggilan berskor 75 tidak lebih sering benar daripada
    # yang berskor 45, berarti sistem skor di analisa.md belum bermakna.
    kel = {}
    for e in dipakai:
        kel.setdefault(_kelompok_skor(e.get("skor")), []).append(e)
    keluar["per_rentang_skor"] = {k: _hitung(v) for k, v in sorted(kel.items())}
    keluar["cara_baca"] = [
        "Bandingkan menang_persen antar rentang skor. Kalau 61-80 TIDAK lebih baik daripada "
        "41-60, sistem skornya belum bermakna dan ambangnya perlu dikalibrasi.",
        "return_30h selalu dibaca bersama nyeri_maks: benar tapi menyakitkan tetap mahal.",
        "Kelompok bertanda SAMPEL KECIL jangan dipakai mengambil keputusan apa pun.",
        "menang_persen sudah SADAR ARAH: untuk HINDARI/KURANGI, benar berarti harganya "
        "memang turun setelah itu — bukan target tercapai. Tanpa ini panggilan menghindar "
        "yang tepat justru terhitung kalah.",
        "Kalibrasi adalah keputusan MANUSIA. Rapor ini menyediakan bahan, bukan menyetel "
        "ambang sendiri.",
    ]
    print(json.dumps(keluar, indent=2, ensure_ascii=False))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("perintah", choices=["nilai", "ringkas"])
    ap.add_argument("--hari", type=int, default=90)
    args = ap.parse_args()
    if args.perintah == "nilai":
        perintah_nilai()
    else:
        perintah_ringkas(args.hari)


if __name__ == "__main__":
    main()
