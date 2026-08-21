# PLMS Rebuild — Prompt Claude Code v2

Menggantikan v1. Seluruh angka di sini sudah diverifikasi langsung terhadap file sumber.

---

# BAGIAN A — Prompt untuk Claude Code

> Paste mulai dari sini.

## Konteks

Saya membangun ulang PLMS (Protection Line Management System) — sistem manajemen data setting proteksi transmisi PLN. Repo lama `hafizna/POC_PLMS` ditinggalkan.

**Kenapa ditinggalkan:** repo lama punya ~47.000 baris kode dan 11 menu, tetapi hanya tiga migrasi database — `setting_case`, `governed_revision`, `source_observation_audit`. Ketiganya lapisan proses. **Tidak ada satu pun tabel topologi jaringan.** Aplikasi menjadi sistem case-management di atas model data yang tidak pernah ada, alurnya belasan langkah, dan akhirnya tidak terpakai.

## Prinsip yang tidak boleh dilanggar

1. **Data layer dulu.** Tidak ada case, approval, freeze, revisi terkendali, inbox, atau audit trail sampai v5. Kalau ragu, jangan buat.
2. **Dokumen UPT adalah penentu scope.** DIgSILENT adalah pelengkap. GI yang ada di dokumen UPT tapi tidak ada di DIgSILENT **tetap masuk sistem**, ditandai `topology_source IS NULL`. Jangan pernah membuang baris karena tidak cocok — tandai.
3. **Maksimal tiga klik** dari halaman depan ke data mana pun.
4. **Tidak ada nilai hardcoded.** Semua dari database. Slider hanya overlay eksploratif.
5. **Baca semua sheet.** Kesalahan terbesar dalam analisis awal terjadi karena hanya satu sheet dibaca lalu disimpulkan. Setiap parser wajib melaporkan jumlah entitas yang ditemukan agar bisa dicocokkan dengan angka yang sudah diketahui benar.

## Scope

**Seed: 44 GI** dari dokumen UPT Durikosambi, tersebar di 5 ULTG — Angke, Cikupa, Citra Raya, Durikosambi, Tangkot.

```
ALAM SUTERA, ANGKE, BALARAJA, CENGKARENG, CENGKARENG BARU, CIKUPA,
CILEDUG, CITRA HABITAT, CURUG, DAAN MOGOT, DADAP, DURIKOSAMBI,
GAJAH TUNGGAL, GROGOL, GROGOL BARU, ITS, JATAKE, JATAKE BARU,
KEBON JERUK, KEMBANGAN, LAUTAN STEEL, LONTAR, MAXIMANGANDO, METLAND,
MILENIUM, MUARAKARANG BARU, MUARAKARANG LAMA, NEW BALARAJA,
NEW SENAYAN, PANTAI INDAH KAPUK, PASAR KEMIS, PASAR KEMIS BARU,
SEPATAN, SEPATAN BARU, SINDANG JAYA, SPINMILL,
SUMMARECON GADING SERPONG, SUVARNA, TANGERANG, TANGERANG BARU,
TELUK NAGA, TIGARAKSA, TOMANG, ULUJAMI
```

Ukuran scope yang sudah dihitung ulang terhadap workbook UPT 22-sheet yang
di-commit 21 Agustus 2026. `KOSAMBI BARU4/5` dan `TELUKJAMBE` dikeluarkan
eksplisit sesuai blocklist; graph tidak boleh merambat melewati node tersebut.

| Cakupan | Node DIgSILENT | Penghantar DIgSILENT | + 4 penghantar manual UPT | % dari 1.187 |
|---|---:|---:|---:|---:|
| seed | 35 | 113 | 117 | 10% |
| **+1 hop (default)** | **60** | **148** | **152** | **13%** |
| +2 hop | 75 | 177 | 181 | 15% |
| +3 hop | 89 | 208 | 212 | 18% |

Di luar node DIgSILENT pada tabel, ada 13 GI seed UPT dengan
`topology_source IS NULL`. Karena itu total node sistem adalah 48 pada seed
dan 73 pada scope +1 hop. Angka 43/127 dan 69/183 pada versi prompt sebelumnya
berasal dari baseline workbook lama dan tidak lagi menjadi acceptance target.

**Scope ditentukan secara topologis, bukan organisasi.** UPT dan ULTG adalah atribut biasa dengan `valid_from`/`valid_to`, karena struktur organisasi berubah (Jatake pindah UPT akibat pemekaran 2024) sementara topologi tidak.

### Management scope vs calculation context

`+1 hop` adalah **management scope**: menentukan 152 penghantar yang muncul di
register dan layar utama. Ini bukan batas graph untuk perhitungan proteksi.
Database tetap memuat seluruh 1.183 penghantar DIgSILENT sehingga perangkat di
luar management scope dapat dipakai sebagai konteks baca-saja.

Engine distance v3a membangun **calculation context per rele**, bukan menaikkan
scope global menjadi +2/+3 hop:

- Z1 memakai protected line.
- Z2 memakai protected line dan bagian line setelah remote bus.
- Z3 minimal melihat protected line, seluruh cabang pada remote bus, dan next
  line (+2 hop sebagai minimum prototipe) untuk menangani backup dan infeed.
- Explicit reverse zone menelusuri cabang di belakang local bus. Reverse
  resistive reach pada karakteristik quadrilateral bukan otomatis hop graph.
- Traversal final berbasis impedansi R/X: berjalan forward/reverse sampai reach
  zona habis, dengan safety cap tiga hop. Jangan berhenti hanya karena batas
  management scope.

Setiap calculation context menyimpan arah, ordered path/cabang yang dicoba,
impedansi kumulatif, dan salah satu status `complete`, `incomplete_topology`,
`incomplete_external`, atau `ambiguous_branch`. Bila graph terputus, tampilkan
titik putusnya; jangan mengestimasi line atau impedansi yang hilang.

### Batas fungsi proteksi

Register memuat **seluruh 17 sheet**. Tetapi tidak semua fungsi masuk mesin koordinasi:

| `coordination_class` | Fungsi | Masuk mesin koordinasi |
|---|---|---|
| `GRADED` | OCR, GFR, DIST | Ya — nilainya bergantung perangkat hulu/hilir |
| `UNIT` | DIFF trafo, LCD/DIFF Pilot, BUSPRO, diff kapasitor | Tidak — zona sudah tertutup oleh definisi |
| `AUXILIARY` | AR, CBF, SYNCHRO, CCP, SZP | Tidak — logika dan waktu, bukan grading |

### Batas tegangan — keras, tidak dapat dinegosiasikan

Koordinasi transmisi berhenti di **incoming trafo**. Sisi 20 kV milik stream distribusi (UP3) dan **tidak akan pernah** masuk scope PLMS.

Verifikasi pada data: sheet OCR memuat 579 penyebutan 150 kV berbanding 6 untuk TM; DV 2.628 berbanding 0. Data memang berhenti di 150 kV.

Mata rantai grading di bawah incoming trafo diberi `chain_status = 'incomplete_external'` dan ditampilkan sebagai rantai yang putus — jangan diisi, jangan diestimasi, jangan disembunyikan. Menampilkan letak putusnya adalah fitur, bukan kekurangan.

**Sembilan GI tidak ditemukan di DIgSILENT** — ALAM SUTERA, DADAP, GAJAH TUNGGAL, ITS, LONTAR, METLAND, MILENIUM, SINDANG JAYA, ULUJAMI. Sebagian GI pelanggan yang mungkin memang tidak dimodelkan; Lontar, Ulujami, Dadap, Sindang Jaya kemungkinan karena model DIgSILENT bertanggal Maret 2021 sudah tertinggal. Semuanya tetap masuk sistem dengan flag.

## Sumber data dan otoritasnya

| Sumber | Otoritatif untuk |
|---|---|
| `Data_Setting_Penghantar_UPT_DKSBI.xlsx` | daftar GI, bay, rele, setting terpasang — **penentu scope** |
| `Aplikasi_Crosscheck_Setting_Relay_Digsilent.xlsx` | topologi, impedansi, arus hubung singkat — **pelengkap** |
| `List_Official_Setting_Resetting_UPT_Durikosambi.xlsx` | riwayat setting resmi dan tanggal berlaku |
| SLD (v4) | **tidak otoritatif untuk apa pun** — hanya validasi visual |

## Peta kolom terverifikasi

### DIgSILENT sheet `DB` — header baris 2, data mulai baris 4

Topologi (index 0-based):

| idx | Kolom |
|---|---|
| 19 | Name |
| 22 | Type — memuat teknologi, kV, konduktor, rating dalam satu string |
| 23 | Terminal i Substation |
| 24 | Terminal i (bay) |
| 25 | Terminal j Substation |
| 26 | Terminal j (bay) |
| 31 | Out of Service |

Parameter kelistrikan — **1.526 baris terisi**, ini fondasi perhitungan setting:

| idx | Kolom | Satuan |
|---|---|---|
| 31 | Thermal Rating | — |
| 32 | Length | km |
| 36 | Type of Phase Conductor | — |
| 37 | Type of Earth Conductor | — |
| 40 | Earth Resistivity | Ohm·m |
| 42 | Irated | kA |
| 43 | Z1 | Ohm |
| 44 | phiz1 | deg |
| 45 | R1 | Ohm |
| 46 | X1 | Ohm |
| 47 | R0 | Ohm |
| 48 | X0 | Ohm |
| 49 | Ice | A |
| 50 | k0 | — |
| 51 | phik0 | deg |

Nilai R/X di sini adalah **total per penghantar dalam ohm**, bukan per km. Untuk mendapat ohm/km, bagi dengan `Length`. Simpan keduanya.

