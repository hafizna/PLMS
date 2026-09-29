const { after, before, test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const Database = require('better-sqlite3');

const { createApp } = require('../server');

let tempDir;
let app;
let server;
let baseUrl;

before(async () => {
  tempDir = fs.mkdtempSync(path.join(os.tmpdir(), 'plms-web-test-'));
  const dbPath = path.join(tempDir, 'fixture.db');
  const db = new Database(dbPath);
  db.exec(fs.readFileSync(path.join(__dirname, '..', '..', 'schema.sql'), 'utf8'));

  const siteA = db.prepare('INSERT INTO site (site_name) VALUES (?)').run('LONTAR').lastInsertRowid;
  const siteB = db.prepare('INSERT INTO site (site_name) VALUES (?)').run('DADAP').lastInsertRowid;
  const insertSs = db.prepare(`
    INSERT INTO substation (site_id, voltage_kv, in_scope, hop_distance, topology_source)
    VALUES (?, NULL, 1, 0, NULL)
  `);
  const ssA = insertSs.run(siteA).lastInsertRowid;
  const ssB = insertSs.run(siteB).lastInsertRowid;
  const lineId = db.prepare(`
    INSERT INTO line (line_name, ss_from, bay_from, ss_to, bay_to, voltage_kv,
                      is_boundary, source)
    VALUES ('LONTAR-DADAP', ?, '?5-1', ?, 'II', NULL, 0, 'UPT_MANUAL')
  `).run(ssA, ssB).lastInsertRowid;
  const relayId = db.prepare(`
    INSERT INTO relay (ss_id, bay, line_id, manufacturer, model, status,
                       identity_key, identity_confidence, identity_status)
    VALUES (?, 'I', ?, 'Schweitzer', 'SEL-411L', 'ACTIVE',
            'SERIAL|FIXTURE', 'HIGH', 'EXACT')
  `).run(ssA, lineId).lastInsertRowid;
  const relayFunctionId = db.prepare(`
    INSERT INTO relay_function
      (relay_id, function_type, coordination_class, source_logical, status)
    VALUES (?, 'DIST', 'GRADED', 'LCD+DIST', 'ACTIVE')
  `).run(relayId).lastInsertRowid;
  db.prepare(`
    INSERT INTO relay_setting
      (relay_id, relay_function_id, parameter_name, parameter_value, unit,
       setting_group, effective_date, source_doc, is_current, source_workbook,
       source_sheet, source_row, source_column, source_header, source_hash, observed_at)
    VALUES (?, ?, 'Z1', '10', 'ohm', 'SET_RELAY', '2026-08-21', 'fixture.pdf', 1,
            'fixture.xlsx', 'DIST', 11, 'T', 'SETTING IMPEDANSI > Z1', 'abc', '2026-08-21')
  `).run(relayId, relayFunctionId);
  const eventId = db.prepare(`
    INSERT INTO official_event
      (gi, bay, protections, effective_date, status, source_workbook, source_sheet,
       source_row, source_hash, observed_at)
    VALUES ('LONTAR', 'DADAP #1', 'DISTANCE', '2026-08-20', 'True',
            'official.xlsx', '2026', 5, 'def', '2026-08-21')
  `).run().lastInsertRowid;
  db.prepare(`INSERT INTO official_event_line VALUES (?, ?, 'EXACT')`).run(eventId, lineId);
  db.close();

  app = createApp(dbPath);
  await new Promise(resolve => {
    server = app.listen(0, '127.0.0.1', resolve);
  });
  baseUrl = `http://127.0.0.1:${server.address().port}`;
});

after(async () => {
  if (server) await new Promise(resolve => server.close(resolve));
  if (app?.locals?.db?.open) app.locals.db.close();
  if (tempDir) fs.rmSync(tempDir, { recursive: true, force: true });
});

test('daftar + detail menampilkan provenance, warning, rele, dan setting', async () => {
  const root = await fetch(`${baseUrl}/`);
  assert.equal(root.status, 200);
  const rootHtml = await root.text();
  assert.match(rootHtml, /1 penghantar \(\+1 hop, termasuk boundary\)/);
  assert.match(rootHtml, /tdk diketahui/);
  assert.match(rootHtml, /UPT_MANUAL/);

  const detail = await fetch(`${baseUrl}/line/1`);
  assert.equal(detail.status, 200);
  const html = await detail.text();
  assert.match(html, /topology_source: NULL/);
  assert.match(html, /bay salah-baca sbg tanggal/);
  assert.match(html, /SEL-411L/);
  assert.match(html, /Z1/);
  assert.match(html, /10 ohm/);
  assert.match(html, /DIST!11:T/);
  assert.match(html, /Riwayat official/);
  assert.match(html, /DISTANCE/);
  assert.doesNotMatch(html, /Belum ada data setting/);
});

test('line yang tidak ada menghasilkan 404', async () => {
  const response = await fetch(`${baseUrl}/line/999999`);
  assert.equal(response.status, 404);
  assert.match(await response.text(), /tidak ditemukan/);
});

test('daftar: toolbar cari/filter dirender dgn data-attribute per baris, opsi filter dari data nyata (bukan hardcode)', async () => {
  const root = await fetch(`${baseUrl}/`);
  const html = await root.text();
  assert.match(html, /id="q"/, 'search box harus ada');
  assert.match(html, /id="f-kv"/);
  assert.match(html, /id="f-source"/);
  assert.match(html, /id="f-boundary"/);
  // Fixture ini cuma py 1 line voltage_kv NULL, source UPT_MANUAL -- opsi
  // kV NULL sengaja tidak dimasukkan ke <select> (lihat index.ejs), tapi
  // opsi source harus muncul dari nilai aktual.
  assert.match(html, /<option value="UPT_MANUAL">UPT_MANUAL<\/option>/);
  assert.match(html, /data-source="UPT_MANUAL"/);
  assert.match(html, /data-boundary="0"/);
  assert.match(html, /data-name="lontar-dadap"/, 'nama baris utk pencarian harus lowercase');
});

test('daftar: mode kelompok per GI merender kedua GI ujung sbg grup terpisah', async () => {
  const root = await fetch(`${baseUrl}/`);
  const html = await root.text();
  assert.match(html, /id="view-grouped"/, 'tombol toggle ke mode kelompok harus ada');
  // Fixture: 1 line LONTAR-DADAP -- harus muncul di KEDUA grup GI (lihat
  // groupLinesBySite() di server.js), bukan cuma salah satu ujung.
  assert.match(html, /data-gi="lontar"/);
  assert.match(html, /data-gi="dadap"/);
  assert.match(html, /<span class="gi-count">1 penghantar<\/span>/g);
});


test('review keeps missing calculations distinct from settings and escapes query input', async () => {
  const response = await fetch(`${baseUrl}/review`);
  assert.equal(response.status, 200);
  const html = await response.text();
  assert.match(html, /Review setting/);
  assert.match(html, /SEL-411L/);
  assert.match(html, /Belum dihitung/);
  assert.match(html, /Belum diverifikasi engineer/);
  assert.match(html, /DIST!T11/);
  const empty = await fetch(`${baseUrl}/review?gi=${encodeURIComponent('<script>bad()</script>')}`);
  const body = await empty.text();
  assert.match(body, /Belum ada fungsi distance/);
  assert.doesNotMatch(body, /<script>bad/);
});


test('corridor has a review workflow and rejects unauthorized writes', async () => {
  const page=await fetch(`${baseUrl}/corridor`);
  assert.equal(page.status,200);
  assert.match(await page.text(), /Perbandingan seluruh koridor/);
  const denied=await fetch(`${baseUrl}/corridor/review`,{method:'POST',headers:{'Content-Type':'application/x-www-form-urlencoded'},body:'note=test&state=Ditinjau'});
  assert.equal(denied.status,403);
});
