"""Apakah kode chain yang dikirim cariwallet.py benar-benar diterima GMGN?

Sampai 23 Sep 2026 CHAIN_CARI mengirim "solana" apa adanya, padahal GMGN memakai "sol".
Dan GMGN TIDAK menolaknya: ia menjawab 200 dengan 0 kandidat (run 35813445159 — "sol"
76 kandidat, "solana" 0). Kode chain yang salah karena itu tidak meninggalkan jejak apa
pun: hasilnya cuma kosong, seperti pencarian yang memang tidak menemukan apa-apa. Skrip
ini yang menjadikannya terlihat — jumlah kandidat 0 diperlakukan sebagai kecurigaan,
bukan sebagai jawaban.

CATATAN KEAMANAN: repo ini publik. Yang dicetak hanya nama chain dan JUMLAH kandidat —
tidak pernah alamat, tidak pernah isi kunci.
"""

import os
import sys
import time

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
        print(f"  {chain:9} (kode {kode:9}) -> diterima, {n} kandidat"
              + ("   <- NOL: kode chain-nya patut dicurigai" if n == 0 else ""))
        if n == 0:
            gagal.append(chain)

# Pembanding: nama chain kita sendiri, yang dulu dikirim mentah-mentah.
d = gmgn.try_json(gmgn._url(f"{gmgn.BASIS}/market/search", {"chain": "solana", "q": KUERI}))
if isinstance(d, dict) and "__err" in d:
    print(f"  pembanding \"solana\" (kode lama)      -> DITOLAK: {str(d['__err'])[:90]}")
else:
    n = len(((d or {}).get("data") or {}).get("coins") or [])
    print(f"  pembanding \"solana\" (kode lama)      -> diterima, {n} kandidat")

print(f"chain tanpa satu pun kandidat: {gagal or 'tidak ada'}")

# ---- atas dasar apa kandidat token boleh diurutkan? --------------------------------------
# Jatah penyisiran jauh lebih kecil daripada jumlah token senama, jadi yang menentukan
# berhasil-tidaknya bukan jumlahnya melainkan URUTANNYA. Bagian ini mencetak medan apa saja
# yang dikembalikan GMGN supaya urutannya bisa didasarkan pada bukti, bukan tebakan.
# Nama token itu publik; alamat TIDAK dicetak.
print("---- medan kandidat dari market/search ----")
time.sleep(2)
d = gmgn.try_json(gmgn._url(f"{gmgn.BASIS}/market/search",
                            {"chain": "robinhood", "q": KUERI}))
if isinstance(d, dict) and "__err" in d:
    print(f"  GAGAL: {str(d['__err'])[:120]}")
else:
    coins = ((d or {}).get("data") or {}).get("coins") or []
    print(f"  {len(coins)} kandidat; medan: {sorted(coins[0].keys()) if coins else '-'}")
    for c in coins[:3]:
        aman = {k: v for k, v in c.items()
                if k not in ("address", "token_address", "pool_address", "creator")
                and not isinstance(v, (dict, list))}
        print(f"  contoh: {aman}")

# Apakah URUTAN kandidat stabil? Run 35813558660 menemukan dompetnya di 5 kandidat
# pertama, run 35813736311 tidak — kode yang sama, kueri yang sama.
print("---- urutan kandidat stabil atau tidak? ----")
urutan = []
for _ in range(2):
    time.sleep(2)
    d = gmgn.try_json(gmgn._url(f"{gmgn.BASIS}/market/search",
                                {"chain": "robinhood", "q": KUERI}))
    coins = ((d or {}).get("data") or {}).get("coins") or [] if isinstance(d, dict) else []
    urutan.append([(c.get("symbol") or c.get("name") or "?")[:14] for c in coins[:6]])
    print(f"  6 teratas: {urutan[-1]}")
print(f"  sama persis: {len(urutan) == 2 and urutan[0] == urutan[1]}")


# Uji jalan penuh: chain yang disebut user harus benar-benar mempersempit. Yang dicetak
# tetap tanpa alamat — cuma jumlah dan jenis kecocokannya.
hasil, catatan = cw.cari_di_token("0xda...09d9", "LEVERA robinhood", maks_token=5)
print(f"  cari di token: {len(hasil)} hasil, kelas={[h['kecocokan'] for h in hasil]}, "
      f"sumber={[h['sumber'] for h in hasil]}")
print(f"  catatan: {catatan}")