`k0` adalah faktor kompensasi residual — wajib untuk jangkauan gangguan tanah pada rele jarak. Jangan diabaikan.

### DIgSILENT sheet `IHS` — header berlapis, data mulai baris 6

| idx | Kolom |
|---|---|
| 5 | Bus |
| 6 | GI/GITET |
| 7 | APB |
| 8 | Tegangan kV |
| 9–15 | R1, X1, R2, X2, R0, X0 (pu) |
| 16–19 | Isc 1ph dan 3ph (kA) |
| 23+ | R1, X1, R2 (Ohm) dan Z base |

1.122 baris terbaca.

### Dokumen UPT — 17 sheet, satu per fungsi proteksi

`LCD+DIST`, `OCR`, `OCR KOPEL`, `DIFF Pilot`, `DV`, `BUSPRO`, `AR`, `CBF`, `Synchro`, `CCP`, `SZP`, `KAPASITOR`, `FR_OCR`, `CBF&CCP`, `Rekap`, `Rekap1`, `Pivot Table 1`.

Header berlapis, umumnya baris 4–6, data mulai baris 7. Pola kolom: `GI/GIS | BAY | ULTG | GI/GIS (lawan) | BAY | SIRKIT | rasio CT | rasio PT | merk | type | no seri | fungsi`.

Nama GI berbentuk `TRS-3413-062.062 - GI 150KV DURIKOSAMBI`. Prefix `TRS-xxxx-nnn.nnn` adalah kode aset, pisahkan.

## Jebakan data — tangani eksplisit, ada test-nya

**1. Nama bay jadi tanggal.** Bay `I`, `II`, `I-5` sebagian terbaca sebagai datetime (contoh `2021-01-05`). Deteksi tipe datetime pada kolom terminal, pulihkan ke string.

**2. Akhiran angka = level tegangan. Diturunkan empiris dari 1.122 baris IHS:**

| Akhiran | Tegangan | Konsistensi |
|---|---|---|
| `4` | 70 kV | 100% (133 kasus) |
| `5` | 150 kV | 99,7% (394 kasus) |
| `7` | 500 kV | 100% (70 kasus) |

**Angka lain BUKAN kode tegangan.** `BEKASI 2`, `BINTARO2`, `TUBAN3`, `PLTU Banten 2` semuanya 150 kV — digitnya bagian dari nama. Hanya potong `4`, `5`, `7`.

**Mayoritas GI tanpa akhiran sama sekali** (478 di 150 kV, 22 di 70 kV, 6 di 500 kV). Ketiadaan akhiran **tidak boleh** diartikan 150 kV secara default — ambil tegangan dari kolom kV di IHS, jangan menebak.

Konvensi sama berlaku pada nama bus: `B-7` = bus B 500 kV, `I-5` = bus I 150 kV.

Akhiran `9` tidak ada sama sekali di dataset ini (594 GI unik). Jangan masukkan ke parser tanpa bukti.

**3. Nama GI beda antar sumber.** DIgSILENT pakai singkatan (`DKSBI`, `CNKRG`, `CKRG2`, `KBNGN5`, `M. KARANG LAMA`), dokumen UPT pakai nama panjang. **Wajib tabel alias yang dikurasi manual.** Dilarang fuzzy match diam-diam.

**4. False positive substring.** `KOSAMBI BARU` bukan UPT Durikosambi — itu GI area Indramayu/Dawuan. `TANGERANG` berbeda dari `TANGERANG BARU`. `TELUKJAMBE` bukan `TELUK NAGA`. Pencocokan hanya lewat tabel alias.

**5. Penghantar lintas UPT itu benar.** Dari 127 penghantar seed, 37 punya satu ujung di luar scope. Pertahankan dengan flag `is_boundary` — koordinasi setting justru terjadi di perbatasan.

## Model data

