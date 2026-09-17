"""Aktivitas developer dari GITHUB LANGSUNG, dipandu taksonomi Electric Capital.

Aturan invalidasi ke-3 kerangka #Kalimasada berbunyi "developer pergi — on-chain & Electric
Capital menunjukkan aktivitas melemah". Sebelum berkas ini, satu-satunya sumbernya
`dev_activity` Santiment: satu angka, tanpa cara memeriksa dari mana asalnya.

KENAPA REPO DARI COINGECKO SAJA TIDAK CUKUP — ini yang membuat berkas ini ada. CoinGecko
menunjuk SATU repo per koin, dan repo itu bisa sudah ditinggalkan. Contoh nyata (diuji
16 Sep 2026): untuk TAO, CoinGecko menunjuk `opentensor/bittensor`, yang 8 minggu terakhir
punya NOL commit. Repo yang benar-benar dikerjakan, `opentensor/subtensor`, 8 minggu terakhir
punya 367. Membaca yang pertama saja menghasilkan kesimpulan "developer pergi" yang terbalik
180 derajat — persis kesalahan yang aturan invalidasi ini seharusnya cegah.

Karena itu daftar repo diambil dari TAKSONOMI Electric Capital (repo open-dev-data, lisensi
terbuka): daftar semua repo milik tiap ekosistem, hasil kurasi manusia. Dari situ diambil
organisasi yang paling sering muncul, GitHub ditanya isi tiap organisasi itu, lalu yang
dipantau adalah repo yang PALING BARU DI-PUSH DARI SELURUH ORGANISASI — bukan beberapa repo
teratas per organisasi. Bedanya bukan teori: percobaan pertama memilih per organisasi dan
melaporkan NOL commit untuk Bittensor, karena `opentensor` memang sudah sepi; kerjanya pindah
ke organisasi lain (RaoFoundation), yang baru terlihat setelah pemilihannya lintas organisasi.

BIAYA DAN BATASNYA:
  - Taksonomi tidak punya API. Yang ada arsip migrasi (~17 MB, 1,1 juta baris perintah).
    Diunduh dan diputar ulang HANYA saat ekosistemnya belum ada di cache; hasilnya disimpan.
  - GitHub tanpa kunci: 60 permintaan/jam. Di GitHub Actions, GITHUB_TOKEN bawaan menaikkannya
    ke 5.000/jam — dipakai otomatis kalau ada di environment.
  - Yang dihitung COMMIT, bukan developer unik. Commit bisa digelembungkan (bot, merge,
    otomatisasi). Angka ini untuk melihat ARAH, bukan untuk menilai besar tim.
  - Hanya organisasi utama yang ditanya, bukan seluruh ekosistem. Kontributor independen di
    luar org itu tidak terhitung.

Pemakaian:
    python cloud/devkode.py TAO
    python cloud/devkode.py TAO --json
    python cloud/devkode.py --ekosistem Bittensor --json
"""

import argparse
import collections
import concurrent.futures
import json
import os
import shlex
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.parse
import cgkunci  # noqa: E402  kunci Demo CoinGecko, dikirim lewat header

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CACHE_DIR = os.environ.get("CACHE_DIR_EKO") or os.path.join(BASE_DIR, "data")
CACHE_PATH = os.path.join(CACHE_DIR, "eko_repos.json")
UA = "riset-koin/1.0"

TARBALL = "https://codeload.github.com/electric-capital/crypto-ecosystems/tar.gz/refs/heads/master"
UMUR_CACHE_DETIK = 30 * 24 * 3600      # taksonomi berubah pelan; sebulan sudah sering
REPO_MAKS_DISIMPAN = 200               # cache ini ikut ter-commit; jangan biarkan membengkak
ORG_MAKS_DISIMPAN = 40
ORG_DITANYA = 15                       # organisasi teratas yang ditanyakan ke GitHub
REPO_DITANYA = 5                       # repo paling baru di-push, DARI SELURUH organisasi
MINGGU_BARU = 4
MINGGU_LAMA = 12

HASIL_UJI = ("Diuji 16 Sep 2026 pada TAO: repo tunjukan CoinGecko (opentensor/bittensor) "
             "0 commit dalam 8 minggu, sedangkan repo yang benar-benar dikerjakan sudah "
             "PINDAH ORGANISASI ke RaoFoundation/subtensor (367 commit). Sumber repo "
             "tunggal, dan juga tebakan 'organisasi terbesar', bisa menyesatkan total.")


