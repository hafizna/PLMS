# Topologi GI tanpa node DIgSILENT — dikurasi dari dokumen UPT

Dari 44 GI seed, 12 tidak punya node topologi di DIgSILENT (model Maret
2021, lihat `alias_review.csv`; awalnya 13 -- ALAM SUTERA ternyata cuma
variasi ejaan dari node DIgSILENT `ALAM SUTRA`, sudah teratasi via
`MANUAL_ALIAS`, bukan gap topologi). DIgSILENT tidak akan pernah diupdate
untuk GI-GI ini — dokumen UPT DKSBI adalah satu-satunya sumber topologi
mereka. Bagian ini mencatat koneksi bay-ke-bay yang berhasil ditelusuri
manual dari dokumen UPT, sudah dimuat ke `MANUAL_LINES` di `load.py`.

Status per GI (dari 12): **selesai ditelusuri & dimuat** — LONTAR, DADAP,
GROGOL BARU, ITS, JATAKE BARU, METLAND, MILENIUM, PASAR KEMIS BARU,
SINDANG JAYA (BALARAJA satu-arah saja). **Belum ditelusuri** — GAJAH
TUNGGAL, ULUJAMI, SEPATAN BARU (tidak py bay `PHT%` sama sekali, cuma
disebut sbg GI lawan).

Metode: cocokkan kode aset (`TRS-xxxx-nnn.nnn`) antar baris GI, lalu
verifikasi kedua ujung saling menyebut nama bay satu sama lain.

## LONTAR (GIS 150kV, kode aset TRS-3413-144.144)

Tidak ada di DIgSILENT sama sekali. Dua bay penghantar ditemukan di
register UPT, keduanya bay-to-bay dua arah terverifikasi:

- **LONTAR ↔ TELUK NAGA** — `GIS 150kV LONTAR` punya bay `PHT 150kV TELUK
  NAGA #1/#2`; sisi lain, `GI 150kV TELUK NAGA` (TRS-3413-050.050) punya
  bay `PHT 150kV LONTAR #1/#2`.
- **LONTAR ↔ TANGERANG BARU** — `GIS 150kV LONTAR` punya bay `PHT 150kV
  TANGERANG BARU #1/#2`; sisi lain, `GI 150kV TANGERANG BARU`
  (TRS-3413-061.061) punya bay `PHT 150kV LONTAR #1/#2`.

`TELUK NAGA` dan `TANGERANG BARU` keduanya sudah exact-match ke DIgSILENT
(lihat `alias_review.csv`), jadi Lontar bisa disambung ke graph topologi
lewat kedua tetangga ini begitu `line` dibangun dari sumber UPT.

## DADAP (GI 150kV)

Tidak ada di DIgSILENT sama sekali. Dikonfirmasi pemilik data: nama lama
Dadap adalah **"Teluk Naga II"** — sebagian file UPT masih pakai nama lama
ini (`Tap Setting Teluk Naga - Dadap 1&2.pdf`), bukan dua GI berbeda.

- **DADAP ↔ TELUK NAGA** — file `Dadap - Teluk Naga 1_2.pdf` /
  `Teluk Naga - Dadap 1&2.pdf` (bay `PHT 150kV DADAP #1/#2` disebut di
  register, tapi Dadap sendiri tidak punya baris GI dengan daftar bay
  lengkap di sheet yang dicek).
- **DADAP ↔ LONTAR** — file `Dadap - Lontar 1_2.pdf` /
  `LONTAR-DADAP 1_2.pdf`.

## Ringkasan graph tambahan (di luar DIgSILENT)

```
LONTAR ↔ TELUK NAGA
LONTAR ↔ TANGERANG BARU
DADAP  ↔ TELUK NAGA
DADAP  ↔ LONTAR
```

TELUK NAGA dan TANGERANG BARU adalah titik masuk graph existing (exact
match DIgSILENT); LONTAR dan DADAP menempel lewat keduanya meski
`topology_source` mereka sendiri `NULL`.

## Catatan penamaan historis

| Nama lama (di sebagian file UPT) | Nama saat ini |
| --- | --- |
| Teluk Naga II | Dadap |

Kemungkinan ada penamaan historis serupa untuk GAJAH TUNGGAL, ULUJAMI,
SEPATAN BARU — belum ditelusuri.

## Sisipan & ekstensi GI pasca-2021 (selain Lontar/Dadap)

Pola dikonfirmasi pemilik data: setting UPT (~2025) mencatat puluhan GI
baru vs DIgSILENT (Maret 2021) -- baik **sisipan** (GI baru memotong
penghantar eksisting jadi 2 segmen, mis. Daan Mogot di Durikosambi-PIK --
sudah termodelkan DIgSILENT) maupun **ekstensi** (GI/cabang baru yang
sebelumnya tak terhubung sama sekali). Metode verifikasi: GI tanpa
topology_source yang bay-nya menyebut 2 lawan dua-arah (X→A dan X→B, A
dan B sama-sama menyebut balik X).

**Sisipan nyata** (DIgSILENT masih punya line langsung A↔B yang disisipi):
- METLAND antara KEMBANGAN↔CILEDUG (line 481/482 `KBNGN-CLDUG` masih ada)
- PASAR KEMIS BARU antara PASAR KEMIS↔SEPATAN (line 818/819
  `PSMIS-SPTAN` masih ada)

