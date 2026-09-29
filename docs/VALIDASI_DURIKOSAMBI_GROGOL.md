# Validasi awal Durikosambi - Grogol Baru - Grogol

Tanggal: 29 September 2026. Bagian pertama dokumen ini (sampai "Tindak
lanjut") adalah pemeriksaan baca-saja awal. Bagian "Migrasi identitas node
& hasil Z1/Z2/Z3" di bawah mendokumentasikan PERUBAHAN NYATA ke `plms.db`
yang dilakukan setelahnya, atas keputusan eksplisit pemilik data pada sesi
yang sama.

## Bukti topologi

Konfirmasi pemilik data: GROGOL II = GROGOL BARU. Kedua SLD versi 8, tanggal gambar 29 Agustus 2022, memperlihatkan dua sirkit SUTT Durikosambi-Grogol Baru dan dua sirkit SUTT Grogol Baru-Grogol. Pada SLD Grogol, dua bay SKTT berikutnya menuju TOMANG. Hubungan lanjut Ulujami belum dibuktikan oleh dua gambar ini.

SLD Grogol Baru menggambar dua trafo 60 MVA 150/22 kV; SLD Grogol menggambar tiga trafo 60 MVA (150/20, 150/22, 150/20 kV). Persentase impedansi trafo tidak tercantum. Bay Kebon Jeruk Baru/Trafo 3 pada SLD Grogol Baru bergaris putus-putus; status operasi tidak diasumsikan.

## Masalah model PLMS

GROGOL II (ss_id 194, 150 kV) dan GROGOL BARU (ss_id 613, tegangan NULL) masih node terpisah. Ruas manual 1192 dan 1193 tanpa impedansi menampung rele dari kedua sirkit sekaligus. Ruas DIgSILENT 319/320 dan 388/389 sudah memiliki impedansi. Ini memerlukan rekonsiliasi pada ETL beserta pemetaan ulang rele per sirkit, bukan menyalin impedansi ke satu ruas manual gabungan.

| Ruas | Sirkit 1 | Sirkit 2 | Panjang model | R1+jX1 primer |
|---|---:|---:|---:|---|
| Durikosambi-Grogol Baru | 319 | 320 | 6.468 km | 0.2503116+j1.815568 |
| Grogol Baru-Grogol | 388 | 389 | 2.000 km | 0.0774+j0.5614 |

## Perbandingan numerik awal Z1

Tabel ini menghubungkan identitas yang telah dikonfirmasi hanya untuk analisis, tanpa mengubah database. Semua rele 7SL87, PT 150 kV/100 V. Hasil 80% mengikuti rumus dasar engine; interpretasi parameter 7SL87 dan basis impedansi tetap harus diverifikasi. Perbandingan X dan magnitudo ditampilkan terpisah agar tidak mencampur besaran.

| Arah | RF ID | CT | Z1 tercatat | 0.8 X sekunder | 0.8 magnitudo Z sekunder |
|---|---|---|---:|---:|---:|
| Durikosambi-Grogol Baru #1 | 1410 | 1600/5 | 0.31 | 0.309857 | 0.312788 |
| Durikosambi-Grogol Baru #2 | 1416 | 1600/5 | 0.31 | 0.309857 | 0.312788 |
| Grogol Baru-Durikosambi #1 | 1404 | 2000/1 | 1.937 | 1.936606 | 1.954925 |
| Grogol Baru-Durikosambi #2 | 1398 | 2000/1 | 1.937 | 1.936606 | 1.954925 |
| Grogol Baru-Grogol #1 | 1402 | 2000/1 | 0.599 | 0.598827 | 0.604491 |
| Grogol Baru-Grogol #2 | 1400 | 2000/1 | 0.599 | 0.598827 | 0.604491 |
| Grogol-Grogol Baru #1 | 1408 | 1600/1 | 0.479 | 0.479061 | 0.483593 |
| Grogol-Grogol Baru #2 | 1414 | 1600/1 | 0.479 | 0.479061 | 0.483593 |

Sumber setting: Data Setting Penghantar UPT DKSBI.xlsx, sheet DIST, baris 143/144 (Durikosambi), 45/46 (Grogol Baru-Durikosambi), 47/48 (Grogol Baru-Grogol), 41/42 (Grogol-Grogol Baru); kolom AP. Data dibaca dari relay_setting dengan sumber tersebut; workbook belum diperiksa ulang pada tahap ini.

Pada delapan rele, 80% X model setelah konversi CT/PT membulat ke Z1 tercatat (0.310, 1.937, 0.599, 0.479). Kecocokan ini konsistensi numerik komponen X, bukan magnitudo Z atau pengesahan seluruh karakteristik 7SL87. Referensi scanning lokal memuat panjang 1.780 dan 2.000 km untuk koridor Grogol-Grogol Baru; model 2.000 km konsisten secara numerik dengan setting tercatat, tetapi panjang aktual belum diverifikasi.

## Tindak lanjut

1. Rekonsiliasi GROGOL BARU/GROGOL II di sumber ETL; pertahankan dua sirkit pada setiap koridor dan tautkan ulang rele sesuai #1/#2.
2. Verifikasi panjang dan impedansi Grogol Baru-Grogol dari sumber terbaru serta definisi setting 7SL87.
3. Lengkapi impedansi persen/reaktansi trafo Grogol Baru dan Grogol untuk evaluasi Z2/Z3.

## Migrasi identitas node & hasil Z1/Z2/Z3 (2026-09-29, setelah addendum XT1)

Setelah aturan XT1 = 0,125 x V_ref^2/MVA dikonfirmasi (lihat addendum di
[VALIDASI_GANDUL_KEMBANGAN_DURIKOSAMBI.md](VALIDASI_GANDUL_KEMBANGAN_DURIKOSAMBI.md)),
percobaan menjalankan `calculation_run.py` menunjukkan Z1 pun gagal utk
kedelapan rele DIST koridor ini -- bukan XT1 yang jadi penghambat pertama,
melainkan pemetaan `relay.line_id`: kedelapan rele ternyata terpasang di
ruas manual `line_id=1192`/`1193` (tanpa `line_electrical`), bukan di ruas
DIgSILENT 319/320/388/389 yang benar-benar punya R/X.

Ditelusuri lebih lanjut: DIgSILENT tidak pernah mengenal `ss_id=613`
("GROGOL BARU" versi manual). Busbar yang sama di model DIgSILENT adalah
`ss_id=194` ("GROGOL II"). Pemilik data mengonfirmasi keduanya substation
fisik yang sama (lihat pesan awal sesi ini). Keputusan pemilik data
2026-09-29: lanjutkan migrasi.

### Cakupan migrasi (sengaja dibatasi, BUKAN merge penuh)

Backup dibuat lebih dulu: `plms.db.bak-20260929T150215-grogol-remap`
(root repo, tidak dilacak git -- `plms.db` sendiri juga tidak dilacak git).

Hanya 8 baris `relay` yang diubah -- SEMUA rele DIST fungsional koridor ini
(diverifikasi dgn query eksplisit `function_type='DIST' AND line_id IN
(1192,1193)`, tidak ada baris DIST lain yang tertinggal):

| relay_id | Bay | ss_id lama->baru | line_id lama->baru |
|---:|---|---|---|
| 1216 | DURIKOSAMBI#1 | 613->194 | 1192->319 |
| 1213 | DURIKOSAMBI#2 | 613->194 | 1192->320 |
| 1220 | GROGOL BARU#1 | 154 (tetap) | 1192->319 |
| 1224 | GROGOL BARU#2 | 154 (tetap) | 1192->320 |
| 1215 | GROGOL#1 | 613->194 | 1193->388 |
| 1214 | GROGOL#2 | 613->194 | 1193->389 |
| 1219 | GROGOL BARU#1 | 193 (tetap) | 1193->388 |
| 1223 | GROGOL BARU#2 | 193 (tetap) | 1193->389 |

Sirkit 1/2 dipetakan dari suffix bay (#1/#2) yang sudah dipakai sbg bukti
di validasi Cengkareng (`line.circuit_no` masih NULL di seluruh db, ini
bukan pengecualian baru). Diverifikasi tiap baris: `ss_id` hasil migrasi
memang salah satu ujung `line.ss_from/ss_to` dari `line_id` barunya.

TIDAK dilakukan (sengaja, di luar scope permintaan ini): menghapus/
menandai `ss_id=613` sbg mati, migrasi ~24 baris `relay` lain yang masih
memakai `ss_id=613` (bay MPU/TRF/KOPEL BUS 150kV atau duplikat
identity_status=REVIEW tanpa `relay_function` DIST -- tidak memengaruhi
kalkulasi zona), atau mengubah baris `line` 1192/1193 itu sendiri. Ini
tetap utang rekonsiliasi terbuka bila `ss_id=613` suatu saat perlu benar-
benar dipensiunkan.

### Whitelist XT1 dikoreksi

Whitelist awal (`613`, `194`) sempat salah kutip sumber: `194` dikutip
memakai nameplate SLD GRGOL (Grogol, `ss_id=193`, 3x60MVA) padahal `194`
adalah GROGOL BARU (sama dgn `613`) yang nameplate-nya dari SLD GRLBR
(2x60MVA). Angka XT1 kebetulan sama (60MVA -> 46,875 Ohm utk keduanya)
sehingga tidak memengaruhi hasil numerik, tapi sitasi sumbernya salah --
sudah diperbaiki di `calculation_loader.py`. `ss_id=193` (GROGOL, substation
lain, 3x60MVA dari SLD GRGOL) ditambahkan sbg entri whitelist terpisah.

### Hasil setelah migrasi + koreksi whitelist

`python3 calculation_run.py plms.db`:

| Zona | complete | complete_assumed_transformer | incomplete_topology |
|---|---:|---:|---:|
| Z1 | 105 (+8 dari 97) | 0 | 79 |
| Z2 | 0 | 4 | 180 |
| Z3 | 0 | 0 | 184 |

Kedelapan rele DIST koridor ini sekarang Z1 `complete`. Z2 `complete_
assumed_transformer` utk 4 dari 8 (XT1 GROGOL BARU/194, 46,875 Ohm):

| relay_id | Bay | Z2 hitung (sekunder) | Z2 SET_RELAY (ph-ph) | Selisih |
|---:|---|---:|---:|---:|
| 1220 | GROGOL BARU#1 (di Durikosambi) | 0,464785 | 0,465 | ~0,05% |
| 1224 | GROGOL BARU#2 (di Durikosambi) | 0,464785 | 0,465 | ~0,05% |
| 1219 | GROGOL BARU#1 (di Grogol) | 1,718489 | 1,718 | ~0,03% |
| 1223 | GROGOL BARU#2 (di Grogol) | 1,718489 | 1,718 | ~0,03% |

Kecocokan empat hasil Z2 tersebut memeriksa reach cabang. Pada keempatnya
`capped_by_transformer=False`; jadi kecocokan ini **tidak memvalidasi nilai
XT1**. Nilai 12,5% berasal dari asumsi template workbook, bukan hasil
pengujian impedansi trafo.

### Koreksi audit dan rebuild ETL (29 September 2026)

Uraian migrasi delapan relay di atas adalah riwayat patch database awal,
bukan mekanisme final. Rekonsiliasi kini berada di `load.py`: GROGOL BARU
150 kV memakai satu node dengan nama model asli GROGOL II. Seluruh fungsi
relay dimuat ulang melalui identitas ini; nomor sirkit I/II dipetakan ke
1/2. Dua ruas manual duplikat dihapus dari daftar konstruksi graph.
Nomor SQLite dalam tabel sejarah bukan identifier stabil lintas rebuild.

Koreksi diagnosis: GROGOL-TOMANG 1/2 sudah mempunyai `line_electrical`
(R1=0.05343, X1=0.62061 ohm per sirkit). Penghambat sebelumnya adalah ruas
manual duplikat GROGOL BARU-GROGOL tanpa impedansi, bukan kekurangan R/X
Grogol-Tomang. Tidak perlu mengisi atau menggandakan data ruas itu.

Resolver XT1 sekarang mencari identitas GI + tegangan dalam database.
Identitas hilang, ambigu, atau belum ditinjau tetap menghasilkan None;
nomor ss_id tidak lagi menentukan asumsi. Untuk Grogol Baru dan Grogol,
60 MVA adalah daya **per unit**, sehingga 0.125 x 150^2 / 60 = 46.875 ohm.
Status hasil tetap `complete_assumed_transformer`, bukan data terukur.

Rebuild uji `sld_audit/grogol_rebuild.db` dari CSV ETL dan alias repo,
diikuti `calculation_run.py`, menghasilkan 184 fungsi DIST:

| Zona | complete | complete_assumed_transformer | incomplete_topology | ambiguous_branch |
|---|---:|---:|---:|---:|
| Z1 | 105 | 0 | 79 | 0 |
| Z2 | 0 | 8 | 176 | 0 |
| Z3 | 0 | 4 | 176 | 4 |

Angka ini cakupan seluruh database, bukan seluruhnya koridor Grogol.
Integrity check dan foreign-key check lulus. Database kerja `plms.db`
tidak ditimpa: data POC protection_chain lokal tidak boleh hilang oleh
rebuild sumber. Database uji adalah artefak verifikasi, bukan setting
relay yang disahkan untuk diterapkan di lapangan.

Tindak lanjut: lengkapi sumber T3 untuk empat hasil Z3 berstatus ambiguous_branch, lengkapi nameplate
sisi remote yang belum tersedia, dan rekonsiliasi POC lokal sebelum
menggantikan database kerja. MKBRU dan phi 500 kV tidak diubah oleh fix ini.

## Hash PDF bukti

- SLD Durikosambi/ULTG DURIKOSAMBI/GIS GROGOL BARU/SINGLE LINE GRLBR Ver 8 2022.pdf: `a20c0d9172bf9185230096f2c07751690ea6cb982a3fa266e1e293fde633bf88` (halaman 1 diperiksa visual).
- SLD Durikosambi/ULTG DURIKOSAMBI/GIS GROGOL/SINGLE LINE GRGOL Ver 8 2022.pdf: `077aa70682f8308302b8415e7ace7bd55caf5e3396f2ed25d632a5ac7c91f287` (halaman 1 diperiksa visual).