```sql
-- Lokasi fisik. Satu GI bisa punya beberapa level tegangan.
site (
  site_id PK, site_name, site_code,
  latitude, longitude, is_gis
)

-- Site x level tegangan. INI yang jadi node graph, bukan site.
substation (
  ss_id PK, site_id FK, voltage_kv,
  name_digsilent, ultg, upt, unit_induk,
  valid_from, valid_to,
  in_scope, hop_distance, topology_source
)

ss_alias (
  alias_id PK, ss_id FK, alias_text, source_system, is_curated
)

line (
  line_id PK, line_name, line_name_digsilent,
  ss_from FK, bay_from, ss_to FK, bay_to,
  circuit_no, technology, voltage_kv,
  conductor_type, conductor_earth, rating_a,
  out_of_service, is_boundary, source
)

-- Dipisah dari line: parameter berubah saat rekonduktoring,
-- sementara identitas penghantar tetap.
line_electrical (
  line_id FK, length_km,
  z1_ohm, phiz1_deg, r1_ohm, x1_ohm, r0_ohm, x0_ohm,
  r1_ohm_km, x1_ohm_km, r0_ohm_km, x0_ohm_km,
  k0, phik0_deg, irated_ka, ice_a, earth_resistivity,
  model_version, model_date, source
)

bus_sc (
  bus_id PK, ss_id FK, bus_name, voltage_kv,
  r1_pu, x1_pu, r2_pu, x2_pu, r0_pu, x0_pu,
  r1_ohm, x1_ohm, z_base,
  isc_1ph_ka, isc_3ph_ka, model_version, source
)

relay (
  relay_id PK, ss_id FK, bay, line_id FK NULL,
  manufacturer, model, serial_no,
  ct_ratio, pt_ratio, status,
  pst_asset_id NULL     -- rujukan register aset PLN, diisi bila tersedia
)

-- Satu IED fisik dapat muncul di beberapa sheet/fungsi (terbukti pada profil
-- v2a: antara lain LCD, DIST, dan AR dengan nomor seri yang sama). Karena itu
-- fungsi tidak menjadi bagian identity key dan tidak disimpan sebagai satu
-- kolom tunggal di `relay`.
relay_function (
  relay_function_id PK, relay_id FK,
  function_type,        -- DIST, LCD, OCR_GFR, DIFF_PILOT, BUSPRO, dst.
  coordination_class,   -- GRADED | UNIT | AUXILIARY
  source_logical, status,
  UNIQUE (relay_id, function_type, source_logical)
)

-- Rantai grading vertikal. TERPISAH dari `line` karena arahnya menembus
-- level tegangan di dalam satu GI, bukan antar-GI.
protection_chain (
  chain_id PK, chain_type,      -- OCR_GRADING | GFR_GRADING
  relay_function_id FK, upstream_relay_function_id FK,
  level_order, voltage_kv,
  chain_status                  -- complete | incomplete_external
)

relay_setting (
  setting_id PK, relay_id FK, relay_function_id FK,
  parameter_name, parameter_value, unit,
  setting_group, effective_date, source_doc, is_current,
  topology_version NULL,   -- versi model yang jadi dasar hitung
  source_event_id NULL     -- rujukan Power Inspect
)

scope_definition (
  scope_id PK, scope_name, seed_substations,
  hop_depth, snapshot_date, notes
)
```

Catatan desain:

- `site` dan `substation` dipisah karena satu GI fisik bisa muncul sebagai `KEMBANGAN` dan `KEMBANGAN5`. Graph menempel ke `substation`, bukan `site`. Tanpa pemisahan ini GI dua tegangan menjadi satu simpul dan graph salah sambung.
- `relay_setting` sengaja key-value panjang. Parameter proteksi terlalu beragam antar fungsi dan merk untuk skema lebar.
- `pst_asset_id`, `topology_version`, `source_event_id` nullable dan **tidak diintegrasikan sekarang**. Disediakan agar migrasi nanti tidak besar. Jangan bangun integrasi apa pun ke PST, Power Inspect, atau NMM di tahap ini.
- `line_electrical` menyimpan `model_version` supaya setting yang dihitung di atas topologi lama bisa ditandai otomatis ketika model diperbarui.

## Status implementasi dan tahap yang dikerjakan sekarang

### v0 — ETL dan profiling

1. Parser untuk ketiga workbook. Laporan profiling: jumlah baris, kelengkapan per kolom, nilai unik kategorikal, dan setiap anomali dari daftar jebakan di atas.
2. Tabel alias GI dikurasi untuk 44 GI seed dan seluruh ujung lawannya, keluarkan sebagai CSV untuk saya periksa manual **sebelum** loader ditulis.
3. Laporan cakupan: berapa penghantar in-scope, berapa punya setting, berapa punya parameter kelistrikan, berapa tanpa keduanya.

**Gerbang:** jangan lanjut ke v1 sebelum saya menyetujui tabel alias.

### v1 — data layer dan satu layar

1. Migrasi SQL untuk skema di atas.
2. Loader idempoten dengan validasi referensial.
3. **Satu layar:** daftar penghantar in-scope → pilih satu → tampil kedua ujung, bay, rele terpasang, setting terkini, parameter kelistrikan, dan tetangga satu hop.
4. Tanpa autentikasi, case, approval, audit.

**Kriteria penerimaan v1:**

- 113 penghantar seed DIgSILENT dan 148 penghantar +1 hop terbaca; setelah 4
  penghantar manual UPT, daftar sistem masing-masing 117 dan 152
- 44 GI seed masuk; 13 GI tanpa node DIgSILENT tetap ada dengan
  `topology_source IS NULL`
- Tidak ada bay tampil sebagai tanggal
- Tidak ada `KOSAMBI BARU` atau `TELUKJAMBE` sebagai node in-scope;
  `TANGERANG` dan `TANGERANG BARU` tetap dua seed berbeda, bukan alias silang
- Satu klik dari halaman depan ke section setting; v1 menampilkan empty state
  eksplisit, dan layar menampilkan setting terkini bila `relay_setting` tersedia
