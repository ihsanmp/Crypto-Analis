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
import secrets
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import statistik

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
    # Akhiran acak supaya id tetap unik. Dengan detik saja, dua panggilan untuk aset yang
    # sama dalam detik yang sama menghasilkan id IDENTIK — dan itu membuat janji di
    # docstring ("koreksi lewat entri baru yang merujuk id lama") mustahil dipenuhi,
    # sekaligus membuat pembaruan status di nilai() menjadi ambigu.
    acak = secrets.token_hex(3)
    entri = {
        "id": f"{aset}-{sekarang.strftime('%Y%m%d%H%M%S')}-{acak}",
        "tanggal_utc": sekarang.strftime("%Y-%m-%d %H:%M"),
        "aset": aset,
        "jenis": jenis,
        "mode": mode,
        "status": "TERBUKA",
        **p,
    }
    # Rasio imbalan:risiko dihitung SEKARANG, bukan saat penilaian. Levelnya sudah ada di
    # sini, dan menundanya berarti panggilan yang tak pernah selesai tak pernah terperiksa
    # — padahal justru di situ kelemahannya paling sering bersembunyi.
    rr = statistik.imbalan_risiko(p.get("harga_saat_panggilan"),
                                  p.get("level_target"), p.get("level_invalid"))
    if rr:
        entri.update(rr)
    os.makedirs(os.path.dirname(RAPOR_PATH), exist_ok=True)
    with open(RAPOR_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(entri, ensure_ascii=False) + "\n")
    return entri["id"]


# -------------------------------------------------------------- penilaian

# TOLOK UKUR PASAR per jenis aset. Diambil dari TradingAgents, yang menilai keputusannya
# terhadap ALPHA (kelebihan atas benchmark), bukan return mentah.
#
# Kenapa ini memperbaiki cacat nyata: di pasar naik, hampir SEMUA panggilan AKUMULASI
# otomatis tercatat "benar" — return 30 hari positif — padahal koin yang naik 5% saat BTC
# naik 20% adalah panggilan yang BURUK. Tanpa pembanding pasar, rapor mengukur arah pasar,
# bukan keahlian.
#
# Emas dan forex sengaja TIDAK diberi tolok ukur: tidak ada indeks yang jelas menjadi
# "pasarnya", dan memaksakan satu pembanding hanya melahirkan angka yang terlihat sah tapi
# tidak berarti. Untuk keduanya alpha dilaporkan tidak tersedia, apa adanya.
TOLOK_UKUR = {"crypto": "BTC", "saham": "SPY"}


