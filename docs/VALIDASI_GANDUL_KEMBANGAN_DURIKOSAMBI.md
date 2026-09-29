# Validasi Gandul - Kembangan - Durikosambi 500 kV

Tanggal review: 29 September 2026. Status: inferensi topologi, belum
menetapkan pasangan nomor sirkit atau mengubah status operasi database.

## Bukti dan batas inferensi

SLD Durikosambi 2022 menampilkan bay KEMBANGAN 2 dan GANDUL tanpa nomor.
SLD Kembangan 2022 memberi label **TIDAK OPERASI pada GANDUL 2 dan
DURIKOSAMBI 1**. Klaim sebelumnya bahwa GANDUL 2 aktif dikoreksi.
Keberadaan setting dalam workbook tidak menetapkan status operasi aktual.
Nilai nol pada SET_RELAY juga tidak sendirinya membuktikan rele dinonaktifkan;
TAP_SET tidak dapat diberi tanggal historis tanpa bukti tambahan.

Workbook `GANDUL-DURKOS` menggabungkan segmen DKSBI-KMBGN1 (3.950 km)
dan GNDUL-KMBGN-1 (30.143 km). Nilai gabungan:

- Panjang 34.093 km.
- R1 = 0.091008 + 0.7565893 = 0.8475973 ohm primer.
- X1 = 1.096994 + 8.464155 = 9.561149 ohm primer.
- 80% X dengan CT/PT = 4000/(500000/100) = 0.8 menghasilkan
  6.119135 ohm sekunder; setting tercatat sekitar 6.14 ohm.

Ini mendukung hipotesis jalur proteksi yang mencakup dua segmen.
Namun kedua sirkit paralel mempunyai impedansi model sama, sehingga
kecocokan angka **tidak memilih sirkit fisik**. Jangan menetapkan pasangan
323+359 atau menyatakan sirkit 2 tetap dua-terminal berdasarkan angka saja.
Label bay SLD, penomoran workbook, dan keadaan lapangan harus direkonsiliasi
lebih dahulu. Model belum diubah menjadi sambungan phi final.

## Asumsi impedansi trafo yang dapat dipakai

Workbook memakai input 12.5% pada tujuh sheet perhitungan distance.
`CALCULATION!Y18=12.5`, `Y19=60`, `Y20=150`; rumus F92 adalah
`COMPLEX(0,Y18*Y20^2/Y19/100)`, dipakai dalam batas zona H114/H126.
Ini bukti asumsi template workbook, bukan standar universal PLN atau
impedansi nameplate terukur setiap trafo.

- 60 MVA **per unit**, sisi referensi 150 kV: XT1 = **46.875 ohm**.
  Angka 45 ohm pada versi catatan sebelumnya adalah kesalahan hitung.
- 500 MVA, sisi referensi 500 kV: XT1 = **62.5 ohm**.
- R trafo diabaikan sesuai rumus workbook. Jumlah unit bank tidak otomatis
  dijumlahkan sebagai basis MVA; konfigurasi operasi perlu bukti terpisah.

Implementasi hanya mengaktifkan asumsi untuk identitas GI/tegangan dengan
nameplate SLD yang sudah ditinjau, dan memberi status
`complete_assumed_transformer`. Kecocokan reach ketika cap trafo tidak
terpakai tidak membuktikan XT1 benar.

## Error formula dan versi sumber

Pada L1 di GANDUL-DURKOS, slot segmen C kosong memicu VLOOKUP #N/A dan
menular ke total. Segmen A/B tetap berisi data. Temuan ini spesifik pada
slot tersebut; #N/A lainnya tetap harus diperiksa per formula, bukan
semuanya diganti nol. Workbook sumber tidak diubah.

Salinan workbook DIgSILENT dan official history di Downloads identik
dengan repo saat diperiksa. Workbook setting UPT berbeda: Downloads
memakai sheet LCD+DIST, repo memakai DIST. Rebuild memakai versi repo;
keduanya tidak dicampur diam-diam.

## Keputusan berikutnya

Konfirmasi pasangan fisik bay/segmen beserta tanggal status operasi melalui
SLD resmi terbaru atau pemilik data. Setelah itu baru modelkan jalur phi,
impedansi turunannya, dan status segmen lama dengan provenance eksplisit.
MKBRU tetap ditunda sesuai arahan pemilik data.

## Sidik sumber

SHA256:

| Sumber | Hash |
|---|---|
| plms.db | c828fd63594905fe033e518b02757d99960539a44f23e97680c28a1dd98d501c |
| Workbook DIgSILENT | 46061b0726c6a13c7cce9eb2b678101bb9c65c19f7b11c88686916d0e5174465 |
| Workbook setting UPT | f0ba5b0036e47fb050940334d394bb217cdf81dcbdeea63e562db5b25048167c |
| SLD GITET 500kV Durikosambi | 275e4afce5b5f2421730955e6aab481c768087015b0f5b06bf0cbb5f2e6be047 |
| SLD GITET 500kV Kembangan | 2a1ddb3decc42f2eb92ba63240f0a49745e7090b4ea5941649b4f0bb2d2108ec |