- Query tetangga satu hop tanpa hardcode
- `r1_ohm_km` hasil hitung konsisten dengan `r1_ohm / length_km` untuk seluruh baris

**Status:** selesai dan sudah dipakai langsung oleh pemilik data. Pemakaian
pertama memvalidasi daftar/detail nyata dan menghasilkan kebutuhan desain
calculation context Z3/reverse di atas. Gerbang v1 → v2 terpenuhi.

### v2 — register rele, setting lengkap, dan riwayat resmi

#### v2a — profiling dan identity candidates (read-only)

1. Profilkan seluruh 22 tab workbook UPT dan petakan 17 fungsi/logical source
   yang ditetapkan prompt; tab helper tetap dilaporkan dan tidak dibuang diam-diam.
2. Bentuk kandidat identitas IED fisik secara deterministik. Fungsi **bukan**
   bagian identity key karena satu IED dapat menjalankan/muncul pada beberapa
   fungsi. Prioritas key: nomor seri exact; fallback exact GI + bay + sirkit +
   merk + type + peran rele. Jangan melakukan fuzzy match.
3. Profilkan 7 tab workbook official sebagai event history atau helper. Belum
   ada write ke database, perubahan UI, atau penentuan `is_current` pada v2a.
4. Konflik exact identity, key ber-confidence rendah, layout wide/grouped, dan
   fungsi yang belum terklasifikasi harus menjadi review queue eksplisit.

**Status v2a (21 Agustus 2026): selesai dikoding dan terverifikasi terhadap
workbook nyata; belum menjadi loader.** Hasil baseline:

- 22/22 tab UPT terprofil dan 17/17 logical source terpetakan
- 7/7 tab official terprofil (`DV` ditandai helper, bukan event history)
- 1.504 kandidat row/device-slot dan 292 event official bermakna
- 199 grup exact identity lintas-sheet; 3 konflik nomor seri vs bay/model masuk review
- 749 baris review eksplisit: 726 identity confidence rendah, 18 klasifikasi,
  3 konflik metadata, dan 2 layout dengan parser khusus
- 18 kandidat `CAP_UNBALANCE`/`UVR_OVR` tetap `REVIEW`, tidak dipaksa ke kelas produksi
- `FR_OCR` (wide form 143 kolom) dan `CBF&CCP` (setting multi-row) ditandai parser khusus v2b
- Artefak: `v2a_profile/report.md` dan CSV profil/candidate/event/review; sumber tidak diubah

#### v2b — loader long-form dan UI

1. Review queue v2a diselesaikan atau dipertahankan sebagai gap eksplisit.
2. Isi `relay`, `relay_function`, dan `relay_setting` long-form dengan provenance minimal:
   workbook, sheet, row, column/header, source hash, dan tanggal observasi.
3. Tetapkan `coordination_class`: `GRADED`, `UNIT`, atau `AUXILIARY` sesuai
   tabel fungsi. Kelas ini adalah klasifikasi; v2 belum menghitung koordinasi.
4. Gabungkan riwayat dari workbook official. Jangan menimpa record lama;
   tentukan `is_current` dari urutan tanggal berlaku dan tandai konflik tanggal.
5. Tampilkan rele, setting terkini, dan riwayat pada layar detail yang sama.

**Status implementasi v2b (21 Agustus 2026): core loader + UI sudah berjalan
terhadap database nyata.** Baseline hasil load atomik:

- 1.580 candidate source termasuk parser khusus `FR_OCR` dan `CBF&CCP`
- 1.394 IED fisik, 1.576 fungsi rele, dan 10.239 nilai setting long-form termuat
- 7.296 nilai current; constraint/test memastikan maksimum satu current per
  `relay_function + parameter_name`
- 66 ruas mempunyai rele exact-linked; 50 ruas mempunyai setting current
- 292 event official dipertahankan dan 115 relasi event-ke-ruas terbentuk exact
- 1.510 review/gap eksplisit; mayoritas identity source tidak lengkap, link bay
  ke ruas belum exact, atau event official belum punya bukti link ruas
- UI detail menampilkan rele multi-fungsi, kelas koordinasi, setting current,
  workbook/sheet/row/column/header, dan riwayat official pada layar yang sama

Event official tidak dipakai untuk menimpa nilai setting workbook. Event yang
belum dapat dikaitkan exact tetap disimpan tanpa `official_event_line` dan masuk
review queue. Penyelesaian 18 klasifikasi `CAP_UNBALANCE`/`UVR_OVR`, 50 konflik
identity metadata lintas layout, dan gap link adalah kurasi data lanjutan—bukan
alasan melakukan fuzzy merge.

**Kriteria penerimaan v2:**

