const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');const os=require('node:os');const path=require('node:path');
const Database=require('better-sqlite3');const {createApp}=require('../server');
test('corridor persists review history, escapes notes, and rejects stale snapshots',async()=>{
 const dir=fs.mkdtempSync(path.join(os.tmpdir(),'plms-corridor-'));
 const file=path.join(dir,'test.db');const seed=new Database(file);
 seed.exec(fs.readFileSync(path.join(__dirname,'../../schema.sql'),'utf8'));
 seed.exec(`INSERT INTO site(site_id,site_name) VALUES(1,'DURIKOSAMBI'),(2,'GROGOL II');
 INSERT INTO substation(ss_id,site_id,voltage_kv) VALUES(1,1,150),(2,2,150);
 INSERT INTO line(line_id,line_name,ss_from,ss_to,source) VALUES(1,'PILOT',1,2,'DIGSILENT');
 INSERT INTO relay(relay_id,ss_id,line_id,bay,identity_key,identity_confidence,identity_status) VALUES(1,1,1,'PHT GROGOL BARU#2','test','HIGH','EXACT');
 INSERT INTO relay_function(relay_function_id,relay_id,function_type,coordination_class,source_logical) VALUES(1,1,'DIST','GRADED','DIST');
 INSERT INTO calculation_context(relay_function_id,line_id,zone,direction,status,computed_at,delay_s) VALUES(1,1,'Z3','FORWARD','complete_assumed_inputs','2026-09-30',1.6);`);
 const app=createApp(file);const server=app.listen(0,'127.0.0.1');await new Promise(r=>server.once('listening',r));
 const base='http://127.0.0.1:'+server.address().port;
 try {
  const html=await (await fetch(base+'/corridor')).text();
  assert.match(html,/complete_assumed_inputs/);
  // Default (tanpa ?gi=) harus jatuh ke GI yang benar2 py fungsi DIST --
  // di fixture ini cuma DURIKOSAMBI, jadi dropdown tetap harus muncul.
  assert.match(html,/name="gi"/);
  const field=n=>html.match(new RegExp('name="'+n+'" value="([^"]+)"'))[1];
  const body=new URLSearchParams({token:field('token'),gi:field('gi'),key:field('key'),snapshot:field('snapshot'),state:'Perlu verifikasi',note:'<script>bad()</script>'});
  const saved=await fetch(base+'/corridor/review',{method:'POST',body,redirect:'manual'});assert.equal(saved.status,303);
  const next=await (await fetch(base+'/corridor')).text();assert.match(next,/&lt;script&gt;bad/);assert.doesNotMatch(next,/<script>bad/);
  const audit=new Database(file+'.reviews.db',{readonly:true});assert.equal(audit.prepare('SELECT count(*) n FROM review_event').get().n,1);audit.close();
  seed.exec("UPDATE calculation_context SET delay_s=1.2");
  assert.equal((await fetch(base+'/corridor/review',{method:'POST',body})).status,400);
  assert.match(await (await fetch(base+'/corridor')).text(),/Input\/hasil berubah/);
 } finally {await new Promise(r=>server.close(r));app.locals.db.close();seed.close();fs.rmSync(dir,{recursive:true,force:true});}
});

test('corridor is GI-driven, not a hardcoded 3-site corridor', async () => {
  // Sebelumnya WHERE di corridor.js hardcode site_name -- regresi diam2 saat
  // GROGOL BARU/GROGOL II digabung. Sekarang harus jalan utk GI manapun yg
  // benar2 py fungsi DIST, dan menampilkan GI lain sbg pilihan kosong yg jujur.
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'plms-corridor-'));
  const file = path.join(dir, 'test.db');
  const seed = new Database(file);
  seed.exec(fs.readFileSync(path.join(__dirname, '../../schema.sql'), 'utf8'));
  seed.exec(`INSERT INTO site(site_id,site_name) VALUES(1,'ANGKE'),(2,'CENGKARENG'),(3,'GI TANPA DIST');
   INSERT INTO substation(ss_id,site_id,voltage_kv) VALUES(1,1,150),(2,2,150),(3,3,150);
   INSERT INTO line(line_id,line_name,ss_from,ss_to,source) VALUES(1,'ANGKE-CENGKARENG',1,2,'DIGSILENT');
   INSERT INTO relay(relay_id,ss_id,line_id,bay,identity_key,identity_confidence,identity_status)
     VALUES(1,1,1,'PHT CENGKARENG#1','test-angke','HIGH','EXACT');
   INSERT INTO relay_function(relay_function_id,relay_id,function_type,coordination_class,source_logical)
     VALUES(1,1,'DIST','GRADED','DIST');`);
  const app = createApp(file);
  const server = app.listen(0, '127.0.0.1');
  await new Promise(r => server.once('listening', r));
  const base = 'http://127.0.0.1:' + server.address().port;
  try {
    const angke = await (await fetch(base + '/corridor?gi=ANGKE')).text();
    assert.match(angke, /ANGKE/);
    assert.match(angke, /CENGKARENG/);

    // GI valid tapi tanpa fungsi DIST -- empty state jujur, bukan error/crash.
    const empty = await (await fetch(base + '/corridor?gi=' + encodeURIComponent('GI TANPA DIST'))).text();
    assert.match(empty, /Belum ada fungsi DIST/);
    // Dropdown hanya berisi GI yg benar2 py fungsi DIST -- "GI TANPA DIST" itu
    // sendiri tidak boleh muncul sbg opsi meski site-nya ada di database.
    assert.doesNotMatch(empty, /<option[^>]*>GI TANPA DIST</);

    // gi tidak dikenal (bukan cuma tanpa DIST) jatuh ke default, bukan crash.
    const unknown = await (await fetch(base + '/corridor?gi=TIDAK-ADA')).status;
    assert.equal(unknown, 200);
  } finally {
    await new Promise(r => server.close(r));
    app.locals.db.close();
    seed.close();
    fs.rmSync(dir, { recursive: true, force: true });
  }
});
