const { test } = require('node:test');
const assert = require('node:assert/strict');

const { describeIdentity } = require('../server');

// identity_confidence LOW pada ~736 rele terverifikasi baris-per-baris
// sebagai gap dokumen sumber UPT (merk/type/no.seri memang belum
// dicantumkan), bukan bug parser/alias -- lihat describeIdentity() di
// server.js. UI wajib menjelaskan penyebabnya, bukan cuma menampilkan
// kode status mentah yang bisa disalahartikan sebagai kesalahan sistem.

test('describeIdentity: HIGH -> label ringkas, tooltip serial exact', () => {
  const d = describeIdentity('HIGH');
  assert.equal(d.label, 'HIGH');
  assert.match(d.tooltip, /[Nn]omor seri/);
});

test('describeIdentity: MEDIUM -> tooltip jelaskan fallback atribut lengkap', () => {
  const d = describeIdentity('MEDIUM');
  assert.equal(d.label, 'MEDIUM');
  assert.match(d.tooltip, /GI\/bay\/sirkit/);
});

test('describeIdentity: LOW -> label & tooltip menjelaskan gap dokumen, bukan kesalahan sistem', () => {
  const d = describeIdentity('LOW');
  assert.match(d.label, /merk\/type belum tercatat/);
  assert.match(d.tooltip, /dokumen sumber UPT/i);
  assert.match(d.tooltip, /[Bb]ukan kesalahan/);
});

test('describeIdentity: nilai tak dikenal/kosong -> fallback aman, tidak melempar', () => {
  assert.deepEqual(describeIdentity(null), { label: '—', tooltip: '' });
  assert.deepEqual(describeIdentity(undefined), { label: '—', tooltip: '' });
});
