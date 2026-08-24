"""Funding rate & open interest lintas bursa — tanpa API key, tahan pemblokiran geo.

KENAPA BUKAN LANGSUNG KE BURSA. Binance, Bybit, dan OKX punya endpoint funding/OI yang
bagus dan keyless, tapi SEMUANYA memblokir datacenter AS — dan runner GitHub Actions
adalah datacenter AS. Batas yang sama sudah tercatat di indicators.py sejak lama. Jadi
sumbernya agregator: CoinGecko /derivatives (150 kontrak perpetual BTC dari 100 bursa)
dan Hyperliquid (venue perp on-chain terbesar, penting untuk koin yang pasar utamanya
di sana).

APA YANG TIDAK ADA DI SINI, DAN JANGAN DIKARANG:
  - LIKUIDASI. Tidak ada sumber keyless mana pun yang memberikannya. Kalau ditanya,
    jawab tidak tersedia — jangan menyimpulkannya dari lonjakan harga.
  - PERUBAHAN OI sebelum arsipnya terisi. CoinGecko hanya memberi snapshot saat ini.
    Perubahan dihitung dari arsip harian yang ditumbuhkan berkas ini sendiri, jadi
    angkanya baru muncul setelah beberapa hari — dan sampai itu terjadi, laporkan
    apa adanya.

PERGESERAN PERAN (24 Agu 2026): coinalyze.py kini menyediakan likuidasi DAN riwayat OI
harian sampai 400 hari ke belakang, jadi arsip yang ditumbuhkan berkas ini bukan lagi
satu-satunya jalan. Arsipnya TETAP dipertahankan sebagai cadangan: Coinalyze butuh API key
dan punya batas 40 panggilan/menit, sedangkan berkas ini jalan tanpa kunci sama sekali.
Kalau kuncinya mati, funding dan OI saat ini tetap ada.

CATATAN SATUAN FUNDING: tiap bursa punya interval sendiri (umumnya 8 jam, Hyperliquid
1 jam). CoinGecko tidak menyebut intervalnya, jadi rata-rata tertimbang volume di sini
adalah PENUNJUK ARAH, bukan biaya pendanaan yang presisi. Positif = posisi long membayar
short (permintaan leverage bullish); negatif = sebaliknya.

Pemakaian:
    python cloud/derivatif.py BTC
    python cloud/derivatif.py HYPE --ringkas
"""

import argparse
import json
import os
import time
import urllib.request
from datetime import datetime, timezone

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CACHE_PATH = os.path.join(BASE_DIR, "data", "derivatif_cache.json")
ARSIP_PATH = os.path.join(BASE_DIR, "data", "derivatif_arsip.jsonl")

CG = "https://api.coingecko.com/api/v3/derivatives"
HL = "https://api.hyperliquid.xyz/info"
UA = {"User-Agent": "Mozilla/5.0 (compatible; riset-koin/1.0)"}
TIMEOUT = 30
CACHE_UMUR = 30 * 60

# Balasan mentah CoinGecko 8,8 MB. Yang disimpan HANYA agregatnya — berkas cache di repo
# ini ikut di-commit, jadi menyimpan mentahnya akan menggemukkan tiap clone.
OI_MINIMUM = 10_000_000        # koin di bawah ini tidak punya pasar derivatif berarti
ARSIP_TERATAS = 25             # riwayat ditumbuhkan hanya untuk yang pasarnya nyata


