const Database = require('better-sqlite3');
const crypto = require('node:crypto');
const express = require('express');
module.exports = (app, db, dbPath) => {
  const token = crypto.randomBytes(32).toString('hex');
  function rows() {
    const data = db.prepare(`SELECT r.identity_key,r.bay,r.model,r.ct_ratio,r.pt_ratio,
      f.relay_function_id,a.site_name origin,b.site_name remote,c.*
      FROM relay r JOIN relay_function f USING(relay_id)
      JOIN substation s ON s.ss_id=r.ss_id JOIN site a ON a.site_id=s.site_id
      JOIN line l ON l.line_id=r.line_id
      JOIN substation t ON t.ss_id=CASE WHEN l.ss_from=r.ss_id THEN l.ss_to WHEN l.ss_to=r.ss_id THEN l.ss_from END
      JOIN site b ON b.site_id=t.site_id
      LEFT JOIN calculation_context c ON c.relay_function_id=f.relay_function_id AND c.direction='FORWARD'
      WHERE f.function_type='DIST' AND s.voltage_kv=150 AND t.voltage_kv=150
      AND ((a.site_name='DURIKOSAMBI' AND b.site_name='GROGOL BARU')
      OR (a.site_name='GROGOL BARU' AND b.site_name IN ('DURIKOSAMBI','GROGOL'))
      OR (a.site_name='GROGOL' AND b.site_name='GROGOL BARU'))
      ORDER BY origin,remote,r.bay,c.zone`).all();
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
    const data=rows();
    const history=withStore(store=>store.prepare('SELECT * FROM review_event ORDER BY id DESC').all());
    const items=data.map(r=>({...r,review:history.find(h=>h.item_key===r.key),history:history.filter(h=>h.item_key===r.key)}));
    res.render('corridor',{items,token,fmt:n=>n==null?'Belum tersedia':Number(n).toLocaleString('id-ID',{maximumFractionDigits:6}),saved:req.query.saved==='1'});
  });
  app.post('/corridor/review',express.urlencoded({extended:false,limit:'16kb'}),(req,res)=>{
    if(req.body.token!==token) return res.status(403).send('Token review tidak valid. Muat ulang halaman.');
    const row=rows().find(r=>r.key===req.body.key && r.snapshot===req.body.snapshot);
    const states=['Perlu data','Perlu verifikasi','Ditinjau'];
    if(!row || !states.includes(req.body.state) || typeof req.body.note!=='string' || !req.body.note.trim() || req.body.note.length>4000)
      return res.status(400).send('Data berubah atau catatan belum valid. Muat ulang dan isi alasan review.');
    withStore(store=>store.prepare('INSERT INTO review_event(item_key,snapshot,state,note,created_at) VALUES(?,?,?,?,?)')
      .run(row.key,row.snapshot,req.body.state,req.body.note.trim(),new Date().toISOString()));
    res.redirect(303,'/corridor?saved=1#'+row.key);
  });
};
