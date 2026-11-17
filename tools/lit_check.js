// the lights chosen by the budget must really light the view (and the ones left out must not break it)
const { chromium } = require('playwright'); const http = require('http'), fs = require('fs'), path = require('path');
const root = process.env.WEB; const port = 8900 + Math.floor(Math.random() * 90);
const srv = http.createServer((q, r) => { const f = path.join(root, decodeURIComponent(q.url.split('?')[0])); fs.readFile(f, (e, d) => { if (e) { r.writeHead(404); r.end(); return; } r.writeHead(200, { 'Content-Type': f.endsWith('.js') ? 'text/javascript' : f.endsWith('.html') ? 'text/html' : 'application/octet-stream' }); r.end(d); }); }).listen(port, async () => {
  const b = await chromium.launch({ args: ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--ignore-gpu-blocklist'] });
  const pg = await b.newPage({ viewport: { width: 500, height: 400 } }); const logs = []; pg.on('console', (m) => logs.push(m.text())); pg.on('pageerror', (e) => logs.push('PAGEERROR ' + e.message));
  await pg.goto(`http://localhost:${port}/viewer.html?test=1`); await pg.waitForFunction(() => window.__dbg && window.__dbg.renderer, null, { timeout: 60000 });
  await pg.evaluate(() => { const D = window.__dbg, T = D.THREE; window.mk = (id, x, y = 0) => { const g = new T.Group(); g.userData.simpler_id = id; g.position.set(x, y, 0); D.scene.add(g); D.byId.set(id, g); return g; };
    const g = window.mk('box', 0); const m = new T.Mesh(new T.BoxGeometry(2, 2, 2), new T.MeshStandardMaterial({ color: 0xcccccc, roughness: 0.6 })); g.add(m); D.camera.position.set(0, -8, 3); D.camera.lookAt(0, 0, 0); D.orbit && D.orbit.update && D.orbit.update(); });
  const wait = (ms) => pg.waitForTimeout(ms); const settle = async () => { for (let i = 0; i < 60; i++) { await wait(400); if (!(await pg.evaluate(() => window.__dbg.shaderPrep.busy)) && i > 2) return; } };
  const objs = {}; const push = () => pg.evaluate((o) => window.__dbg.onMessage({ type: 'sync', objects: o }), Object.values(objs));
  const lum = async () => { await wait(600); const buf = await pg.screenshot(); return pg.evaluate(async (b64) => { const img = new Image(); img.src = 'data:image/png;base64,' + b64; await img.decode(); const c = document.createElement('canvas'); c.width = 500; c.height = 400; const x = c.getContext('2d'); x.drawImage(img, 0, 0); const d = x.getImageData(150, 100, 200, 200).data; let s = 0; for (let i = 0; i < d.length; i += 4) s += d[i] + d[i + 1] + d[i + 2]; return s / (d.length / 4 * 3); }, buf.toString('base64')); };
  await settle(); const base = await lum();
  // 1) ONE point light close to the box: must brighten the view
  await pg.evaluate(() => window.mk('P', 0, -3)); objs.P = { id: 'P', kind: 'point', light: { color: [1, 1, 1], power: 3000, shadow: false, radius: 0.1 } }; await push(); await settle();
  const one = await lum();
  // 2) the same near light among 14 far and stronger-looking ones: the near one must still be chosen (nearest wins), view as bright
  for (let i = 0; i < 14; i++) { await pg.evaluate((i) => window.mk('F' + i, 200 + i * 5, 200), i); objs['F' + i] = { id: 'F' + i, kind: 'point', light: { color: [1, 1, 1], power: 4000, shadow: false, radius: 0.1 } }; } await push(); await settle();
  const many = await lum();
  const vis = await pg.evaluate(() => [...window.__dbg.lights.values()].filter((L) => L.light.visible).length);
  console.log(`brightness: no light ${base.toFixed(1)}, one near light ${one.toFixed(1)}, with 14 more far lights ${many.toFixed(1)}; lights visible in the view: ${vis} of 15`);
  const bad = []; if (!(one > base + 5)) bad.push('a point light does not light the view'); if (!(many > base + 5)) bad.push('the near light was lost among the far ones'); if (vis > 4) bad.push('budget not applied'); if (logs.some((l) => /PAGEERROR|light budget/.test(l))) bad.push('errors in the page');
  console.log(bad.length ? 'FAIL ' + bad.join(' | ') : 'ok: the chosen lights light the view'); process.exitCode = bad.length ? 1 : 0; await b.close(); srv.close(); });
