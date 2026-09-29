// PLMS v2 -- satu layar: daftar penghantar in-scope -> detail penghantar.
// Kriteria v1 (PLMS_Rebuild_Prompt_v2.md): tampil kedua ujung, bay, rele
// terpasang, setting terkini, parameter kelistrikan, tetangga satu hop.
// Tanpa autentikasi, case, approval, audit (belum masuk scope sampai v5).
//
// Relay, fungsi, setting, provenance sel, dan riwayat official dimuat oleh v2b.

const express = require('express');
const Database = require('better-sqlite3');
const path = require('path');
const fs = require('node:fs');
const crypto = require('node:crypto');

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

// Pivot setting: sumbernya key-value panjang (1 baris = 1 parameter),
// tapi dibaca insinyur sbg tabel (1 baris = 1 rele, kolom = parameter) --
// sama seperti spreadsheet Mathcad/scanning yang jadi acuan mereka.
// parameter_name berpola path 'KATEGORI > ... > label' (1-4 level
// tergantung fungsi rele) -- level pertama jadi header grup kolom,
// sisanya digabung jadi label kolom (mis. 'Z1 ph-gnd', 't1'). Fungsi
// murni (tanpa akses db) supaya bisa diuji langsung tanpa fixture DB.
function pivotSettings(rows) {
  const groups = new Map(); // key: relay_id|function_type|setting_group
  for (const row of rows) {
    const key = `${row.relay_id}|${row.function_type}|${row.setting_group}`;
    if (!groups.has(key)) {
      groups.set(key, {
        relay_id: row.relay_id,
        substation_name: row.substation_name,
        bay: row.bay,
        function_type: row.function_type,
        coordination_class: row.coordination_class,
        manufacturer: row.manufacturer,
        model: row.model,
        identity_confidence: row.identity_confidence,
        setting_group: row.setting_group,
        effective_date: row.effective_date,
        columns: [], // [{label, value, unit}] in encounter order
      });
    }
    // Separator path adalah ' > ' (spasi di kedua sisi) -- BUKAN '>'
    // polos, yang di proteksi arus-lebih adalah notasi baku vendor rele
    // numerik utk TINGKAT stage (jumlah '>' = makin cepat/tinggi
    // ambangnya): I> = low-set (IDMT/definite-time, py time-delay utk
    // grading hulu/hilir), I>> = high-set (biasanya instantaneous, ~30ms,
    // tanpa time-delay krn sudah di luar zona overlap grading), I>>> =
    // tingkat tertinggi. Dataset ini juga py penomoran gaya lain (I>1,
    // I>2 = OCR standar tingkat 1/2, masing2 py time-delay sendiri --
    // dikonfirmasi pemilik data). Split naif pada '>' polos akan memotong
    // label2 ini jadi kolom yang salah ('I', '1') -- lihat test unit.
    const parts = (row.parameter_name || '').split(' > ').map(s => s.trim());
    const category = parts.length > 1 ? parts[0] : null;
    const label = parts.length > 1 ? parts.slice(1).join(' ') : parts[0] || row.parameter_name;
    groups.get(key).columns.push({
      category, label,
      value: row.parameter_value,
      unit: row.unit,
      provenance: `${row.source_sheet || '?'}!${row.source_row ?? '?'}:${row.source_column || '?'}`,
    });
  }
  return Array.from(groups.values());
}

