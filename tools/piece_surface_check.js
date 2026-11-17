// A model put in the scene from the library (drawn from its prototype) must be a surface for the brush and for the area.
const { chromium } = require('playwright'); const http = require('http'), fs = require('fs'), path = require('path');
const root = process.argv[2] || '/tmp/lt/new'; const port = 9700 + Math.floor(Math.random() * 80);
const srv = http.createServer((q, r) => {
  const u = new URL(q.url, 'http://x');
  const cors = { 'Access-Control-Allow-Origin': '*' };
  if (u.pathname === '/eng/paint/proto') { r.writeHead(200, { 'Content-Type': 'application/json', ...cors }); r.end(JSON.stringify({ state: 'done', key: 'k1', file: 'modelA.glb' })); return; }
  if (u.pathname === '/eng/paint/proto.glb') { r.writeHead(200, { 'Content-Type': 'model/gltf-binary', ...cors }); r.end(fs.readFileSync(path.join(root, 'modelA.glb'))); return; }
  if (u.pathname.startsWith('/eng/')) { r.writeHead(200, { 'Content-Type': 'application/json', ...cors }); r.end('{}'); return; }
  const f = path.join(root, decodeURIComponent(u.pathname)); fs.readFile(f, (e, d) => { if (e) { r.writeHead(404); r.end(); return; } r.writeHead(200, { 'Content-Type': f.endsWith('.js') ? 'text/javascript' : f.endsWith('.html') ? 'text/html' : 'application/octet-stream' }); r.end(d); });
}).listen(port, async () => {
  const b = await chromium.launch({ args: ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--ignore-gpu-blocklist'] });
  const pg = await b.newPage({ viewport: { width: 900, height: 600 } }); const errs = []; pg.on('pageerror', (e) => errs.push(e.message));
  await pg.goto(`http://localhost:${port}/viewer.html?test=1&glb=/scene.glb&engine=${encodeURIComponent(`http://localhost:${port}/eng/`)}`);
  await pg.waitForFunction(() => window.simplerLoaded, null, { timeout: 90000 }); await pg.waitForTimeout(3000);
  const has = await pg.evaluate(() => !!(window.__dbg.scatterAdopt && window.__dbg.surfaceHits));
  if (!has) { console.log('FAIL: the test hook has no scatterAdopt / surfaceHits'); await b.close(); srv.close(); process.exit(1); }
  // the piece far from everything else of the scene, 500 m up: only it can be hit there
  await pg.evaluate(() => { const D = window.__dbg, T = D.THREE; const n = new T.Object3D(); n.name = 'library mountain'; n.userData.simpler_id = 'piece1';
    n.position.set(1000, 1000, 500); n.scale.setScalar(3); D.root.add(n); n.updateMatrixWorld(true); D.byId.set('piece1', n); D.scatterAdopt(n, 'modelA', false, 'k1'); window.__n = n; });
  await pg.waitForFunction(() => { const P = window.__dbg.scatter.protos.get('k1'); return P && P.state === 'ready'; }, null, { timeout: 60000 }).catch(() => {});
  const r = await pg.evaluate(() => { const D = window.__dbg, T = D.THREE, n = window.__n; const P = D.scatter.protos.get('k1');
    if (!P || P.state !== 'ready') return { err: 'prototype not ready: ' + (P && P.state) };
    const c = P.center.clone().applyMatrix4(n.matrixWorld), R = P.radius * 3;
    const rc = new T.Raycaster(c.clone().add(new T.Vector3(0, 0, R * 3)), new T.Vector3(0, 0, -1));
    const hits = D.surfaceHits(rc);
    const top = hits[0];
    const ps = D.paintSurfaces(c, R * 0.5);
    const as = D.areaSurfaces(c.x - R, c.y - R, c.x + R, c.y + R);
    let owner = null; if (top) for (let p = top.object; p; p = p.parent) if (p.userData && p.userData.simpler_id) { owner = p.userData.simpler_id; break; }
    // hidden: no longer a surface
    n.visible = false; const hid = D.surfaceHits(rc).filter((h) => { for (let p = h.object; p; p = p.parent) if (p === n) return true; return false; }).length; n.visible = true;
    // the piece being the distribution painted into would not count; a normal mesh elsewhere still does
    const rc2 = new T.Raycaster(new T.Vector3(D.orbit.target.x, D.orbit.target.y, 500), new T.Vector3(0, 0, -1));
    return { hits: hits.length, dz: top ? +(top.point.z - c.z).toFixed(3) : null, R: +R.toFixed(3), owner, paint: ps.length, area: as.length, hid, scene: D.surfaceHits(rc2).length, inScene: n.children.length }; });
  let bad = 0;
  const say = (ok, t) => { if (!ok) bad++; console.log((ok ? 'ok   ' : 'BAD  ') + t); };
  if (r.err) say(false, r.err); else {
    say(r.hits > 0 && Math.abs(r.dz) <= r.R, `the ray from above hits the library model (${r.hits} hits, ${r.dz} m from its centre, radius ${r.R})`);
    say(r.owner === 'piece1', `the surface hit belongs to the model (${r.owner})`);
    say(r.paint > 0, `the brush has its surfaces (${r.paint})`);
    say(r.area > 0, `the area has its surfaces (${r.area})`);
    say(r.hid === 0, `hidden: not a surface (${r.hid})`);
    say(r.scene > 0, `a normal mesh of the scene is still a surface (${r.scene})`);
    say(r.inScene === 0, `nothing was added to the scene (${r.inScene} children)`);
  }
  for (const e of errs) { console.log('PAGEERROR ' + e); bad++; }
  console.log(bad ? 'FAIL: a model from the library is not a surface for the brush' : 'ok: a model from the library is a surface for the brush and the area');
  await b.close(); srv.close(); process.exit(bad ? 1 : 0); });
