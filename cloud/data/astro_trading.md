# Astro-trading pada BTC — dua repo user & dokumen risetnya, diuji

Permintaan user 24 Sep 2026: memakai ilmu **jesse-astrology-trading-strategy** dan
**pyAstroTrader** di setiap analisa, ditambah dokumen riset "A-Z Guide to Astro Time
Trading for AI" dan gambar-gambar Astronacci. Sebelum dipakai, keduanya DIUJI — prinsip 3
README: temuan wajib lolos uji ketahanan. Skrip: `cloud/uji_astro.py`. Posisi planet dari
`cloud/astro.py` (elemen orbit JPL + Meeus, divalidasi ke peristiwa langit nyata).
Data: BTC harian Bitstamp di repo, 2 Jan 2012 – 1 Sep 2026.

## Lisensi — kenapa kodenya tidak disalin

| Repo | Lisensi | Yang dipakai |
|---|---|---|
| jesse-astrology-trading-strategy | **AGPL-3.0** | metode & data sinyalnya, diunduh saat uji — tidak disimpan di repo ini |
| pyAstroTrader | **tidak ada** (semua hak dipegang pembuat) | metodenya saja, diimplementasi ulang |
| pyswisseph (dipakai pyAstroTrader) | AGPL / komersial | tidak dipakai — diganti elemen orbit publik JPL |

## Uji 1 — sinyal jesse-astrology BTC

File `ml-BTC-USD-daily-index.csv` memuat sinyal buy/sell harian 2010–2022, tapi **terakhir
diterbitkan 6 Sep 2021** (git log). 7 Sep 2021 – 31 Des 2022 = **481 hari ramalan
sungguhan**. README repo mengklaim akurasi rata-rata 60%.

| | Target mereka (arah harga tengah OHLC/4) | Arah close | Long hanya hari "buy" |
|---|---|---|---|
| In-sample 2014 – 6 Sep 2021 | **74,2%** (baseline 53,9%) | 69,2% | **+1,9 triliun %** vs beli-tahan +7.101% |
| **Luar sampel, 481 hari** | **47,6%** (baseline 54,5%, p=0,29) | 53,4% (baseline 53,2%) | −36,4% vs beli-tahan −68,6% |

Backtest in-sample +1,9 triliun % adalah tanda pasti model menghafal hari-hari yang
dipakai melatihnya. Di luar sampel akurasinya di bawah lempar koin.

"−36,4% mengalahkan −68,6%" tampak bagus tapi menyesatkan: strategi itu hanya di pasar
293 dari 481 hari selama tahun crash. **Plasebo** — 293 hari dipilih acak, 5.000 kali:
median −49,8%, dan **25% pilihan acak menyamai atau mengalahkan sinyalnya (p = 0,25)**.

## Uji 2 — metode pyAstroTrader, diulang dengan dan tanpa kebocoran

pyAstroTrader melatih model pada posisi planet harian untuk meramal arah 5 hari. Cara ia
menilai modelnya bocor tiga lapis (`notebooks/helpers.py`, `get_best_booster`):

1. `train_test_split(..., shuffle=True)` pada deret waktu — hari uji bertetangga dengan
   hari latih, dan posisi planet nyaris identik antar hari berurutan;
2. skor dihitung pada `total_test` = **seluruh data, termasuk data latih**;
3. diulang hingga `MAX_INTERACTIONS` kali, yang disimpan skor terbaik.

Diulang di sini: fitur sin/cos bujur 9 benda langit (dokumen riset Bagian C.1), k-NN
(k=15), arah 5 hari, 5.352 hari, porsi latih 70% (= test_size 0,3 aslinya).

| Cara memecah data | Akurasi |
|---|---|
| **Acak, seperti pyAstroTrader** | **65,4%** — terlihat hebat |
| **Kronologis** (latih s.d. Apr 2022, nilai Apr 2022 – Agu 2026) | **51,7%** vs baseline 51,4% |

Model dan fitur yang sama persis. **Seluruh "kemampuan" itu kebocoran data.**

## Uji 3 — 123 aspek & retrograde vs volatilitas dan arah

Fitur: aspek mayor (0/60/90/120/180°, orb 6°) antar Matahari, Merkurius, Venus, Mars,
Jupiter, Saturnus, Uranus, Neptunus, plus retrograde Merkurius/Venus/Mars — yang aktif
≥ 60 hari. Target: **volatilitas** harian (saran dokumen riset Bagian C.3: "siklus waktu
tidak menentukan arah") dan arah 5 hari. Plasebo geser-melingkar (≥ 90 hari, 400 kali):
mempertahankan lamanya aspek dan pengelompokan volatilitas, hanya memutus kaitan dengan
tanggal sebenarnya. Koreksi FDR Benjamini–Hochberg, q = 0,10.

| Target | Diuji | p < 0,05 | Diharapkan karena kebetulan | Lolos FDR |
|---|---|---|---|---|
| Volatilitas | 123 | 5 | 6,2 | **0** |
| Arah 5 hari | 123 | 5 | 6,2 | **0** |

**Merkurius retrograde** (1.028 hari aktif): volatilitas sedikit LEBIH RENDAH (−0,08 poin
persen), p = 0,73; arah 5 hari p = 0,68. Tidak ada efek.

Fitur dengan p terkecil (Uranus sextile Neptunus, volatilitas −1,06 poin, p = 0,0025)
aktif 1.117 hari berturut-turut di era awal — aspek planet lambat bertahan bertahun-tahun
dan praktis menjadi penanda REZIM, bukan peristiwa. Dan ia tidak lolos FDR.

Konsisten dengan uji fase bulan sebelumnya (`moon_phase_btc.md`): null.

## Aturan untuk agent

- Kalender astro (stasiun retrograde, aspek eksak, bulan baru/purnama, Out of Bounds)
  **boleh dan selalu** disajikan di bagian WAKTU — sebagai "tanggal yang diperhatikan
  trader astro", karena banyak pelaku pasar memang memperhatikannya.
- **Dilarang** menyebutnya titik balik, sinyal, atau alasan beli/jual. Pada BTC tidak
  satu pun yang lolos uji; kalau ditanya, sebut angka di atas.
- **Dilarang** mengutip akurasi 60% (jesse) atau skor model pyAstroTrader — keduanya
  runtuh begitu diuji di luar sampel.
- "Vibrational date" dan siklus proprietary lain (mis. Astronacci) tidak bisa diuji tanpa
  aturannya; yang bisa dilakukan adalah MENCATAT panggilannya dan menilainya kemudian —
  lihat `cloud/data/panggilan_eksternal.jsonl`.