def _tolok_ukur(aset, jenis):
    """Simbol pembanding, atau None kalau memang tidak ada yang layak."""
    bench = TOLOK_UKUR.get(jenis)
    if not bench or (aset or "").upper() == bench:
        return None                     # BTC tidak dibandingkan dengan dirinya sendiri
    return bench


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
        # Belum ada candle SESUDAH panggilan. Untuk saham & forex ini normal dan sering:
        # panggilan yang dibuat saat bursa tutup (akhir pekan, di luar sesi) baru punya
        # candle baru pada sesi berikutnya. Dulu dikembalikan None sehingga entrinya
        # tetap berstatus TERBUKA dengan seluruh field kosong dan TANPA penjelasan —
        # tidak bisa dibedakan dari kegagalan penilaian yang sesungguhnya.
        akhir = None
        try:
            akhir = datetime.fromtimestamp(candles[-1][0] / 1000, timezone.utc).strftime(
                "%Y-%m-%d")
        except Exception:
            pass
        return {"catatan_penilaian": (
            f"belum ada candle sesudah panggilan (candle terakhir {akhir}). "
            "Untuk saham/forex ini wajar bila bursa sedang tutup — akan dinilai pada "
            "sesi berikutnya."),
            "dinilai_utc": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")}

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

    # Return per horizon. HANYA dilaporkan kalau waktunya BENAR-BENAR sudah berlalu.
    # Dulu tidak dicek, sehingga panggilan berumur 20 hari tetap melaporkan return_30h
    # dan return_90h — isinya return 20 hari yang diberi label salah, lalu masuk ke
    # kalibrasi ambang skor sebagai data sah.
    mulai = datetime.strptime(entri["tanggal_utc"], "%Y-%m-%d %H:%M").replace(
        tzinfo=timezone.utc)
    umur_hari = (datetime.now(timezone.utc) - mulai).days
    kembali["umur_hari"] = umur_hari
    for h in HORIZON:
        if umur_hari < h:
            continue                  # horizon belum penuh — jangan dilaporkan
        sampai = [x for x in jalan if x[0] <= mulai + timedelta(days=h)]
        if len(sampai) >= 2:
            akhir = sampai[-1][1][4]
            kembali[f"return_{h}h_persen"] = round((akhir - awal) / awal * 100, 2)

    # TOLOK UKUR yang benar-benar membandingkan. Versi lama menyalin return panggilan itu
    # sendiri sebagai "tolok ukur" — untuk posisi spot, return sejak panggilan MEMANG sama
    # dengan beli-dan-tahan, jadi selisihnya selalu nol dan tidak mengukur apa pun.
    #
    # Yang ingin diukur: hasil MENGIKUTI SARAN dibanding SELALU MEMBELI.
    #   AKUMULASI/TAHAN        -> memegang aset -> dapat return pasar
    #   HINDARI/KURANGI/TUNGGU -> di kas        -> dapat 0
    # Dengan begitu keunggulannya terlihat: HINDARI saat pasar jatuh 30% bernilai +30,
    # sedangkan AKUMULASI saat pasar naik 40% bernilai 0 — ikut arus, bukan unggul.
    pasar = None
    for h in HORIZON:
        if kembali.get(f"return_{h}h_persen") is not None:
            pasar = kembali[f"return_{h}h_persen"]
    if pasar is None and jalan:
        pasar = round((jalan[-1][1][4] - awal) / awal * 100, 2)
    if pasar is not None:
        ikut = pasar if entri.get("bias") in ("AKUMULASI", "TAHAN") else 0.0
        kembali["beli_dan_tahan_persen"] = pasar
        kembali["hasil_ikut_saran_persen"] = round(ikut, 2)
        kembali["selisih_vs_beli_tahan"] = round(ikut - pasar, 2)
    # ALPHA — return panggilan DIKURANGI return pasar pada jendela yang sama persis.
    # Ini yang memisahkan keahlian dari arus pasar.
    bench = _tolok_ukur(entri["aset"], entri.get("jenis", "crypto"))
    if bench:
        b_candles, b_err = _riwayat_harga(bench, entri.get("jenis", "crypto"))
        b_jalan = _sejak(b_candles, entri["tanggal_utc"]) if b_candles else []
        if b_jalan and len(b_jalan) >= 2:
            b_awal = b_jalan[0][1][4]
            kembali["tolok_ukur"] = bench
            for h in HORIZON:
                if kembali.get(f"return_{h}h_persen") is None:
                    continue
                sampai = [x for x in b_jalan if x[0] <= mulai + timedelta(days=h)]
                if len(sampai) < 2 or not b_awal:
                    continue
                b_ret = (sampai[-1][1][4] - b_awal) / b_awal * 100
                kembali[f"pasar_{h}h_persen"] = round(b_ret, 2)
                kembali[f"alpha_{h}h_persen"] = round(
                    kembali[f"return_{h}h_persen"] - b_ret, 2)
            kembali["arti_alpha"] = (
                f"alpha = return panggilan dikurangi return {bench} pada jendela yang sama. "
                "Positif berarti unggul atas pasar; NEGATIF berarti kalah meski harganya "
                "naik. Panggilan yang naik 5% saat pasar naik 20% adalah panggilan buruk, "
                "dan hanya alpha yang menunjukkannya.")
        else:
            # JANGAN diam. Kalau tolok ukurnya ada tapi tidak bisa diukur, itu harus
            # terlihat — bukan menghilang begitu saja seperti versi pertama perbaikan ini,
            # yang membuat SOL dan ETH tidak melaporkan angka MAUPUN alasannya.
            kembali["alpha_tidak_tersedia"] = (
                f"harga {bench} gagal diambil: {b_err}" if b_err else
                f"riwayat {bench} sejak panggilan belum cukup panjang untuk dibandingkan")
    else:
        kembali["alpha_tidak_tersedia"] = (
            "tidak ada tolok ukur pasar yang layak untuk jenis aset ini (emas/forex), atau "
            "asetnya adalah tolok ukurnya sendiri. Nilai dari return mentah, dan sebutkan "
            "bahwa pembandingnya tidak ada.")

    kembali["dinilai_utc"] = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")
    return kembali


# Status AKHIR — tidak perlu dinilai ulang karena hasilnya sudah terjadi.
STATUS_FINAL = ("TARGET_KENA", "INVALID_KENA")


def perintah_nilai():
    """Nilai ulang SEMUA panggilan yang belum final.

    BUG YANG DIPERBAIKI: dulu penyaringnya `status == "TERBUKA"`, padahal nilai_satu
    mengubah status jadi "MASIH_TERBUKA" begitu dinilai sekali. Akibatnya tiap panggilan
    dinilai TEPAT SEKALI lalu beku selamanya — panggilan yang belakangan menyentuh target
    atau level invalidasinya tidak pernah tercatat, dan rapor mingguan berjalan tanpa
    memperbarui apa pun. Diukur saat ditemukan: 0 dari 11 panggilan masih bisa dinilai.
    """
    entri = _muat()
    terbuka = [e for e in entri if e.get("status") not in STATUS_FINAL]
    if not terbuka:
        print(json.dumps({"pesan": "semua panggilan sudah final",
                          "total_entri": len(entri)}, indent=2, ensure_ascii=False))
        return
    diperbarui = 0
    for e in entri:
        if e.get("status") in STATUS_FINAL:
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
        # Menghindar terbukti benar kalau asetnya TERTINGGAL DARI PASAR — bukan sekadar
        # turun. Menghindari koin yang naik 5% saat pasar naik 20% adalah saran yang BENAR,
        # dan aturan lama menghitungnya salah. Alpha dipakai kalau ada; kalau tidak (emas,
        # forex, atau BTC itu sendiri), kembali ke return mentah dan itu memang batasnya.
        for h in (30, 7):
            a_ = e.get(f"alpha_{h}h_persen")
            if a_ is not None:
                return a_ < 0
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
    # Angka PALING bermakna: keunggulan terhadap sekadar beli-dan-tahan. Menang 70% di
    # pasar yang naik terus bukan prestasi — yang menentukan adalah selisihnya.
    sel = [e.get("selisih_vs_beli_tahan") for e in kelompok
           if e.get("selisih_vs_beli_tahan") is not None]
    h["selisih_vs_beli_tahan_rata2"] = round(sum(sel) / len(sel), 2) if sel else None

    # ALPHA rata-rata terhadap pasar. Ini yang memisahkan keahlian dari arus pasar:
    # menang 70% saat pasar naik terus bukan prestasi kalau alphanya negatif.
    alp = [e.get("alpha_30h_persen") for e in kelompok
           if e.get("alpha_30h_persen") is not None]
    h["alpha_30h_rata2_persen"] = round(sum(alp) / len(alp), 2) if alp else None
    h["alpha_terhitung_dari"] = len(alp)
    if alp and h["menang_persen"] is not None and h["alpha_30h_rata2_persen"] < 0:
        h["peringatan_alpha"] = (
            f"menang {h['menang_persen']}% TAPI alpha rata-rata "
            f"{h['alpha_30h_rata2_persen']}% — panggilan ini mengikuti pasar naik, bukan "
            "mengunggulinya. Tingkat menang yang tinggi di sini BUKAN bukti keahlian.")
    # EKSPEKTANSI dan kawan-kawannya (dari crates/analysis nautilus_trader). Tingkat menang
    # sendirian menyesatkan: benar 75% dengan imbalan +1,9% dan salah 25% dengan rugi -30%
    # menghasilkan ekspektansi -6,25% per panggilan. Rapor yang hanya melaporkan "menang
    # 75%" akan menyebut pola yang merugi itu sebagai keahlian.
    hasil = [e.get("hasil_ikut_saran_persen") for e in kelompok]
    st = statistik.ringkas(hasil)
    for k in ("ekspektansi_persen", "faktor_untung", "rasio_imbalan",
              "menang_rata2_persen", "kalah_rata2_persen", "kalah_terburuk_persen",
              "penurunan_maksimum_persen"):
        h[k] = st[k]
    # Penjaga sampel di bawah memakai n (SEMUA panggilan), padahal ekspektansi hanya
    # dihitung dari yang sudah punya hasil. Dengan 13 panggilan tapi 4 yang bisa dinilai,
    # peringatan ini akan terdengar sekuat kesimpulan padahal berdiri di atas empat titik.
    # Jadi ia punya penjaganya sendiri, dan menyebut sandarannya kalau masih tipis.
    cukup = (st["dinilai"] or 0) >= SAMPEL_MINIMUM
    if st["ekspektansi_persen"] is not None and st["ekspektansi_persen"] < 0:
        h["peringatan_ekspektansi"] = (
            f"dari hasil mengikuti saran: menang {st['menang_persen']}%, TAPI ekspektansi {st['ekspektansi_persen']}% per "
            f"panggilan — menangnya kecil ({st['menang_rata2_persen']}%), kalahnya besar "
            f"({st['kalah_rata2_persen']}%). Mengulang pola ini MERUGI meski sering benar."
            + ("" if cukup else f" [baru {st['dinilai']} panggilan berhasil — arah, bukan vonis]"))

    # TINGKAT MENANG DIHITUNG DARI STATUS, dan status hanya final saat target atau
    # invalidasi tersentuh. Panggilan yang turun 25% tapi belum menyentuh invalidasi tetap
    # MASIH_TERBUKA — jadi tidak pernah masuk hitungan, dan tingkat menang bisa membaca
    # 100% sementara ada posisi terbuka yang dalam sekali merahnya. Itu bias survivorship,
    # dan persis angka menyenangkan-tapi-palsu yang rapor ini dibuat untuk mencegah.
    terbuka = [e for e in kelompok if e.get("status") not in STATUS_FINAL]
    nilai_terbuka = [e.get("hasil_ikut_saran_persen") for e in terbuka
                     if e.get("hasil_ikut_saran_persen") is not None]
    if nilai_terbuka:
        h["masih_terbuka"] = len(terbuka)
        h["terbuka_terburuk_persen"] = round(min(nilai_terbuka), 2)
        # Angka pembanding yang jujur: seandainya semua posisi terbuka ditutup HARI INI.
        semua = [e.get("hasil_ikut_saran_persen") for e in kelompok
                 if e.get("hasil_ikut_saran_persen") is not None]
        menang_kini, kalah_kini = statistik.pisah(semua)
        n_kini = len(menang_kini) + len(kalah_kini)
        if n_kini:
            h["menang_persen_jika_ditutup_sekarang"] = round(
                len(menang_kini) / n_kini * 100, 1)
        if (h.get("menang_persen") is not None
                and h["terbuka_terburuk_persen"] < -10):
            h["peringatan_terbuka"] = (
                f"menang {h['menang_persen']}% dihitung HANYA dari panggilan yang sudah "
                f"selesai. {len(terbuka)} masih terbuka, yang terburuk "
                f"{h['terbuka_terburuk_persen']}% — kalau ditutup sekarang itu kekalahan. "
                f"Tingkat menang sebenarnya "
                f"{h.get('menang_persen_jika_ditutup_sekarang')}%.")

    # Rasio imbalan:risiko yang DIMINTA saat panggilan dibuat. Ini kelemahan yang tidak
    # terlihat dari hasil mana pun: panggilan bisa kena target dan tercatat menang, sambil
    # sepanjang waktu mempertaruhkan sepuluh kali lipat imbalannya.
    rr = [e.get("rasio_imbalan_risiko") for e in kelompok
          if e.get("rasio_imbalan_risiko") is not None]
    if rr:
        rr_urut = sorted(rr)
        tengah = rr_urut[len(rr_urut) // 2]
        h["rasio_imbalan_risiko_tengah"] = tengah
        h["rasio_di_bawah_1"] = sum(1 for x in rr if x < statistik.RASIO_MINIMUM)
        if h["rasio_di_bawah_1"] == len(rr):
            perlu = statistik.perlu_benar_persen(tengah)
            h["peringatan_rasio"] = (
                f"SELURUH {len(rr)} panggilan menaruh risiko lebih besar daripada imbalannya "
                f"(rasio tengah {tengah}). Pada rasio itu panggilan harus benar {perlu}% kali "
                "hanya untuk IMPAS. Levelnya, bukan analisanya, yang perlu diperbaiki.")

    if n < SAMPEL_MINIMUM:
        h["peringatan"] = (f"SAMPEL KECIL ({n} panggilan) — angka ini TIDAK bermakna secara "
                           "statistik. Jangan dipakai mengubah ambang apa pun.")
    return h


def catatan_untuk_brief():
    """Satu paragraf pendek tentang jejak rekam SENDIRI, atau None kalau tak ada yang perlu.

    Rapor selama ini hanya DITULIS, tidak pernah DIBACA saat analisa berikutnya disusun —
    jadi kelemahan yang sama terulang tanpa pernah sampai ke matanya. Ini menutup lingkaran
    itu, dan sengaja hanya muncul kalau ada peringatan nyata supaya tidak membakar token
    untuk mengabarkan bahwa semuanya baik-baik saja.
    """
    try:
        entri = _muat()
    except Exception:
        return None
    if len(entri) < 5:
        return None                      # terlalu sedikit untuk disimpulkan apa pun
    h = _hitung(entri)
    baris = []
    if h.get("peringatan_rasio"):
        baris.append(h["peringatan_rasio"])
    if h.get("peringatan_terbuka"):
        baris.append(h["peringatan_terbuka"])
    if h.get("peringatan_ekspektansi"):
        baris.append(h["peringatan_ekspektansi"])
    if h.get("peringatan_alpha"):
        baris.append(h["peringatan_alpha"])
    if not baris:
        return None
    return ("JEJAK REKAM SENDIRI (" + str(h["panggilan"]) + " panggilan, dihitung dari "
            "rapor.jsonl — ini tentang panggilanmu sendiri, bukan tentang asetnya):"
            + chr(10) + chr(10).join("- " + b for b in baris) + chr(10)
            + "Perbaiki ini pada panggilan sekarang: level target dan invalidasi harus "
              "dipilih supaya imbalannya SEPADAN dengan risikonya, bukan sekadar menempel "
              "pada support/resistance terdekat.")


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
        "selisih_vs_beli_tahan adalah angka yang paling menentukan: nol berarti bot cuma "
        "ikut arus pasar, positif berarti sarannya benar-benar menambah nilai.",
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