def _agregat_semua():
    """{SIMBOL: agregat} untuk seluruh perpetual. Cache 30 menit, isinya agregat saja."""
    cache = {}
    try:
        with open(CACHE_PATH, encoding="utf-8") as f:
            cache = json.load(f)
    except Exception:
        pass
    if cache.get("data") and time.time() - cache.get("waktu", 0) < CACHE_UMUR:
        return cache["data"], True, None
    try:
        with urllib.request.urlopen(urllib.request.Request(CG, headers=UA),
                                    timeout=TIMEOUT) as r:
            mentah = json.loads(r.read().decode(errors="replace"))
    except Exception as e:
        kode = getattr(e, "code", None)
        pesan = f"{type(e).__name__}" + (f" {kode}" if kode else "")
        if cache.get("data"):
            return cache["data"], True, f"{pesan} (pakai cache lama)"
        return None, False, pesan

    kumpul = {}
    for k in mentah or []:
        if k.get("contract_type") != "perpetual":
            continue
        sim = (k.get("index_id") or "").upper()
        if not sim:
            continue
        d = kumpul.setdefault(sim, {"oi": 0.0, "vol": 0.0, "fb": 0.0, "fn": 0.0,
                                    "kontrak": 0, "bursa": set()})
        oi = k.get("open_interest") or 0
        vol = k.get("volume_24h") or 0
        d["oi"] += oi
        d["vol"] += vol
        d["kontrak"] += 1
        d["bursa"].add(k.get("market"))
        f = k.get("funding_rate")
        if f is not None and vol:
            # Ditimbang VOLUME, bukan rata-rata sederhana: bursa kecil dengan funding
            # ekstrem tidak boleh seberat Binance dalam menentukan arah.
            d["fb"] += vol
            d["fn"] += f * vol

    hasil = {}
    for sim, d in kumpul.items():
        if d["oi"] < OI_MINIMUM:
            continue
        hasil[sim] = {
            "oi_usd": round(d["oi"]),
            "volume_24j_usd": round(d["vol"]),
            "funding_rata2_persen": round(d["fn"] / d["fb"], 5) if d["fb"] else None,
            "kontrak": d["kontrak"],
            "bursa": len(d["bursa"]),
        }
        if d["vol"] and d["oi"]:
            # Volume jauh di atas OI = perdagangan berputar cepat tanpa menambah posisi;
            # sering menyertai gerakan yang digerakkan likuidasi, bukan akumulasi.
            hasil[sim]["volume_per_oi"] = round(d["vol"] / d["oi"], 2)

    try:
        os.makedirs(os.path.dirname(CACHE_PATH), exist_ok=True)
        with open(CACHE_PATH, "w", encoding="utf-8") as f:
            json.dump({"waktu": time.time(), "data": hasil}, f)
    except OSError:
        pass
    return hasil, False, None


def hyperliquid():
    """Funding per JAM dan OI di Hyperliquid. Satuannya beda dari CoinGecko — jangan dicampur."""
    try:
        req = urllib.request.Request(
            HL, data=json.dumps({"type": "metaAndAssetCtxs"}).encode(),
            headers={"Content-Type": "application/json", **UA})
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            meta, ctxs = json.loads(r.read().decode(errors="replace"))
    except Exception as e:
        return None, f"{type(e).__name__}"
    keluar = {}
    for u, c in zip(meta.get("universe", []), ctxs):
        try:
            keluar[u["name"].upper()] = {
                "funding_per_jam_persen": round(float(c["funding"]) * 100, 5),
                "oi_koin": float(c["openInterest"]),
                "volume_24j_usd": round(float(c["dayNtlVlm"])),
            }
        except (KeyError, TypeError, ValueError):
            continue
    return keluar, None


def arsipkan(agregat):
    """Simpan snapshot harian untuk koin dengan OI terbesar. UPSERT per (tanggal, simbol)."""
    if not agregat:
        return 0
    hari = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    teratas = sorted(agregat.items(), key=lambda kv: -kv[1]["oi_usd"])[:ARSIP_TERATAS]

    lama = []
    try:
        with open(ARSIP_PATH, encoding="utf-8") as f:
            lama = [json.loads(x) for x in f if x.strip()]
    except Exception:
        pass
    kunci = {(e.get("tanggal"), e.get("simbol")): i for i, e in enumerate(lama)}
    for sim, d in teratas:
        baris = {"tanggal": hari, "simbol": sim, "oi_usd": d["oi_usd"],
                 "volume_24j_usd": d["volume_24j_usd"],
                 "funding_rata2_persen": d["funding_rata2_persen"]}
        i = kunci.get((hari, sim))
        if i is None:
            lama.append(baris)
        else:
            lama[i] = baris          # snapshot terbaru hari ini menggantikan yang lebih tua
    try:
        os.makedirs(os.path.dirname(ARSIP_PATH), exist_ok=True)
        with open(ARSIP_PATH, "w", encoding="utf-8") as f:
            for e in lama:
                f.write(json.dumps(e, ensure_ascii=False) + "\n")
    except OSError:
        return 0
    return len(teratas)


