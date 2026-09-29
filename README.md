# PLMS ? data dan review setting proteksi UPT Durikosambi

PLMS menghubungkan data penghantar, GI/bay/rele, setting, riwayat official,
dan bukti SLD untuk membantu pemeriksaan setting proteksi. Arah produk tahap
ini adalah **digitalisasi spreadsheet dengan sumber yang dapat ditelusuri,
ditambah topologi untuk menjelaskan konteks perhitungan**.

Status diperbarui: **29 September 2026**. Angka berikut berasal dari rebuild
uji `sld_audit/grogol_rebuild.db`, bukan otomatis dari database yang sedang
ditampilkan web. Perubahan rekonsiliasi masih lokal pada saat catatan dibuat.
Database kerja `plms.db` belum ditimpa karena menyimpan POC lokal Claude.

## Yang sudah berjalan

| Area | Implementasi saat ini | Batas cakupan |
|---|---|---|
| ETL | Tiga workbook repo -> CSV -> SQLite; alias GI, tegangan, bay/sirkit, provenance sumber | Versi workbook harus eksplisit; file Downloads dapat berbeda |
| Inventaris proteksi | Relay, fungsi, setting, sumber sel, dan riwayat official | Data terimpor belum berarti setting tervalidasi |
| Topologi | Ruas model, parameter R/X, tetangga dan audit relasi SLD | Relasi yang belum terbukti tetap menjadi gap |
| Identitas Grogol | GROGOL II = GROGOL BARU 150 kV; dua sirkit dipertahankan; dua ruas manual duplikat dikeluarkan | GROGOL tetap GI terpisah |
| Distance | Engine Z1/Z2/Z3, konversi CT/PT, traversal cabang, penyimpanan hasil dan jejak cabang | Belum validasi penuh karakteristik setiap model relay |
| Trafo untuk batas distance | Asumsi workbook 12,5% dengan nameplate per unit Grogol Baru/Grogol | Bukan perhitungan setting proteksi trafo |
| Web | Daftar/filter penghantar, kelompok GI, detail kedua ujung/rele/setting/sumber, audit SLD | Baca-saja; belum workspace review hasil hitung dan asumsi |

Pipeline rebuild uji memuat 1.219 ruas (1.183 DIgSILENT + 36 manual),
1.321 relay, 1.574 fungsi, 10.239 baris setting, dan 292 event official.
Jumlah baris tidak menyatakan jumlah perangkat yang sudah diverifikasi.

Verifikasi terakhir: **163 tes Python + 25 tes web lulus**; integrity check
SQLite dan foreign-key check lulus. Ada warning openpyxl tentang dependency
pivot cache workbook sumber. Tes perangkat lunak tidak mengesahkan setting lapangan.

## Pilot: Durikosambi 150 kV ? Grogol Baru ? Grogol

Dua ruas, masing-masing dua sirkit: empat penghantar dan delapan fungsi
DIST pada kedua ujung. Kelanjutan dari Grogol adalah **Tomang (SKTT)**,
bukan Ulujami; dikonfirmasi pemilik data dan konsisten dengan SLD yang dibaca.

| Arah relay, sirkit 1 dan 2 | Z1 | Z2 | Z3 |
|---|---|---|---|
| Durikosambi -> Grogol Baru | 2/2 terhitung | 2/2 dengan asumsi trafo | #1 terhitung dengan asumsi trafo; #2 reach ada, T3 belum terpetakan |
| Grogol Baru -> Durikosambi | 2/2 terhitung | Kebutuhan remote belum lengkap | Kebutuhan remote belum lengkap |
| Grogol Baru -> Grogol | 2/2 terhitung | 2/2 dengan asumsi trafo | #1 terhitung dengan asumsi trafo; #2 reach ada, T3 belum terpetakan |
| Grogol -> Grogol Baru | 2/2 terhitung | 2/2 dengan asumsi trafo | #1 terhitung dengan asumsi trafo; #2 reach ada, T3 belum terpetakan |

**Cakupan pilot saat ini: Z1 8/8, Z2 6/8, Z3 lengkap 3/8.** Tiga hasil Z3
lainnya sudah mempunyai reach tetapi belum waktu T3; dua sisanya belum
lengkap konteks remote. Delapan Z1 konsisten secara numerik dengan komponen
X setting tercatat. Hasil Z2/Z3 yang terhitung tidak otomatis berarti semua
nilai sudah dibandingkan dan disahkan terhadap laporan pengujian.

