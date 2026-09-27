# Screening narasi cara mentor #2 — dikerjakan kode, lalu diuji

Transkrip webinar mentor yang dikirim user 27 Sep 2026. Kode: `cloud/rotasi.py` (screening
live, disiapkan di awal mode narasi) dan `cloud/uji_rotasi.py` (uji "konsep elevator").

## Metodenya

**Narasi kategori.** CoinGecko → Categories yang menguat; bedakan narasi besar dan kecil.
Koin yang naik (NEAR) → kategorinya (AI) → pemimpin sudah naik → likuiditas diduga turun ke
koin berikutnya yang belum naik ("konsep elevator").

**Narasi chain.** Big cap mana yang unggul 7 hari; kalau layer 1, lihat EKOSISTEM-nya (bukan
kategori Layer 1); ambil hanya koin yang benar-benar dibangun di chain itu.

## Yang dibuat kode

| | Aturan (ditetapkan sekali) |
|---|---|
| Tingkat narasi | BESAR ≥ $5 M · SEDANG $1–5 M · KECIL < $1 M (mcap kategori) |
| Pemimpin | 3 market cap teratas; "sudah bergerak" bila terbaik ≥ +10% 7 hari |
| Kandidat | anggota likuid dengan 7 hari di [−10%, min(+10%, setengah pemimpin)) |
| Melemah | anggota yang turun > 10% saat narasinya naik — bukan kandidat |
| Big cap unggul | ≥ +10% 7 hari (penilaian mentor: ETH +5% & BNB +4% "biasa aja", SOL +14% "bagus") |
| Koin asli chain | platform UTAMA CoinGecko = chain itu; tanpa stablecoin (juga harga ~$1 diam) dan tanpa bridge big cap lain (BTC/ETH/NBTC yang dicetak di NEAR) |

Platform utama = platform pertama di `/coins/list?include_platform=true` — satu panggilan
untuk 21 rb koin. Diperiksa terhadap `asset_platform_id` pada 9 token, 9 cocok. Hasilnya
persis keputusan mentor: RENDER → ethereum, CAKE → binance-smart-chain, STRK → ethereum
(tercoret dari Solana); JUP, RAY, PENGU, BONK → solana (lolos).

## Reproduksi live (run 36321348811, 27 Sep 2026)

| | Mentor | Kode |
|---|---|---|
| ETH / BNB 7 hari | 5% / 4% "biasa aja" | +5,1% / +3,8% |
| XRP / SOL / LINK | 11% / 14% / 19% | +11,4% / +13,9% / +17,9% |
| NEAR memimpin | "Nil protokol lagi naik" | +43,4%, memimpin Data Availability |
| GRASS | "hari ini udah mulai naik" | +75,9% |

## Uji "konsep elevator" (run 36321622251)

Harga harian CoinGecko 365 hari; AI, meme, RWA, DeFi, layer 2, gaming, dan ekosistem Solana
(asli); 15 koin per kelompok. Tiap minggu pemimpin naik ≥ +10% = peristiwa; ukuran utama =
return 7 hari SESUDAHNYA rata-rata kandidat dikurangi rata-rata seluruh anggota di minggu
yang sama. Bootstrap 5.000 kali.

| Kelompok | Minggu | Kandidat − rekan, 7 hari | p |
|---|---|---|---|
| AI | 17 | +2,26 | 0,16 |
| Meme | 16 | +1,59 | 0,19 |
| DeFi | 14 | +1,12 (unggul hanya 5/14 minggu) | 0,56 |
| Gaming | 14 | +0,92 | 0,38 |
| RWA | 12 | +0,05 | 0,87 |
| Solana (asli) | 20 | −0,03 | 0,97 |
| Layer 2 | 15 | −1,94 | 0,28 |
| **Gabungan** | **108** | **+0,59** (unggul 57% minggu) | **0,26** |
| Gabungan, 14 hari | 108 | −0,22 | 0,83 |

**Tidak terbukti.** Ada condongan positif kecil di 7 hari, paling terlihat di AI dan meme,
tapi tidak signifikan dan hilang di 14 hari; di ekosistem Solana — contoh utama mentor —
nol. Batas yang diakui: keanggotaan & peringkat diambil hari ini (survivorship), satu tahun
data, dan saringan likuiditas tidak ikut diuji (volume historis tidak tersedia).

## Aturan untuk agent

- Pakai screening sebagai PETA: narasi mana yang bergerak, besar/kecilnya, pemimpinnya, dan
  koin asli ekosistem chain yang unggul.
- Kandidat = daftar pantau. **Dilarang** menyebutnya "akan naik berikutnya" — sebut bahwa
  pola susul-menyusul tidak terbukti di data setahun terakhir.
- Token yang dicoret saringan (RENDER, CAKE, STRK untuk Solana) jangan ditambahkan kembali.
- Finalis tetap wajib dicek penggerak nyata & teknikal — mentor sendiri: "tetap harus
  di-charting lagi sendiri".
