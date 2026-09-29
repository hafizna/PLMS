const { after, before, test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const crypto = require('node:crypto');
const Database = require('better-sqlite3');
const { createApp } = require('../server');

let tempDir, dbPath, auditPath, app, server, baseUrl, hash;
before(async () => {
  tempDir = fs.mkdtempSync(path.join(os.tmpdir(), 'plms-sld-test-'));
  dbPath = path.join(tempDir, 'fixture.db');
  auditPath = path.join(tempDir, 'audit.json');
  const db = new Database(dbPath);
  db.exec(fs.readFileSync(path.join(__dirname, '..', '..', 'schema.sql'), 'utf8'));
  db.close();
  hash = crypto.createHash('sha256').update(fs.readFileSync(dbPath)).digest('hex');
  app = createApp(dbPath, auditPath);
  await new Promise(resolve => { server = app.listen(0, '127.0.0.1', resolve); });
  baseUrl = `http://127.0.0.1:${server.address().port}`;
});
after(async () => {
  if (server) await new Promise(resolve => server.close(resolve));
  if (app?.locals.db.open) app.locals.db.close();
  if (tempDir && path.dirname(path.resolve(tempDir)) === path.resolve(os.tmpdir())) {
    fs.rmSync(tempDir, { recursive: true, force: true });
  }
});

test('audit absent gives an actionable empty state', async () => {
  const response = await fetch(`${baseUrl}/sld-audit`);
  assert.equal(response.status, 200);
  assert.match(await response.text(), /belum tersedia/);
});

test('audit displays per-relay paths and escaped source evidence, without numeric reach', async () => {
  const branch = { hop: 1, excluded_reason: null, blockers: ['MISSING_LINE_IMPEDANCE'],
    path: [{line_id: null, name: 'DADAP-TELUK NAGA', relation_status: 'CANDIDATE_NEW_CORRIDOR', sld_evidence: ['source:2']}] };
  fs.writeFileSync(auditPath, JSON.stringify({format_version: 1, plms_database_sha256: hash,
    summary: {workbooks: 11, relay_functions: 1, relays_with_sld_evidence: 1},
    relations: [{edge_id: 'source:2', file: '<script>bad()</script>', sheet: 'Jalur_Transmisi', row: 2, views: 'FULL'}],
    relay_contexts: [{relay_function_id: 9, line_id: 1, local_name: 'LONTAR', remote_name: 'DADAP',
      protected_line_name: 'LONTAR-DADAP', blockers: ['MISSING_TRANSFORMER_REACTANCE'], zones: {Z2: [branch], Z3: [branch]}}]}));
  const response = await fetch(`${baseUrl}/sld-audit?relay=9`);
  assert.equal(response.status, 200);
  const html = await response.text();
  assert.match(html, /DADAP-TELUK NAGA/);
  assert.match(html, /CANDIDATE_NEW_CORRIDOR/);
  assert.match(html, /Jalur_Transmisi:2/);
  assert.match(html, /FULL/);
  assert.match(html, /tidak menghasilkan angka reach/);
  assert.doesNotMatch(html, /<script>bad/);
  assert.equal(crypto.createHash('sha256').update(fs.readFileSync(dbPath)).digest('hex'), hash);
});

test('audit from another database is rejected instead of using stale IDs', async () => {
  fs.writeFileSync(auditPath, JSON.stringify({format_version: 1, plms_database_sha256: 'stale'}));
  const response = await fetch(`${baseUrl}/sld-audit?relay=9`);
  assert.equal(response.status, 409);
  assert.match(await response.text(), /Database berubah/);
});

test('corrupt audit has a recoverable error state', async () => {
  fs.writeFileSync(auditPath, '{bad json');
  const response = await fetch(`${baseUrl}/sld-audit`);
  assert.equal(response.status, 503);
  assert.match(await response.text(), /tidak dapat dibaca/);
});