Pada empat pembandingan Z2 awal, cap trafo tidak terpakai. Kecocokan hasil
tersebut tidak membuktikan asumsi XT1 benar. Grogol?Tomang sudah mempunyai
R/X; gap awal berasal dari ruas manual duplikat tanpa impedansi.

### Keputusan asumsi T3 yang sudah disepakati, belum diimplementasikan

Pemilik data menyetujui asumsi kerja **T3 = 1,6 s** untuk sirkit 2 pada:

- Durikosambi -> Grogol Baru.
- Grogol Baru -> Grogol.
- Grogol -> Grogol Baru.

Dasar: expert judgement pemilik data mengenai delay tipikal, dengan nilai
referensi sirkit 1. Akan dibandingkan dengan laporan pemeliharaan/pengujian
individu. Ini bukan default semua relay dan bukan salinan data terukur.

Implementasi berikutnya harus menyimpan lingkup GI asal/tujuan, tegangan,
sirkit, fungsi/zona, nilai, dasar, tanggal keputusan, dan status verifikasi.
Sumber waktu yang pasti harus didahulukan; perbedaan terhadap asumsi harus
terlihat. Penandaan asumsi waktu harus independen dari asumsi trafo.

Setelah implementasi dan pengujian, target cakupan pilot menjadi **Z3 6/8
terhitung dengan asumsi**, bukan 8/8. Dua arah menuju Durikosambi tetap
memerlukan kelengkapan konteks remote. Angka cakupan di atas belum dinaikkan.

### Cakupan trafo dan fungsi lain

| GI | Bukti jumlah/kapasitas | Sudah dipakai | Belum selesai |
|---|---|---|---|
| Durikosambi | Pemilik data: 5 trafo; DB: 5 entri CBF bay TRF | Inventaris CBF | Identitas per unit, nameplate, hubungan bus dan konteks XT1 remote |
| Grogol Baru | SLD: 2 x 60 MVA, 150/22 kV | XT1 asumsi per unit = 46,875 ohm pada sisi 150 kV | Validasi proteksi trafo per unit |
| Grogol | SLD: 3 x 60 MVA, 150/20?22 kV | XT1 asumsi per unit = 46,875 ohm pada sisi 150 kV | Validasi proteksi trafo per unit |

Rumus asumsi: `X = 0.125 * V_kV^2 / S_MVA_per_unit`, dengan R diabaikan
sesuai template workbook. Jumlah unit tidak otomatis dijumlahkan sebagai
basis MVA. Nilai 12,5% bukan bukti semua trafo mempunyai impedansi identik.

LCD, OCR/GFR, AR, synchrocheck, CBF dan busbar protection tersedia dalam
inventaris ketiga GI; perhitungan/koordinasinya belum tervalidasi menyeluruh.
Differential trafo, REF, OCR/GFR trafo, netral/NGR dan koordinasi HV/LV
belum termasuk capaian pilot distance. POC lokal perlu diinventarisasi dan
masuk pipeline/test sebelum dianggap fitur yang dapat direproduksi.

## Gap dan keputusan yang masih terbuka

| Gap | Dampak | Langkah berikut |
|---|---|---|
| T3 sirkit 2 belum terpetakan | Z3 berlabel `ambiguous_branch` meski reach terhitung | Implementasikan asumsi terbatas; tampilkan alasan spesifik ?waktu belum tersedia? |
| Data lima trafo Durikosambi belum terstruktur per unit | Arah Grogol Baru -> Durikosambi belum lengkap | Cocokkan nameplate/rasio/bus SLD dan inventaris, lalu audit seluruh cabang remote |
| POC database kerja berbeda dari rebuild | UI default belum menampilkan hasil rebuild terbaru | Backup, petakan data khusus POC dan migrasi yang dapat diulang sebelum mengganti DB |
| Workbook setting Downloads berbeda dari repo | Risiko mencampur versi setting | Bandingkan DIST vs LCD+DIST, tanggal dan provenance sebelum memilih versi |
| Setting relay vs hasil formula | X, magnitudo, primer/sekunder dan parameter vendor bisa berbeda | Review parameter per model; jangan memberi label match untuk besaran berbeda |
| Phi Gandul?Kembangan?Durikosambi | Nomor sirkit fisik belum terbukti | Rekonsiliasi bay/status operasi dengan SLD terbaru; impedansi sama tidak memilih sirkit |
| MKBRU/GIS PIK | Kondisi lapangan belum dipahami penuh | Ditunda sesuai arahan; sumber yang belum dimodelkan tidak diasumsikan nol |
| Cengkareng | Bukti SLD belum tersedia pada sesi ini | Lanjutkan setelah bukti pendukung ada; jangan anggap pilot selesai |

