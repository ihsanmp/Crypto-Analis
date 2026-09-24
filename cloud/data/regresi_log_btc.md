# Regresi logaritmik BTC — chart BitcoinTalk 2014, dibaca lalu diuji

Dikirim user 24 Sep 2026 untuk "ditanamkan ke agent" (kode QR donasi di gambarnya
diabaikan sesuai permintaan). Yang ditanam: bacaan chart yang sudah dibuktikan, dan
UJIAN luar-sampelnya. Dihitung ulang tiap analisa BTC oleh `cloud/logregresi.py`;
dipaku oleh `tests/test_logregresi.py`.

## 1. Bacaan chart — dibuktikan, bukan ditafsirkan

Rumus di chart (apostrof = tanda desimal):

    log10(harga) = 2,9065 · ln(x) − 19,493        R² = 0,9886

dengan **x = hari sejak 9 Jan 2009** (rilis Bitcoin v0.1). Dengan blok genesis 3 Jan,
semua tonggak bergeser 6–9 hari — jadi 9 Jan yang dipakai chart.

| Yang tercetak di chart | Dihasilkan ulang rumus | Selisih |
|---|---|---|
| $1 — 6 Apr 2011 | 6 Apr 2011 | 0 hari |
| $10 — 7 Mar 2012 | 7 Mar 2012 | 0 |
| $100 — 24 Jun 2013 | 24 Jun 2013 | 0 |
| $1rb — 24 Apr 2015 | 23 Apr 2015 | 1 |
| $10rb — 22 Nov 2017 | 21 Nov 2017 | 1 |
| $100rb — 16 Jul 2021 | 13 Jul 2021 | 3 |

Deretan angka di atas chart (0,004 · 0,44 · 6,77 · 46,96 · … · 332.632) adalah nilai
garis di **akhir** tiap tahun; labelnya diletakkan di awal tahun. Dibaca sebagai nilai
awal tahun, semuanya meleset 36–99% — bacaan yang salah, bukan chart yang salah.

Jeda antar-10x: 336 · 474 · 669 · 943 · 1.332 hari, tumbuh dengan rasio tetap
**1,41 = e^(1/2,9065)**. Rasio itu bawaan bentuk rumusnya, bukan temuan terpisah.

**Persen di chart ini adalah KELIPATAN × 100, bukan kenaikan** — jebakan terbesar saat
membacanya. Dibuktikan pada kedua baris:

| Di chart | Kelipatan × 100 | Kenaikan sebenarnya |
|---|---|---|
| 159% (2022→2023, deret atas) | 159 | **+59%** |
| 202% (2017→2018) | 203 | +103% |
| 262% (baris hijau, 5,10 → 13,34) | 262 | **+162%** |
| 5.588% (13,34 → 745,45) | 5.588 | +5.488% |

Jadi "159%" berarti garisnya naik 1,59× setahun, BUKAN naik 159%. Satu-satunya
pengecualian adalah `[-46%]` dalam kurung: itu perubahan 2014 hingga tanggal chart
dibuat (14 Okt 2014), ditulis sebagai perubahan biasa.

Baris hijau di bawah chart (0,30 · 5,10 · 13,34 · 745,45) adalah harga aktual akhir
tahun 2010–2013.

## 2. Ujian luar-sampel — 12 tahun yang tidak pernah dilihat chart ini

Data: Bitstamp harian di repo (1 Jan 2012 – 1 Sep 2026, 5.358 hari).

- Harga di atas garis 2014 hanya **53 dari 4.340 hari (1,2%)** sesudah chart dibuat —
  dan **ke-53 hari itu semuanya 1 Des 2017 – 28 Jan 2018**, puncak gelembung 2017. Di
  luar sampelnya, garis "tengah" itu bekerja sebagai garis PUNCAK siklus, lalu tak
  pernah tersentuh lagi.
- Ramalan **$10rb: 21 Nov 2017** → nyata 1 Des 2017. **Meleset 10 hari.**
- Ramalan **$100rb: 13 Jul 2021** → nyata 8 Des 2024. **Terlambat 1.244 hari.**
- Ramalan **$1 juta: 1 Sep 2026** → belum pernah; harga saat itu $78rb (0,08× garis).

Satu tebakan jitu tidak menyelamatkan sebuah model. Yang dihitung adalah semuanya.

## 3. Fit ulang — rumus sama, parameter dihitung dari data

| Data sampai | a | Garis untuk 1 Sep 2026 |
|---|---|---|
| 31 Des 2017 | 2,4204 | ~$126rb |
| 31 Des 2021 | 2,5769 | ~$199rb |
| 1 Sep 2026 | 2,4187 | ~$134rb |

Titik potong ditetapkan **sebelum** melihat hasil (akhir tiap siklus besar yang sudah
selesai). Garis "wajar" untuk hari yang sama bergeser 58% hanya karena batas datanya
digeser. R² fit penuh 0,944, tapi **autokorelasi residu lag-1 = 0,998**: simpangan dari
garis bertahan bertahun-tahun, jadi hampir seluruh R² berasal dari kenaikan jangka
panjang yang sudah diketahui, bukan dari kemampuan meramal.

Posisi 1 Sep 2026 pada fit penuh: 0,59× garis, persentil 24 sejarah simpangannya
(rentang 0,37×–10,8×). Itu **in-sample** — fit yang sama dipakai mengukur posisinya
sendiri.

**Batas data:** repo mulai 2012, chart asli memakai data sejak 2010. Parameter fit ulang
karena itu tidak bisa dibandingkan langsung dengan 2,9065 — fit s.d. 14 Okt 2014 pada
data kita memberi a = 4,10, jauh dari 2,9065, karena dua tahun paling eksplosif
(2010–2011) tidak ada di data kita. Itu sendiri pelajaran: parameternya peka terhadap
titik AWAL data, bukan hanya titik akhir.

## 4. Aturan untuk agent

- Boleh: satu kalimat konteks siklus jangka panjang, angkanya disalin dari blok brief.
- Dilarang: garis mana pun sebagai nilai wajar/target/"harga seharusnya"; R² sebagai
  bukti; "1,41×" sebagai temuan; regresi mengalahkan PROYEKSI.
- Selalu sebut ramalan yang jitu BERSAMA ramalan yang meleset.
- Rainbow chart dan power-law: keluarga yang sama, belum diuji terpisah di repo ini.
