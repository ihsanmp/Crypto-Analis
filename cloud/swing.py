"""MINOR SWING STRATEGY (H1) — dari materi Astronacci yang dikirim user, dideteksi KODE.

ATURANNYA, DIURAI DARI GAMBAR (24 Sep 2026):
  Step 1 — arah tren di H1: BELI hanya kalau harga di atas EMA 50 DAN garis MACD di atas
           titik 0; JUAL kebalikannya.
  Step 2 — swing high & swing low yang BERDEKATAN, jaraknya maks 200 pips. Satuan "pips"
           di gambarnya: rentang 1.155,61 ditulis "115 pips" dan 1.212,66 ditulis
           "121 pips" — jadi 1 pip = $10 di BTC, dan 200 pips = $2.000.
  Beli    — setelah swing low terbentuk DI ATAS EMA 50, pasang BUY STOP di swing high
           (resisten); SL di swing low; TP sejauh rentang swing low→high (RR 1:1).
  Invalid — harga turun di bawah EMA 50 dan MACD di bawah 0.
  Jual    — cermin dari semua di atas.

Contoh di gambarnya (BTC, 21-23 Sep 2026): buy stop 87.281, target 89.140, support
85.460. Rentangnya 1.821 (= 182 pips, di bawah 200) dan 87.281 + 1.821 = 89.102 — dekat
89.140 di gambar. (Catatan: teks gambar itu bertanggal "23 Sept 2025", padahal sumbu
chart-nya "21 Sep '26" — salah ketik di sumbernya.)

YANG TIDAK DISEBUT DI GAMBAR, DITETAPKAN DI SINI SEKALI — sebelum melihat hasil:
  - swing = fraktal 3 candle di tiap sisi, dan baru SAH setelah 3 candle sesudahnya
    tertutup (tanpa itu backtest mengintip masa depan);
  - MACD 12/26/9 (bawaan standar);
  - order buy/sell stop kedaluwarsa setelah 48 candle, dan batal kalau filter tren
    runtuh atau swing low/high-nya tertembus sebelum terisi;
  - candle yang menyentuh SL dan TP sekaligus dihitung KALAH (tak bisa tahu mana duluan);
  - biaya 0,1% pulang-pergi (dan 0,2% sebagai uji kepekaan).
Satu aturan untuk dua pemakaian: deteksi() dipakai analisa langsung DAN uji_swing.py.

KHUSUS BTC. Definisi pip $10 hanya berlaku untuk BTC; aset lain punya skala berbeda dan
gambarnya tidak memberi aturannya.

Pemakaian:
    python cloud/swing.py --ringkas          # status setup BTC H1 saat ini
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

EMA_PERIODE = 50
MACD_CEPAT, MACD_LAMBAT, MACD_SINYAL = 12, 26, 9
FRAKTAL = 3
PIP_BTC = 10.0
MAKS_PIPS = 200
RR = 1.0
KEDALUWARSA = 48
BIAYA_PP = 0.001


def ema(nilai, n):
    k = 2 / (n + 1)
    out, e = [], None
    for v in nilai:
        e = v if e is None else v * k + e * (1 - k)
        out.append(e)
    return out


def macd(close):
    cepat, lambat = ema(close, MACD_CEPAT), ema(close, MACD_LAMBAT)
    garis = [a - b for a, b in zip(cepat, lambat)]
    return garis, ema(garis, MACD_SINYAL)


def _pivot(candle, i, tinggi):
    """Swing high (tinggi=True) / low di indeks i, fraktal FRAKTAL candle per sisi."""
    kol = 2 if tinggi else 3
    v = candle[i][kol]
    sisi = candle[i - FRAKTAL:i] + candle[i + 1:i + 1 + FRAKTAL]
    return all(v > c[kol] for c in sisi) if tinggi else all(v < c[kol] for c in sisi)


def _indikator(candle):
    close = [c[4] for c in candle]
    return ema(close, EMA_PERIODE), macd(close)[0]


def setup_di(candle, t, e50=None, garis=None):
    """Setup yang TERBENTUK tepat saat candle t tertutup, atau None.

    Pivot di indeks p baru sah saat candle p+FRAKTAL tertutup — jadi pada candle t hanya
    pivot di t-FRAKTAL yang baru saja sah.
    """
    if e50 is None:
        e50, garis = _indikator(candle)
    p = t - FRAKTAL
    if p < max(EMA_PERIODE, FRAKTAL):
        return None
    batas = MAKS_PIPS * PIP_BTC
    close = candle[t][4]
    for arah in ("BELI", "JUAL"):
        tren_ok = (close > e50[t] and garis[t] > 0) if arah == "BELI" else \
                  (close < e50[t] and garis[t] < 0)
        if not tren_ok:
            continue
        # Pivot yang baru sah = pullback (swing low untuk BELI).
        if not _pivot(candle, p, tinggi=(arah == "JUAL")):
            continue
        if arah == "BELI":
            bawah = candle[p][3]
            if bawah <= e50[p]:
                continue              # "swing low DI ATAS EMA 50"
            # Swing high terdekat sebelum pullback itu = resisten.
            atas = next((candle[q][2] for q in range(p - 1, FRAKTAL - 1, -1)
                         if _pivot(candle, q, True)), None)
            if atas is None or not (0 < atas - bawah <= batas):
                continue
            return {"arah": "BELI", "entry": atas, "sl": bawah,
                    "tp": atas + RR * (atas - bawah), "rentang": atas - bawah, "t": t}
        atas = candle[p][2]
        if atas >= e50[p]:
            continue
        bawah = next((candle[q][3] for q in range(p - 1, FRAKTAL - 1, -1)
                      if _pivot(candle, q, False)), None)
        if bawah is None or not (0 < atas - bawah <= batas):
            continue
        return {"arah": "JUAL", "entry": bawah, "sl": atas,
                "tp": bawah - RR * (atas - bawah), "rentang": atas - bawah, "t": t}
    return None


def _batal(candle, i, s, e50, garis):
    c = candle[i]
    if s["arah"] == "BELI":
        return (c[4] < e50[i] and garis[i] < 0) or c[3] <= s["sl"]
    return (c[4] > e50[i] and garis[i] > 0) or c[2] >= s["sl"]


def backtest(candle, biaya=BIAYA_PP):
    """Daftar transaksi: {arah, t_setup, t_isi, hasil_R} — satu posisi pada satu waktu."""
    e50, garis = _indikator(candle)
    transaksi, i = [], EMA_PERIODE + FRAKTAL
    n = len(candle)
    while i < n:
        s = setup_di(candle, i, e50, garis)
        if not s:
            i += 1
            continue
        # Menunggu order stop terisi.
        isi = None
        for j in range(i + 1, min(n, i + 1 + KEDALUWARSA)):
            c = candle[j]
            kena = c[2] >= s["entry"] if s["arah"] == "BELI" else c[3] <= s["entry"]
            if kena:
                isi = j
                break
            if _batal(candle, j, s, e50, garis):
                break
        if isi is None:
            i += 1
            continue
        # Mengelola posisi sampai SL atau TP.
        hasil, k = None, isi
        while k < n and hasil is None:
            c = candle[k]
            if s["arah"] == "BELI":
                sl_kena, tp_kena = c[3] <= s["sl"], c[2] >= s["tp"]
            else:
                sl_kena, tp_kena = c[2] >= s["sl"], c[3] <= s["tp"]
            if sl_kena:
                hasil = -1.0            # termasuk candle yang menyentuh keduanya
            elif tp_kena:
                hasil = RR
            k += 1
        if hasil is None:
            break                       # posisi masih terbuka di akhir data
        biaya_r = biaya * s["entry"] / s["rentang"]
        transaksi.append({"arah": s["arah"], "t_setup": s["t"], "t_isi": isi,
                          "ts_isi": candle[isi][0], "hasil_R": hasil - biaya_r,
                          "rentang": s["rentang"]})
        i = k
    return transaksi


def ringkas_uji(transaksi):
    n = len(transaksi)
    if not n:
        return {"n": 0}
    menang = sum(1 for x in transaksi if x["hasil_R"] > 0)
    total = sum(x["hasil_R"] for x in transaksi)
    beruntun = terpanjang = 0
    for x in transaksi:
        beruntun = beruntun + 1 if x["hasil_R"] <= 0 else 0
        terpanjang = max(terpanjang, beruntun)
    return {"n": n, "menang_persen": round(100 * menang / n, 1),
            "ekspektansi_R": round(total / n, 3), "total_R": round(total, 1),
            "kalah_beruntun_terpanjang": terpanjang,
            "rentang_rata_usd": round(sum(x["rentang"] for x in transaksi) / n)}


def status_kini(candle):
    """Keadaan setup di candle TERAKHIR: setup aktif, menunggu, atau tidak ada."""
    e50, garis = _indikator(candle)
    n = len(candle)
    t = n - 1
    harga = candle[t][4]
    arah_tren = ("NAIK" if harga > e50[t] and garis[t] > 0 else
                 "TURUN" if harga < e50[t] and garis[t] < 0 else "CAMPUR")
    # Setup terakhir yang masih hidup (belum terisi, belum batal, belum kedaluwarsa).
    for mulai in range(t, max(EMA_PERIODE + FRAKTAL, t - KEDALUWARSA), -1):
        s = setup_di(candle, mulai, e50, garis)
        if not s:
            continue
        hidup, terisi = True, False
        for j in range(mulai + 1, n):
            c = candle[j]
            if (s["arah"] == "BELI" and c[2] >= s["entry"]) or \
               (s["arah"] == "JUAL" and c[3] <= s["entry"]):
                terisi = True
                break
            if _batal(candle, j, s, e50, garis):
                hidup = False
                break
        if hidup:
            return {"tren": arah_tren, "harga": harga, "ema50": e50[t], "macd": garis[t],
                    "setup": dict(s, terisi=terisi, umur_candle=t - mulai)}
        break
    return {"tren": arah_tren, "harga": harga, "ema50": e50[t], "macd": garis[t],
            "setup": None}


# Hasil backtest yang dipaku dari uji_swing.py (runner GitHub, Bitstamp H1). Diisi
# setelah ujinya berjalan; sampai saat itu blok brief menyebutnya BELUM diuji.
HASIL_UJI = None


def _usd(x):
    return "$" + f"{x:,.0f}".replace(",", ".")


def ringkas(st):
    b = [f"MINOR SWING STRATEGY BTC H1 (aturan Astronacci, dideteksi kode swing.py)",
         f"Tren H1: {st['tren']} — harga {_usd(st['harga'])}, EMA50 {_usd(st['ema50'])}, "
         f"MACD {st['macd']:+.0f}"]
    s = st["setup"]
    if s:
        kata = "BUY STOP" if s["arah"] == "BELI" else "SELL STOP"
        b.append(f"Setup {s['arah']} {'SUDAH TERISI' if s['terisi'] else 'menunggu'}: "
                 f"{kata} {_usd(s['entry'])} · SL {_usd(s['sl'])} · TP {_usd(s['tp'])} "
                 f"(rentang {s['rentang'] / PIP_BTC:.0f} pips, RR 1:1, umur "
                 f"{s['umur_candle']} candle)")
    elif st["tren"] == "CAMPUR":
        b.append("Tidak ada setup: harga & MACD tidak searah (tren campur) — tunggu.")
    else:
        b.append("Belum ada setup: tren searah, tapi swing pullback yang memenuhi syarat "
                 "belum terbentuk — wait & see (Step 1 gambar).")
    if HASIL_UJI:
        h = HASIL_UJI
        b.append(f"Uji balik ({h['periode']}, biaya {h['biaya']}): {h['n']} transaksi, menang "
                 f"{h['menang_persen']}%, ekspektansi {h['ekspektansi_R']}R per transaksi.")
        b.append(h["arti"])
    else:
        b.append("Uji balik: BELUM dijalankan — jangan menyebut peluang menang strategi ini.")
    return "\n".join(b)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ringkas", action="store_true")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    from indicators import fetch_base, resolve_cg_id
    candle, sumber, _kual, err = fetch_base("BTC", resolve_cg_id("BTC"), "1h")
    if not candle or len(candle) < EMA_PERIODE + 20:
        print(f"MINOR SWING STRATEGY BTC H1: candle H1 tidak tersedia ({err}) — "
              "status setup tidak bisa dihitung, jangan mengarang levelnya.")
        return
    st = status_kini(candle)
    st["sumber"] = sumber
    if a.json:
        print(json.dumps(st, indent=2, default=str))
        return
    print(ringkas(st))


if __name__ == "__main__":
    main()
