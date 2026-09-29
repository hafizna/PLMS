const path = require('node:path');
module.exports = function registerReview(app, db, dbPath) {
  app.get('/review', (req, res) => {
    const relays = db.prepare(`SELECT f.relay_function_id, r.*, t.site_name,
      s.voltage_kv, l.line_name, l.ss_from, l.ss_to, other.site_name remote_name
      FROM relay_function f JOIN relay r USING(relay_id)
      JOIN substation s ON s.ss_id=r.ss_id JOIN site t ON t.site_id=s.site_id
      LEFT JOIN line l ON l.line_id=r.line_id
      LEFT JOIN substation os ON os.ss_id=CASE WHEN l.ss_from=r.ss_id THEN l.ss_to WHEN l.ss_to=r.ss_id THEN l.ss_from END
      LEFT JOIN site other ON other.site_id=os.site_id
      WHERE f.function_type='DIST' ORDER BY t.site_name,r.bay`).all();
    const gi = typeof req.query.gi === 'string' ? req.query.gi : '';
    const filtered = gi ? relays.filter(r => r.site_name === gi) : relays;
    const selected = filtered.find(r => String(r.relay_function_id) === req.query.rf) || filtered[0];
    const zones = ['Z1','Z2','Z3'].map(zone => ({zone}));
    let settings = [], branches = [], electrical = null;
    if (selected) {
      const contexts = db.prepare('SELECT * FROM calculation_context WHERE relay_function_id=? ORDER BY zone').all(selected.relay_function_id);
      for (const zone of zones) Object.assign(zone, contexts.find(c => c.zone === zone.zone && c.direction === 'FORWARD'));
      settings = db.prepare('SELECT * FROM relay_setting WHERE relay_function_id=? AND is_current=1 ORDER BY setting_group,source_row,source_column').all(selected.relay_function_id);
      branches = db.prepare(`SELECT b.*, c.zone, l.line_name FROM calculation_branch b
        JOIN calculation_context c USING(context_id) LEFT JOIN line l ON l.line_id=b.line_id
        WHERE c.relay_function_id=? ORDER BY c.zone,b.step_order`).all(selected.relay_function_id);
      electrical = db.prepare('SELECT * FROM line_electrical WHERE line_id=?').get(selected.line_id);
    }
    res.render('review', {relays:filtered, gis:[...new Set(relays.map(r=>r.site_name))], gi, selected,
      zones, settings, branches, electrical, database:path.basename(dbPath),
      fmt:v=>v == null ? 'Belum tersedia' : Number(v).toLocaleString('id-ID',{maximumFractionDigits:6})});
  });
};
