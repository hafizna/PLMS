// Peta folder SLD (PDF sumber asli) -> site_name di plms.db.
//
// HANYA berisi pasangan yang sudah diverifikasi manual satu-satu (folder
// dibaca, dicocokkan ke substation.site_id via query) -- prompt v2: jangan
// menebak identitas. GI yang namanya ambigu (mis. "GI MUARAKARANG" bisa
// berarti M. KARANG LAMA atau entitas lain yang belum jelas) SENGAJA tidak
// dimasukkan di sini; findSldForSite() akan mengembalikan null untuk itu,
// dan UI menampilkan "SLD belum terhubung" alih-alih menebak salah.
//
// root: folder relatif dari root repo tempat file PDF disimpan.
// entries[].siteNames: site_name yang dicakup 1 folder SLD yang sama (bisa
// lebih dari satu -- mis. GROGOL II/GROGOL BARU adalah identitas fisik yang
// sama, lihat docs/VALIDASI_DURIKOSAMBI_GROGOL.md; atau KEMBANGAN yang
// punya 2 SLD terpisah, 150kV dan 500kV, tapi 1 site_name).
'use strict';

const ROOT = 'SLD Durikosambi/ULTG DURIKOSAMBI';

const ENTRIES = [
  { folder: 'GI ANGKE', file: 'SINGLE LINE ANGKE Ver 8.1 2022.pdf', siteNames: ['ANGKE'] },
  { folder: 'GI DADAP', file: 'SINGLE LINE DADAP 2022 - Ver 1.pdf', siteNames: ['DADAP'] },
  { folder: 'GI DURIKOSAMBI', file: 'SINGLE LINE DKSBI Ver 8 2022 - FIX.pdf', siteNames: ['DURIKOSAMBI'] },
  { folder: 'GI MUARAKARANG BARU', file: 'SINGLE LINE MKBRU Ver 8 2022.pdf', siteNames: ['M. KARANG BARU'] },
  { folder: 'GIS DAAN MOGOT', file: 'SINGLE LINE DNMGT Ver 8 2022.pdf', siteNames: ['DAAN MOGOT GIS'] },
  { folder: 'GIS GROGOL BARU', file: 'SINGLE LINE GRLBR Ver 8 2022.pdf', siteNames: ['GROGOL II', 'GROGOL BARU'] },
  { folder: 'GIS GROGOL', file: 'SINGLE LINE GRGOL Ver 8 2022.pdf', siteNames: ['GROGOL'] },
  { folder: 'GIS KEBON JERUK', file: 'SINGLE LINE KBJRK Ver 8 2022.pdf', siteNames: ['KEBON JERUK'] },
  { folder: 'GIS KEMBANGAN', file: 'SINGLE LINE KMBGN 150KV Ver 8 2022.pdf', siteNames: ['KEMBANGAN'] },
  { folder: 'GIS MUARAKARANG BARU', file: 'SINGLE LINE GMKRU Ver 8.1 2022.pdf', siteNames: ['MUARAKARANG BARU GIS'] },
  { folder: 'GIS NEW SENAYAN', file: 'SINGLE LINE NWSYN Ver 8 2022.pdf', siteNames: ['NEW SENAYAN'] },
  { folder: 'GIS PANTAI INDAH KAPUK', file: 'SINGLE LINE PINKA Ver 8 2022.pdf', siteNames: ['PANTAI INDAH KAPUK'] },
  { folder: 'GIS TOMANG', file: 'SINGLE LINE TOMANG Ver 8 2022.pdf', siteNames: ['TOMANG'] },
  { folder: 'GIS ULUJAMI', file: 'SINGLE LINE ULUJAMI Ver 8 2022.pdf', siteNames: ['ULUJAMI'] },
  { folder: 'GISTET DURIKOSAMBI', file: 'SINGLE LINE GITET DKSB7 Ver 8 2022.pdf', siteNames: ['DKSBI'] },
  // KEMBANGAN sengaja muncul 2x (150kV & 500kV) -- 1 site_name, 2 SLD.
  { folder: 'GISTET KEMBANGAN', file: 'SINGLE LINE KMBNG 500kV Ver 8.pdf', siteNames: ['KEMBANGAN'] },
];

// site_name -> [{folder, file, url}] -- 1 site bisa py >1 SLD (mis. KEMBANGAN).
const BY_SITE = new Map();
for (const entry of ENTRIES) {
  const url = `/sld-files/${encodeURIComponent(entry.folder)}/${encodeURIComponent(entry.file)}`;
  for (const siteName of entry.siteNames) {
    if (!BY_SITE.has(siteName)) BY_SITE.set(siteName, []);
    BY_SITE.get(siteName).push({ folder: entry.folder, file: entry.file, url });
  }
}

function findSldForSite(siteName) {
  return BY_SITE.get(siteName) || [];
}

module.exports = { ROOT, ENTRIES, findSldForSite };
