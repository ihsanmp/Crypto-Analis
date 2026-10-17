# Acuan Analisa MINYAK WTI (CL=F) — Penggerak & Jebakan

Disusun 16 Okt 2026, setelah "analisa minyak" dirutekan ke CL=F. Dipakai bot saat
menganalisa minyak mentah. **STATUS BUKTI:** arah-arah di bawah adalah kecenderungan umum
pasar minyak, BELUM diuji dengan data repo ini. Yang sudah terukur untuk CL=F hanya
`kejutan.py` (reaksi terhadap CPI/NFP/FOMC) dan `backtest.py` (sinyal teknikal) — kalau
keduanya ada di brief, vonisnya MENGALAHKAN arah umum di sini.

---

## Apa itu CL=F

- Kontrak berjangka WTI (NYMEX) bulan terdekat, dalam USD per barel.
- BUKAN Brent (BZ=F, acuan global), BUKAN saham minyak (XOM, CVX), BUKAN ETF (USO).
  Kalau user minta "analisa minyak", yang dimaksud harga minyak mentahnya.
- Diperdagangkan hampir 24 jam Minggu malam–Jumat (CME Globex); tetap ada gap akhir pekan.

## Penggerak utama — PASOKAN & PERMINTAAN, bukan suku bunga

Berbeda dari emas, minyak adalah komoditas yang DIKONSUMSI. Penggeraknya keseimbangan
fisik pasokan-permintaan, dan jalur suku bunga hanya tidak langsung.

1. **OPEC+** — keputusan kuota produksi dan pemangkasan sukarela. Yang menggerakkan adalah
   keputusan yang MENYIMPANG dari ekspektasi pasar, bukan keputusannya sendiri. Sebut
   tanggal pertemuan berikutnya kalau ditemukan.
2. **Stok minyak AS — laporan mingguan:**
   - API (laporan industri, tidak resmi): Selasa 16.30 waktu New York.
   - **EIA Weekly Petroleum Status Report (resmi): Rabu 10.30 waktu New York** —
     21.30 WIB saat AS memakai jam musim panas, 22.30 WIB di luar itu. Bergeser bila
     ada libur AS.
   - Yang dibaca: perubahan stok minyak mentah DIBANDING PERKIRAAN, lalu stok bensin,
     distilat, dan stok Cushing (titik serah fisik WTI).
   - Kecenderungan umum (belum diuji di sini): penarikan stok lebih besar dari perkiraan
     → harga cenderung naik; penambahan stok lebih besar dari perkiraan → cenderung turun.
3. **Produksi AS & rig count Baker Hughes** (Jumat 13.00 waktu New York) — indikator
   lambat; trennya lebih bermakna daripada satu angka mingguan.
4. **Permintaan global** — pertumbuhan ekonomi (terutama China & AS), musim berkendara AS,
   dan laporan bulanan IEA, OPEC, serta EIA STEO.
5. **Geopolitik pasokan** — konflik di produsen besar atau jalur pengiriman (mis. Timur
   Tengah, Selat Hormuz, Rusia). Premi risikonya bisa naik cepat dan HILANG sama cepatnya
   bila pasokan nyata tidak terganggu. Penjelas, bukan penentu target.

## Makro AS — JANGAN memakai logika emas

- `makro.py` membawa field `arah_emas_bila_naik`. Itu HANYA untuk emas/perak dan
  **TIDAK berlaku untuk minyak.** Data ekonomi KUAT justru bisa MENAIKKAN minyak lewat
  permintaan — kebalikan dari emas.
- Dolar kuat cenderung menekan komoditas berdenominasi USD, tapi hubungannya longgar dan
  berubah-ubah. Jangan disajikan sebagai aturan.
- **CPI: arah sebabnya terbalik.** Energi adalah komponen CPI, jadi minyak yang naik
  menaikkan CPI headline — bukan sebaliknya. Jangan menulis "CPI tinggi menggerakkan minyak"
  kecuali `kejutan.py` menunjukkannya.

## Jebakan khusus kontrak berjangka

- **Roll bulanan.** CL=F berganti kontrak tiap bulan (perdagangan kontrak berakhir sekitar
  pekan ketiga bulan sebelum bulan serah). Candle di sekitar roll bisa MELOMPAT karena
  selisih harga antar-kontrak, bukan karena harga minyak bergerak. Lonjakan volume di
  hari roll juga bukan breakout.
- **Harga negatif 20 April 2020** (penutupan −37,63). Ada di riwayat 15 tahun. Persen
  perubahan dari harga di sekitar nol tidak bermakna; `kejutan.py` sudah membuangnya.
- **Volatilitas jauh lebih tinggi dari emas.** Pakai `metrik_risiko` di brief; jangan
  memasang invalidasi serapat untuk emas.

## Peringkat pemicu terjadwal untuk minyak

Keputusan OPEC+ > laporan stok EIA (mingguan) > FOMC/CPI/NFP (lewat permintaan & dolar)
> rig count. Sebut jadwal terdekat di bagian RISIKO.

## Skor & kartu (pengganti bagian forex/gold di analisa_pasar.md)

- Bobot skor: pasokan-permintaan (OPEC+, stok EIA, geopolitik) & makro 60% + teknikal 40%.
- Aturan "kedua kaki" & divergensi bank sentral hanya untuk pasangan mata uang — bukan minyak.
- Header kartu: `$CL=F — minyak WTI (CL=F)`.
- Ganti dua baris pertama blok makro forex/gold dengan:
  • Pasokan: <OPEC+ terakhir & berikutnya> · <stok EIA terakhir vs perkiraan, tanggal>
  • Permintaan & makro: <arah, dasarnya — BUKAN arah emas>
- RISIKO: sebut stok EIA Rabu & pertemuan OPEC+ terdekat.