# --- Utilitas jaringan --------------------------------------------------------------------
def _curl(url, timeout=40, kepala=None):
    perintah = ["curl", "-s", "-L", "--max-time", str(timeout), "-A", UA]
    for k in kepala or []:
        perintah += ["-H", k]
    perintah += cgkunci.argumen_curl(url)
    perintah.append(url)
    try:
        p = subprocess.run(perintah, capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=timeout + 10)
        return p.stdout if p.returncode == 0 else ""
    except Exception:
        return ""


def _kepala_github():
    """GITHUB_TOKEN dipakai kalau ada — 60 permintaan/jam jadi 5.000/jam di GitHub Actions."""
    kepala = ["Accept: application/vnd.github+json"]
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if token:
        kepala.append("Authorization: Bearer " + token)
    return kepala


# Sekali batas GitHub kena, SEMUA permintaan berikutnya pasti ditolak juga. Tanpa penanda ini
# alatnya tetap mencoba satu per satu, lengkap dengan jeda ulangnya: diukur 16 Sep 2026, satu
# panggilan memakan 2 menit 35 detik hanya untuk mengumpulkan penolakan. Sekarang berhenti.
_STATUS = {"batas_kena": False}


def _gh(jalur, timeout=40):
    if _STATUS["batas_kena"]:
        return None
    teks = _curl("https://api.github.com" + jalur, timeout=timeout, kepala=_kepala_github())
    if not teks:
        return None
    try:
        d = json.loads(teks)
    except json.JSONDecodeError:
        return None
    if isinstance(d, dict) and "rate limit" in (d.get("message") or "").lower():
        _STATUS["batas_kena"] = True
        return None
    return d


# --- Cache ---------------------------------------------------------------------------------
def _baca_cache():
    try:
        with open(CACHE_PATH, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}


def _tulis_cache(isi):
    try:
        os.makedirs(CACHE_DIR, exist_ok=True)
        with open(CACHE_PATH, "w", encoding="utf-8") as f:
            json.dump(isi, f, ensure_ascii=False, indent=1, sort_keys=True)
    except OSError:
        pass


# --- Taksonomi Electric Capital -------------------------------------------------------------
def _baris_migrasi(jalur_tar):
    """Semua baris perintah migrasi, URUT WAKTU. Urutan menentukan hasil: repadd lalu reprem
    berarti repo itu dibuang; terbalik berarti ia ada."""
    with tarfile.open(jalur_tar, "r:gz") as t:
        anggota = [m for m in t.getmembers()
                   if m.isfile() and "/migrations/" in m.name]
        anggota.sort(key=lambda m: os.path.basename(m.name)[:19])
        for m in anggota:
            f = t.extractfile(m)
            if not f:
                continue
            for baris in f.read().decode("utf-8", "replace").splitlines():
                baris = baris.strip()
                if baris and not baris.startswith("--"):
                    yield baris


def _pecah(baris):
    try:
        bagian = shlex.split(baris)
    except ValueError:
        return None
    return bagian or None


def _subpohon(baris_semua, akar):
    """Nama ekosistem `akar` + semua anaknya (rekursif), mengikuti ecoadd/ecocon/ecodis/ecomov.

    Jalan pertama hanya menyentuh perintah ekosistem — jutaan baris repo dilewati, jadi
    memorinya tetap kecil. Nama dicocokkan tanpa peduli besar-kecil huruf.
    """
    anak = collections.defaultdict(set)
    semua = set()
    for baris in baris_semua:
        b = _pecah(baris)
        if not b:
            continue
        cmd = b[0]
        if cmd == "ecoadd" and len(b) >= 2:
            semua.add(b[1])
        elif cmd == "ecocon" and len(b) >= 3:
            anak[b[1]].add(b[2])
            semua.update(b[1:3])
        elif cmd == "ecodis" and len(b) >= 3:
            anak[b[1]].discard(b[2])
        elif cmd == "ecomov" and len(b) >= 3:
            semua.discard(b[1])
            semua.add(b[2])
            anak[b[2]] |= anak.pop(b[1], set())
            for s in anak.values():
                if b[1] in s:
                    s.discard(b[1])
                    s.add(b[2])
        elif cmd == "ecorem" and len(b) >= 2:
            semua.discard(b[1])
            anak.pop(b[1], None)
    cocok = next((n for n in semua if n.lower() == (akar or "").lower()), None)
    if not cocok:
        return None, sorted(semua)
    keluar, antre = set(), [cocok]
    while antre:
        n = antre.pop()
        if n in keluar:
            continue
        keluar.add(n)
        antre.extend(anak.get(n, ()))
    return keluar, sorted(semua)