- Seluruh 17 fungsi terpetakan dan seluruh 22 tab terprofil, termasuk tab helper
- Setiap rele in-scope mempunyai setting terkini atau gap eksplisit dengan alasan
- Tidak ada dua rele digabung hanya karena nama mirip
- Setiap nilai setting dapat ditelusuri kembali ke workbook/sheet/baris/kolom
- Riwayat resmi tidak hilang dan hanya satu versi current per rele/parameter/grup
- `coordination_class` terisi untuk setiap fungsi yang dikenali
- Belum ada rumus setting, simulasi reach, approval, case, atau governance

## Cara kerja

- Tanya bila ada ambiguitas struktur, jangan menebak
- Tulis test untuk parsing nama dan pencocokan alias — di situ kesalahan bersembunyi
- Tampilkan profiling sebelum menulis loader
- Jangan menambah fitur yang tidak diminta

> Paste sampai di sini.

---

# BAGIAN B — Roadmap

| Versi | Isi | Selesai bila |
|---|---|---|
| **v0** | ETL, profiling, tabel alias terkurasi | Laporan cakupan diperiksa manual |
| **v1** | Skema inti + satu layar penghantar | Angka cocok; tiga klik; graph jalan |
| **v2** | Setting lengkap 17 sheet + `coordination_class` + riwayat versi resmi | Tiap rele in-scope punya setting terkini dan riwayat |
| **v3a** | Engine koordinasi distance + calculation context forward/reverse berbasis impedansi | Cocok dengan Mathcad untuk ≥10 kasus uji; graph putus tertandai eksplisit |
| **v3b** | OCR/GFR grading dalam batas transmisi — penghantar 150 kV → incoming trafo | Rantai terbentuk; yang putus di bawah incoming tertandai `incomplete_external` |
| **v4** | SLD sebagai validasi visual | Selisih DB vs gambar tertandai otomatis |
| **v5** | Governance domain proteksi: case, revisi, kewenangan/approval sesuai jenis perubahan, notifikasi, dan audit setting | Hanya bila v1–v3 dipakai rutin; satu lifecycle setting teruji di scope PLMS tanpa integrasi enterprise |
| **v6** | Perluasan konteks governance v5: relasi rele ↔ Defence Scheme P2B | Prasyarat: mapping DS ≥80% terisi dan kepemilikan data disepakati; tidak membuat approval engine kedua |
| **v7a** | Perluasan governance v5 lintas UPT–UIT–UIP2B/NMM: federated authority dan kontrak data | Matriks otoritas dan RACI disahkan; lifecycle/status v5 dipakai ulang; ID aset/topologi dapat dicrosswalk; waktu berlaku, bukti, serta skema change-event disepakati |
| **v7b** | Implementasi closed-loop publishing di atas governance v5: kondisi as-built dan setting → model steward/NMM → DIgSILENT serta consumer lain | Pilot perubahan nyata melewati issue/apply–record–notify/coordinate–publish–reconcile sesuai jenis kewenangannya tanpa entry ulang; versi, diff, rollback, dan SLA teruji |
| **v8** | Validasi model otomatis dan perluasan enterprise | Hanya setelah antarmuka NMM terbukti; drift lapangan–model terdeteksi dan ditindaklanjuti terukur |

**Aturan tangga:** jangan naik sebelum tahap sebelumnya benar-benar **dipakai**, bukan sekadar selesai dikoding. Gerbang v1 → v2 sudah terpenuhi melalui pemakaian langsung; syarat pemakaian rutin tetap berlaku sebelum governance v5. Repo lama gagal karena melompat ke v5. Setiap versi mewarisi lifecycle, identitas, provenance, dan audit versi sebelumnya; dilarang membuat jalur approval paralel per integrasi.

### Scope tetap berjenjang

| Tahap | Scope data/organisasi | Yang belum boleh dilakukan |
|---|---|---|
| **v1–v4** | Register +1 hop dan calculation context baca-saja sesuai definisi di atas | Case, approval, atau integrasi enterprise |
| **v5** | Workflow setting domain proteksi pada aset in-scope | Menguasai model jaringan NMM/DIgSILENT atau memperluas register global |
| **v6** | Tambah konteks Defence Scheme untuk rele in-scope | Mengubah approval DS atau model operasi P2B dari PLMS |
| **v7a** | Discovery dan data contract lintas UPT–UIT–UIP2B/NMM, dimulai dari aset in-scope | Connector production dan migrasi massal |
| **v7b** | Pilot closed loop pada subset perubahan nyata yang disepakati | Rollout enterprise atau perluasan scope otomatis |
| **v8** | Scale-out bertahap setelah pilot dan ownership lolos gate | Big-bang replacement sistem sumber |

Management scope tetap `+1 hop`. Kebutuhan calculation context v3, referensi Defence
Scheme v6, dan pembacaan model enterprise v7 tidak otomatis membuat seluruh aset
tersebut masuk register kelolaan. Perluasan wilayah/aset harus menjadi keputusan
scope tersendiri dengan acceptance target baru.

## Arah v7 — perluasan governance v5, bukan governance baru

