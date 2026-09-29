# Relasi SLD Jakban untuk Zone 2/3

Implementasi 28 September 2026 menambahkan audit relasi lintas sumber ke PLMS.
Sumbernya 11 workbook `samples/ss_*_ingest.xlsx` milik MANTAPS Topology Engine,
termasuk revisi LBK, GUCL, dan PRBC. Workbook asli dibaca tanpa perubahan.

## Menjalankan

Dari root PLMS:

```powershell
python sld_topology_audit.py --sld-root C:\Users\hafizna.fadhli\Downloads\mantaps-topology-engine
npm start --prefix web
```

Buka `/sld-audit`, atau klik **Audit relasi SLD Jakban untuk Z2/Z3** pada
daftar penghantar. Detail penghantar menyediakan tautan yang menyaring rele
pada ruas tersebut. Pilih rele untuk melihat GI asal, GI lawan, path cabang,
data yang belum lengkap, serta workbook/sheet/baris/PoV sumber.

`--sld-root` menerima root repo engine atau direktori `samples`.
`--db` memilih database PLMS; `--out` memilih direktori hasil. Default hasil
adalah `sld_audit/`, yang tidak dimasukkan ke Git. Web membaca
`sld_audit/audit.json`; lokasi dapat diubah melalui `PLMS_SLD_AUDIT`.

Untuk memperbarui hasil kalkulasi dan membuat audit sesudahnya:

```powershell
python calculation_run.py plms.db --sld-root C:\Users\hafizna.fadhli\Downloads\mantaps-topology-engine
```

Perintah audit pertama hanya membaca database. `calculation_run.py` menulis
`calculation_context` dan `calculation_branch`, seperti perilaku CLI sebelumnya.
Rebuild database atau perubahan hasil kalkulasi membuat hash database berbeda;
web meminta audit dibuat ulang sebelum menampilkan ID lama.

## Pemetaan dan review

`gi_crosswalk.csv` menyimpan satu identitas sumber per workbook, kode dan
tegangan. Pencocokan memakai nama/kode tepat serta alias PLMS yang telah
dikurasi. Variasi spasi dan ejaan `M. KARANG` yang sudah dikenal PLMS ditangani;
LAMA, BARU, NEW, II, nomor dan GIS dipertahankan. Tegangan kosong di PLMS hanya
dapat dibantu oleh tegangan ruas insiden yang semuanya sama; asal informasi
tegangan tetap dicatat, tanpa mengubah `substation.voltage_kv`.

Nama historis Jakban hanya membantu baris yang masih berupa kode, pada kode
dan tegangan yang sama. Nama deskriptif pada revisi baru tidak ditimpa.
Kemunculan berupa kode saja di PoV lain dapat memakai pasangan unik kode dan
tegangan dari sumber Jakban yang sudah memiliki nama jelas. Kasus ini diberi
`MATCHED_SHARED_CODE` dan menyimpan referensi kemunculan yang menjadi bukti.
Bus 150 kV berlabel DKSBI pada workbook GITET ditahan sebagai ambigu pada
pencocokan otomatis. Review 29 September 2026 menetapkan kedua kemunculan ini
ke DURIKOSAMBI 150 kV melalui `SLD_DURIKOSAMBI_REVIEW.csv`, berdasarkan konfirmasi
pemilik data dan pemeriksaan visual halaman 1 `SINGLE LINE DKSBI Ver 8 2022 - FIX.pdf`
(gambar bertanggal 29 Agustus 2022). Incomer IBT #1 dan IBT #2 terhubung ke
sistem busbar GI Durikosambi, dengan seksi 1A/2A dan 1B/2B. Ini keputusan identitas
pada tingkat GI, bukan penggabungan semua seksi menjadi satu bus fisik atau
penetapan posisi switching saat ini. DKSBI/DKSBI7 500 kV tetap terpisah.
Hash PDF dan workbook dicatat dalam CSV review. PDF berada di
`SLD Durikosambi/ULTG DURIKOSAMBI/GI DURIKOSAMBI/` pada repo lokal.

Untuk mempertahankan keputusan tersebut pada audit berikutnya:

```powershell
python sld_topology_audit.py --sld-root C:\Users\hafizna.fadhli\Downloads\mantaps-topology-engine --review docs/SLD_DURIKOSAMBI_REVIEW.csv
```

Gunakan juga `--review docs/SLD_DURIKOSAMBI_REVIEW.csv` bila menjalankan
`calculation_run.py` dengan `--sld-root`. Tanpa opsi review, dua kemunculan
tersebut kembali berstatus ambigu. MKBRU belum diputuskan dalam review ini.

`neighbor_suggestions` menunjukkan kandidat berdasarkan tetangga yang telah
terpetakan. Kemiripan graf tidak otomatis menetapkan identitas GI.
`affected_relay_count` membantu mendahulukan identitas yang memengaruhi banyak
konteks rele.

Untuk memasukkan hasil verifikasi:

1. Salin `gi_crosswalk.csv` ke berkas review terpisah.
2. Isi `review_plms_name` dengan `site.site_name` PLMS, `review_voltage_kv`, dan
   `review_note` dengan bukti/alasan pemetaan.
3. Jalankan audit ulang memakai `--review berkas_review.csv`.

