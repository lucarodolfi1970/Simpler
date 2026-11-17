// A glass object with two sides put in the scene: no shader may be made inside a frame (they are all prepared before).
const { chromium } = require('playwright'); const http = require('http'), fs = require('fs'), path = require('path');
const root = process.argv[2] || '/tmp/lt/new'; const port = 9800 + Math.floor(Math.random() * 80);
const srv = http.createServer((q, r) => { const f = path.join(root, decodeURIComponent(q.url.split('?')[0])); fs.readFile(f, (e, d) => { if (e) { r.writeHead(404); r.end(); return; } r.writeHead(200, { 'Content-Type': f.endsWith('.js') ? 'text/javascript' : f.endsWith('.html') ? 'text/html' : 'application/octet-stream' }); r.end(d); }); }).listen(port, async () => {
  const b = await chromium.launch({ args: ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--ignore-gpu-blocklist'] });
  const pg = await b.newPage({ viewport: { width: 900, height: 600 } }); const logs = [];
  pg.on('console', (m) => logs.push(m.text()));
  await pg.exposeFunction('__hostLog', (t) => logs.push(String(t)));
  await pg.addInitScript(() => { window.chrome = window.chrome || {}; window.chrome.webview = { postMessage: (m) => { try { if (m && m.type === 'log') window.__hostLog(m.text); } catch (e) {} }, addEventListener() {}, removeEventListener() {} }; });
  await pg.goto(`http://localhost:${port}/viewer.html?test=1&glb=/scene.glb`); await pg.waitForFunction(() => window.simplerLoaded, null, { timeout: 90000 }); await pg.waitForTimeout(6000);
  const n0 = logs.length;
  await pg.evaluate(() => { const D = window.__dbg, T = D.THREE;
    const g = new T.Mesh(new T.BoxGeometry(2, 2, 2), new T.MeshPhysicalMaterial({ color: 0xffffff, transmission: 1, roughness: 0.05, thickness: 0.01, side: T.DoubleSide, transparent: true }));
    g.material.name = 'TestGlass'; g.position.copy(D.orbit.target); D.scene.add(g);
    const w = new T.Mesh(new T.BoxGeometry(1, 1, 1), new T.MeshPhysicalMaterial({ color: 0x88aaff, transmission: 0.9, side: T.DoubleSide })); w.material.name = 'TestWindow'; w.position.copy(D.orbit.target); w.position.x += 3; D.scene.add(w); });
  await pg.waitForTimeout(9000);
  const mine = logs.slice(n0).filter((l) => /inside a frame|slow frame|shaders ready/.test(l));
  for (const l of mine) console.log('   ' + l.slice(0, 230));
  const bad = mine.filter((l) => /inside a frame/.test(l) && !/BackgroundCubeMaterial|no name/.test(l));
  console.log(bad.length ? `FAIL: ${bad.length} shaders of materials made inside a frame` : 'ok: with glass in the scene no shader of a material is made inside a frame');
  await b.close(); srv.close(); process.exit(bad.length ? 1 : 0); });
