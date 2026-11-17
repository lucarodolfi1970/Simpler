// Real-browser check (Chromium, software GL) of the day's waits: a change of the ambience (lamps lit/unlit), the fill light,
// the stand-in sun when the scene gets its first light / loses its last, and a change of order in the list of lights must
// NOT make shaders again. Run: WEB=<web folder> NODE_PATH=$(npm root -g) node tools/lights_state_check.js
const { chromium } = require('playwright');
const http = require('http'), fs = require('fs'), path = require('path');
const root = process.env.WEB || path.resolve(__dirname, '../app/Simpler/web');
const port = 8200 + Math.floor(Math.random() * 500);
const srv = http.createServer((q, r) => { const f = path.join(root, decodeURIComponent(q.url.split('?')[0])); fs.readFile(f, (e, d) => { if (e) { r.writeHead(404); r.end(); return; }
  r.writeHead(200, { 'Content-Type': f.endsWith('.js') ? 'text/javascript' : f.endsWith('.html') ? 'text/html' : 'application/octet-stream' }); r.end(d); }); }).listen(port, async () => {
  const b = await chromium.launch({ args: ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--ignore-gpu-blocklist'] });
  const pg = await b.newPage(); const logs = [];
  pg.on('console', (m) => logs.push(m.text())); pg.on('pageerror', (e) => logs.push('PAGEERROR ' + e.message));
  await pg.goto(`http://localhost:${port}/viewer.html?test=1`);
  await pg.waitForFunction(() => window.__dbg && window.__dbg.renderer, null, { timeout: 60000 });
  await pg.evaluate(() => { const D = window.__dbg, T = D.THREE;
    window.mk = (id, x) => { const g = new T.Group(); g.userData.simpler_id = id; g.position.set(x, 0, 0); D.scene.add(g); D.byId.set(id, g); return g; };
    for (let i = 0; i < 6; i++) { const g = window.mk('m' + i, i * 2);
      const m = new T.Mesh(new T.BoxGeometry(1, 1, 1), new T.MeshStandardMaterial({ color: 0x884400 + i * 99, roughness: 0.3 + i * 0.1 }));
      m.castShadow = m.receiveShadow = true; g.add(m); } });
  const wait = (ms) => pg.waitForTimeout(ms);
  const settle = async () => { for (let i = 0; i < 80; i++) { await wait(400); const busy = await pg.evaluate(() => window.__dbg.shaderPrep.busy); if (!busy && i > 2) return; } };
  const stat = () => pg.evaluate(() => ({ progs: window.__dbg.renderer.info.programs.length, sig: window.__dbg.lightSig() }));
  const objs = {};
  const push = () => pg.evaluate((o) => window.__dbg.onMessage({ type: 'sync', objects: o }), Object.values(objs));
  const msg = (m) => pg.evaluate((m) => window.__dbg.onMessage(m), m);
  const res = [];
  const step = async (name, rule, fn) => { const l0 = logs.length, s0 = await stat(); await fn(); await settle(); const s1 = await stat();
    const prep = logs.slice(l0).filter((l) => /shaders ready|slow frame/.test(l));   // (a check that finds nothing new takes milliseconds and is not logged)
    res.push({ name, rule, newPrograms: s1.progs - s0.progs, prepLines: prep.length, sig0: s0.sig, sig1: s1.sig }); };
  const add = async (id, kind, extra) => { await pg.evaluate((id) => window.mk(id, 0), id);
    objs[id] = { id, kind, light: Object.assign({ color: [1, 1, 1], power: 800, shadow: false, coneAngle: 45, radius: 0.1 }, extra || {}) }; await push(); };
  await settle();
  // the working set of a night street: lamps with and without shadows, a sun, the fill light
  await step('build the scene (info)', false, async () => {
    await add('S1', 'sun', { power: 3, shadow: true });
    await add('P1', 'point', { shadow: true }); await add('P2', 'point'); await add('P3', 'point');
    await add('T1', 'spot', { shadow: true }); await add('T2', 'spot');
    await msg({ type: 'fill', fraction: 0.4, ev: 0 }); });
  // a first pass of every state, so what follows is a repetition (the first time a state exists may cost a preparation)
  const lit = async (ids, on) => { for (const id of ids) objs[id].light.lit = on; await push(); };
  await step('warm up: night (info)', false, () => lit(['P1', 'T1', 'P2'], true));
  await step('warm up: day (info)', false, () => lit(['P1', 'T1', 'P2'], false));
  for (let i = 1; i <= 3; i++) {
    await step(`DAY -> NIGHT #${i}: lamps lit (shadowed point and spot too)`, true, () => lit(['P1', 'T1', 'P2'], true));
    await step(`NIGHT -> DAY #${i}: lamps unlit`, true, () => lit(['P1', 'T1', 'P2'], false));
  }
  await step('switch one shadowed lamp off by hand and on again', true, async () => { await lit(['P1'], false); await lit(['P1'], true); });
  await step('fill light off', true, () => msg({ type: 'fill', fraction: 0, ev: 0 }));
  await step('fill light on again', true, () => msg({ type: 'fill', fraction: 0.6, ev: 0 }));
  await step('fill light change strength', true, () => msg({ type: 'fill', fraction: 0.2, ev: 1 }));
  await step('a light deleted and made again (the order of the list changes)', true, async () => { delete objs.P3; await push(); objs.P3 = { id: 'P3', kind: 'point', light: { color: [1, 1, 1], power: 800, shadow: false, coneAngle: 45, radius: 0.1 } }; await push(); });
  // the scene with NO light at all (the stand-in sun shows) and back
  await step('delete EVERY light (stand-in sun comes) (info: only the first time)', false, async () => { for (const k of Object.keys(objs)) delete objs[k]; await push(); });
  await step('first light again after none (info: a state not seen before costs once)', false, () => add('S1', 'sun', { power: 3, shadow: true }));
  for (let i = 1; i <= 3; i++) {
    await step(`delete it: back to no light #${i}`, i > 1, async () => { delete objs.S1; await push(); });
    await step(`add it again #${i}`, true, () => add('S1', 'sun', { power: 3, shadow: true }));
  }
  // (the view allows 4 lights with shadow at most: S1 + N1 + N3 + N5)
  // what the user does most: a new light, with shadow (the default), of every kind, one after the other
  await step('NEW shadowed point light #1', true, () => add('N1', 'point', { shadow: true }));
  await step('NEW plain point light #2', true, () => add('N2', 'point'));
  await step('NEW shadowed spot light #1', true, () => add('N3', 'spot', { shadow: true }));
  await step('NEW plain spot light #2', true, () => add('N4', 'spot'));
  await step('NEW sun with shadow #2', true, () => add('N5', 'sun', { power: 3, shadow: true }));
  await step('NEW plain point light #6', true, () => add('N6', 'point'));
  await step('NEW plain point light #7', true, () => add('N7', 'point'));
  await step('NEW plain point light #8', true, () => add('N8', 'point'));
  await step('NEW plain point light #9 (info: goes over the step of 8 lights once)', false, () => add('N9', 'point'));
  await step('NEW plain point light #10', false, () => add('N10', 'point'));
  const bad = [];
  for (const r of res) console.log((r.rule ? 'rule  ' : 'info  ') + r.name + ': ' + r.newPrograms + ' new shaders, ' + r.prepLines + ' preparations');
  for (const r of res) if (r.rule && (r.newPrograms > 0 || r.prepLines > 0)) console.log('   ' + r.name + '\n     ' + r.sig0 + '\n  -> ' + r.sig1);
  for (const r of res) if (r.rule && (r.newPrograms > 0 || r.prepLines > 0)) bad.push(`${r.name}: ${r.newPrograms} new shaders, ${r.prepLines} preparations`);
  if (logs.some((l) => /PAGEERROR|light reserve/.test(l))) { bad.push('errors in the page'); console.log(logs.filter((l) => /PAGEERROR|light reserve/.test(l)).slice(0, 4).join('\n')); }
  console.log(bad.length ? 'FAIL (' + bad.length + '): ' + bad.join(' | ') : 'ok: none of these changes makes shaders again');
  process.exitCode = bad.length ? 1 : 0; await b.close(); srv.close();
});
