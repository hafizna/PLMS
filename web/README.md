# PLMS v1 — satu layar

Daftar penghantar in-scope → detail (dua ujung, bay, rele, setting,
parameter kelistrikan, tetangga satu hop). Baca-saja, tanpa autentikasi.

## Jalankan

Butuh `plms.db` di root repo (satu tingkat di atas `web/`), dibuat lewat:

```bash
python3 ../plms_etl.py <dir_sumber_xlsx> <dir_out>
python3 ../load.py <dir_out> ../alias_review.csv ../plms.db
```

Lalu:

```bash
npm install
node server.js
```

Buka `http://localhost:3000`. Override lokasi DB/port lewat env var
`PLMS_DB` / `PORT`.

## Status data yang ditampilkan

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