def _repo_subpohon(baris_semua, subpohon):
    """Repo milik ekosistem di `subpohon`. Jalan kedua, hanya untuk nama yang relevan."""
    punya = set()
    kecil = {n.lower() for n in subpohon}
    for baris in baris_semua:
        b = _pecah(baris)
        if not b:
            continue
        cmd = b[0]
        if cmd == "repadd" and len(b) >= 3 and b[1].lower() in kecil:
            punya.add(b[2])
        elif cmd == "reprem" and len(b) >= 3 and b[1].lower() in kecil:
            punya.discard(b[2])
        elif cmd == "repmov" and len(b) >= 3 and b[1] in punya:
            punya.discard(b[1])
            punya.add(b[2])
    return sorted(punya)


def taksonomi(nama_ekosistem, paksa=False):
    """Repo satu ekosistem menurut Electric Capital. Return (repos, catatan, n_total).

    `n_total` dikembalikan terpisah karena daftar yang disimpan DIPOTONG: tanpa ini, angka
    yang dilaporkan jadi 200 untuk ekosistem apa pun yang lebih besar dari itu — batas cache
    menyamar sebagai fakta tentang ekosistemnya.

    Cache-nya per ekosistem supaya berkasnya tetap kecil: hanya yang pernah ditanyakan yang
    ikut tersimpan dan ter-commit.
    """
    cache = _baca_cache()
    simpan = (cache.get("ekosistem") or {}).get((nama_ekosistem or "").lower())
    if not paksa and simpan and time.time() - (simpan.get("waktu") or 0) < UMUR_CACHE_DETIK:
        repos = simpan.get("repos") or []
        return repos, "cache", simpan.get("n_repo", len(repos))
    # Nama yang sudah diketahui TIDAK ADA di taksonomi juga dicatat, supaya tidak mengunduh
    # 17 MB berulang kali cuma untuk menemukan ketiadaan yang sama.
    tidak_ada = cache.get("tidak_ada") or {}
    if not paksa and (nama_ekosistem or "").lower() in tidak_ada:
        return [], "tidak ada di taksonomi (cache)", 0
    if os.environ.get("EKO_TANPA_UNDUH"):
        return [], "unduhan taksonomi dimatikan (EKO_TANPA_UNDUH)", 0

    with tempfile.TemporaryDirectory(prefix="eko_") as d:
        jalur = os.path.join(d, "ec.tar.gz")
        p = subprocess.run(["curl", "-s", "-f", "-L", "--max-time", "120", "-o", jalur,
                            TARBALL], capture_output=True, timeout=180)
        if p.returncode != 0 or not os.path.exists(jalur):
            return [], "arsip taksonomi gagal diunduh", 0
        sub, _semua = _subpohon(_baris_migrasi(jalur), nama_ekosistem)
        if not sub:
            cache.setdefault("tidak_ada", {})[(nama_ekosistem or "").lower()] = time.time()
            _tulis_cache(cache)
            return [], "tidak ada di taksonomi", 0
        repos = _repo_subpohon(_baris_migrasi(jalur), sub)

    cache.setdefault("ekosistem", {})[(nama_ekosistem or "").lower()] = {
        "waktu": time.time(), "nama": nama_ekosistem, "n_repo": len(repos),
        "sub_ekosistem": sorted(sub)[:50],
        # Hitungan organisasi dibuat dari daftar PENUH, sebelum dipotong. Versi pertama alat
        # ini menghitungnya setelah dipotong 200 teratas secara alfabetis, jadi organisasi
        # yang namanya di ujung abjad hilang tanpa jejak.
        "org_hitung": dict(_hitung_org(repos).most_common(ORG_MAKS_DISIMPAN)),
        "repos": repos[:REPO_MAKS_DISIMPAN]}
    _tulis_cache(cache)
    return repos, "taksonomi diunduh", len(repos)


