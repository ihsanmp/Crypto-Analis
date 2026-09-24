# Minor Swing Strategy (Astronacci) — diurai dari gambar, diuji pada BTC H1

Materi Astronacci yang dikirim user 24 Sep 2026 ("Minor Swing Strategy", "Cara Entry dan
Exit di Bitcoin", "Bitcoin Price Action Analysis"). Aturannya lengkap dan mekanis, jadi
bisa dideteksi kode (`cloud/swing.py`) dan diuji balik (`cloud/uji_swing.py`, workflow
`Uji minor swing`).

## Aturan

| Langkah | Dari gambar | Ditetapkan di sini (tidak disebut gambar) |
|---|---|---|
| Time frame | H1 | — |
| Arah tren | BELI bila harga > EMA 50 **dan** MACD > 0; JUAL kebalikannya | MACD 12/26/9 |
| Swing | swing high & low berdekatan, **maks 200 pips** | fraktal 3 candle per sisi, sah setelah 3 candle tertutup |
| Satuan pip | "1.155,61" ditulis "115 pips", "1.212,66" ditulis "121 pips" → **1 pip = $10** | — |
| Entry | buy stop di swing high (setelah swing low terbentuk di atas EMA 50) | setup sah hanya bila penembusan belum terjadi |
| SL / TP | SL di swing low, TP sejauh rentang swing → **RR 1:1** | candle yang menyentuh SL & TP = kalah |
| Invalid | harga di bawah EMA 50 dan MACD di bawah 0 | order kedaluwarsa 48 candle |

Contoh di gambar (BTC, 21–23 Sep 2026): buy stop 87.281, target 89.140, support 85.460 —
rentang 182 pips, TP 1:1 = 89.102. Teks gambar itu bertanggal "23 Sept 2025", padahal
sumbu chart-nya "21 Sep '26": salah ketik di sumbernya.

## Hasil — Bitstamp BTC/USD 1h, 24 Sep 2023 – 24 Sep 2026 (26.298 candle)

### Versi pertama BERBIAS — jangan dipakai

Run 35993312501: 451 transaksi, menang **60,3%**, **+0,099R** setelah biaya 0,1%. Terlihat
bagus — sampai status live menampilkan "SELL STOP $83.730" padahal harga sudah $83.504.
Penembusan terjadi selama 3 candle konfirmasi pivot, dan backtest mengisi order di level
yang sudah terlewati: hadiah ~0,26R per transaksi yang mustahil didapat. Separuh
transaksinya adalah setup semacam itu.

### Versi yang benar

Run 35993653964, sesudah dua bias dibuang (setup yang pemicunya sudah lewat ditolak;
isian lewat gap memakai harga pembukaan):

| Biaya pulang-pergi | Transaksi | Menang | Ekspektansi | Impas butuh |
|---|---|---|---|---|
| 0% | 234 | 47,4% | **−0,051R** | 50,0% |
| **0,1%** | 234 | 47,4% | **−0,143R** | 54,6% |
| 0,2% | 234 | 47,4% | **−0,234R** | 59,2% |

p menang vs 50% = 0,43 — tidak berbeda dari lempar koin.

| Arah (biaya 0,1%) | Menang | Ekspektansi |
|---|---|---|
| BELI | 52,0% | −0,053R (tanpa biaya +0,039R) |
| JUAL | 42,1% | −0,250R |

Per tahun (biaya 0,1%): 2023 (sebagian tahun) +0,197R · 2024 −0,276R · 2025 −0,120R ·
2026 −0,081R.

**Kesimpulan: pada BTC H1 tiga tahun terakhir, Minor Swing Strategy RUGI — bahkan
sebelum biaya.** Sisi BELI tanpa biaya sedikit positif, tapi tidak cukup menutup biaya
transaksi yang paling murah pun.

## Aturan untuk agent

- Status setup saat ini (`MINOR SWING STRATEGY BTC H1`) boleh ditampilkan sebagai
  informasi struktur H1 — levelnya dihitung kode.
- **Dilarang** menyajikannya sebagai strategi yang punya keunggulan, menyebut win rate
  selain 47,4%, atau mengutip angka versi berbias (60,3%).
- Setup JUAL = short: bot ini khusus spot, jadi bukan saran. Bagi pemegang spot artinya
  tren H1 sedang turun.