V5 membangun primitives satu kali: `case`, revision, status transition, authority,
approval bila dipersyaratkan, notification, evidence, dan immutable audit. V6 dan
v7 **memperluas aktor, objek, serta handoff**
di atas primitives yang sama. Tidak ada `NMM approval`, `DS approval`, atau workflow
lain yang berdiri paralel. Bila sistem eksternal memiliki approval resminya sendiri,
PLMS menyimpan reference dan status sinkronisasinya, bukan menduplikasi keputusan.

SSOT bukan berarti satu tabel yang boleh diedit semua pihak.

Masalah yang hendak diselesaikan v7 bukan sekadar "hubungkan PLMS ke NMM". Snapshot
DIgSILENT Maret 2021 yang tertinggal dari dokumen unit menunjukkan adanya **model
drift** dan mata rantai perubahan yang belum tertutup. Pemisahan peran antara unit
pengelola transmisi dan pengelola operasi sistem tetap dipertahankan; yang harus
dibangun adalah kontrak handoff, otoritas per atribut, versi model, dan rekonsiliasi.

PLMS tidak otomatis menjadi master enterprise. Perannya adalah **system of record
domain proteksi** untuk bukti lapangan, setting, provenance, dan usulan delta. NMM
hanya boleh disebut master model jaringan setelah fungsi, owner, dan interface
resminya dikonfirmasi. DIgSILENT diposisikan sebagai consumer/study view dari
baseline model yang telah dipublikasikan, bukan tempat setiap unit menulis langsung.

### Hipotesis matriks otoritas — wajib dikonfirmasi pada discovery v7a

| Domain data | Otoritas yang diusulkan | Peran PLMS |
|---|---|---|
| Kondisi fisik/as-built: konduktor, bay, CT/PT, IED, serial, firmware, hasil commissioning | UPT/ULTG sebagai penghasil dan pemilik bukti lapangan; validasi induk sesuai kewenangan | Register bukti, histori, dan delta |
| Setting awal/baseline dan perhitungan pertama | UIT/induk fungsi proteksi sebagai issuer utama | Simpan paket perhitungan, penerbit, versi, dan waktu berlaku |
| Modifikasi setting karena kebutuhan lapangan | UPT/ULTG berwenang mengubah sesuai kebutuhan lapangan dan batas SOP yang berlaku | Rekam alasan teknis, pelaksana, bukti, waktu efektif, serta status notifikasi/rekonsiliasi; jangan otomatis klasifikasikan sebagai deviasi |
| Setting terpasang/as-left | UPT/ULTG | Rekam pembacaan aktual dan bandingkan dengan setting efektif terakhir, sambil tetap menampilkan baseline UIT |
| Koordinasi lintas batas, kriteria operasi, Defence Scheme, dan dampak ke sistem | UIP2B/P2B | Menyediakan konteks serta status persetujuan; bukan menggantikannya |
| Baseline model jaringan operasional dan publikasi ke consumer | Model steward/NMM — **belum boleh diasumsikan; konfirmasi v7a** | Ajukan delta dan rekonsiliasi hasil publish |
| Model studi DIgSILENT | Turunan berversi dari baseline yang disahkan, ditambah study case | Tautkan setiap hasil/setting ke `model_version` |

SSOT di sini bersifat **federated authoritative model**: satu identitas kanonik dan
satu nilai efektif yang dapat ditemukan untuk setiap atribut, tetapi pembuat,
validator, dan pemberi persetujuan dapat berbeda. Setiap nilai wajib memiliki
`source`, `owner`, `status`, `recorded_at`, `valid_from`, `valid_to`, bukti, dan
riwayat koreksi. Data rencana tidak boleh menimpa kondisi aktual; minimal pisahkan
state `planned`, `issued_initial`, `modified_in_field`, `effective`, `as_built`,
`operational`, dan `superseded`. Status otorisasi perubahan dan status sinkronisasi
ke UIT/NMM adalah dua hal berbeda; setting dapat sah berlaku di lapangan tetapi
belum direkonsiliasi ke consumer data.

### Closed loop perubahan yang dituju

```text
perencanaan/desain
  → model dan perhitungan setting usulan
  → UIT menerbitkan setting awal/baseline
  → commissioning dan pencatatan as-left oleh UPT
  → bila diperlukan di lapangan, UPT memodifikasi setting sesuai kewenangannya
  → catat alasan, bukti, pelaksana, dan waktu efektif perubahan UPT
  → notifikasi/rekonsiliasi ke UIT dan koordinasi UIP2B bila dipersyaratkan/berdampak sistem
  → pemeriksaan baseline UIT vs setting efektif vs nilai installed/as-left
  → publish baseline model oleh model steward/NMM
  → ekspor berversi ke DIgSILENT/EMS/consumer
  → rekonsiliasi dan penutupan change-event
```

