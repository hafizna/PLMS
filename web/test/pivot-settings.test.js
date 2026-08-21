const { test } = require('node:test');
const assert = require('node:assert/strict');

const { pivotSettings, groupSettingsByFunction } = require('../server');

// Baris mentah spt yg keluar dari getCurrentSettingsFlat(): 1 baris per
// parameter, relay_id + function_type + setting_group menentukan grup.
function row(overrides) {
  return {
    relay_id: 1,
    substation_name: 'DKSBI',
    bay: 'PHT 500kV MUARAKARANG#1',
    function_type: 'DIST',
    coordination_class: 'GRADED',
    manufacturer: 'SIEMENS',
    model: '7SL87',
    setting_group: 'SET_RELAY',
    effective_date: null,
    parameter_name: 'SETTING IMPEDANSI > Z1 > ph-gnd',
    parameter_value: '0',
    unit: '',
    source_sheet: 'DIST',
    source_row: 182,
    source_column: 'AQ',
    ...overrides,
  };
}

test('pivotSettings: baris key-value multi-level jadi 1 grup per rele+fungsi+grup', () => {
  const rows = [
    row({ parameter_name: 'SETTING IMPEDANSI > Z1 > ph-gnd', parameter_value: '1.5' }),
    row({ parameter_name: 'SETTING IMPEDANSI > Z1 > ph-ph', parameter_value: '2.0' }),
    row({ parameter_name: 'SETTING WAKTU > t1', parameter_value: '0' }),
  ];
  const pivoted = pivotSettings(rows);
  assert.equal(pivoted.length, 1, 'ketiga baris milik relay_id+function_type+setting_group yang sama -> 1 grup');
  assert.equal(pivoted[0].columns.length, 3);
  assert.deepEqual(pivoted[0].columns.map(c => c.label), ['Z1 ph-gnd', 'Z1 ph-ph', 't1']);
  assert.equal(pivoted[0].columns[0].value, '1.5');
});

test('pivotSettings: relay_id berbeda -> grup terpisah, bukan tergabung', () => {
  const rows = [
    row({ relay_id: 1, parameter_name: 'SETTING IMPEDANSI > Z1 > ph-gnd' }),
    row({ relay_id: 2, parameter_name: 'SETTING IMPEDANSI > Z1 > ph-gnd' }),
  ];
  const pivoted = pivotSettings(rows);
  assert.equal(pivoted.length, 2, 'dua rele fisik berbeda tidak boleh tercampur jadi satu baris tabel');
});

test('pivotSettings: parameter_name 1-level (tanpa " > ") tetap jadi kolom', () => {
  const rows = [row({ parameter_name: 'Dead Time 1 Pole', parameter_value: '1.0' })];
  const pivoted = pivotSettings(rows);
  assert.equal(pivoted[0].columns[0].label, 'Dead Time 1 Pole');
  assert.equal(pivoted[0].columns[0].category, null);
});

test('pivotSettings: label parameter yang mengandung ">" literal (bukan separator path) tetap utuh', () => {
  // '>' berulang di proteksi arus-lebih adalah notasi baku vendor rele
  // numerik utk tingkat stage: I> = low-set (IDMT/definite-time, py
  // time-delay grading), I>> = high-set (biasanya instantaneous, tanpa
  // grading krn di luar zona overlap). 'I>1'/'I>2' pola penomoran lain
  // (OCR standar tingkat 1/2, masing2 py time-delay sendiri --
  // dikonfirmasi pemilik data). BUKAN path 2 level 'I' > '1'/'2'.
  // Separator path sebenarnya selalu ' > ' (dgn spasi); regresi: split
  // naif pada '>' polos akan memotong label ini jadi kolom yang salah.
  const rows = [
    row({ parameter_name: 'I>1', parameter_value: '5' }),
    row({ parameter_name: 'I>2', parameter_value: '10' }),
  ];
  const pivoted = pivotSettings(rows);
  assert.deepEqual(pivoted[0].columns.map(c => c.label), ['I>1', 'I>2']);
  assert.equal(pivoted[0].columns[0].category, null, 'I>1 bukan path multi-level, tidak boleh py category');
});

test('pivotSettings: provenance per kolom mengikuti sel, bukan grup', () => {
  const rows = [
    row({ parameter_name: 'SETTING IMPEDANSI > Z1 > ph-gnd', source_row: 182, source_column: 'AQ' }),
    row({ parameter_name: 'SETTING IMPEDANSI > Z1 > ph-ph', source_row: 182, source_column: 'AP' }),
  ];
  const pivoted = pivotSettings(rows);
  assert.equal(pivoted[0].columns[0].provenance, 'DIST!182:AQ');
  assert.equal(pivoted[0].columns[1].provenance, 'DIST!182:AP');
});

test('groupSettingsByFunction: fungsi berbeda dapat sub-tabel & skema kolom sendiri', () => {
  const rows = [
    row({ relay_id: 1, function_type: 'DIST', coordination_class: 'GRADED',
          parameter_name: 'SETTING IMPEDANSI > Z1 > ph-gnd' }),
    row({ relay_id: 2, function_type: 'OCR_GFR', coordination_class: 'GRADED',
          parameter_name: 'SETTING (TERPASANG) > In' }),
  ];
  const groups = groupSettingsByFunction(pivotSettings(rows));
  assert.equal(groups.length, 2);
  const dist = groups.find(g => g.functionType === 'DIST');
  const ocr = groups.find(g => g.functionType === 'OCR_GFR');
  assert.deepEqual(dist.columnLabels, ['Z1 ph-gnd']);
  assert.deepEqual(ocr.columnLabels, ['In']);
});

test('groupSettingsByFunction: kolom union dalam satu fungsi, baris tanpa kolom tampil sbg absen (bukan salah geser)', () => {
  // Rele A (SIEMENS) punya Z1 ph-gnd + Z1 ph-ph; rele B (merk lain) cuma
  // punya Z1 ph-gnd -- kolom union harus tetap 2, baris B kosong di kolom
  // Z1 ph-ph (bukan menggeser nilai ke kolom yg salah).
  const rows = [
    row({ relay_id: 1, manufacturer: 'SIEMENS', parameter_name: 'SETTING IMPEDANSI > Z1 > ph-gnd', parameter_value: '1.0' }),
    row({ relay_id: 1, manufacturer: 'SIEMENS', parameter_name: 'SETTING IMPEDANSI > Z1 > ph-ph', parameter_value: '2.0' }),
    row({ relay_id: 2, manufacturer: 'ABB', parameter_name: 'SETTING IMPEDANSI > Z1 > ph-gnd', parameter_value: '3.0' }),
  ];
  const groups = groupSettingsByFunction(pivotSettings(rows));
  const dist = groups.find(g => g.functionType === 'DIST');
  assert.deepEqual(dist.columnLabels, ['Z1 ph-gnd', 'Z1 ph-ph']);
  const relayB = dist.rows.find(r => r.manufacturer === 'ABB');
  assert.equal(relayB.cellsByLabel['Z1 ph-gnd'].value, '3.0');
  assert.equal(relayB.cellsByLabel['Z1 ph-ph'], undefined, 'rele B tidak punya Z1 ph-ph -- harus absen, bukan terisi nilai rele lain');
});
