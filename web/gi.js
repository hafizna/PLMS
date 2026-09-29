// Halaman per-GI: SLD asli dulu, baru daftar bay & setting terpasang --
// meniru alur insinyur bekerja dengan Excel (buka SLD, telusuri bay, lihat
// setting), bukan dropdown relay_function acak. Lihat diskusi arsitektur
// web app (2026-09-30): "SLD engine" yang ada (sld_topology_audit.py) itu
// crosswalk data thd Excel Jakban, BUKAN penampil gambar -- SLD asli (PDF)
// yang dilink di sini datang langsung dari folder sumber, bukan dibuat ulang.
'use strict';

const { findSldForSite } = require('./sld-index');

// Normalisasi nama GI dari official_event.gi ("GI 150KV ANGKE", "GIS Grogol",
// "GI Muarakarang Lama") supaya bisa dicocokkan ke site_name ("ANGKE",
// "GROGOL", "M. KARANG LAMA"). HANYA level GI -- bay di official_event
// ("Budi Kemuliaan 1,2") tidak dalam format yang sama dgn relay.bay kita
// ("PHT 150kV BUDI KEMULIAAN#1"), jadi belum dicocokkan per-bay di sini;
// itu pekerjaan terpisah yang butuh parsing nomor sirkit, bukan tebakan.
function giNameKey(value) {
  return (value || '')
    .toUpperCase()
    .replace(/\bM\.\s*KARANG\b/g, 'MUARAKARANG')
    .replace(/^(GI|GIS|GITET|GISTET)\s+(\d+\s*KV\s+)?/, '')
    .replace(/[^A-Z0-9]+/g, ' ')
    .trim();
}

module.exports = function registerGi(app, db, dbPath, helpers) {
  const { pivotSettings, groupSettingsByFunction, describeIdentity } = helpers;

  function listSites() {
    return db.prepare(`
      SELECT DISTINCT s.site_id, s.site_name
      FROM site s JOIN substation sub ON sub.site_id = s.site_id
      WHERE sub.in_scope = 1
      ORDER BY s.site_name
    `).all();
  }

  function getSite(siteName) {
    return db.prepare('SELECT * FROM site WHERE site_name = ?').get(siteName);
  }

  function getSubstations(siteId) {
    return db.prepare('SELECT * FROM substation WHERE site_id = ? ORDER BY voltage_kv DESC').all(siteId);
  }

  // Semua bay yang punya rele di GI ini, lintas level tegangan -- 1 baris
  // per bay+ss_id (bukan per rele), supaya UI mengelompokkan spt SLD nyata
  // (1 bay = 1 grup rele, bukan 1 baris per parameter).
  function getBays(siteId) {
    const relays = db.prepare(`
      SELECT r.relay_id, r.ss_id, r.bay, r.line_id, r.manufacturer, r.model,
        r.identity_confidence, r.identity_status, sub.voltage_kv,
        group_concat(DISTINCT rf.function_type) AS function_types
      FROM relay r
      JOIN substation sub ON sub.ss_id = r.ss_id
      LEFT JOIN relay_function rf ON rf.relay_id = r.relay_id
      WHERE sub.site_id = ?
      GROUP BY r.relay_id
      ORDER BY sub.voltage_kv DESC, r.bay, r.relay_id
    `).all(siteId);

    const byBay = new Map(); // key: voltage_kv|bay
    for (const r of relays) {
      const key = `${r.voltage_kv ?? '?'}|${r.bay ?? '(tanpa bay)'}`;
      if (!byBay.has(key)) {
        byBay.set(key, { voltageKv: r.voltage_kv, bay: r.bay || '(tanpa bay)', lineId: r.line_id, relayIds: [] });
      }
      byBay.get(key).relayIds.push(r.relay_id);
      // Bay dgn >1 line_id beda (jarang, tapi jangan sembunyikan) -- hanya
      // pasang link /line/:id kalau SEMUA rele di bay itu sepakat 1 line_id.
      const group = byBay.get(key);
      if (group.lineId !== r.line_id) group.lineId = undefined;
    }
    return Array.from(byBay.values());
  }

  function getSettingsByRelayIds(relayIds) {
    if (!relayIds.length) return [];
    const placeholders = relayIds.map(() => '?').join(',');
    return db.prepare(`
      SELECT rs.*, rf.function_type, rf.coordination_class, r.manufacturer, r.model,
        r.identity_confidence, s.site_name AS substation_name, r.bay
      FROM relay_setting rs
      JOIN relay r ON rs.relay_id = r.relay_id
      JOIN relay_function rf ON rs.relay_function_id = rf.relay_function_id
      JOIN substation ss ON r.ss_id = ss.ss_id
      JOIN site s ON ss.site_id = s.site_id
      WHERE r.relay_id IN (${placeholders}) AND rs.is_current = 1
      ORDER BY rf.function_type, rs.setting_group, rs.parameter_name
    `).all(...relayIds);
  }

  // Cache: official_event jarang berubah (ingest sekali via ETL terpisah),
  // 292 baris -- cocokkan di JS per-request drpd LIKE/fuzzy SQL per site.
  let officialEventsCache = null;
  function getOfficialEventsForSite(siteName) {
    if (!officialEventsCache) {
      officialEventsCache = db.prepare(`
        SELECT official_event_id, gi, bay, protections, requester, sequence_no,
          effective_date, official_setting, note, status
        FROM official_event ORDER BY effective_date DESC
      `).all().map(e => ({ ...e, giKey: giNameKey(e.gi) }));
    }
    const key = giNameKey(siteName);
    return officialEventsCache.filter(e => e.giKey === key);
  }

  app.get('/gi', (req, res) => {
    res.render('gi-index', { sites: listSites() });
  });

  app.get('/gi/:siteName', (req, res) => {
    const site = getSite(req.params.siteName);
    if (!site) return res.status(404).render('not-found', { lineId: req.params.siteName });

    const substations = getSubstations(site.site_id);
    const slds = findSldForSite(site.site_name);
    const bays = getBays(site.site_id).map(b => ({
      ...b,
      settings: groupSettingsByFunction(pivotSettings(getSettingsByRelayIds(b.relayIds))),
    }));
    const officialEvents = getOfficialEventsForSite(site.site_name);

    res.render('gi', { site, substations, slds, bays, officialEvents });
  });
};