SLD Kembangan 2022 menandai GANDUL 2 dan DURIKOSAMBI 1 TIDAK OPERASI.
Setting nol atau keberadaan record setting tidak sendiri membuktikan status
operasi aktual. Jangan mengubah model phi menjadi final dari kecocokan angka.

## Arah UI/UX yang direkomendasikan

**Tahap pertama: workspace review setting yang berpusat pada tabel, dengan
konteks topologi di sampingnya.** Pengguna sudah bekerja dengan spreadsheet;
prioritasnya membandingkan, menemukan gap dan membuka bukti dengan cepat.
Editor jaringan dan simulasi sistem tenaga penuh belum menjadi target tahap ini.

### Alur utama

1. Pilih koridor/GI, level tegangan, arah, sirkit dan fungsi proteksi lewat
   dropdown yang dapat dicari. Kombinasi pilihan mengikuti data yang tersedia.
2. Lihat tabel per relay/zona: setting tercatat, hasil hitung, satuan/basis,
   selisih, waktu, kelengkapan data, asumsi, dan status review.
3. Klik baris untuk membuka panel berisi input R/X dan CT/PT, rumus/cabang
   yang dipakai, sumber workbook/sel atau halaman SLD, serta alasan gap.
4. Lihat diagram kecil GI asal -> GI remote -> cabang 1?2 hop. Sorot jalur
   sesuai baris; bedakan 150/500 kV, arah dan sirkit 1/2 secara eksplisit.
5. Buka daftar pekerjaan yang memuat data hilang, identitas ambigu,
   perbedaan setting, dan asumsi yang menunggu laporan uji.

Contoh kolom tabel utama:

| GI asal -> tujuan | Sirkit | Relay / zona | Tercatat | Hitung | Basis | Delay | Asumsi | Review |
|---|---|---|---|---|---|---|---|---|
| Durikosambi -> Grogol Baru | 2 | 7SL87 / Z3 | Dari sumber | Dari engine | X, ohm sekunder | 1,6 s (rencana asumsi) | Trafo + waktu | Menunggu laporan uji |

Pisahkan tiga dimensi: **kelengkapan perhitungan**, **asal input/asumsi**,
dan **status review manusia**. Satu warna hijau ?complete? tidak cukup.
Data kosong ditampilkan sebagai belum tersedia, bukan nol. Perbandingan
hanya muncul jika parameter dan basis sama. Diagram adalah alat penjelas;
tabel tetap dapat digunakan tanpa membuka diagram.

### Saran relasi topologi

Tawarkan kandidat berdasarkan identitas GI, tegangan, bay, sirkit, endpoint,
dan bukti SLD. Tampilkan alasan cocok dan konfliknya, plus pilihan ?belum
cukup bukti?. Kandidat tidak otomatis menjadi relasi final. Keputusan
review disimpan terpisah dari sumber mentah dan memicu perhitungan ulang
konteks yang terdampak. Jangan menyamakan panjang/R/X sebagai bukti identitas.

### Urutan pengembangan

1. **Tutup gap pilot:** asumsi T3 terbatas beserta provenance/test, data lima
   trafo Durikosambi, dan review parameter terhadap laporan pengujian.
2. **Satukan database kerja dan pipeline:** pertahankan POC, gunakan identitas
   stabil, lakukan rebuild uji dan rekonsiliasi sebelum mengaktifkan hasil.
3. **Bangun layar review distance:** tabel perbandingan + panel bukti + filter
   koridor; tampilkan seluruh delapan fungsi pilot dan alasan gap per zona.
4. **Tambahkan diagram konteks dan review kandidat relasi:** tersinkron dengan
   baris tabel; keputusan dapat ditelusuri dan dibatalkan.
5. **Perluas proteksi:** inventaris trafo per unit, OCR/GFR dan koordinasinya,
   lalu fungsi lain dengan formula, sumber dan tes yang spesifik.