def _hitung_org(repos):
    hitung = collections.Counter()
    for u in repos:
        bagian = urllib.parse.urlparse(u).path.strip("/").split("/")
        if len(bagian) >= 2 and "github.com" in u:
            hitung[bagian[0]] += 1
    return hitung


def organisasi(nama_ekosistem, repos, n=ORG_DITANYA):
    """Organisasi GitHub yang paling sering muncul di ekosistem itu.

    Diambil dari `org_hitung` di cache kalau ada (dihitung dari daftar penuh); kalau tidak,
    dari daftar yang diberikan.
    """
    simpan = (_baca_cache().get("ekosistem") or {}).get((nama_ekosistem or "").lower()) or {}
    hitung = collections.Counter(simpan.get("org_hitung") or {}) or _hitung_org(repos)
    return [o for o, _ in hitung.most_common(n)]


# --- GitHub ---------------------------------------------------------------------------------
def _repo_org(org):
    """Repo satu organisasi beserta tanggal push terakhirnya. Coba /orgs, lalu /users."""
    for jalur in (f"/orgs/{org}/repos", f"/users/{org}/repos"):
        d = _gh(jalur + "?sort=pushed&direction=desc&per_page=100")
        if isinstance(d, list) and d:
            return [{"penuh": r.get("full_name"), "push": (r.get("pushed_at") or "")}
                    for r in d if not r.get("fork") and not r.get("archived")
                    and r.get("full_name")]
    return []


def _mingguan(penuh, ulang=1):
    """Commit mingguan 52 minggu terakhir. GitHub membalas 202 + badan kosong saat statistik
    masih dihitung, jadi sekali coba lagi setelah jeda — dan TIDAK menunggu setelah percobaan
    terakhir, karena menunggu untuk sesuatu yang tidak akan ditanyakan lagi cuma memperlambat."""
    for sisa in range(ulang, -1, -1):
        d = _gh(f"/repos/{penuh}/stats/participation")
        if isinstance(d, dict) and isinstance(d.get("all"), list) and d["all"]:
            return d["all"]
        if sisa:
            time.sleep(2)
    return None


def pilih_repo(kolam, n=REPO_DITANYA):
    """Repo yang paling baru di-push, LINTAS organisasi. Fungsi murni supaya bisa diuji."""
    return sorted(kolam, key=lambda r: r.get("push") or "", reverse=True)[:n]


def aktivitas(orgs):
    """Commit mingguan dari repo yang PALING BARU DI-PUSH di seluruh organisasi ekosistem.

    Dipilih lintas organisasi, bukan per organisasi: kerja nyata sering pindah ke organisasi
    lain (Bittensor: opentensor -> RaoFoundation), dan memilih per organisasi membuat
    organisasi lama yang sudah mati tetap ikut mengisi jatah repo yang dipantau.
    """
    kolam = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as ex:
        for hasil in ex.map(_repo_org, orgs):
            kolam.extend(hasil)
    if not kolam:
        return None
    pilih = pilih_repo(kolam)
    total, dipakai = [0] * 52, []
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as ex:
        minggu = list(ex.map(lambda r: _mingguan(r["penuh"]), pilih))
    for r, w in zip(pilih, minggu):
        if not w:
            continue
        w = ([0] * (52 - len(w)) + w)[-52:]
        total = [a + b for a, b in zip(total, w)]
        dipakai.append({"repo": r["penuh"], "commit_4_minggu": sum(w[-MINGGU_BARU:]),
                        "terakhir_push": r["push"][:10]})
    if not dipakai:
        return None
    baru = sum(total[-MINGGU_BARU:]) / MINGGU_BARU
    lama = sum(total[-(MINGGU_BARU + MINGGU_LAMA):-MINGGU_BARU]) / MINGGU_LAMA
    tren = None
    if lama > 0:
        r = baru / lama
        tren = "melemah" if r < 0.7 else ("menguat" if r > 1.3 else "stabil")
    elif baru > 0:
        tren = "menguat"
    return {"commit_per_minggu_4_minggu": round(baru, 1),
            "commit_per_minggu_12_minggu_sebelumnya": round(lama, 1),
            "tren": tren,
            "n_repo_dilihat": len(kolam),
            # Dari `pilih`, yang SUDAH terurut — bukan dari `kolam`, yang tidak pernah
            # diurutkan (pilih_repo mengembalikan salinan). Versi sebelumnya melaporkan
            # tanggal repo pertama yang kebetulan dikembalikan organisasi pertama: 2026-05-07
            # dilaporkan sebagai "push terbaru" padahal repo teratasnya di-push 2026-09-16.
            "push_terbaru_di_ekosistem": pilih[0]["push"][:10],
            "repo_dipantau": sorted(dipakai, key=lambda x: -x["commit_4_minggu"])}


