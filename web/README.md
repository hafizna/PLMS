# PLMS v1 — satu layar

Daftar penghantar in-scope → detail (dua ujung, bay, rele, setting,
parameter kelistrikan, tetangga satu hop). Baca-saja, tanpa autentikasi.

## Jalankan

Jalankan dari root repo. Pipeline memakai tiga workbook yang sudah ada di
repo dan tabel alias yang sudah dikurasi:

```bash
python plms_etl.py . etl_out
python load.py etl_out alias_review.csv plms.db
```

Loader membangun file sementara, menjalankan integrity/FK check, lalu mengganti
`plms.db` secara atomik. Database lama tidak hilang bila rebuild gagal.

Lalu jalankan web:

```bash
cd web
npm ci
npm start
```

Buka `http://localhost:3000`. Override lokasi DB/port lewat env var
`PLMS_DB` / `PORT`.

## Test

Dari root repo:

```bash
python -m pytest -q
npm test --prefix web
```

## Status data yang ditampilkan

- Daftar depan adalah scope topologis +1 hop, termasuk penghantar boundary.
- Topologi, bay, parameter kelistrikan, hubung-singkat (bus_sc): terisi
  dari `plms_etl.py`/`load.py`.
- Rele terpasang dan setting terkini: **selalu kosong di v1** — tabel
  `relay`/`relay_setting` baru diisi mulai v2. Halaman menampilkan ini
  eksplisit ("belum ada data"), bukan menyembunyikan section-nya.
- Bay berawalan `?` = ditandai `fix_bay()` (Excel salah baca sbg
  tanggal) — tampil dengan peringatan, perlu koreksi manual.
- `kV tdk diketahui` = `voltage_kv` NULL di sumber (mayoritas GI tanpa
  akhiran tegangan) — bukan ditebak 150kV secara default.
- `topology_source: NULL` pada satu ujung = GI itu tidak ada di model
  DIgSILENT (lihat `legacy-knowledge/TOPOLOGI_GI_TANPA_DIGSILENT.md`).