6. **Evaluasi kebutuhan studi jaringan lebih luas:** hanya setelah model,
   status operasi dan data sumber cukup; jangan mengklaim kesetaraan dengan
   perangkat studi sistem tenaga penuh dari pilot ini.

Kriteria selesai layar pilot: pengguna dapat memilih kedua sirkit pada dua
ruas, membandingkan kedua ujung, menjelaskan setiap hasil/gap lewat sumber,
dan melihat asumsi trafo/waktu tanpa membaca kode. Implementasi layar baru
ini masih rencana; UI existing sudah bisa dipakai untuk inventaris dan audit.

## Menjalankan dan memverifikasi

Dari root repo, gunakan target database uji agar POC pada `plms.db` tidak
tertimpa. Loader mengganti file target secara atomik setelah validasi;
ini bukan migrasi yang mempertahankan record khusus di target lama.

```powershell
python plms_etl.py . etl_out
python plms_v2_etl.py . v2b_out
python load.py etl_out alias_review.csv plms-review.db v2b_out
python calculation_run.py plms-review.db
python -m pytest -q
npm test --prefix web
```

Untuk membuka UI dengan database uji di PowerShell:

```powershell
$env:PLMS_DB = (Resolve-Path .\plms-review.db).Path
npm ci --prefix web
npm start --prefix web
```

Buka `http://localhost:3000`. Audit SLD harus dibuat ulang terhadap database
yang dipakai UI; audit dengan hash database lama ditolak. Instruksi audit
ada di [README web](web/README.md) dan [panduan SLD](docs/SLD_JAKBAN_ZONES.md).

## Bukti dan catatan rinci

- [Validasi Durikosambi?Grogol Baru?Grogol](docs/VALIDASI_DURIKOSAMBI_GROGOL.md).
- [Validasi Cengkareng](docs/VALIDASI_DURIKOSAMBI_CENGKARENG.md).
- [Inferensi phi dan asumsi impedansi trafo](docs/VALIDASI_GANDUL_KEMBANGAN_DURIKOSAMBI.md).
- [Lineage sumber](legacy-knowledge/DATA_LINEAGE_UPT_DURIKOSAMBI.md).

Dokumen validasi memuat riwayat patch database awal; bagian koreksi/rebuild
terbaru menjadi acuan status implementasi. ID SQLite pada riwayat snapshot
bukan identitas yang dijamin tetap sama setelah rebuild.


## Update UI - 30 September 2026

Versi awal `/review` sudah tersedia: pilih GI dan bay/sirkit/relay,
periksa endpoint dan CT/PT/R/X, baca setting beserta sel sumber,
tinjau R/X reach sekunder dan delay Z1-Z3, lalu buka jejak cabang.
Halaman menggunakan database yang sama dengan konfigurasi `PLMS_DB`.
Tidak menulis ke database atau menyimpan persetujuan engineer.

Belum tersedia: selisih otomatis (padanan parameter vendor belum direview),
saran relasi interaktif, penyimpanan keputusan, dan implementasi asumsi T3.
Rancangan roadmap di atas tetap menjadi arah pengembangan berikutnya.
Verifikasi UI: 26 tes web lulus dan endpoint pilot diuji memakai rebuild.


## Perluasan workspace koridor - 30 September 2026

`/corridor` menampilkan delapan fungsi DIST dan 24 zona sekaligus, filter
baris, setting ph-ph beserta sel sumber, X sekunder, selisih numerik, delay,
status asumsi dan rincian cabang. Selisih bukan verdict engineering karena
padanan parameter vendor dan satuan sumber belum disahkan.

T3 1,6 s kini diterapkan sebagai fallback pada tiga arah sirkit 2 yang
sudah disetujui, dengan catatan sumber judgement di jejak cabang dan status
`complete_assumed_inputs`. Waktu bersumber tetap diprioritaskan. Rebuild
pilot: Z1 8/8, Z2 6/8, Z3 6/8 termasuk asumsi. Dua arah menuju Durikosambi
masih belum lengkap; hitungan cakupan lama di atas adalah riwayat.

Catatan review lokal dapat disimpan dengan alasan wajib dan riwayat append-only
ke `<database>.reviews.db`. Snapshot input/hasil disimpan agar perubahan
menandai review sebagai perlu ditinjau ulang. File ini perlu ikut backup;
jangan dihapus saat rebuild. Belum ada autentikasi/multiuser, pengesahan
formal, atau pengiriman setting ke perangkat. Status Ditinjau bukan approval.

