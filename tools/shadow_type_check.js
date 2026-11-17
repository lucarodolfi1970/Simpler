const { chromium } = require('playwright'); const http = require('http'), fs = require('fs'), path = require('path');
const root = process.argv[2]; const port = 9500 + Math.floor(Math.random() * 80);
const srv = http.createServer((q, r) => { const f = path.join(root, decodeURIComponent(q.url.split('?')[0])); fs.readFile(f, (e, d) => { if (e) { r.writeHead(404); r.end(); return; } r.writeHead(200, { 'Content-Type': f.endsWith('.js') ? 'text/javascript' : f.endsWith('.html') ? 'text/html' : 'application/octet-stream' }); r.end(d); }); }).listen(port, async () => {
  const b = await chromium.launch({ args: ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--ignore-gpu-blocklist'] });
  const pg = await b.newPage({ viewport: { width: 900, height: 600 } });
  await pg.addInitScript(() => { const g = HTMLCanvasElement.prototype.getContext; window.__links = 0; HTMLCanvasElement.prototype.getContext = function (t, ...a) { const gl = g.call(this, t, ...a); if (gl && gl.linkProgram && !gl.__w) { gl.__w = 1; const o = gl.linkProgram.bind(gl); gl.linkProgram = (p) => { window.__links++; return o(p); }; } return gl; }; });
  await pg.goto(`http://localhost:${port}/viewer.html?test=1&glb=/scene.glb`); await pg.waitForFunction(() => window.simplerLoaded, null, { timeout: 90000 });
  await pg.waitForTimeout(12000);
  const r = await pg.evaluate(() => { const by = {}; for (const p of window.__dbg.renderer.info.programs) { const k = String(p.cacheKey).split(','); let i = -1; for (let j = 0; j < k.length; j++) if (/^\d+$/.test(k[j]) && +k[j] > 8000000) i = j; const t = k[i - 6]; by[t] = (by[t] || 0) + 1; } return { by, links: window.__links, n: window.__dbg.renderer.info.programs.length, type: window.__dbg.renderer.shadowMap.type }; });
  console.log(root, JSON.stringify(r)); await b.close(); srv.close(); });
