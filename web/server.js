// PLMS v1 -- satu layar: daftar penghantar in-scope -> detail penghantar.
// Kriteria v1 (PLMS_Rebuild_Prompt_v2.md): tampil kedua ujung, bay, rele
// terpasang, setting terkini, parameter kelistrikan, tetangga satu hop.
// Tanpa autentikasi, case, approval, audit (belum masuk scope sampai v5).
//
// relay/relay_setting belum diisi loader (v2+) -- ditampilkan sbg
// "belum ada data" eksplisit, BUKAN disembunyikan atau ditebak.

const express = require('express');
const Database = require('better-sqlite3');
const path = require('path');

const DEFAULT_DB_PATH = process.env.PLMS_DB || path.join(__dirname, '..', 'plms.db');
const PORT = process.env.PORT || 3000;

// ---------------------------------------------------------------- queries

// kV NULL ditampilkan 'kV tdk diketahui', BUKAN ditebak (mis. default
// 150kV) -- prompt v2: mayoritas GI tanpa akhiran tegangan, ketiadaan
// akhiran tidak boleh diartikan 150kV secara default.
const substationLabel = `
  COALESCE(sub.name_digsilent, site.site_name) || ' (' ||
  CASE WHEN sub.voltage_kv IS NOT NULL THEN CAST(sub.voltage_kv AS INTEGER) || 'kV' ELSE 'kV tdk diketahui' END
  || ')'`;

