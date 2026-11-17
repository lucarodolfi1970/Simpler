// Rain turned on step by step with glass in the scene: no shader of a material may be made inside a frame.
const { chromium } = require('playwright'); const http = require('http'), fs = require('fs'), path = require('path');
const root = process.argv[2] || '/tmp/lt/new'; const port = 9500 + Math.floor(Math.random() * 80);
const srv = http.createServer((q, r) => { const f = path.join(root, decodeURIComponent(q.url.split('?')[0])); fs.readFile(f, (e, d) => { if (e) { r.writeHead(404); r.end(); return; } r.writeHead(200, { 'Content-Type': f.endsWith('.js') ? 'text/javascript' : f.endsWith('.html') ? 'text/html' : 'application/octet-stream' }); r.end(d); }); }).listen(port, async () => {
  const b = await chromium.launch({ args: ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--ignore-gpu-blocklist'] });
  const pg = await b.newPage({ viewport: { width: 900, height: 600 } }); const logs = [];
  pg.on('console', (m) => logs.push(m.text())); pg.on('pageerror', (e) => logs.push('PAGEERROR ' + e.message));
  await pg.exposeFunction('__hostLog', (t) => logs.push(String(t)));
  await pg.addInitScript(() => { window.chrome = window.chrome || {}; window.chrome.webview = { postMessage: (m) => { try { if (m && m.type === 'log') window.__hostLog(m.text); } catch (e) {} }, addEventListener() {}, removeEventListener() {} }; });
  await pg.goto(`http://localhost:${port}/viewer.html?test=1&glb=/scene.glb`); await pg.waitForFunction(() => window.simplerLoaded, null, { timeout: 90000 }); await pg.waitForTimeout(5000);
  await pg.evaluate(() => { const D = window.__dbg, T = D.THREE;
    const g = new T.Mesh(new T.BoxGeometry(2, 2, 2), new T.MeshPhysicalMaterial({ color: 0xffffff, transmission: 1, roughness: 0.05, thickness: 0.01, side: T.DoubleSide, transparent: true }));
    g.material.name = 'TestGlass'; g.position.copy(D.orbit.target); D.scene.add(g);
    const w = new T.Mesh(new T.SphereGeometry(0.5), new T.MeshPhysicalMaterial({ color: 0xffffff, transmission: 0.9 })); w.material.name = 'TestBulb'; w.position.copy(D.orbit.target); w.position.x += 3; D.scene.add(w); });
  await pg.waitForTimeout(9000);
  // every frame: programs linked inside renderer.render of the page's own tick are what the log calls «inside a frame»
  const steps = [
    ['wet', { wet: 0.786 }], ['puddles', { wet: 0.786, puddles: 0.5 }],
    ['drops, beads on', { wet: 0.786, puddles: 0.5, drop: true, splash: true, beads: true, dropAmount: 0.5, beadAmount: 0.55, beadSize: 0.45, beadBig: 0.3, beadRivul: 0.4, beadFilm: 0.5, puddleRings: 0.5 }],
    ['beads off', { wet: 0.786, puddles: 0.5, drop: true, beads: false, dropAmount: 0.5, puddleRings: 0.5 }],
    ['drops off', { wet: 0.786, puddles: 0.5, drop: false, beads: true, beadAmount: 0.55 }],
    ['rain off', null], ['all on at once', { wet: 0.5, puddles: 0.3, drop: true, beads: true, dropAmount: 0.7, beadAmount: 0.5, puddleRings: 0.7 }], ['rain off again', null],
  ];
  let bad = 0;
  for (const [name, rain] of steps) {
    const n0 = logs.length;
    await pg.evaluate((rain) => window.__dbg.onMessage({ type: 'rainPreview', mode: 'sky', rain, snow: null }), rain);
    await pg.waitForTimeout(7000);
    const mine = logs.slice(n0).filter((l) => /inside a frame|slow frame|shaders ready|PAGEERROR/.test(l));
    const b2 = mine.filter((l) => /PAGEERROR/.test(l) || (/inside a frame/.test(l) && !/BackgroundCubeMaterial|no name/.test(l)));
    bad += b2.length;
    console.log((b2.length ? 'BAD  ' : 'ok   ') + name); for (const l of mine) console.log('       ' + l.replace(/^\[to host\] /, '').slice(0, 220));
  }
  console.log(bad ? `FAIL: ${bad} shaders of materials made inside a frame while the rain changed` : 'ok: the rain changes and no shader of a material is made inside a frame');
  await b.close(); srv.close(); process.exit(bad ? 1 : 0); });