Review harus menunjuk tepat satu substation pada tegangan sumber. Hash workbook
harus tetap sama; keputusan lama ditolak bila sumber sudah direvisi. Hasil review
mengubah pemetaan dalam audit, belum mempromosikan ruas ke tabel `line`.

## Arti relasi

| Status | Makna |
|---|---|
| `CORROBORATED_CORRIDOR` | Pasangan ujung dan tegangan juga ada di PLMS; identitas per sirkit masih diperiksa terpisah. |
| `CANDIDATE_NEW_CORRIDOR` | Kedua GI terpetakan tetapi koridor belum ada di PLMS. |
| `UNRESOLVED_IDENTITY` | Satu atau kedua ujung belum memiliki pasangan GI yang cukup jelas. |
| `BOUNDARY_EVIDENCE` | Bay/stub memberi konteks batas gambar, belum dianggap penghantar baru. |
| `NON_LINE_ASSET` | Koneksi yang melibatkan pembangkit/trafo, dikeluarkan dari traversal ruas distance. |

Konflik status operasi, jumlah sirkit, atau nama ruas terhadap kode ujung
dicatat pada `issues`. Nama yang tidak muncul di suatu halaman SLD tidak
dianggap bukti bahwa ruas PLMS salah atau sudah tidak ada.

Beberapa PoV yang menggambar koridor kandidat sama digabung menjadi satu relasi
dengan seluruh bukti sumber. Sirkit paralel PLMS tetap membawa `line_id`
masing-masing. PoV dan Tier adalah konteks gambar; arah traversal berasal dari
GI tempat rele terpasang dan ujung lain protected line.

## Jejak Zone 2/3

`audit.json` memuat konteks seluruh fungsi rele DIST, termasuk yang belum punya
protected line. `zone_branches.csv` memuat cabang langsung untuk Z2, serta cabang
satu dan dua hop setelah GI lawan untuk Z3. Path terus ditelusuri secara
topologis walaupun impedansi segmen belum ada. Data yang hilang diwariskan ke
path lanjutannya. Status tidak aktif, stub, beda tegangan, dan path yang
kembali ke bus yang sudah dilalui ditandai sebagai pengecualian.

Loader kalkulasi diperbaiki agar:

- Jejak Z3 dua hop tetap dibuat ketika XT1 belum tersedia.
- Cabang tanpa `line_electrical` tetap muncul di audit kalkulasi.
- Bila cabang langsung kehilangan impedansi/ujung, Z2 dan Z3 ditahan; bila
  hanya cabang dua hop yang kehilangan data, Z2 masih bisa dievaluasi.
- Ruas yang eksplisit `out_of_service=1` dan path kembali ke GI asal tidak
  menjadi cabang forward.

Audit SLD belum memasok nilai impedansi atau XT1. `rating_mva=500` pada jalur
ingest IBT engine SLD merupakan nilai tetap dalam kode sehingga tidak diimpor
sebagai parameter trafo nyata. Data sirkit, impedansi dan XT1 tetap diperlukan
untuk reach final. Sumber SLD revisi juga belum seluruhnya diverifikasi terhadap
master SLD, sebagaimana dicatat engine dalam `docs/JAKBAN_REVIEWED_IMPORT.md`.

## Verifikasi data nyata

Baseline: 303 kemunculan node pada 11 workbook; 138 terpetakan langsung, 3 melalui
kode Jakban yang sama, 160 belum terpetakan, 2 ambigu. Sebanyak 141 kemunculan
tersebut merujuk 112 substation PLMS unik. Ada 62 observasi sumber yang
mendukung 60 koridor PLMS unik dan 7
observasi kandidat koridor tambahan. Seluruh 184 fungsi DIST memperoleh konteks;
137 memiliki bukti SLD pada cabang yang ditelusuri.

Ketidaksesuaian konkret yang ditemukan: workbook Muarakarang–Durikosambi,
`Jalur_Transmisi` baris 7, memakai kode ujung `ANGKE` tetapi nama ruas menyebut
`Ancol`. Sistem mencatat `ENDPOINT_LABEL_CONFLICT`.

Uji pada salinan database menghasilkan 2.402 jejak cabang (sebelumnya 896),
termasuk 1.582 jejak dua hop. Status hasil tetap Z1: 97 lengkap dan 87 belum
lengkap; Z2/Z3: masing-masing 184 belum lengkap. Database sumber tidak berubah.

```powershell
python -m pytest test_sld_topology_audit.py test_calculation_loader.py test_distance_engine.py -q
npm test --prefix web
```

## Hasil review Durikosambi, 29 September 2026

Dua kemunculan DKSBI 150 kV berubah dari AMBIGUOUS menjadi REVIEWED_MATCH,
menunjuk DURIKOSAMBI (ss_id 154 pada snapshot database ini). Jumlah substation
unik terpetakan naik dari 112 ke 113; koridor PLMS unik yang didukung SLD
naik dari 60 ke 64 (observasi 62 ke 66). Observasi UNRESOLVED_IDENTITY turun
dari 158 ke 153, dan kandidat koridor naik dari 7 ke 8. Sebanyak 160
kemunculan node masih UNRESOLVED. Audit mencakup 184 fungsi DIST.
Database sumber tidak berubah; keputusan ini hanya diterapkan pada audit.
Validasi: 69 tes Python dan 25 tes web lulus.
