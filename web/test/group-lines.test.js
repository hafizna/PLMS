const { test } = require('node:test');
const assert = require('node:assert/strict');

const { groupLinesBySite } = require('../server');

// ss_from/ss_to arahnya arbitrer di data nyata (terverifikasi manual thd
// plms.db: DURIKOSAMBI muncul di from_site_name utk sebagian line, di
// to_site_name utk sebagian lain, tergantung urutan sumber DIgSILENT/
// manual) -- groupLinesBySite() harus tetap mengumpulkan grup GI yg utuh
// terlepas dari sisi mana GI itu tercatat.
function line(overrides) {
  return {
    line_id: 1, line_name: 'A-B', voltage_kv: 150,
    from_site_name: 'A', to_site_name: 'B',
    ...overrides,
  };
}

test('groupLinesBySite: satu line muncul di KEDUA grup GI ujungnya, bukan cuma salah satu', () => {
  const groups = groupLinesBySite([line({ from_site_name: 'DURIKOSAMBI', to_site_name: 'CENGKARENG' })]);
  const names = groups.map(g => g.siteName);
  assert.deepEqual(names.sort(), ['CENGKARENG', 'DURIKOSAMBI']);
  assert.equal(groups.find(g => g.siteName === 'DURIKOSAMBI').lines.length, 1);
  assert.equal(groups.find(g => g.siteName === 'CENGKARENG').lines.length, 1);
});

test('groupLinesBySite: GI yg sama tetap 1 grup walau arah from/to tertukar antar-line', () => {
  // Meniru pola nyata: DAAN MOGOT-DURIKOSAMBI ada di kedua arah tergantung
  // baris DIgSILENT/manual mana yg jadi sumbernya.
  const groups = groupLinesBySite([
    line({ line_id: 1, line_name: 'DAAN MOGOT - DURIKOSAMBI 1', from_site_name: 'DURIKOSAMBI', to_site_name: 'DAAN MOGOT GIS' }),
    line({ line_id: 2, line_name: 'DAAN MOGOT - DURIKOSAMBI 2', from_site_name: 'DAAN MOGOT GIS', to_site_name: 'DURIKOSAMBI' }),
  ]);
  const dksbi = groups.find(g => g.siteName === 'DURIKOSAMBI');
  assert.equal(dksbi.lines.length, 2, 'kedua line harus masuk grup DURIKOSAMBI walau arahnya tertukar');
});

test('groupLinesBySite: GI dgn nama sama tapi level tegangan berbeda tetap 1 grup (grouping by site, bukan substation)', () => {
  const groups = groupLinesBySite([
    line({ line_id: 1, from_site_name: 'KEMBANGAN', to_site_name: 'X', voltage_kv: 150 }),
    line({ line_id: 2, from_site_name: 'KEMBANGAN', to_site_name: 'Y', voltage_kv: 500 }),
  ]);
  const kembangan = groups.find(g => g.siteName === 'KEMBANGAN');
  assert.equal(kembangan.lines.length, 2);
});

test('groupLinesBySite: line dgn site_name null (satu ujung di luar scope) tidak membuat grup "null"', () => {
  const groups = groupLinesBySite([line({ from_site_name: 'DURIKOSAMBI', to_site_name: null })]);
  assert.equal(groups.length, 1);
  assert.equal(groups[0].siteName, 'DURIKOSAMBI');
});

test('groupLinesBySite: grup diurutkan alfabetis, baris dalam grup diurutkan by nama', () => {
  const groups = groupLinesBySite([
    line({ line_id: 1, line_name: 'B-LINE', from_site_name: 'ZEBRA', to_site_name: null }),
    line({ line_id: 2, line_name: 'A-LINE', from_site_name: 'ZEBRA', to_site_name: null }),
    line({ line_id: 3, line_name: 'X', from_site_name: 'ALPHA', to_site_name: null }),
  ]);
  assert.deepEqual(groups.map(g => g.siteName), ['ALPHA', 'ZEBRA']);
  const zebra = groups.find(g => g.siteName === 'ZEBRA');
  assert.deepEqual(zebra.lines.map(l => l.line_name), ['A-LINE', 'B-LINE']);
});