**Ekstensi/cabang baru** (tidak ada line langsung A↔B untuk disisipi):
- GROGOL BARU (Durikosambi↔Grogol)
- ITS (Cengkareng Baru↔Tangerang Baru)
- JATAKE BARU (Jatake↔Tangerang)
- MILENIUM (Citra Habitat↔Spinmill)
- SINDANG JAYA (Lontar↔Suvarna Sutera dua-arah; ↔Balaraja satu arah saja,
  butuh verifikasi tambahan)

Semua sudah dimuat ke `MANUAL_LINES` (`load.py`). Dampak: relay ter-link
ke `line_id` naik dari 33% → 51% (465→715 dari 1394 total).

## Gap 500kV (GITET/GISTET) — jaringan 500kV sendiri, bukan "site lain"

Klarifikasi penting dari pemilik data: setiap GITET/GISTET punya
**penghantar 500kV sendiri yang solid** (nyata secara fisik, bukan gap
data) menghubungkan GITET-GITET lain di jaringan 500kV — jaringan ini
sebagian besar **belum termodelkan di DIgSILENT** (model Maret 2021)
karena banyak dibangun setelahnya. Variasi penulisan nama yang mirip
(`MUARAKARANG BARU` / `GIS MUARAKARANG BARU` / `GISTET MUARAKARANG`)
merujuk **satu entitas fisik yang sama**, bukan site/GI berbeda.

`DURIKOSAMBI` (`DKSBI7`) dan `KEMBANGAN` (`KEMBANGAN7`) sudah termodelkan
(line `DKSBI-KMBGN1/2` ada di DIgSILENT). Rantai 500kV lain yang bay
rele-nya menyebutnya tapi **tidak ada line-nya** di DIgSILENT:

- **`GITET MUARAKARANG` ↔ `DKSBI7`** — 16 rele orphan di M. Karang Baru
  (`PHT 500kV DURIKOSAMBI#1/#2`). Dikonfirmasi via spreadsheet helper
  scanning resmi (`[500kV] MUARAKARANG - DURIKOSAMBI`, ULTG Angke, UPT
  Durikosambi, tanggal 15 Okt 2025): rantai L1 = Muarakarang→Durikosambi,
  L2 = Durikosambi→Gandul. Jadi `DKSBI7↔GANDUL7` (500kV) JUGA nyata,
  meski `GANDUL7` sudah ada di DIgSILENT — line spesifik ke arah
  Muarakarang/Gandul inilah yang belum termodelkan, bukan node-nya.
- **`GITET MUARAKARANG` ↔ `TANJUNG PRIOK` (500kV)** — 16 rele orphan
  (`PHT 500kV TANJUNG PRIOK#1/#2`). Node `TANJUNG PRIOK` 500kV tidak ada
  di DIgSILENT sama sekali (yang ada: `NEW PRIOK`, `PRIOK BARAT`,
  `PRIOK TIMUR5` — semua 150kV, tidak jelas mana yang berelasi).
- **`GITET BALARAJA` ↔ `SURALAYA`/`LENGKONG`/`KEMBANGAN`/`JAWA 7`** — bay
  `PHT 500kV BALARAJA (FUTURE)` menandakan sebagian trafo belum operasi
  saat data direkam (kode aset TRS-3413-008.008).

`DURIKOSAMBI` sendiri **sudah** punya node 500kV di DIgSILENT, hanya
disingkat `DKSBI7` (bukan `DURIKOSAMBI7`) sehingga tak ketemu otomatis —
sudah ditambahkan sebagai alias manual di `plms_etl.py` (`MANUAL_ALIAS`)
dan `OPPONENT_ALIAS_BY_VOLTAGE` di `load.py` (scoped ke bay 500kV saja).

## Arah v3: helper sheet kalkulasi grading per penghantar

`Data Setting Penghantar UPT DKSBI.xlsx`, sheet `MASTER_PHT`, punya dua
kolom (`HELPER SHEET SCANNING KOORDINASI` dan `HELPER SHEET IMPLEMENTASI
SETTING`) berisi **link Google Sheets terpisah per baris penghantar** —
bukan satu file besar, satu spreadsheet per penghantar. Contoh:
`[500kV] MUARAKARANG - DURIKOSAMBI` — judul `DISTANCE COORDINATION
SCANNING`, isi: metadata GI/bay/ULTG/UPT/jenis rele/merk, rantai GI A→B→C
(L1, L2 = segmen dgn impedansi terkecil di GI B), tabel `KALKULASI
SCANNING PROTEKSI PENGHANTAR` (baris "ROW IMPEDANSI" per segmen), lalu
input manual `PT/CT Ratio`, `L (km)`, `X/km`, `Xline`, `Zone 1/2/3` per
line.

Ini persis arsitektur yang ditarget v3 (engine koordinasi distance,
lihat roadmap `PLMS_Rebuild_Prompt_v2.md`) — helper sheet ini kemungkinan
jadi referensi/ground-truth untuk memvalidasi hasil engine nanti. Belum
ditarik ke repo (perlu manual per link, di luar 3 sumber otoritatif
v0-v2); dicatat di sini sbg arah, bukan tugas sekarang.
