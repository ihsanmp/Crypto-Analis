"""Perkembangan AI dari RSS resmi — GRATIS, tanpa API key, tanpa server tambahan.

Kenapa RSS langsung, bukan MCP berita:
  - Sumbernya sama persis (feed resmi lab AI & media teknologi), tapi tanpa memasang
    binary/Docker tambahan di tiap run GitHub Actions.
  - Tidak menitipkan kueri ke endpoint pihak ketiga yang di-host orang lain.
  - Cukup pustaka standar Python, sejalan dengan script lain di repo ini.

Relevansi untuk bot crypto: narasi AI menggerakkan sektor token AI (TAO, RENDER, FET,
NEAR, dsb). Rilis model besar, pendanaan, atau regulasi AI sering jadi katalis sektor itu.

BATASAN (sampaikan apa adanya):
  - RSS memuat JUDUL + ringkasan, bukan artikel penuh. Untuk isi lengkap pakai WebFetch.
  - Feed bisa mati/pindah tanpa pemberitahuan; yang gagal dilaporkan apa adanya di
    field `feed_gagal`, TIDAK disembunyikan.
  - Anthropic tidak punya feed RSS publik (semua URL yang beredar 404 per Agustus 2026) —
    untuk berita Anthropic pakai WebSearch.

Pemakaian:
    python cloud/ainews.py                 # semua sumber, 7 hari terakhir
    python cloud/ainews.py --hari 3 --limit 15
    python cloud/ainews.py --crypto        # hanya yang menyinggung crypto/token/chip
"""

import argparse
import json
import re
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

UA = {"User-Agent": "Mozilla/5.0 (compatible; riset-koin/1.0)"}
TIMEOUT = 20
ATOM = "{http://www.w3.org/2005/Atom}"

# Hanya feed yang SUDAH DIVERIFIKASI hidup. Anthropic sengaja tidak ada (tidak punya RSS
# publik; semua URL yang beredar mengembalikan 404).
FEEDS = {
    "OpenAI": "https://openai.com/news/rss.xml",
    "Google DeepMind": "https://deepmind.google/blog/rss.xml",
    "Hugging Face": "https://huggingface.co/blog/feed.xml",
    "TechCrunch AI": "https://techcrunch.com/category/artificial-intelligence/feed/",
    "VentureBeat AI": "https://venturebeat.com/category/ai/feed/",
    "The Decoder": "https://the-decoder.com/feed/",
    "MIT Tech Review": "https://www.technologyreview.com/feed/",
    "Ars Technica": "https://feeds.arstechnica.com/arstechnica/index",
}

# Kata kunci yang menandakan berita AI itu menyentuh dunia crypto / infrastruktur token.
_CRYPTO_RE = re.compile(
    r"\b(crypto|bitcoin|ethereum|blockchain|token|web3|defi|nft|onchain|on-chain|"
    r"stablecoin|mining|miner|gpu|nvidia|chip|datacenter|data center|compute|"
    r"decentrali[sz]ed|dao)\b", re.IGNORECASE)


def teks(el):
    return (el.text or "").strip() if el is not None else ""


def waktu(item):
    """Ambil tanggal terbit dari RSS (pubDate) atau Atom (published/updated)."""
    for tag in ("pubDate", "{http://purl.org/dc/elements/1.1/}date"):
        n = item.find(tag)
        if n is not None and n.text:
            try:
                d = parsedate_to_datetime(n.text)
                return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
            except Exception:
                pass
    for tag in (ATOM + "published", ATOM + "updated"):
        n = item.find(tag)
        if n is not None and n.text:
            try:
                return datetime.fromisoformat(n.text.replace("Z", "+00:00"))
            except Exception:
                pass
    return None


def tautan(item):
    n = item.find("link")
    if n is not None:
        if n.text and n.text.strip():
            return n.text.strip()
        if n.get("href"):
            return n.get("href")
    n = item.find(ATOM + "link")
    return n.get("href") if n is not None else ""


def ambil_feed(pasangan):
    """Return (nama, daftar_item, pesan_error). Kegagalan TIDAK dilempar — dilaporkan."""
    nama, url = pasangan
    try:
        req = urllib.request.Request(url, headers=UA)
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            root = ET.fromstring(r.read())
    except urllib.error.HTTPError as e:
        return nama, [], f"HTTP {e.code}"
    except Exception as e:
        return nama, [], f"{type(e).__name__}"

    # PENTING: Element tanpa anak bernilai False di ElementTree, jadi pemeriksaan
    # WAJIB memakai 'is not None' — bukan 'or'. Kekeliruan ini pernah membuat seluruh
    # judul terbaca kosong padahal feed-nya baik-baik saja.
    entri = root.findall(".//item")
    if not entri:
        entri = root.findall(".//" + ATOM + "entry")

    keluar = []
    for it in entri:
        judul = teks(it.find("title")) or teks(it.find(ATOM + "title"))
        if not judul:
            continue
        keluar.append({"sumber": nama, "judul": judul,
                       "url": tautan(it), "terbit": waktu(it)})
    return nama, keluar, None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--hari", type=int, default=7, help="rentang hari ke belakang")
    ap.add_argument("--limit", type=int, default=25, help="maksimal berita ditampilkan")
    ap.add_argument("--crypto", action="store_true",
                    help="saring hanya yang menyinggung crypto/chip/compute")
    args = ap.parse_args()

    batas = datetime.now(timezone.utc) - timedelta(days=args.hari)
    semua, gagal = [], {}

    with ThreadPoolExecutor(max_workers=8) as pool:
        for nama, item, err in pool.map(ambil_feed, FEEDS.items()):
            if err:
                gagal[nama] = err
                continue
            semua.extend(item)

    dipakai = []
    for b in semua:
        if b["terbit"] and b["terbit"] < batas:
            continue
        if args.crypto and not _CRYPTO_RE.search(b["judul"]):
            continue
        dipakai.append(b)

    # Yang tidak punya tanggal ditaruh di belakang, bukan dibuang — tetap dilaporkan.
    dipakai.sort(key=lambda b: b["terbit"] or datetime.min.replace(tzinfo=timezone.utc),
                 reverse=True)

    hasil = {
        "generated_utc": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M"),
        "sumber": "RSS resmi lab AI & media teknologi (gratis, tanpa API key)",
        "rentang_hari": args.hari,
        "saringan_crypto": bool(args.crypto),
        "jumlah": len(dipakai[:args.limit]),
        "berita": [{
            "tanggal": b["terbit"].strftime("%Y-%m-%d") if b["terbit"] else "tanggal tidak ada",
            "sumber": b["sumber"],
            "judul": b["judul"],
            "url": b["url"],
            "menyinggung_crypto": bool(_CRYPTO_RE.search(b["judul"])),
        } for b in dipakai[:args.limit]],
        "cara_pakai": [
            "Ini JUDUL + tanggal, bukan artikel penuh. Untuk isi lengkap pakai WebFetch ke url-nya.",
            "Judul RSS = klaim media, bukan fakta terverifikasi. Sebut sumber + tanggalnya.",
            "'menyinggung_crypto' hanya cocokan kata kunci di judul — periksa isinya sebelum "
            "menyimpulkan dampak ke sebuah token.",
            "Anthropic tidak punya feed RSS publik; untuk berita Anthropic pakai WebSearch.",
        ],
    }
    if gagal:
        hasil["feed_gagal"] = gagal
    print(json.dumps(hasil, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
