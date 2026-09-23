"""Apakah kode chain yang dikirim cariwallet.py benar-benar diterima GMGN?

Sampai 23 Sep 2026 CHAIN_CARI mengirim "solana" apa adanya, padahal GMGN memakai "sol".
Chain yang ditolak TIDAK menimbulkan galat di jalur pencarian — hasilnya cuma kosong, jadi
sapuan Solana bisa mati berbulan-bulan tanpa satu pun tanda. Skrip ini yang menjadikannya
terlihat.

CATATAN KEAMANAN: repo ini publik. Yang dicetak hanya nama chain dan JUMLAH kandidat —
tidak pernah alamat, tidak pernah isi kunci.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cariwallet as cw  # noqa: E402
import gmgn  # noqa: E402

KUERI = "levera"
gagal = []

for chain in cw.CHAIN_CARI:
    kode = cw.KODE_GMGN.get(chain, chain)
    d = gmgn.try_json(gmgn._url(f"{gmgn.BASIS}/market/search", {"chain": kode, "q": KUERI}))
    if isinstance(d, dict) and "__err" in d:
        print(f"  {chain:9} (kode {kode:9}) -> DITOLAK: {str(d['__err'])[:90]}")
        gagal.append(chain)
    else:
        n = len(((d or {}).get("data") or {}).get("coins") or [])
        print(f"  {chain:9} (kode {kode:9}) -> diterima, {n} kandidat")

# Pembanding: nama chain kita sendiri, yang dulu dikirim mentah-mentah.
d = gmgn.try_json(gmgn._url(f"{gmgn.BASIS}/market/search", {"chain": "solana", "q": KUERI}))
if isinstance(d, dict) and "__err" in d:
    print(f"  pembanding \"solana\" (kode lama)      -> DITOLAK: {str(d['__err'])[:90]}")
else:
    n = len(((d or {}).get("data") or {}).get("coins") or [])
    print(f"  pembanding \"solana\" (kode lama)      -> diterima, {n} kandidat")

print(f"chain yang ditolak: {gagal or 'tidak ada'}")
