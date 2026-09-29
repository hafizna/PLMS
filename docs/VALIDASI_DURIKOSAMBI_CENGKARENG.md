# Validasi Durikosambi - Cengkareng

Tanggal pemeriksaan: 29 September 2026. Basis kode: commit `5a9e8b3`.
Pemeriksaan baca-saja terhadap workbook lokal dan `plms.db`; tidak mengubah
setting, status operasi, impedansi, maupun hasil kalkulasi tersimpan.

## Kesimpulan

Identitas dua sirkit, empat rele DIST, CT/PT, dan impedansi dalam database
konsisten dengan workbook sumber yang diperiksa. Magnitudo reach Z1 hasil
rumus PLMS membulat ke setting ph-ph 1.018 pada keempat rele. Ini validasi
konsistensi numerik sumber lokal, belum pengesahan setting aktual lapangan
atau seluruh karakteristik MiCOM P545. Satuan setting pada workbook tidak
ditulis eksplisit; interpretasi ohm sekunder didukung kecocokan konversi CT/PT.
Z2/Z3 belum dapat disahkan: XT1 remote belum tersedia, sebagian ruas dua hop
belum mempunyai impedansi, dan referensi scanning belum konsisten satuannya.

## Identitas dan sumber

Ujung protected line adalah DURIKOSAMBI 150 kV (`ss_id=154`) dan CENGKARENG
150 kV (`ss_id=83`). CENGKARENG BARU merupakan node lain.

| Sirkit | line_id | Nama DIgSILENT | Baris sumber DB |
|---|---:|---|---:|
| 1 | 275 | CNKRG-DKSBI -1 | 325 |
| 2 | 276 | CNKRG-DKSBI -2 | 326 |

Sumber: `Aplikasi Crosscheck Setting Relay [Digsilent_ 9 Maret 2021, IHS 1-2021].xlsx`,
sheet `DB`, T nama, X/Z ujung, W teknologi, AG panjang, AR magnitudo Z1,
AT/AU R1/X1, AV/AW R0/X0. Nilainya sama dengan database.

`line.circuit_no` masih NULL, tetapi suffix nama -1/-2 dan sumber rele #1/#2
mendukung pemetaan masing-masing sirkit. Kedua baris memakai label bay
DIgSILENT yang sama (I-5/II-5), sehingga label itu sendiri bukan bukti sirkit.
`out_of_service` NULL; loader saat ini memasukkannya dalam traversal. Status
operasi terkini belum dibuktikan oleh pemeriksaan ini. `model_date` dan
`model_version` kosong; tanggal 2021 berasal dari nama workbook.

| Sisi rele | Sirkit | relay_function_id | Serial P545 | Sumber DIST baris |
|---|---:|---:|---|---:|
| Durikosambi | 1 | 1163 | 36039279/03/22 | 140 |
| Durikosambi | 2 | 1165 | 36039282/03/22 | 141 |
| Cengkareng | 1 | 1161 | 36039278/03/22 | 124 |
| Cengkareng | 2 | 1167 | 36039283/03/22 | 125 |

Sumber: `Data Setting Penghantar UPT DKSBI.xlsx`, sheet `DIST`.
Keempat rele GE MiCOM P545, identity HIGH/EXACT, line_link_status EXACT.
Kolom G: CT 2000/5; H: PT 150 kV/100 V. Hash workbook cocok dengan
`relay_source.source_hash`. SET_RELAY aktif ada di AM:AX; TAP_SET T:AB
tidak aktif di database dan tidak dipakai sebagai nilai setting terkini.

## Impedansi dan hitung ulang Z1

Kedua sirkit memiliki panjang 10.32 km, OHL/SUTT, ACSR 1x520 mm menurut
workbook DIgSILENT. Semua nilai berikut dalam ohm primer kecuali dinyatakan lain.

| Parameter | Nilai |
|---|---:|
| R1 | 0.470592 |
| X1 | 4.747200 |
| R0 | 2.022720 |
| X0 | 14.241600 |
| R1/km | 0.045600 |
| X1/km | 0.460000 |
| R0/km | 0.196000 |
| X0/km | 1.380000 |

Panjang dikalikan parameter per km sesuai nilai total. Magnitudo
sqrt(R1^2 + X1^2) = 4.770467972 ohm, konsisten dengan AR = 4.770468.
Konversi primer ke sekunder: (2000/5)/(150000/100) = 0.266666667.

- Reach Z1 PLMS = 0.8 * (R1+jX1) = 0.3764736+j3.79776 ohm primer.
- Reach sekunder = 0.10039296+j1.012736 ohm.
- Magnitudo sekunder = 1.017699834 ohm, membulat menjadi 1.018.
- SET_RELAY AP124/AP125/AP140/AP141 = 1.018; selisih terhadap magnitudo
  hitung sebelum pembulatan sekitar 0.0295%.
- Komponen X sekunder 1.012736 bukan magnitudo Z. Jangan membandingkan
  angka ini dengan 1.018 sebagai besaran identik.
- Waktu Z1 AV pada keempat baris = 0 s, sesuai hasil engine.

Kolom AQ ph-gnd juga berisi 1.018. Ini belum memvalidasi elemen tanah:
hasil internal `z0_secondary_ohm` engine berbasis Z0 tidak boleh langsung
dibandingkan dengan setelan reach tanah P545 tanpa memeriksa definisi
parameter, kompensasi residual, dan karakteristik rele. Engine memakai rumus
referensi kasus REL670; kecocokan magnitudo Z1 tidak membuktikan seluruh
parameter RFPP/RFPE dapat ditransfer ke P545.

## Setting tercatat dan cabang berikutnya

