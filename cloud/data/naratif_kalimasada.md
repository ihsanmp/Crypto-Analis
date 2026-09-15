# Narrative Trading #Kalimasada — kerangka dari video "Bongkar Naratif Trading di Crypto 2026"

Sumber: video YouTube Kalimasada (id `oDAo2EMCiEc`, 35 menit), dipelajari 16 Sep 2026 dari
transkrip DAN slide-nya. Slide dibaca langsung dari bingkai video karena beberapa hal
penting tidak terucap atau terucap berbeda — lihat bagian "Slide vs ucapan".

**Status: kerangka KEPUTUSAN, bukan edge yang teruji.** Tidak seperti setup deviation
(`gaya_kalimasada.md`), kerangka ini tidak bisa di-backtest dengan data gratis: skor katalis,
TAM, dan kualitas tim butuh penilaian historis yang tidak tersimpan di mana pun. Gunanya
membuat keputusan KONSISTEN — "bukan berdasarkan mood atau timeline X", kata slidenya sendiri.

---

## 1. Kenapa naratif

Altcoin terlalu banyak (launchpad seperti Pump.fun membuat ratusan ribu pair lahir tiap hari)
untuk menebar uang ke semuanya. Modal dikonsentrasikan ke SEKTOR yang sedang diincar banyak
orang. Definisi CoinGecko yang dikutip: tema/tren/keyakinan **dominan** yang membentuk cara
investor menilai aset digital — kata kuncinya *dominan*.

Tiga pendekatan yang disebut: **value investing** (nilai intrinsik — samar dan mudah
dipalsukan di crypto: user aktif bisa bot atau pemburu airdrop), **fundamental** (revenue,
TVL, user), dan **momentum** (volume naik, sedang ramai).

Naratif menurut Robert Shiller menular seperti penyakit. Cerita dibangun smart money supaya
ritel ikut membeli (contoh: ETF & Trump untuk BTC, "AI menggantikan manusia" untuk token AI).

## 2. Siklus hidup naratif (slide)

| fase | ciri |
|---|---|
| 1 Emergence | developer & VC masuk, belum ada perhatian ritel |
| 2 Validation | metrik on-chain naik, media niche mulai membahas |
| 3 Mainstream | listing tier-1, influencer, harga parabolik |
| 4 Exhaustion | funding rate ekstrem, open interest memuncak |
| 5 Decay | volume kering, mindshare turun, drawdown dalam |

"Yang exit ke dalam hype untung. Yang masuk terlambat menjadi exit liquidity."

**Pelajaran dua studi kasus (DeFi Summer 2020, AI agent):** durasi hype naratif mikro
**1-3 bulan** (infrastruktur besar bisa bertahun-tahun) · upside **40-100x** untuk leader
sektor yang masuk di fase awal · drawdown **80-95%** normal saat decay. Take profit adalah
kuncinya; unrealized profit bukan profit.

## 3. Peta naratif 2026 (slide, snapshot saat rekaman)

| EARLY — masih dini | MID — sedang berjalan | DECAY — sudah lewat |
|---|---|---|
| Stablecoin & stablechains | RWA / tokenized treasuries | Digital Asset Treasury (DAT) |
| Tokenized equities | Perp DEX | Memecoin |
| AI x Crypto & agentic | Prediction markets | Layer 2 generik |
| Collectible cards | AI x DePIN | GameFi & NFT |
| | ETF altcoin | |
| | Privacy / ZK | |

Tema besar 2026 menurut slide: **flight to quality** — rotasi ke protokol dengan revenue
nyata dan adopsi institusional. Catatan per sektor dari ucapannya:
- **Stablecoin**: paling matang 2026-2027; katalis GENIUS Act (sudah aktif), kepatuhan
  regulasi, pembayaran lintas negara.
- **RWA / tokenized equity**: katalis Robinhood Chain. Periksa backing-nya — ada yang 1:1
  dengan aset riil, ada yang sintetis. Tokenized equity ia sebut *bearish untuk altcoin*:
  makin banyak opsi on-chain, makin berat persaingan altcoin.
- **AI agent**: Coinbase mendorong agen ber-wallet; "tidak ada yang too good to be true".
- **DePIN**: Bittensor pemimpinnya, tapi adopsi terhambat biaya komputasi dan lokasi.
- **Perp DEX**: Hyperliquid menang di produk, komunitas, dan tokenomics (vs dYdX, GMX).
  Menurutnya sudah agak ketinggian.
- **ETF altcoin**: SOL & XRP ETF sejak Nov 2025 menambah flow, tapi fitur aset asli hilang.
- **DAT**: bearish — dari ratusan, hanya ~9-10 yang profitable; model bisnis menaikkan
  valuasi lalu founder exit.

