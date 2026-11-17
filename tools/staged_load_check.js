// A scene whose lights arrive in steps (the lamps of the distributions, the lights of the scene, the spare lights: opening a street)
// must make its shaders ONCE, not once per step. Run: WEB=<web folder> NODE_PATH=$(npm root -g) node tools/staged_load_check.js
const { chromium } = require('playwright'); const http = require('http'), fs = require('fs'), path = require('path');
const root = process.env.WEB || path.resolve(__dirname, '../app/Simpler/web'); const port = 8700 + Math.floor(Math.random() * 200);
const srv = http.createServer((q, r) => { const f = path.join(root, decodeURIComponent(q.url.split('?')[0])); fs.readFile(f, (e, d) => { if (e) { r.writeHead(404); r.end(); return; }
  r.writeHead(200, { 'Content-Type': f.endsWith('.js') ? 'text/javascript' : f.endsWith('.html') ? 'text/html' : 'application/octet-stream' }); r.end(d); }); }).listen(port, async () => {
  const b = await chromium.launch({ args: ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--ignore-gpu-blocklist'] });
  const pg = await b.newPage(); const logs = []; pg.on('console', (m) => logs.push(m.text())); pg.on('pageerror', (e) => logs.push('PAGEERROR ' + e.message));
  await pg.goto(`http://localhost:${port}/viewer.html?test=1`); await pg.waitForFunction(() => window.__dbg && window.__dbg.renderer, null, { timeout: 60000 });
  await pg.evaluate(() => { const D = window.__dbg, T = D.THREE;
    window.mk = (id, x) => { const g = new T.Group(); g.userData.simpler_id = id; g.position.set(x, 0, 0); D.scene.add(g); D.byId.set(id, g); return g; };
    for (let i = 0; i < 6; i++) { const g = window.mk('m' + i, i * 2); const m = new T.Mesh(new T.BoxGeometry(1, 1, 1), new T.MeshStandardMaterial({ color: 0x884400 + i * 99, roughness: 0.3 + i * 0.1 })); m.castShadow = m.receiveShadow = true; g.add(m); } });
  const wait = (ms) => pg.waitForTimeout(ms);
  const settle = async () => { for (let i = 0; i < 100; i++) { await wait(400); if (!(await pg.evaluate(() => window.__dbg.shaderPrep.busy)) && i > 2) return; } };
  await settle();
  const objs = {}; const push = () => pg.evaluate((o) => window.__dbg.onMessage({ type: 'sync', objects: o }), Object.values(objs));
  const add = async (id, kind, extra) => { await pg.evaluate((id) => window.mk(id, 0), id); objs[id] = { id, kind, light: Object.assign({ color: [1, 1, 1], power: 800, shadow: false, coneAngle: 45, radius: 0.1 }, extra || {}) }; await push(); };
  const l0 = logs.length; const p0 = await pg.evaluate(() => window.__dbg.renderer.info.programs.length);
  // three steps 250 ms apart (timed inside the page: the pushes of this test must not wait for each other), like the parts of a scene arriving
  const L0 = (id, kind, extra) => ({ id, kind, light: Object.assign({ color: [1, 1, 1], power: 800, shadow: false, coneAngle: 45, radius: 0.1 }, extra || {}) });
  await pg.evaluate(async (steps) => { const D = window.__dbg; const all = [];
    for (const st of steps) { for (const o of st) { window.mk(o.id, 0); all.push(o); } D.onMessage({ type: 'sync', objects: all.slice() }); await new Promise((r) => setTimeout(r, 250)); } },
    [[L0('S1', 'sun', { power: 3, shadow: true })], [L0('T1', 'spot', { shadow: true }), L0('T2', 'spot')], [L0('P1', 'point'), L0('P2', 'point'), L0('P3', 'point', { shadow: true })]]);
  await settle();
  const L = logs.slice(l0); const rounds = L.filter((l) => /lights of the view:/.test(l)).length; const ready = L.filter((l) => /shaders ready/.test(l)).length;
  const made = (await pg.evaluate(() => window.__dbg.renderer.info.programs.length)) - p0;
  console.log(`steps of lights: 3, rounds of «lights of the view»: ${rounds}, «shaders ready» lines: ${ready}, shaders made: ${made}`);
  const bad = rounds > 1 || logs.some((l) => /PAGEERROR/.test(l));
  console.log(bad ? 'FAIL: more than one round for lights arriving in steps' : 'ok: one round for lights arriving in steps');
  process.exitCode = bad ? 1 : 0; await b.close(); srv.close();
});
