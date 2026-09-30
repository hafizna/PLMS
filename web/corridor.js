const Database = require('better-sqlite3');
const crypto = require('node:crypto');
const express = require('express');
module.exports = (app, db, dbPath) => {
  const token = crypto.randomBytes(32).toString('hex');

  // GI yang benar2 py fungsi DIST -- dropdown picker, bukan semua ~85 site.
  function listGis() {
    return db.prepare(`SELECT DISTINCT a.site_name
      FROM relay r JOIN relay_function f USING(relay_id)
      JOIN substation s ON s.ss_id=r.ss_id JOIN site a ON a.site_id=s.site_id
      WHERE f.function_type='DIST' ORDER BY a.site_name`).all().map(x => x.site_name);
  }

  // Site_name manapun yang genuinely ada -- dipakai HANYA utk membedakan
  // "GI valid tapi 0 fungsi DIST" (tampilkan empty state jujur) dari "gi
  // param tidak dikenal sama sekali" (baru jatuh ke default). Kalau dites
  // thd listGis() saja, GI valid tanpa DIST akan diam2 dilempar ke GI lain
  // -- persis bug hardcode lama yang baru saja kita perbaiki.
  function siteExists(name) {
    return !!db.prepare('SELECT 1 FROM site WHERE site_name=?').get(name);
  }

  // Sebelumnya hardcode 3 nama GI di WHERE -- korban pertama saat identitas
  // GROGOL BARU/GROGOL II digabung (site_name berubah, corridor diam-diam
  // jadi 0 baris). Sekarang parameterized per GI dipilih, spt GI-A/GI-B di
  // sheet GANDUL-DURKOS: pilih 1 GI lokal, tampilkan SEMUA arah/hop yang
  // memang ada di topologi (line + calculation_context/branch), bukan
  // corridor yang ditulis tangan.
  function rows(gi) {
    if (!gi) return [];
    const data = db.prepare(`SELECT r.identity_key,r.bay,r.model,r.ct_ratio,r.pt_ratio,
      f.relay_function_id,a.site_name origin,b.site_name remote,c.*
      FROM relay r JOIN relay_function f USING(relay_id)
      JOIN substation s ON s.ss_id=r.ss_id JOIN site a ON a.site_id=s.site_id
      JOIN line l ON l.line_id=r.line_id
      JOIN substation t ON t.ss_id=CASE WHEN l.ss_from=r.ss_id THEN l.ss_to WHEN l.ss_to=r.ss_id THEN l.ss_from END
      JOIN site b ON b.site_id=t.site_id
      LEFT JOIN calculation_context c ON c.relay_function_id=f.relay_function_id AND c.direction='FORWARD'
      WHERE f.function_type='DIST' AND s.voltage_kv=150 AND t.voltage_kv=150
      AND a.site_name=?
      ORDER BY origin,remote,r.bay,c.zone`).all(gi);
    return data.map(r => {
      const sources = db.prepare(`SELECT * FROM relay_setting WHERE relay_function_id=? AND is_current=1
        AND setting_group='SET_RELAY'`).all(r.relay_function_id)
        .filter(s => s.parameter_name === `SETTING IMPEDANSI > ${r.zone} > ph-ph`);
      const source = sources.length===1 ? sources[0] : null;
      const notes = r.context_id ? db.prepare('SELECT note FROM calculation_branch WHERE context_id=? ORDER BY step_order').all(r.context_id).map(n=>n.note).filter(Boolean) : [];
      const input = JSON.stringify({r,source,notes});
      return {...r,source,notes:[...new Set(notes)], key:crypto.createHash('sha256').update(r.identity_key+'|'+r.zone).digest('hex'),
        snapshot:crypto.createHash('sha256').update(input).digest('hex')};
    });
  }
  function withStore(fn) {
    const store = new Database(dbPath+'.reviews.db');
    try {
      store.exec(`CREATE TABLE IF NOT EXISTS review_event(id INTEGER PRIMARY KEY, item_key TEXT NOT NULL,snapshot TEXT NOT NULL,state TEXT NOT NULL,note TEXT NOT NULL,created_at TEXT NOT NULL)`);
      return fn(store);
    } finally { store.close(); }
  }
  app.get('/corridor', (req,res) => {
    const gis = listGis();
    const gi = typeof req.query.gi === 'string' && siteExists(req.query.gi) ? req.query.gi : (gis.includes('DURIKOSAMBI') ? 'DURIKOSAMBI' : gis[0] || '');
    const data=rows(gi);
    const history=withStore(store=>store.prepare('SELECT * FROM review_event ORDER BY id DESC').all());
    const items=data.map(r=>({...r,review:history.find(h=>h.item_key===r.key),history:history.filter(h=>h.item_key===r.key)}));
    const remotes=[...new Set(items.map(r=>r.remote))].sort();
    res.render('corridor',{items,gis,gi,remotes,token,fmt:n=>n==null?'Belum tersedia':Number(n).toLocaleString('id-ID',{maximumFractionDigits:6}),saved:req.query.saved==='1'});
  });
  app.post('/corridor/review',express.urlencoded({extended:false,limit:'16kb'}),(req,res)=>{
    if(req.body.token!==token) return res.status(403).send('Token review tidak valid. Muat ulang halaman.');
    const row=rows(req.body.gi).find(r=>r.key===req.body.key && r.snapshot===req.body.snapshot);
    const states=['Perlu data','Perlu verifikasi','Ditinjau'];
    if(!row || !states.includes(req.body.state) || typeof req.body.note!=='string' || !req.body.note.trim() || req.body.note.length>4000)
      return res.status(400).send('Data berubah atau catatan belum valid. Muat ulang dan isi alasan review.');
    withStore(store=>store.prepare('INSERT INTO review_event(item_key,snapshot,state,note,created_at) VALUES(?,?,?,?,?)')
      .run(row.key,row.snapshot,req.body.state,req.body.note.trim(),new Date().toISOString()));
    res.redirect(303,'/corridor?gi='+encodeURIComponent(req.body.gi)+'&saved=1#'+row.key);
  });
};
