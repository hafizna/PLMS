# Data Lineage dan Kurasi Data Relay

Dokumen ini membatasi pekerjaan pada fondasi data sebelum workflow PLMS diperbaiki.
Workbook sumber tetap read-only, setiap koreksi disimpan sebagai keputusan kurasi,
dan PLMS yang sudah ada tetap dipertahankan.

## Cakupan organisasi

Pada struktur lama, UPT Durikosambi mencakup ULTG Tangkot, ULTG Cikupa, dan
ULTG Angke. Ownership saat ini dipetakan sebagai berikut:

| UPT saat ini | ULTG |
| --- | --- |
| UPT Cikupa | ULTG Cikupa, ULTG Tangkot |
| UPT Durikosambi | ULTG Durikosambi, ULTG Citra Raya, ULTG Angke |

Konteks legacy tetap disimpan sebagai provenance dan tidak dipakai untuk
menimpa ownership saat ini.

## Source of truth

1. `Data Setting Penghantar UPT DKSBI (1).xlsx`
   - sumber observasi aset relay dan snapshot setting;
   - 12 sheet operasional dipakai oleh seed;
   - setiap nilai setting mempertahankan sheet, row, column, dan observation ID.
2. `Aplikasi Crosscheck Setting Relay [Digsilent_ 9 Maret 2021, IHS 1-2021].xlsx`
   - sumber referensi saluran DIgSILENT dan legacy calculation;
   - bukan master identitas relay.

## Layer data

| Layer | Makna | Jumlah saat ini | Aturan |
| --- | --- | ---: | --- |
| Source observation | Satu kemunculan relay pada satu row sheet | 771 | Immutable; tidak di-deduplicate |
| Relay asset | Kandidat aset fisik hasil konsolidasi dan kurasi | 557 | Serial dipakai bersama konteks model/instalasi dan keputusan kurasi |
| Installation reference | Konteks station/bay/circuit/breaker position | 771 refs | Selalu menunjuk observation ID |
| Setting snapshot | Tap Setting atau Setting Relay pada row sumber | 1.368 groups | Menunjuk observation ID dan source row |
| Populated setting value | Nilai non-empty hasil baca workbook | 10.177 | Typed value; formula sumber hanya ditandai |
| Parameter comparison | Pasangan Tap Setting vs Setting Relay | 5.328 | Match, mismatch, salah satu kosong, atau keduanya kosong |
| Quality audit | Status konsumsi data | 104 ready / 451 review / 2 blocked | Blocker tidak dipromosikan sebagai canonical identity |

Ownership aset saat ini adalah 69 aset pada UPT Cikupa dan 488 aset pada UPT
Durikosambi.

## Semantik setting

- **Tap Setting** adalah dokumen hasil perhitungan setting terakhir yang
  terdokumentasi. Setting awal/baseline diterbitkan oleh UIT sebagai issuer utama;
  UPT berwenang memodifikasinya sesuai kebutuhan lapangan. Modifikasi UPT menjadi
  engineering reference efektif bila provenance, alasan teknis, pelaksana, bukti,
  dan waktu berlakunya terdokumentasi sesuai proses yang berlaku.
- **Setting Relay** adalah nilai terakhir yang dimasukkan manual berdasarkan
  nilai yang terpasang pada relay. Bulk input per relay belum tersedia.
- Perbedaan numerik tetap dicatat sebagai **mismatch**, tetapi mismatch bukan
  otomatis kesalahan atau perubahan tanpa otorisasi. Pada governance berikutnya,
  klasifikasikan sebagai modifikasi lapangan UPT yang sah, perubahan belum
  diterapkan, referensi yang belum direkonsiliasi, atau deviasi yang perlu ditinjau.
- Nilai kosong selalu berarti **belum diinput**, bukan nol dan bukan default.

Hasil comparison saat ini: 1.729 match, 1.176 mismatch, 62 nilai Setting Relay
belum diinput, 28 nilai Tap Setting belum terdokumentasi, dan 2.333 pasangan
sama-sama belum diinput.

## Semantik fungsi proteksi

Main Protection Unit umumnya menjalankan autoreclose, line current differential,
dan distance. Pada sistem 500 kV atau instalasi lama, autoreclose dapat berada
di luar MPU. Karena itu, kemunculan satu serial pada beberapa function sheet
tidak otomatis berarti duplicate asset.

## Keputusan kurasi identitas

| Serial | Keputusan | Status |
| --- | --- | --- |
| `34724836/02/19` | Dipisah menjadi P545 dan P142 karena model, fungsi, dan bay berbeda | Confirmed; dua aset fisik |
| `197931U` | Digabung lintas fungsi Diff, Distance, dan AR | Confirmed; satu multifunction relay |
| `31830604/07/11` | Digabung lintas fungsi Diff, Distance, dan AR | Confirmed; satu multifunction relay |
| `637080B` | Dipisah per instalasi karena relay lama muncul pada dua GI | Probable; dua aset dengan duplicate manufacturer serial |
| `7.4301E+12` | Fungsi CBF dikonfirmasi, tetapi digit serial asli tidak dapat dipastikan | Blocked; serial format unresolved |
| `7.7281E+12` | Belum ada klarifikasi domain | Blocked; serial format unresolved |

Raw observation tidak pernah dihapus atau ditimpa oleh keputusan di atas.

## Gate sebelum data dipakai workflow PLMS

1. Source observation dapat ditelusuri kembali ke sheet dan row.
2. Setting group menunjuk source observation yang benar.
3. Aset berstatus `blocked` tidak dianggap canonical relay identity.
4. Missing field tidak diisi dengan default atau tebakan.
5. Koreksi identitas menghasilkan revision/audit event; raw observation tidak
   ditimpa.
6. Explorer membedakan `ready`, `needs-review`, dan `blocked`.