Nilai impedansi di tabel ini disalin dari SET_RELAY, bukan hasil rekomendasi baru.

| Arah rele (kedua sirkit) | Z1 | Z2 | Z3 | t1 | t2 | t3 |
|---|---:|---:|---:|---:|---:|---:|
| Durikosambi menuju Cengkareng | 1.018 | 1.528 | 2.966 | 0 | 0.4 | 1.6 |
| Cengkareng menuju Durikosambi | 1.018 | 1.528 | 2.700 | 0 | 0.8 | 1.6 |

Untuk fokus rele sisi Durikosambi, empat cabang forward di bus Cengkareng:

| Ruas | line_id | Teknologi DB | Panjang km | R1+jX1 primer |
|---|---|---|---:|---|
| Cengkareng - Cengkareng Baru 1/2 | 235/236 | CAB | 0.397 | 0.00260035+j0.123864 |
| Cengkareng - Tangerang 1/2 | 277/278 | OHL | 9.230 | 0.683020+j4.448860 |

Ini topologi database, masih perlu dicocokkan dengan SLD Cengkareng terkini.
Audit Jakban saat ini mendukung CNKNG-TGRNG (ss_lbk_ingest.xlsx,
Jalur_Transmisi baris 29); CKDRU-CNKNG baris 28 masih UNRESOLVED_IDENTITY.
Jangan menjadikan cakupan gambar sebagai bukti tidak adanya ruas lain.

Penelusuran engine dari sisi Durikosambi menghasilkan 4 path Z2 dan 22 path Z3
(termasuk 4 path satu hop). XT1 Cengkareng belum tersedia -- **catatan
koreksi**: aturan XT1 = j x 0,125 x V^2/S_trafo (S_trafo dari nameplate SLD
GI, asumsi 12,5% dikonfirmasi dua kali di workbook DIgSILENT) kini
terdokumentasi di [VALIDASI_GANDUL_KEMBANGAN_DURIKOSAMBI.md](VALIDASI_GANDUL_KEMBANGAN_DURIKOSAMBI.md).
"Belum tersedia" di sini berarti nameplate trafo Cengkareng belum dibaca dari
SLD-nya dalam pemeriksaan ini, bukan berarti Z% terukur diperlukan. Impedansi yang
kosong pada path dua hop: Cengkareng Baru-ITS (1194), Cengkareng Baru-Bandara
Soekarno Hatta (1216), Cengkareng Baru-Tangerang Baru (1217), Jatake Baru-
Tangerang (1197), dan Jatake-Tangerang (1213). Sebagian nama manual mungkin
tumpang tindih dengan model lama; jumlah ini bukan jumlah sirkit fisik tervalidasi.
Faktor infeed default engine 1.0 belum dibuktikan untuk kasus ini.

## Temuan referensi scanning

`scanning_reference/scanning_reference.csv` baris 45 (helper ID
`1e9cWuBvufXKB1JvvQ1r0GrZLb5rseZad8N8zoBv8Yt4`, tanggal tertulis
4 Desember 2025, arah Durikosambi-Cengkareng) memuat:

- `x_per_km_primary=0.123`, `xline_primary=1.272`, `z1_primary=1.013`.
- `z1_secondary=0.270`, t2=0.8 s; berbeda dengan SET_RELAY t2=0.4 s.

Indikasi kuat perbedaan basis satuan: X primer/km 0.46 dikalikan 400/1500
= 0.1226667, dekat 0.123. Magnitudo Z ruas sekunder = 1.27212479,
dekat 1.272. X reach Z1 sekunder = 1.012736, dekat 1.013. Dengan demikian
angka yang diberi label primer di CSV berpotensi sudah sekunder, dan
0.270 berpotensi hasil konversi kedua. Ini diagnosis numerik, belum konfirmasi
formula helper asli; CSV tidak dikoreksi atau dipakai mengganti impedansi.
Baris 28 dan 35 juga memberi representasi yang tidak konsisten untuk koridor
yang sama. Label LINE 1/LINE 2 pada helper bukan bukti nomor sirkit.

Prioritas berikut: cocokkan SLD Cengkareng terkini beserta data trafo, lalu
periksa helper scanning asli untuk satuan dan perbedaan t2. Kesesuaian Z1
dapat dicatat sementara tanpa meloloskan Z2/Z3 atau setting tanah.

## Konfirmasi pemilik data dan batas pekerjaan

- Pemilik data mengonfirmasi GROGOL II = GROGOL BARU dan arah lanjut menuju
  Ulujami berupa SKTT. Identitas ini sudah diputuskan secara domain, bukan
  pertanyaan terbuka lagi. Rekonsiliasi node/ruas duplikat di ETL/database
  belum dikerjakan dalam validasi Cengkareng ini.
- MKBRU ditunda; tidak diasumsikan sebagai sumber nol maupun mengubah PIK
  menjadi ujung radial.
- Informasi teardown Durikosambi-Muarakarang Lama dicatat pada percakapan;
  status per sirkit dan tanggal efektif belum diperbarui ke database.

## Sidik sumber

SHA256:

| Sumber | Hash |
|---|---|
| plms.db | c828fd63594905fe033e518b02757d99960539a44f23e97680c28a1dd98d501c |
| Workbook DIgSILENT | 46061b0726c6a13c7cce9eb2b678101bb9c65c19f7b11c88686916d0e5174465 |
| Workbook setting UPT | f0ba5b0036e47fb050940334d394bb217cdf81dcbdeea63e562db5b25048167c |
| CSV scanning | cc0d9e032bbf4c5453aff63004d256ae2e9d2874ce8b73bb30f9647dc9f34617 |
