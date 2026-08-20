# Topologi GI tanpa node DIgSILENT — dikurasi dari dokumen UPT

Dari 44 GI seed, 13 tidak punya node topologi di DIgSILENT (model Maret
2021, lihat `alias_review.csv`). DIgSILENT tidak akan pernah diupdate untuk
GI-GI ini — dokumen UPT DKSBI adalah satu-satunya sumber topologi mereka.
Bagian ini mencatat koneksi bay-ke-bay yang berhasil ditelusuri manual dari
dokumen UPT, supaya v1 (loader tabel `line`) tidak perlu menelusuri ulang.

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

Kemungkinan ada penamaan historis serupa untuk GI lain yang belum
ditelusuri (LONTAR, ALAM SUTERA, GAJAH TUNGGAL, ITS, METLAND, MILENIUM,
SINDANG JAYA, ULUJAMI, GROGOL BARU, JATAKE BARU, PASAR KEMIS BARU, SEPATAN
BARU juga TANPA TOPOLOGI DIgSILENT — belum dicek satu per satu seperti
Lontar/Dadap di atas).

## Gap 500kV (GITET/GISTET) di luar seed 150kV

Dua GI seed punya level tegangan 500kV yang disebut di dokumen UPT tapi
tidak punya node DIgSILENT:

- **GISTET MUARAKARANG** — site 500kV terpisah dari `M. KARANG BARU`/
  `M. KARANG LAMA` (keduanya 150kV). Dokumen SLD terkait bertanggal 2024 —
  lebih baru dari model DIgSILENT (Maret 2021), proyek baru.
- **GITET BALARAJA** — kode aset TRS-3413-008.008, punya bay `PHT 500kV
  BALARAJA (FUTURE) #1/#2` — tampaknya trafo 500kV yang belum beroperasi
  saat data direkam. Kode aset yang sama juga menaungi bay `PHT 500kV
  LENGKONG` dan `PHT 500kV SURALAYA` (GI-GI di luar scope 44 seed, tidak
  ditelusuri lebih jauh).

`DURIKOSAMBI` sendiri **sudah** punya node 500kV di DIgSILENT, hanya
disingkat `DKSBI7` (bukan `DURIKOSAMBI7`) sehingga tak ketemu otomatis —
sudah ditambahkan sebagai alias manual di `plms_etl.py` (`MANUAL_ALIAS`).
