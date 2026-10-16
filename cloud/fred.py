"""Satu pintu ke FRED untuk semua modul (makro.py, jam_likuiditas.py, ppi_cpi.py, sentix.py).

KENAPA ADA (16 Okt 2026, periksa_fred.py dari runner GitHub): fred.stlouisfed.org dan
alfred.stlouisfed.org TIDAK terjangkau dari runner — setiap permintaan habis waktu, apa pun
ukuran riwayat atau jumlah paralelnya. api.stlouisfed.org (API resmi FRED) TERJANGKAU, tapi
butuh kunci gratis (secret FRED_API_KEY). Seri dan angkanya sama persis; hanya pintunya.

Urutan: API resmi bila FRED_API_KEY ada -> fredgraph.csv publik. Bila fredgraph sekali saja
habis waktu, sisa permintaan di proses yang sama langsung dilewati: tujuh seri x 45 detik
menunggu host yang diblokir hanya membuang batas 300 detik pengumpul data bot.

KUNCI TIDAK PERNAH ikut ke keluaran mana pun — repo ini publik dan log Actions terbaca
publik. Pesan galat hanya memuat jenis galat atau kode HTTP, tidak pernah URL.

    python cloud/fred.py DGS2 [mulai]
"""
import json
import os
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request

API = "https://api.stlouisfed.org/fred/series/observations"
GRAPH = "https://fred.stlouisfed.org/graph/fredgraph.csv"
UA = {"User-Agent": "Mozilla/5.0 (compatible; riset-pasar/1.0)"}
TIMEOUT = 45
_GRAPH_DIBLOKIR = [False]


def _kunci():
    return os.environ.get("FRED_API_KEY", "").strip()


def _lewat_api(kode, mulai, kunci):
    p = {"series_id": kode, "api_key": kunci, "file_type": "json"}
    if mulai:
        p["observation_start"] = mulai
    req = urllib.request.Request(API + "?" + urllib.parse.urlencode(p), headers=UA)
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            d = json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        return None, f"API HTTP {e.code}"            # tanpa URL: URL memuat kunci
    except Exception as e:
        return None, f"API {type(e).__name__}"
    keluar = []
    for o in d.get("observations") or []:
        v = (o.get("value") or "").strip()
        if v in (".", ""):
            continue            # FRED menandai data kosong dengan titik — jangan ditambal
        try:
            keluar.append((o["date"], float(v)))
        except (KeyError, ValueError):
            continue
    return (keluar, None) if keluar else (None, "API tidak ada data terbaca")


def _lewat_graph(kode, mulai):
    """fredgraph.csv lewat curl (di sebagian jaringan urllib menggantung di proxy)."""
    if _GRAPH_DIBLOKIR[0]:
        return None, "fredgraph dilewati (habis waktu sebelumnya di proses ini)"
    url = f"{GRAPH}?id={kode}" + (f"&cosd={mulai}" if mulai else "")
    try:
        p = subprocess.run(["curl", "-s", "-f", "--max-time", str(TIMEOUT), "-A", UA["User-Agent"],
                            url], capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=TIMEOUT + 15)
    except subprocess.TimeoutExpired:
        _GRAPH_DIBLOKIR[0] = True
        return None, "fredgraph TimeoutError"
    except FileNotFoundError:
        return _lewat_graph_urllib(url)
    if p.returncode == 28:                           # curl: operation timed out
        _GRAPH_DIBLOKIR[0] = True
        return None, "fredgraph TimeoutError"
    if p.returncode != 0 or not p.stdout.strip():
        return None, f"fredgraph curl kode {p.returncode}"
    return _urai_csv(p.stdout)


def _lewat_graph_urllib(url):
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=UA),
                                    timeout=TIMEOUT) as r:
            return _urai_csv(r.read().decode())
    except urllib.error.HTTPError as e:
        return None, f"fredgraph HTTP {e.code}"
    except Exception as e:
        if "timed out" in str(e).lower() or isinstance(e, TimeoutError):
            _GRAPH_DIBLOKIR[0] = True
        return None, f"fredgraph {type(e).__name__}"


def _urai_csv(teks):
    keluar = []
    for b in teks.strip().split("\n")[1:]:
        bagian = b.split(",")
        if len(bagian) < 2 or bagian[1].strip() in (".", ""):
            continue
        try:
            keluar.append((bagian[0].strip(), float(bagian[1])))
        except ValueError:
            continue
    return (keluar, None) if keluar else (None, "fredgraph tidak ada data terbaca")


def seri(kode, mulai=None):
    """[(tanggal ISO, nilai)] lama->baru, atau (None, error yang menyebut SEMUA jalur)."""
    galat = []
    kunci = _kunci()
    if kunci:
        data, err = _lewat_api(kode, mulai, kunci)
        if data:
            return data, None
        galat.append(err)
    data, err = _lewat_graph(kode, mulai)
    if data:
        return data, None
    galat.append(err)
    if not kunci:
        galat.append("FRED_API_KEY kosong (fredgraph diblokir dari runner GitHub; "
                     "API resmi butuh kunci gratis)")
    return None, "; ".join(galat)


if __name__ == "__main__":
    d, e = seri(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else None)
    print(e or f"{len(d)} titik, terakhir {d[-1]}")