## Workspace per-GI (SLD dulu, baru setting) - 30 September 2026

`/gi` dan `/gi/:siteName` menggantikan alur "pilih dari dropdown relay_function"
dengan alur yang meniru cara insinyur bekerja dengan workbook sumber: buka GI,
lihat SLD aslinya, telusuri bay, baca setting terpasang.

1. **SLD asli** — PDF sumber di-serve langsung dari folder `SLD Durikosambi/`
   (bukan digambar ulang). Peta folder->`site_name` di `web/sld-index.js`
   hanya berisi 17 GI yang sudah diverifikasi manual satu-satu; GI yang
   namanya ambigu di sumber (mis. "GI Muarakarang" tanpa qualifier BARU/LAMA)
   sengaja ditandai "belum terhubung", bukan ditebak.
2. **Bay & setting terpasang** — dikelompokkan per bay lintas level tegangan,
   collapsed by default dengan ringkasan function_type di summary line (semula
   auto-expand semua, tidak terpakai untuk GI dengan >20 bay).
3. **Riwayat resmi** — `official_event`/`official_event_line` (292 baris,
   sumber `List Official Setting & Resetting UPT Durikosambi.xlsx`) sudah
   ada di skema sejak awal tapi belum pernah ditampilkan; sekarang muncul
   per GI via `giNameKey()`. Sengaja level GI saja — teks bay di sumber
   ("Budi Kemuliaan 1,2") belum dalam format yang sama dengan `relay.bay`
   ("PHT 150kV BUDI KEMULIAAN#1"), jadi pencocokan per-bay ditunda, bukan
   ditebak paksa.

Tema `index`/`detail`/`not-found`/`sld-audit` disatukan ke `review.css` yang
sama dengan halaman baru (`/gi`, `/review`, `/corridor`) — sebelumnya app ini
punya dua tema berbeda tanpa alasan produk, cuma karena ditambahkan di waktu
berbeda. Markup dan JS di halaman lama tidak diubah, hanya shell dan
stylesheet-nya. `web/corridor.js` juga diperbaiki: query-nya masih memfilter
`site_name='GROGOL BARU'` yang sudah pensiun sejak migrasi identitas GROGOL
II, sehingga halaman itu diam-diam menampilkan 0 baris sebelum diperbaiki.

Verifikasi: 32/32 tes web lulus, diperiksa langsung di browser (bukan cuma
baca kode) untuk tiap perubahan di atas.

## Purpose vs requirement — celah menuju "tools model PLN"

PLMS hari ini adalah alat *baca dan crosscheck*: mengimpor, menautkan, dan
membandingkan data yang sudah ada. Diskusi arah produk (30 September 2026)
membagi tujuan penuhnya jadi 4 pilar, masing-masing diperiksa terhadap kode
yang benar-benar ada — bukan diasumsikan:

| # | Pilar (tujuan) | Kebutuhan konkret | Status di repo |
|---|---|---|---|
| 1 | Repo data setting — tabel lengkap per data fisik aset | Setiap rele/fungsi/parameter tersimpan dgn provenance, terhubung ke bay & GI-nya | **Sebagian besar sudah ada.** `relay`/`relay_function`/`relay_setting` plus `official_event` (log persetujuan resmi, 292 baris, baru disambungkan ke UI bulan ini). Gap: ratusan baris identity `LOW confidence` (merk/type belum tercatat di sumber), bukan bug sistem. |
| 2 | Tools hitung setting — pilih GI+arah, tervalidasi thd jaringan, keluar setting sesuai merk/tipe rele, PDF ber-approval | Traversal topologi, rumus per fungsi proteksi, template output per vendor, alur approval | **Paling jauh dari selesai.** `distance_engine.py` menghitung Z1/Z2/Z3 tapi nempel di rele yang sudah terdaftar (bukan "dari nol pilih GI+arah"). Sheet `GANDUL-DURKOS` (workbook crosscheck asli) memetakan kebutuhan penuhnya: reach Z1-3 (ada), jangkauan resistif/blinder/power-swing (belum ada sama sekali), output per-merk relay (belum ada). Tidak ada generator PDF atau approval workflow. |
| 3 | Tools crosscheck — tap setting tersimpan vs database, atau vs hasil hitung baru | Bandingkan nilai tercatat dgn hasil engine, tandai selisih, simpan keputusan review | **Paling dekat selesai.** `calculation_loader.py` + `/corridor` + `/review` sudah membandingkan hasil hitung vs `SET_RELAY`, dengan status `complete_assumed_transformer`/`complete_assumed_inputs` yang eksplisit memisahkan data terukur dari asumsi. `setting_group='TAP_SET'` di skema kemungkinan representasi "tap setting resmi" yang dimaksud — perlu dikonfirmasi definisinya dgn pemilik data. |
| 4 | Ekspor RIO/XRIO untuk pengujian | Serialisasi setting ke format tukar-menukar per vendor | **Belum mulai**, dan sengaja ditunda ("soon") oleh pemilik data. Format per-vendor, perlu riset terpisah sebelum implementasi. |