function createApp(dbPath = DEFAULT_DB_PATH) {
  const db = new Database(dbPath, { readonly: true, fileMustExist: true });
  const app = express();
  app.set('view engine', 'ejs');
  app.set('views', path.join(__dirname, 'views'));
  app.use('/public', express.static(path.join(__dirname, 'public')));
  app.locals.db = db;

function listInScopeLines() {
  return db.prepare(`
    SELECT
      l.line_id, l.line_name, l.voltage_kv, l.is_boundary, l.source,
      ${substationLabel.replace(/sub\./g, 'sf.').replace(/site\./g, 'sitef.')} AS from_label,
      ${substationLabel.replace(/sub\./g, 'st.').replace(/site\./g, 'sitet.')} AS to_label
    FROM line l
    LEFT JOIN substation sf ON l.ss_from = sf.ss_id
    LEFT JOIN site sitef ON sf.site_id = sitef.site_id
    LEFT JOIN substation st ON l.ss_to = st.ss_id
    LEFT JOIN site sitet ON st.site_id = sitet.site_id
    WHERE (sf.in_scope = 1 OR st.in_scope = 1)
    ORDER BY l.line_name
  `).all();
}

function getLine(lineId) {
  return db.prepare(`
    SELECT l.*,
      ${substationLabel.replace(/sub\./g, 'sf.').replace(/site\./g, 'sitef.')} AS from_label,
      ${substationLabel.replace(/sub\./g, 'st.').replace(/site\./g, 'sitet.')} AS to_label,
      sf.ss_id AS from_ss_id, st.ss_id AS to_ss_id,
      sf.topology_source AS from_topology_source, st.topology_source AS to_topology_source
    FROM line l
    LEFT JOIN substation sf ON l.ss_from = sf.ss_id
    LEFT JOIN site sitef ON sf.site_id = sitef.site_id
    LEFT JOIN substation st ON l.ss_to = st.ss_id
    LEFT JOIN site sitet ON st.site_id = sitet.site_id
    WHERE l.line_id = ?
  `).get(lineId);
}

function getElectrical(lineId) {
  return db.prepare('SELECT * FROM line_electrical WHERE line_id = ?').get(lineId);
}

function getNeighbors(ssId, excludeLineId) {
  if (!ssId) return [];
  return db.prepare(`
    SELECT l.line_id, l.line_name, l.voltage_kv,
      CASE WHEN l.ss_from = ? THEN
        ${substationLabel.replace(/sub\./g, 'st.').replace(/site\./g, 'sitet.')}
      ELSE
        ${substationLabel.replace(/sub\./g, 'sf.').replace(/site\./g, 'sitef.')}
      END AS neighbor_label
    FROM line l
    LEFT JOIN substation sf ON l.ss_from = sf.ss_id
    LEFT JOIN site sitef ON sf.site_id = sitef.site_id
    LEFT JOIN substation st ON l.ss_to = st.ss_id
    LEFT JOIN site sitet ON st.site_id = sitet.site_id
    WHERE (l.ss_from = ? OR l.ss_to = ?) AND l.line_id != ?
    ORDER BY l.line_name
  `).all(ssId, ssId, ssId, excludeLineId);
}

function getBusSc(ssId) {
  if (!ssId) return [];
  return db.prepare('SELECT * FROM bus_sc WHERE ss_id = ? ORDER BY bus_name').all(ssId);
}

function getRelays(ssId, lineId) {
  // Relay selalu punya ss_id. Syarat line_id mencegah rele penghantar lain
  // pada GI yang sama ikut tampil dan mencegah rele line terduplikasi di
  // kedua ujung.
  if (!ssId) return [];
  return db.prepare(`
    SELECT * FROM relay
    WHERE ss_id = ? AND (line_id IS NULL OR line_id = ?)
    ORDER BY function_type, manufacturer, model
  `).all(ssId, lineId);
}

function getCurrentSettings(lineId) {
  return db.prepare(`
    SELECT rs.*, r.function_type, r.manufacturer, r.model,
      s.site_name AS substation_name, r.bay
    FROM relay_setting rs
    JOIN relay r ON rs.relay_id = r.relay_id
    JOIN substation ss ON r.ss_id = ss.ss_id
    JOIN site s ON ss.site_id = s.site_id
    WHERE r.line_id = ? AND rs.is_current = 1
    ORDER BY s.site_name, r.function_type, rs.setting_group, rs.parameter_name
  `).all(lineId);
}

// Bay yang diawali '?' berasal dari fix_bay() di plms_etl.py: Excel salah
// baca nilai bay (mis. 'I-5') sbg datetime, dipulihkan tapi ditandai utk
// koreksi manual -- prompt v2 jebakan #1. Tampilkan sbg peringatan
// eksplisit, bukan nama bay biasa.
function describeBay(bay) {
  if (!bay) return { text: '—', suspect: false };
  if (bay.startsWith('?')) {
    return { text: bay, suspect: true };
  }
  return { text: bay, suspect: false };
}

// ------------------------------------------------------------------ routes

app.get('/', (req, res) => {
  const lines = listInScopeLines();
  res.render('index', { lines });
});

app.get('/line/:id', (req, res) => {
  const line = getLine(req.params.id);
  if (!line) return res.status(404).render('not-found', { lineId: req.params.id });

  const electrical = getElectrical(line.line_id);
  const neighborsFrom = getNeighbors(line.from_ss_id, line.line_id);
  const neighborsTo = getNeighbors(line.to_ss_id, line.line_id);
  const relaysFrom = getRelays(line.from_ss_id, line.line_id);
  const relaysTo = getRelays(line.to_ss_id, line.line_id);
  const currentSettings = getCurrentSettings(line.line_id);
  const busScFrom = getBusSc(line.from_ss_id);
  const busScTo = getBusSc(line.to_ss_id);
  const bayFrom = describeBay(line.bay_from);
  const bayTo = describeBay(line.bay_to);

  res.render('detail', {
    line, electrical, neighborsFrom, neighborsTo,
    relaysFrom, relaysTo, currentSettings,
    busScFrom, busScTo, bayFrom, bayTo,
  });
});

  return app;
}

if (require.main === module) {
  const app = createApp();
  app.listen(PORT, () => {
    console.log(`PLMS v1 jalan di http://localhost:${PORT}`);
    console.log(`Database: ${DEFAULT_DB_PATH}`);
  });
}

module.exports = { createApp };