**Snapshot pasar di video** (tanggal rekaman tidak disebut): total market cap $2,785T,
dominasi BTC ~57,5%, ETH ~10,9%, altcoin season index 35-49 (di bawah ambang 75 = masih
Bitcoin season). Pada 16 Sep 2026 CoinGecko mencatat $2,620T, BTC 58,4%, ETH 11,2%.
**Tarik angka terkini — jangan kutip snapshot ini sebagai kondisi sekarang.**

## 4. Di mana mencari sinyal awal (slide)

| sinyal | tool yang disebut di video | status gratis (diuji 16 Sep 2026) |
|---|---|---|
| 1 Developer activity | Electric Capital Developer Report ("sinyal paling hulu") | **Santiment `dev_activity`: gratis, data terkini** · Electric Capital: web & repo taksonomi GitHub gratis · GitHub API gratis |
| 2 Funding VC | CryptoRank, Galaxy Research ("mendahului ritel 6-12 bulan"); ChainBroker disebut lisan | CryptoRank & ChainBroker: **web gratis, API berkunci** · Galaxy: laporan web |
| 3 Mindshare | Kaito AI, Cookie.fun, LunarCrush, Santiment | **Tidak ada yang gratis untuk data terkini.** Kaito/LunarCrush berbayar; social volume Santiment gratis tapi rentang terbarunya ditolak. Pengganti: CoinGecko trending, Wikipedia pageviews, grup Telegram user |
| 4 Data on-chain | DefiLlama, Token Terminal, Dune, Nansen, rwa.xyz | **DefiLlama fees/revenue/TVL gratis** · Token Terminal & Nansen berbayar · Dune butuh kunci (akun gratis) · rwa.xyz web |
| 5 Katalis regulasi | GENIUS Act, CLARITY Act, persetujuan ETF, kebijakan Fed | Google News RSS gratis · kalender makro bot |
| 6 Airdrop & testnet | farming, Kaito Yaps | web |

Unlock (langkah 4): video memakai **Tokenomist** dan CoinMarketCap. **Tidak ada API unlock
yang gratis** — DefiLlama unlocks membalas 402, Tokenomist & CryptoRank berkunci. Periksa di
web (tokenomist.ai, defillama.com/unlocks). Yang gratis lewat API hanya **float** (beredar vs
maksimum, mcap vs FDV) dari CoinGecko — itu yang dipakai `naratif.py`.

## 5. Metodologi screening → eksekusi (slide)

### Langkah 1 — Framework scoring naratif

| kriteria | bobot | pertanyaan kunci |
|---|---|---|
| Kekuatan katalis | 20% | Ada event atau deadline konkret di 2026? |
| Tokenomics (float/FDV) | 20% | Float sehat? Jadwal unlock terkendali? |
| Ukuran pasar (TAM) | 15% | Seberapa besar sektor ini bisa tumbuh? |
| Kualitas tim & VC | 15% | Didukung fund tier-1 yang kredibel? |
| Likuiditas | 10% | Cukup dalam untuk masuk dan keluar? |
| Timing siklus | 10% | Masih early atau sudah mainstream? |
| Revenue & user nyata | 10% | Ada substansi, atau hanya hype? |

Beri skor 1-5 per kriteria, lalu hitung skor tertimbang.

### Langkah 2 — Membaca hasil

| skor | keputusan |
|---|---|
| **> 3,5 — layak dikejar** | alokasikan sesuai aturan sizing, masuk bertahap di leader sektor |
| **2,5-3,5 — watchlist** | pantau mingguan, tunggu katalis atau konfirmasi on-chain |
| **< 2,5 — hindari** | lewati; tidak ada kewajiban ikut setiap naratif yang ramai |

### Langkah 3 — Memilih token di dalam naratif

| tingkat | porsi | alasan |
|---|---|---|
| Leader sektor | **mayoritas** | beta lebih rendah, likuiditas dalam, revenue terbukti |
| Mid-cap | porsi kecil | upside lebih besar, risiko lebih tinggi |
| Long-tail | sangat kecil | token baru high-FDV & memecoin sektor; exit ketat, "97% memecoin akhirnya mati" |

### Langkah 4 — Cek unlock sebelum entry

**Unlock > 5% supply beredar = potensi tekanan jual signifikan.** Prioritaskan proyek dengan
buyback dari fee di atas proyek dengan emisi tinggi.

### Langkah 5 — Sinyal fase distribusi

Funding rate ekstrem · open interest puncak · listing tier-1 · liputan mainstream · saturasi
influencer · Google Trends puncak. **"Semakin banyak yang menyala bersamaan, semakin dekat
puncaknya. Exit during hype, not after."**

### Langkah 6 — Rutinitas mingguan (lisan)