# --- Rakitan ----------------------------------------------------------------------------------
def _coingecko(simbol):
    if BASE_DIR not in sys.path:
        sys.path.insert(0, BASE_DIR)
    try:
        import indicators as ind
        cg_id = ind.resolve_cg_id(simbol.upper())
    except Exception:
        cg_id = None
    if not cg_id:
        return None
    teks = _curl(f"https://api.coingecko.com/api/v3/coins/{cg_id}?localization=false"
                 "&tickers=false&community_data=false&developer_data=false&sparkline=false")
    try:
        d = json.loads(teks or "{}")
    except json.JSONDecodeError:
        return None
    repo = ((d.get("links") or {}).get("repos_url") or {}).get("github") or []
    return {"nama": d.get("name"), "repo_coingecko": repo[:3]}


def analisa(simbol=None, nama_ekosistem=None, repo_coingecko=None, nama=None):
    """Aktivitas developer satu koin. `nama`/`repo_coingecko` boleh diisi pemanggil supaya
    CoinGecko tidak ditembak dua kali (naratif.py sudah punya keduanya)."""
    hasil = {"koin": (simbol or "").upper() or None, "hasil_uji": HASIL_UJI}
    if nama is None and simbol:
        cg = _coingecko(simbol) or {}
        nama, repo_coingecko = cg.get("nama"), cg.get("repo_coingecko")
    hasil["nama"] = nama
    hasil["repo_coingecko"] = repo_coingecko or []

    repos, catatan, n_repo = taksonomi(nama_ekosistem or nama or simbol)
    hasil["ekosistem_electric_capital"] = {
        "nama_dicari": nama_ekosistem or nama or (simbol or "").upper(),
        "ditemukan": bool(repos), "n_repo": n_repo, "catatan": catatan}
    orgs = organisasi(nama_ekosistem or nama or simbol, repos)
    sumber = "taksonomi Electric Capital"
    # Pemilik repo tunjukan CoinGecko selalu ikut dipantau, bukan cuma saat taksonomi kosong:
    # ia sering repo bendera proyeknya, dan kadang tidak ada di daftar organisasi terbanyak.
    for o in _hitung_org(repo_coingecko or []):
        if o not in orgs:
            orgs.append(o)
            if not repos:
                sumber = ("pemilik repo tunjukan CoinGecko (ekosistem tidak ada di taksonomi) "
                          "— satu sumber saja, bisa menunjuk repo yang sudah ditinggalkan")
    hasil["organisasi_dipantau"] = orgs
    hasil["sumber_daftar_repo"] = sumber if orgs else None
    hasil["github"] = aktivitas(orgs) if orgs else None
    if _STATUS["batas_kena"]:
        hasil["github_gagal"] = ("batas GitHub habis (60 permintaan/jam tanpa kunci). Di "
                                 "GitHub Actions setel GITHUB_TOKEN supaya jadi 5.000/jam.")
        hasil["github"] = None          # separuh repo terbaca bukan angka, itu angka bohong
    elif orgs and hasil["github"] is None:
        hasil["github_gagal"] = "GitHub tidak menjawab statistik (mungkin masih dihitung)"
    return hasil


def main():
    ap = argparse.ArgumentParser(description="Aktivitas developer dari GitHub + Electric Capital")
    ap.add_argument("simbol", nargs="?")
    ap.add_argument("--ekosistem", help="nama ekosistem Electric Capital kalau beda dari nama koin")
    ap.add_argument("--nama", help="nama koin (menghemat satu panggilan CoinGecko)")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    if not args.simbol and not args.ekosistem:
        ap.error("beri simbol koin atau --ekosistem")
    h = analisa(args.simbol, args.ekosistem, nama=args.nama)
    print(json.dumps(h, indent=None if args.json else 2, ensure_ascii=False))
    return 0 if h.get("github") else 1


if __name__ == "__main__":
    sys.exit(main())