def perubahan(simbol, hari=7):
    """Perubahan OI terhadap ~`hari` lalu, dari arsip sendiri. None kalau riwayatnya belum ada."""
    try:
        with open(ARSIP_PATH, encoding="utf-8") as f:
            baris = [json.loads(x) for x in f if x.strip()]
    except Exception:
        return None
    milik = sorted([e for e in baris if e.get("simbol") == simbol.upper()],
                   key=lambda e: e.get("tanggal") or "")
    if len(milik) < 2:
        return None
    kini = milik[-1]
    tgl_kini = datetime.strptime(kini["tanggal"], "%Y-%m-%d")
    # Ambil entri TERDEKAT dengan target, bukan yang terlama — kalau arsipnya baru 3 hari,
    # menyebutnya "perubahan 7 hari" adalah kebohongan kecil yang menular ke kesimpulan.
    calon = min(milik[:-1],
                key=lambda e: abs((tgl_kini
                                   - datetime.strptime(e["tanggal"], "%Y-%m-%d")).days - hari))
    jarak = (tgl_kini - datetime.strptime(calon["tanggal"], "%Y-%m-%d")).days
    if not calon.get("oi_usd") or jarak < 1:
        return None
    return {
        "oi_ubah_persen": round((kini["oi_usd"] - calon["oi_usd"]) / calon["oi_usd"] * 100, 2),
        "jarak_hari_sebenarnya": jarak,
        "diminta_hari": hari,
        "dari_tanggal": calon["tanggal"],
        "sampai_tanggal": kini["tanggal"],
    }


def ringkas(simbol):
    simbol = (simbol or "").upper()
    hasil = {"simbol": simbol,
             "generated_utc": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")}

    agregat, dari_cache, err = _agregat_semua()
    if err and not agregat:
        hasil["lintas_bursa_tidak_tersedia"] = err
    else:
        hasil["dari_cache"] = dari_cache
        d = (agregat or {}).get(simbol)
        if d:
            hasil["lintas_bursa"] = d
        else:
            hasil["lintas_bursa_tidak_tersedia"] = (
                f"{simbol} tidak punya pasar perpetual dengan OI di atas "
                f"${OI_MINIMUM/1e6:.0f} juta di CoinGecko. Perlakukan sebagai TIDAK ADA "
                "pasar derivatif berarti, bukan sebagai data yang gagal diambil.")
        if not dari_cache:
            hasil["arsip_baris_ditulis"] = arsipkan(agregat)

    ub = perubahan(simbol, 7)
    if ub:
        hasil["perubahan_oi"] = ub
    else:
        hasil["perubahan_oi_belum_ada"] = (
            "Arsip OI belum cukup panjang. CoinGecko hanya memberi snapshot; riwayatnya "
            "ditumbuhkan berkas ini sendiri sejak run pertama. Katakan belum tersedia — "
            "JANGAN menyimpulkan arah OI dari harga.")

    hl, hl_err = hyperliquid()
    if hl_err:
        hasil["hyperliquid_tidak_tersedia"] = hl_err
    elif simbol in (hl or {}):
        hasil["hyperliquid"] = hl[simbol]

    hasil["wajib_dibaca"] = (
        "Funding POSITIF = long membayar short (permintaan leverage bullish ramai, reli "
        "jadi lebih rentan koreksi kalau pembeli spot melemah); NEGATIF = sebaliknya. "
        "Interval funding berbeda tiap bursa dan CoinGecko tidak menyebutnya, jadi angka "
        "rata-rata di sini PENUNJUK ARAH, bukan biaya yang presisi — jangan mengalikannya "
        "jadi biaya tahunan. LIKUIDASI TIDAK TERSEDIA di sumber gratis mana pun: kalau "
        "ditanya, jawab tidak tersedia, jangan menyimpulkannya dari lonjakan harga. "
        "Satuan Hyperliquid PER JAM dan OI-nya dalam KOIN, bukan dolar — jangan dicampur "
        "dengan angka lintas bursa.")
    return hasil


def main():
    p = argparse.ArgumentParser(description="Funding & open interest lintas bursa")
    p.add_argument("simbol")
    p.add_argument("--ringkas", action="store_true", help="tanpa indentasi")
    a = p.parse_args()
    print(json.dumps(ringkas(a.simbol), ensure_ascii=False,
                     indent=None if a.ringkas else 1))


if __name__ == "__main__":
    main()
