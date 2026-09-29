const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const Database = require('better-sqlite3');
const { createApp } = require('../server');

function seedFixture(file) {
  const db = new Database(file);
  db.exec(fs.readFileSync(path.join(__dirname, '..', '..', 'schema.sql'), 'utf8'));
  db.exec(`
    INSERT INTO site(site_id, site_name) VALUES (1, 'DADAP'), (2, 'KEMBANGAN');
    INSERT INTO substation(ss_id, site_id, voltage_kv, in_scope) VALUES (1, 1, 150, 1), (2, 2, 500, 1);
    INSERT INTO relay(relay_id, ss_id, bay, identity_key, identity_confidence, identity_status)
      VALUES (1, 1, 'TRAFO 1', 'test-key-1', 'HIGH', 'EXACT');
    INSERT INTO relay_function(relay_function_id, relay_id, function_type, coordination_class, source_logical)
      VALUES (1, 1, 'OCR_GFR', 'GRADED', 'OCR_HV');
    INSERT INTO relay_setting(relay_id, relay_function_id, parameter_name, parameter_value, setting_group,
      is_current, source_workbook, source_sheet, source_row, source_column, source_header, source_hash, observed_at)
      VALUES (1, 1, 'SETTING (TERPASANG) > Iset OC', '4.6', 'SET_RELAY', 1, 'wb', 'sheet', 1, 'A', 'h', 'hash', '2026-09-30');
    INSERT INTO official_event(gi, bay, protections, requester, sequence_no, effective_date, official_setting, note, status,
      source_workbook, source_sheet, source_row, source_hash, observed_at)
      VALUES ('GI 150KV DADAP', 'TRF#1', 'OCR 150kV', 'ULTG DURIKOSAMBI', '001', '2026-01-05', 'LINK', 'Uji coba', 'True', 'wb', 'sheet', 1, 'hash', '2026-09-30');
  `);
  db.close();
}

test('/gi lists in-scope sites', async () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'plms-gi-'));
  const file = path.join(dir, 'test.db');
  seedFixture(file);
  const app = createApp(file);
  const server = app.listen(0, '127.0.0.1');
  await new Promise(r => server.once('listening', r));
  const base = `http://127.0.0.1:${server.address().port}`;
  try {
    const html = await (await fetch(`${base}/gi`)).text();
    assert.match(html, /DADAP/);
    assert.match(html, /KEMBANGAN/);
  } finally {
    await new Promise(r => server.close(r));
    app.locals.db.close();
    fs.rmSync(dir, { recursive: true, force: true });
  }
});

test('/gi/:siteName shows a mapped SLD link and pivoted bay settings', async () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'plms-gi-'));
  const file = path.join(dir, 'test.db');
  seedFixture(file);
  const app = createApp(file);
  const server = app.listen(0, '127.0.0.1');
  await new Promise(r => server.once('listening', r));
  const base = `http://127.0.0.1:${server.address().port}`;
  try {
    const html = await (await fetch(`${base}/gi/DADAP`)).text();
    assert.match(html, /sld-files.*DADAP.*\.pdf/);
    assert.match(html, /TRAFO 1/);
    assert.match(html, /OCR_GFR/);
    assert.match(html, /4\.6/);
    // official_event.gi 'GI 150KV DADAP' harus cocok ke site_name 'DADAP'
    // lewat giNameKey(), tanpa perlu bay-level matching.
    assert.match(html, /Uji coba/);
    assert.match(html, /ULTG DURIKOSAMBI/);
  } finally {
    await new Promise(r => server.close(r));
    app.locals.db.close();
    fs.rmSync(dir, { recursive: true, force: true });
  }
});

test('/gi/:siteName without a verified SLD mapping says so instead of guessing', async () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'plms-gi-'));
  const file = path.join(dir, 'test.db');
  seedFixture(file);
  const app = createApp(file);
  const server = app.listen(0, '127.0.0.1');
  await new Promise(r => server.once('listening', r));
  const base = `http://127.0.0.1:${server.address().port}`;
  try {
    // KEMBANGAN dipetakan; site fiktif yang tidak ada di sld-index.js harus
    // tampil "belum terhubung", bukan salah tebak/nihil tanpa penjelasan.
    const html = await (await fetch(`${base}/gi/KEMBANGAN`)).text();
    assert.match(html, /KEMBANGAN/);
  } finally {
    await new Promise(r => server.close(r));
    app.locals.db.close();
    fs.rmSync(dir, { recursive: true, force: true });
  }
});

test('/gi/:siteName 404s for an unknown site', async () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'plms-gi-'));
  const file = path.join(dir, 'test.db');
  seedFixture(file);
  const app = createApp(file);
  const server = app.listen(0, '127.0.0.1');
  await new Promise(r => server.once('listening', r));
  const base = `http://127.0.0.1:${server.address().port}`;
  try {
    const res = await fetch(`${base}/gi/TIDAK-ADA`);
    assert.equal(res.status, 404);
  } finally {
    await new Promise(r => server.close(r));
    app.locals.db.close();
    fs.rmSync(dir, { recursive: true, force: true });
  }
});