// Kelompokkan baris ter-pivot per function_type, supaya tiap fungsi rele
// (DIST, LCD, OCR_GFR, ...) dapat sub-tabel sendiri dgn skema kolom yang
// konsisten -- menghindari satu tabel raksasa dgn banyak sel kosong dari
// union semua kolom fungsi yang tidak nyambung.
function groupSettingsByFunction(pivoted) {
  const byFunction = new Map();
  for (const group of pivoted) {
    const key = group.function_type || '(tanpa fungsi)';
    if (!byFunction.has(key)) byFunction.set(key, []);
    byFunction.get(key).push(group);
  }
  // Kolom union dalam urutan encounter, per function_type -- baris yang
  // tidak punya kolom tsb tampil '—' (bukan digeser/salah kolom).
  const result = [];
  for (const [functionType, groups] of byFunction) {
    const columnLabels = [];
    const seen = new Set();
    for (const g of groups) {
      for (const c of g.columns) {
        if (!seen.has(c.label)) { seen.add(c.label); columnLabels.push(c.label); }
      }
    }
    result.push({
      functionType,
      coordinationClass: groups[0].coordination_class,
      columnLabels,
      rows: groups.map(g => ({
        ...g,
        identity: describeIdentity(g.identity_confidence),
        cellsByLabel: Object.fromEntries(g.columns.map(c => [c.label, c])),
      })),
    });
  }
  return result;
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

// identity_confidence LOW pada ~736 rele (terutama AR, SYNCHRO, CBF, BUSPRO,
// SZP) terverifikasi baris-per-baris bukan bug parser/alias -- dokumen
// sumber UPT memang tidak mencantumkan MERK/TYPE/no seri utk baris tsb
// (identity_for() di plms_v2_profile.py butuh 6 atribut lengkap tanpa
// serial utk naik ke MEDIUM). Ini gap dokumen yang jujur, bukan gap sistem
// -- jangan ditutup dgn fuzzy-match atau tebakan. Register merk/type/serial
// otoritatif sudah ada di PST; begitu pst_asset_id (kolom relay, nullable,
// belum diintegrasikan sampai v7a) terisi, identity_for() akan naik
// otomatis ke HIGH lewat serial exact match tanpa perubahan logika.
function describeIdentity(confidence) {
  switch (confidence) {
    case 'HIGH':
      return { label: 'HIGH', tooltip: 'Nomor seri cocok persis.' };
    case 'MEDIUM':
      return { label: 'MEDIUM', tooltip: 'Tanpa nomor seri, tapi GI/bay/sirkit/merk/type/peran lengkap & cocok persis.' };
    case 'LOW':
      return {
        label: 'LOW — merk/type belum tercatat',
        tooltip: 'Dokumen sumber UPT belum mencantumkan merk/type/no. seri rele ini. '
          + 'Bukan kesalahan pembacaan sistem. Data otoritatif sudah ada di register PST; '
          + 'akan terisi otomatis begitu integrasi PST tersedia (lihat pst_asset_id).',
      };
    default:
      return { label: confidence || '—', tooltip: '' };
  }
}

// Kelompokkan baris per GI (site fisik, BUKAN substation -- satu GI bisa
// py beberapa level tegangan tapi tetap 1 site/grup, mis. KEMBANGAN 150kV
// & 500kV masuk grup sama) utk toggle collapse spt outline Excel di
// spreadsheet UPT asal. ss_from/ss_to arahnya ARBITRER (terverifikasi:
// DURIKOSAMBI muncul di from utk sebagian line, di to utk sebagian lain)
// -- jadi grouping HANYA dari from_site_name akan memecah GI yg sama jadi
// tidak lengkap. Tiap line sengaja dimasukkan ke KEDUA grup GI ujungnya,
// konsisten dgn cara UPT sendiri mendaftar bay per GI (row per GI+bay,
// kolom GI lawan terpisah) dan dgn "Tetangga satu hop" yg sudah ada di
// halaman detail. Fungsi murni (tanpa akses db) supaya bisa diuji langsung.
function groupLinesBySite(lines) {
  const groups = new Map(); // site_name -> lines[]
  for (const line of lines) {
    for (const siteName of new Set([line.from_site_name, line.to_site_name])) {
      if (!siteName) continue;
      if (!groups.has(siteName)) groups.set(siteName, []);
      groups.get(siteName).push(line);
    }
  }
  return Array.from(groups.entries())
    .sort((a, b) => a[0].localeCompare(b[0]))
    .map(([siteName, siteLines]) => ({
      siteName,
      lines: siteLines.slice().sort((a, b) => (a.line_name || '').localeCompare(b.line_name || '')),
    }));
}

function createApp(dbPath = DEFAULT_DB_PATH, auditPath = process.env.PLMS_SLD_AUDIT || path.join(__dirname, '..', 'sld_audit', 'audit.json')) {
  const db = new Database(dbPath, { readonly: true, fileMustExist: true });
  const app = express();
  app.set('view engine', 'ejs');
  app.set('views', path.join(__dirname, 'views'));
  app.use('/public', express.static(path.join(__dirname, 'public')));
  app.locals.db = db;
  require('./review')(app, db, dbPath);
  require('./corridor')(app, db, dbPath);

function listInScopeLines() {
  return db.prepare(`
    SELECT
      l.line_id, l.line_name, l.voltage_kv, l.is_boundary, l.source,
      ${substationLabel.replace(/sub\./g, 'sf.').replace(/site\./g, 'sitef.')} AS from_label,
      ${substationLabel.replace(/sub\./g, 'st.').replace(/site\./g, 'sitet.')} AS to_label,
      sitef.site_name AS from_site_name, sitet.site_name AS to_site_name
    FROM line l
    LEFT JOIN substation sf ON l.ss_from = sf.ss_id
    LEFT JOIN site sitef ON sf.site_id = sitef.site_id
    LEFT JOIN substation st ON l.ss_to = st.ss_id
    LEFT JOIN site sitet ON st.site_id = sitet.site_id
    WHERE (sf.in_scope = 1 OR st.in_scope = 1)
    ORDER BY l.line_name
  `).all();
}

// Kelompokkan baris per GI (site fisik, BUKAN substation -- satu GI bisa
// py beberapa level tegangan tapi tetap 1 site/grup, mis. KEMBANGAN 150kV
// & 500kV masuk grup sama) utk toggle collapse spt outline Excel di
// spreadsheet UPT asal. ss_from/ss_to arahnya ARBITRER (terverifikasi:
// DURIKOSAMBI muncul di from utk sebagian line, di to utk sebagian lain)
// -- jadi grouping HANYA dari from_site_name akan memecah GI yg sama jadi
// tidak lengkap. Tiap line sengaja dimasukkan ke KEDUA grup GI ujungnya,
// konsisten dgn cara UPT sendiri mendaftar bay per GI (row per GI+bay,
// kolom GI lawan terpisah) dan dgn "Tetangga satu hop" yg sudah ada di
// halaman detail. Fungsi murni (tanpa akses db) supaya bisa diuji langsung.
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
  // Hanya relay yang terhubung exact ke ruas. Relay site/bus-level yang belum
  // punya line_id tidak ditempelkan ke semua ruas pada GI yang sama.
  if (!ssId) return [];
  return db.prepare(`
    SELECT r.*,
      group_concat(DISTINCT rf.function_type) AS function_types,
      group_concat(DISTINCT rf.coordination_class) AS coordination_classes
    FROM relay r
    JOIN relay_function rf ON rf.relay_id = r.relay_id
    WHERE r.ss_id = ? AND r.line_id = ?
    GROUP BY r.relay_id
    ORDER BY function_types, r.manufacturer, r.model
  `).all(ssId, lineId);
}

function getCurrentSettingsFlat(lineId) {
  return db.prepare(`
    SELECT rs.*, rf.function_type, rf.coordination_class, r.manufacturer, r.model,
      r.identity_confidence, s.site_name AS substation_name, r.bay
    FROM relay_setting rs
    JOIN relay r ON rs.relay_id = r.relay_id
    JOIN relay_function rf ON rs.relay_function_id = rf.relay_function_id
    JOIN substation ss ON r.ss_id = ss.ss_id
    JOIN site s ON ss.site_id = s.site_id
    WHERE r.line_id = ? AND rs.is_current = 1
    ORDER BY s.site_name, rf.function_type, rs.setting_group, rs.parameter_name
  `).all(lineId);
}

function getCurrentSettings(lineId) {
  return groupSettingsByFunction(pivotSettings(getCurrentSettingsFlat(lineId)));
}

function getOfficialHistory(lineId) {
  return db.prepare(`
    SELECT oe.*, oel.link_status
    FROM official_event_line oel
    JOIN official_event oe ON oe.official_event_id = oel.official_event_id
    WHERE oel.line_id = ?
    ORDER BY oe.effective_date DESC, oe.source_sheet DESC, oe.source_row DESC
  `).all(lineId);
}

// ------------------------------------------------------------------ routes

app.get('/sld-audit', (req, res) => {
  const view = { audit: null, contexts: [], selected: null, evidence: {}, message: null };
  if (!fs.existsSync(auditPath)) {
    view.message = 'Audit SLD Jakban belum tersedia. Jalankan sld_topology_audit.py untuk membuat laporan.';
    return res.render('sld-audit', view);
  }
  try {
    const audit = JSON.parse(fs.readFileSync(auditPath, 'utf8'));
    const hash = crypto.createHash('sha256').update(fs.readFileSync(dbPath)).digest('hex');
    const walPath = `${dbPath}-wal`;
    const walHash = fs.existsSync(walPath) ? crypto.createHash('sha256').update(fs.readFileSync(walPath)).digest('hex') : null;
    if (audit.format_version !== 1 || audit.plms_database_sha256 !== hash || (audit.plms_wal_sha256 || null) !== walHash) {
      view.message = 'Database berubah sejak audit dibuat. Buat ulang audit agar ID rele dan ruas sesuai dengan data saat ini.';
      return res.status(409).render('sld-audit', view);
    }
    view.audit = audit;
    view.contexts = audit.relay_contexts.filter(r => !req.query.line_id || String(r.line_id) === req.query.line_id);
    view.selected = view.contexts.find(r => String(r.relay_function_id) === req.query.relay) || null;
    view.evidence = Object.fromEntries(audit.relations.map(r => [r.edge_id, r]));
    return res.render('sld-audit', view);
  } catch (error) {
    view.message = 'Laporan audit tidak dapat dibaca. Buat ulang laporan SLD Jakban.';
    return res.status(503).render('sld-audit', view);
  }
});

app.get('/', (req, res) => {
  const lines = listInScopeLines();
  const groupsBySite = groupLinesBySite(lines);
  res.render('index', { lines, groupsBySite });
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
  const officialHistory = getOfficialHistory(line.line_id);
  const busScFrom = getBusSc(line.from_ss_id);
  const busScTo = getBusSc(line.to_ss_id);
  const bayFrom = describeBay(line.bay_from);
  const bayTo = describeBay(line.bay_to);
  const withIdentity = (relays) => relays.map(r => ({ ...r, identity: describeIdentity(r.identity_confidence) }));

  res.render('detail', {
    line, electrical, neighborsFrom, neighborsTo,
    relaysFrom: withIdentity(relaysFrom), relaysTo: withIdentity(relaysTo),
    currentSettings, officialHistory,
    busScFrom, busScTo, bayFrom, bayTo,
  });
});

  return app;
}

if (require.main === module) {
  const app = createApp();
  app.listen(PORT, () => {
    console.log(`PLMS v2 jalan di http://localhost:${PORT}`);
    console.log(`Database: ${DEFAULT_DB_PATH}`);
  });
}

module.exports = { createApp, pivotSettings, groupSettingsByFunction, describeIdentity, groupLinesBySite };