Kewenangan UPT memodifikasi setting pada perangkat **tidak sama** dengan kewenangan
menulis langsung ke production network model. UPT dapat menerapkan perubahan setting
sesuai kebutuhan lapangan, lalu mengirim change-event dan bukti agar setting efektif,
dokumen UIT, serta model consumer tetap terekonsiliasi. Approval retrospektif tidak
boleh diwajibkan oleh aplikasi kecuali SOP memang mewajibkannya; yang selalu wajib
adalah provenance, waktu efektif, dan status notifikasi/rekonsiliasi. Model steward
tetap mempublikasikan baseline model baru. Target waktunya ditetapkan sebagai SLA
organisasi pada v7a, bukan di-hardcode oleh aplikasi.

### Landasan arah — bukan pengganti SOP internal

- [Permen ESDM 20/2020 tentang Grid Code](https://jdih.esdm.go.id/dokumen/view?id=2120)
  membedakan pengelola transmisi dan pengelola operasi sistem serta menetapkan
  kebutuhan pelaporan, evaluasi, dan koordinasi ketika peralatan atau konfigurasi
  transmisi berubah. Jadi separation of duties tetap dipertahankan.
- [PLN Sulawesi Control Center of the Future Road Map](https://globalpst.org/wp-content/uploads/Sulawesi-Control-Center-of-the-Future-Road-Map_02.27_clean.pdf)
  merekomendasikan inventaris parameter beserta data owner, governance model,
  authoritative single-base model, IEC CIM/unique ID, serta validasi berkala untuk
  mencegah model divergence. Ini arah arsitektur, bukan bukti bahwa fungsi NMM di
  Jawa-Bali saat ini sudah persis demikian.
- Dokumen publik yang diperiksa belum cukup untuk menetapkan kepanjangan, scope,
  owner, atau interface NMM di proses internal ini. Semua klaim NMM tetap hipotesis
  sampai discovery v7a dan SOP/keputusan internal tersedia.

### Gerbang discovery sebelum integrasi NMM

Sebelum membuat connector atau menambah tabel integrasi, jawab dan dokumentasikan:

1. NMM sebenarnya menguasai apa: registry aset, model konektivitas, workflow
   perubahan, atau kombinasi? Siapa owner dan model steward-nya?
2. Siapa pemegang master DIgSILENT sekarang, bagaimana cadence pembaruannya, dan
   model mana yang dipakai untuk perencanaan, operasi, serta kajian setting?
3. Bagaimana alur UIT menerbitkan setting awal, sejauh apa batas kewenangan UPT
   memodifikasi setting, dan perubahan mana yang wajib dinotifikasikan,
   direkonsiliasi, atau dikoordinasikan kembali dengan UIT/UIP2B/P2B?
4. Dokumen/event apa yang memicu perubahan: energize, commissioning, uprating,
   reconductoring, penggantian CT/PT/IED, revisi setting, atau koreksi data?
5. Interface yang tersedia apa: API, event, export file, IEC CIM, atau proses
   manual; bagaimana kontrol akses, approval, audit, rollback, dan SLA-nya?

Output v7a bukan connector. Outputnya adalah matriks field-level authority, RACI,
canonical ID crosswalk, pemetaan setiap transisi ke lifecycle v5, aturan waktu
berlaku, data contract, serta pilot scope. Baru v7b mengimplementasikan jalur
publish dan reconciliation sebagai extension workflow v5.

## Kenapa v3 bisa lebih cepat dari perkiraan

Semua bahan perhitungan setting ternyata sudah tersedia di sheet `DB`:

| Kebutuhan | Sumber | Status |
|---|---|---|
| Panjang penghantar | `DB` kol 32 | ada, 1.526 baris |
| R1, X1, R0, X0 penghantar | `DB` kol 45–48 | ada |
| k0 kompensasi residual | `DB` kol 50–51 | ada |
| Impedansi sumber, Isc | `IHS` | ada, 1.122 baris |
| Rating termal | `DB` kol 31, 42 | ada |
| Rasio CT/PT | dokumen UPT | ada |
| Topologi cabang untuk infeed | `line` hasil v1 | ada setelah v1 |

Yang belum ada hanya logika perhitungannya sendiri — dan itu ada di Mathcad milikmu. Sheet `CALCULATION` di file DIgSILENT bahkan sudah memuat konfigurasi cabang L1–L4 untuk model infeed Z3. Pada v3a konfigurasi itu menjadi golden test untuk traversal seluruh cabang remote-bus, reach Z3, dan arah reverse; jangan menyederhanakannya menjadi satu next-line hardcoded.

## Modul dari repo lama yang layak diselamatkan

Hanya modul perhitungan murni, disalin sebagai fungsi lepas tanpa dependensinya:

```
src/lib/impedance-math.ts
src/lib/distance-calculation.ts
src/lib/ocr-calculation.ts
src/lib/corridor-math.ts
src/lib/coordination-checks.ts
```

Sisanya — 11 view, wizard, case, governance — biarkan. Godaan terbesar dalam rebuild adalah membawa kembali kode lama karena "sayang sudah ada".