Pantau mindshare, funding, dan unlock tiap minggu. Portofolio **5-10 token saja** — lebih dari
itu jadi "supermarket sampah" yang tidak bisa dipantau.

## 6. Manajemen risiko

### Slide vs ucapan — dan ucapannya yang berlaku

| | slide | ucapan mentor |
|---|---|---|
| Core | 60-80% **BTC dan ETH** | ETH **dicoret** — fokus BTC 60-80% |
| Naratif | 10-40% | **maksimal 15%** |
| Buffer stablecoin | 10-15% | **setidaknya 30%** cash/stablecoin |

Tiga profil risiko (slide): **konservatif** 80% BTC · 15% ETH · 5% alts naratif ·
**moderat** 70% BTC · 20% ETH · 10% alts · **agresif** 60% BTC · 25% ETH · 15% alts.
"60% BTC aja udah agresif." Tidak ada satu altcoin melebihi 5%. Jangan alokasikan ke
narrative trading sebelum core stabil.

**Position sizing (slide):** risk per trade **1-2% dari modal crypto**; posisi naratif
high-risk dibatasi 1-2% total holding; pakai **half-Kelly** karena estimasi edge di crypto
sangat tidak pasti. Secara lisan ia menekankan **RPT 1%**. Satu posisi yang jatuh ke nol harus
jadi kemunduran yang bisa dikelola, bukan peristiwa yang menghancurkan portofolio.

**Moonbag (lisan):** begitu naik 100%, jual 50% — modal kembali, sisanya dibiarkan jalan.

**Tanpa leverage, tanpa uang orang lain, tanpa all-in.** BTC & ETH bisa drop 50%+, altcoin 99%.

### Jenis risiko (slide)

- **Di luar kendali (struktural):** likuiditas tipis & slippage, exit liquidity, low float /
  high FDV, unlock cliff, risiko exchange, smart contract, oracle.
- **Di dalam kendali (psikologis):** jatuh cinta pada naratif, sunk cost fallacy, revenge
  trading setelah rugi, over-concentration di satu tema.

### Lima aturan invalidasi (slide) — "Don't marry a narrative."

1. **Katalis gagal** — thesis tidak terwujud, atau ditunda tanpa batas waktu jelas.
2. **Mindshare turun** — penurunan konsisten beberapa minggu berturut-turut.
3. **Developer pergi** — on-chain & Electric Capital menunjukkan aktivitas melemah.
4. **Fase decay** — funding normal kembali, volume kering, volume DEX anjlok.
5. **Break support** — struktur harga rusak di level kunci; keluar tanpa menawar.

## 7. Klaim video yang sudah diperiksa (16 Sep 2026)

| klaim | hasil | sumber |
|---|---|---|
| Virtuals turun 88% dari puncak | **cocok** — 88,1% dari ATH $5,07 | CoinGecko |
| AI16Z turun 99,9% | **cocok** — ~100% dari ATH $2,47 | CoinGecko |
| BTC puncak ~$126.000 Okt 2025 | **cocok** — $126.100 pada 6 Okt 2025 | CoinGecko |
| Revenue Hyperliquid ~$1 miliar | **tidak cocok** dengan revenue 1 tahun DefiLlama **$0,70 miliar** — mungkin kumulatif atau metrik lain | DefiLlama |
| $155 miliar unlock altcoin 2024-2030 | belum diperiksa — tidak ada API unlock gratis | — |
| 1 dari 5 altcoin low float / high FDV | belum diperiksa | — |
| 97% memecoin akhirnya mati | belum diperiksa | — |
| Hanya ~9-10 DAT yang profitable | belum diperiksa | — |

Klaim yang belum diperiksa **tidak boleh dikutip sebagai fakta** — sebut sebagai "menurut video".

## 8. Yang sudah dikerjakan bot

`python cloud/naratif.py KOIN` mengisi kriteria yang terukur kode dari sumber gratis:
**tokenomics** (float CoinGecko), **likuiditas** (volume vs kapitalisasi), **revenue**
(DefiLlama 1 tahun), plus data untuk menilai timing (jarak dari ATH, perubahan 30 hari & 1
tahun, CoinGecko trending, Wikipedia pageviews), tren developer Santiment, jumlah berita 7 hari,
dan tingkat kapitalisasi (leader/mid-cap/long-tail).

**Ambang 1-5 untuk ketiga kriteria itu milik alat ini, bukan dari video** — mentornya hanya
memberi pertanyaan kunci. Katalis, TAM, tim & VC, dan timing tetap harus DINILAI, dengan dasar
yang disebut. Skor tertimbang di balasan diperiksa ulang kode.

⚠️ Materi acuan dari konten edukasi mentor, bukan nasihat keuangan.
