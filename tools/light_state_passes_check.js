const { chromium } = require('playwright'); const http = require('http'), fs = require('fs'), path = require('path');
const root = '/tmp/lt/new'; const port = 9600 + Math.floor(Math.random() * 80);
const srv = http.createServer((q, r) => { const f = path.join(root, decodeURIComponent(q.url.split('?')[0])); fs.readFile(f, (e, d) => { if (e) { r.writeHead(404); r.end(); return; } r.writeHead(200, { 'Content-Type': f.endsWith('.js') ? 'text/javascript' : f.endsWith('.html') ? 'text/html' : 'application/octet-stream' }); r.end(d); }); }).listen(port, async () => {
  const b = await chromium.launch({ args: ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--ignore-gpu-blocklist'] });
  const pg = await b.newPage({ viewport: { width: 900, height: 600 } });
  await pg.goto(`http://localhost:${port}/viewer.html?test=1&glb=/scene.glb`); await pg.waitForFunction(() => window.simplerLoaded, null, { timeout: 90000 }); await pg.waitForTimeout(5000);
  await pg.evaluate(() => { const D = window.__dbg, R = D.renderer, o = R.render.bind(R); window.__sigs = {};
    R.render = (sc, cam) => { if (sc.isScene && sc.children.length > 3) { const c = {}; sc.traverseVisible((x) => { if (x.isLight && x.layers.test(cam.layers)) { const k = x.type.replace('Light', '') + (x.castShadow ? 's' : ''); c[k] = (c[k] || 0) + 1; } });
      const rt = R.getRenderTarget(); const k = JSON.stringify(c) + ' tone' + R.toneMapping + (rt ? ' RT' : ' screen') + (sc.overrideMaterial ? ' override' : ''); window.__sigs[k] = (window.__sigs[k] || 0) + 1; } return o(sc, cam); }; });
  const D = (m) => pg.evaluate((m) => window.__dbg.onMessage(m), m);
  const ids = await pg.evaluate(() => [...window.__dbg.byId.keys()]);
  await D({ type: 'select', ids: [ids.find((x) => x === 'b219ddf45c77') || ids[0]], primary: 'b219ddf45c77' }); await pg.waitForTimeout(1500);
  await D({ type: 'snapshot', id: 'a' }); await pg.waitForTimeout(800);
  await pg.mouse.move(450, 300); await pg.mouse.down(); await pg.mouse.move(500, 320, { steps: 4 }); await pg.mouse.up(); await pg.waitForTimeout(1200);
  await D({ type: 'boxMode', on: true }); await pg.waitForTimeout(1200); await D({ type: 'boxMode', on: false }); await pg.waitForTimeout(1200);
  console.log(JSON.stringify(await pg.evaluate(() => window.__sigs), null, 1)); await b.close(); srv.close(); });
