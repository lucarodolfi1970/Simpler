// Real-browser check (Chromium, software GL): the view must not prepare shaders again when a light is copied or deleted,
// nor when a car with a glowing area light is moved. Run: NODE_PATH=$(npm root -g) node tools/shader_check.js  (needs `playwright`)
const { chromium } = require('playwright');
const http = require('http'), fs = require('fs'), path = require('path');
const root = process.env.WEB || path.resolve(__dirname, '../app/Simpler/web');
const srv = http.createServer((q, r) => { const f = path.join(root, decodeURIComponent(q.url.split('?')[0])); fs.readFile(f, (e, d) => { if (e) { r.writeHead(404); r.end(); } else { r.writeHead(200, { 'content-type': f.endsWith('.js') ? 'text/javascript' : f.endsWith('.html') ? 'text/html' : 'application/octet-stream' }); r.end(d); } }); }).listen(8123, async () => {
  const b = await chromium.launch({ args: ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--ignore-gpu-blocklist'] });
  const pg = await b.newPage();
  const logs = [];
  pg.on('console', (m) => logs.push(m.text()));
  pg.on('pageerror', (e) => logs.push('PAGEERROR ' + e.message));
  await pg.goto('http://localhost:8123/viewer.html?test=1');
  await pg.waitForFunction(() => window.__dbg && window.__dbg.renderer, null, { timeout: 30000 });
  await pg.evaluate(() => { const D = window.__dbg, T = D.THREE;
    window.mk = (id, x) => { const g = new T.Group(); g.userData.simpler_id = id; g.position.set(x, 0, 0);
      D.scene.add(g); D.byId.set(id, g); return g; };
    for (let i = 0; i < 6; i++) { const g = window.mk('m' + i, i * 2);
      const m = new T.Mesh(new T.BoxGeometry(1, 1, 1), new T.MeshStandardMaterial({ color: 0x884400 + i * 99, roughness: 0.3 + i * 0.1 }));
      m.castShadow = m.receiveShadow = true; g.add(m); }
    window.sc = { n: () => D.renderer.info.programs.length };
  });
  const wait = (ms) => pg.waitForTimeout(ms);
  const settle = async () => { for (let i = 0; i < 60; i++) { await wait(500); const busy = await pg.evaluate(() => window.__dbg.shaderPrep.busy); if (!busy && i > 3) break; } await wait(1500); };
  await settle();
  const stat = () => pg.evaluate(() => ({ progs: window.__dbg.renderer.info.programs.length, rev: window.__dbg.shaderRev, sig: window.__dbg.lightSig() }));
  const count = (re) => logs.filter((l) => re.test(l)).length;
  const sync = (objs) => pg.evaluate((o) => window.__dbg.onMessage({ type: 'sync', objects: o }), objs);
  const res = [];
  const objs = {};   // id -> sync item
  const push = () => pg.evaluate((o) => window.__dbg.onMessage({ type: 'sync', objects: o }), Object.values(objs));
  const step = async (name, fn) => { const l0 = logs.length, s0 = await stat(); await fn(); await settle(); const s1 = await stat();
    const prep = logs.slice(l0).filter((l) => /shaders ready|lights of the view|slow frame/.test(l));
    res.push({ name, newPrograms: s1.progs - s0.progs, prepLines: prep.length, sig: s1.sig, lines: prep.map((l) => l.slice(0, 140)) }); };
  const addLight = async (id, kind, extra) => { await pg.evaluate((id) => window.mk(id, 0), id);
    objs[id] = { id, kind, light: Object.assign({ color: [1, 1, 1], power: 800, shadow: false, coneAngle: 45, radius: 0.1 }, extra || {}) }; await push(); };
  await step('first spot light (may cost one preparation)', () => addLight('L1', 'spot'));
  await step('first point light (may cost one preparation)', () => addLight('L2', 'point'));
  await step('COPY the point light (must cost nothing)', () => addLight('L3', 'point'));
  await step('copy it again', () => addLight('L4', 'point'));
  await step('delete one copy', async () => { delete objs.L3; await push(); });
  await step('glow light, first time (may cost one preparation)', () => addLight('G', 'area', { visibleCamera: true, width: 20, height: 10, shape: 'RECTANGLE' }));
  await step('MOVE the car with the glow light 5 times (must cost nothing)', async () => {
    for (let k = 1; k <= 5; k++) { objs.G.matrix = [1,0,0,0, 0,1,0,0, 0,0,1,0, k * 0.5,0,0,1]; await push(); await wait(400); } });
  await step('SMARTVIEW on (info)', async () => { await pg.evaluate(() => window.__dbg.setSmartView(true)); });
  await step('SmartView: copy a point light', () => addLight('L5', 'point'));
  await step('SmartView: copy it again', () => addLight('L6', 'point'));
  await step('SmartView: delete a light', async () => { delete objs.L5; await push(); });
  await step('SMARTVIEW off (info)', async () => { await pg.evaluate(() => window.__dbg.setSmartView(false)); });
  await step('after SmartView, first copy (info: spare lights counted again)', () => addLight('L7', 'point'));
  await step('after SmartView: copy a light (must cost nothing)', () => addLight('L8', 'point'));
  await step('after SmartView: delete a light (must cost nothing)', async () => { delete objs.L6; await push(); });
  const fps = await pg.evaluate(async () => { const t0 = performance.now(); let n = 0; const D = window.__dbg;
    while (performance.now() - t0 < 3000) { D.camera.position.x += 0.01; D.onMessage({ type: 'ping' }); await new Promise((r) => requestAnimationFrame(r)); n++; } return n / 3; });
  console.log('frames/s with the lights above (software GL, only to compare versions): ' + fps.toFixed(1));
  // the same materials made again after the old ones were thrown away (a car replaced, a copy, a reload of the scene): the
  // programs must be found ready, not compiled again (the real cost: 0.5-1.5 s each on a slow driver)
  await pg.evaluate(() => { const gl = window.__dbg.renderer.getContext(); window.__links = 0; const o = gl.linkProgram.bind(gl); gl.linkProgram = (p) => { window.__links++; return o(p); }; });
  const links = () => pg.evaluate(() => window.__links);
  const mkCar = (tag) => pg.evaluate((tag) => { const D = window.__dbg, T = D.THREE, g = new T.Group(); g.name = 'car-' + tag;
    for (let i = 0; i < 8; i++) { const m = new T.Mesh(new T.BoxGeometry(), new T.MeshStandardMaterial({ color: 0x300000 + i * 4000, roughness: 0.1 + i * 0.07, flatShading: !!(i & 1), side: (i & 2) ? T.DoubleSide : T.FrontSide, alphaTest: (i & 4) ? 0.3 : 0 })); m.castShadow = m.receiveShadow = true; g.add(m); }
    D.scene.add(g); window['car_' + tag] = g; D.onMessage({ type: 'ping' }); }, tag);
  const dropCar = (tag) => pg.evaluate((tag) => { const D = window.__dbg, g = window['car_' + tag]; D.scene.remove(g);
    g.traverse((o) => { if (o.material) o.material.dispose(); if (o.geometry) o.geometry.dispose(); }); }, tag);
  let l0 = await links(); await mkCar('A'); await settle(); const first = (await links()) - l0;
  await dropCar('A'); await wait(7000); await settle();
  l0 = await links(); await mkCar('B'); await settle(); const again = (await links()) - l0;
  console.log(`info  a car of 10 materials: ${first} programs made the first time, ${again} made again after the first one was thrown away`);
  if (again > 1) res.push({ name: 'rebuilt materials: programs made again', newPrograms: again, prepLines: 0 });
  const bad = [];
  for (const r of res) if (/must cost nothing|copy it again|delete one|SmartView: |programs made again/.test(r.name) && (r.newPrograms > 0 || r.prepLines > 0)) bad.push(`${r.name}: ${r.newPrograms} new shaders, ${r.prepLines} preparations`);
  for (const r of res) console.log((/must cost nothing|copy it again|delete one|SmartView: |programs made again/.test(r.name) ? 'rule  ' : 'info  ') + r.name + ': ' + r.newPrograms + ' new shaders, ' + r.prepLines + ' preparations');
  if (logs.some((l) => /PAGEERROR|light reserve/.test(l))) bad.push('errors in the page');
  console.log(bad.length ? 'FAIL ' + bad.join(' | ') : 'ok: a copied or deleted light and a moved car with a glowing light make no shaders');
  process.exitCode = bad.length ? 1 : 0;
  await b.close(); srv.close();
});