Konsekuensi praktis: pekerjaan berikutnya yang paling bernilai bukan menambah
halaman baru, tapi mengisi pilar #2 (mesin hitung) memakai `GANDUL-DURKOS`
sebagai blueprint rumus, dan mengonfirmasi makna `TAP_SET` di pilar #3
sebelum dibangun lebih jauh di atasnya.

## Riset PSS®CAPE (Siemens) — konsep yang relevan untuk PLMS

PSS®CAPE adalah software komersial protection engineering (dipakai di lebih
dari 50 negara) yang paling dekat dengan visi 4 pilar di atas. Brosur produk
menunjukkan pemisahan modul yang jelas, dan beberapa konsepnya langsung
relevan utk arah PLMS:

| Modul PSS®CAPE | Fungsinya | Relevansi utk PLMS |
|---|---|---|
| Database Editor | Satu database relasional (ODBC/SQL), semua modul baca-tulis data yang sama | Sudah sejalan dgn pendekatan `plms.db` + provenance kita |
| One-Line Diagram | Diagram SLD interaktif: klik elemen -> lihat data/hasil simulasi langsung di diagram, buka breaker, terapkan gangguan | Jauh lebih maju dari `/gi` kita (PDF statis) — arah lanjutan yang masuk akal, TAPI butuh data koordinat bay yang belum kita punya |
| **Relay Setting** | Prosedur setting **perusahaan sendiri** ditulis sbg macro (bukan 1 formula universal); macro menghitung raw setting lalu memilih tap aktual | **Paling relevan utk pilar #2.** Ini persis pola `GANDUL-DURKOS`: prosedur UPT Durikosambi sendiri, bukan rumus generik buku teks. Desain "macro per prosedur organisasi" > "1 formula hardcoded" |
| Coordination Graphics | Plot bidang R-X interaktif, kurva OCR/GFR, reset tap grafis | Konsep yang sama sempat diusulkan sesi ini utk visualisasi Z1/Z2/Z3; PSS®CAPE membuktikan ini pola yang sudah terbukti dipakai industri |
| Relay Checking / System Simulator | Simulasi stepped-event otomatis lintas jaringan, deteksi miscoordination dgn traffic-light | Arah lanjutan utk pilar #3 setelah crosscheck 1-rele sudah matang |
| **Order Production** | Generate laporan **kertas/PDF** setting berdasar tap & test point per lokasi | Persis "PDF tap setting + approval berjenjang" di pilar #2 |
| Compliance Module | Studi keandalan proteksi otomatis, review koordinasi wide-area, kepatuhan standar NERC PRC | Referensi bentuk laporan (lihat contoh "1. Protection Information / 2. Coordination Review / 3. Summary") utk format keluaran resmi kita nanti |
| Bridge Module | Pertukaran data 2 arah dgn sistem asset management | Relevan kalau integrasi PST (disebut di beberapa komentar kode) jadi prioritas |

Yang **tidak** relevan diambil sekarang: Power Flow, Short Circuit Reduction,
Breaker Duty, PSS®CAPE-TS Link (studi stabilitas transien) — itu scope studi
sistem tenaga penuh, di luar tahap PLMS saat ini (lihat "Arah UI/UX yang
direkomendasikan" di atas, poin 6: jangan klaim setara software studi
sistem tenaga penuh dari tahap pilot ini).

Sources:
- [PSS®CAPE Protection Simulation Software (brosur produk)](https://descargas.indielec.com/web/PSS-CAPE%20Brochure.pdf)
- [Siemens — PSS®CAPE product page](https://www.siemens.com/global/en/products/energy/grid-software/maintain/grid-resiliency-software/psscape.html)
