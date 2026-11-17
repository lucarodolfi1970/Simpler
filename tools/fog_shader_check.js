// Fog on and off: not one new shader (the view always has its fog, at density 0 with none).
const { chromium } = require('playwright'); const http = require('http'), fs = require('fs'), path = require('path');
const root = process.argv[2] || '/tmp/lt/new'; const port = 9600 + Math.floor(Math.random() * 80);
const srv = http.createServer((q, r) => { const f = path.join(root, decodeURIComponent(q.url.split('?')[0])); fs.readFile(f, (e, d) => { if (e) { r.writeHead(404); r.end(); return; } r.writeHead(200, { 'Content-Type': f.endsWith('.js') ? 'text/javascript' : f.endsWith('.html') ? 'text/html' : 'application/octet-stream' }); r.end(d); }); }).listen(port, async () => {
  const b = await chromium.launch({ args: ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--ignore-gpu-blocklist'] });
  const pg = await b.newPage({ viewport: { width: 900, height: 600 } }); const errs = []; pg.on('pageerror', (e) => errs.push(e.message));
  await pg.goto(`http://localhost:${port}/viewer.html?test=1&glb=/scene.glb`); await pg.waitForFunction(() => window.simplerLoaded, null, { timeout: 90000 }); await pg.waitForTimeout(8000);
  const info = (vis) => ({ evTotal: 0, fog: vis ? { visibility: vis, color: [0.7, 0.75, 0.8], height: null, falloff: null, start: 0, haze2: 0 } : { visibility: 0, color: [0, 0, 0] } });
  let bad = 0;
  const n = () => pg.evaluate(() => window.__dbg.renderer.info.programs.length);
  const has = await pg.evaluate(() => typeof window.__dbg.ambApply === 'function');
  if (!has) { console.log('FAIL: no ambApply in the test hook'); process.exit(1); }
  for (const [name, vis] of [['fog on (260 m)', 260], ['fog off', 0], ['thick fog (40 m)', 40], ['fog off again', 0]]) {
    const n0 = await n();
    const px0 = await pg.evaluate((i) => { const D = window.__dbg; D.ambApply(i); D.renderer.render(D.scene, D.camera); const gl = D.renderer.getContext(); const p = new Uint8Array(4); gl.readPixels(450, 200, 1, 1, gl.RGBA, gl.UNSIGNED_BYTE, p); return [...p]; }, info(vis));
    await pg.waitForTimeout(2500);
    const n1 = await n(); const st = await pg.evaluate(() => ({ is: !!(window.__dbg.scene.fog && window.__dbg.scene.fog.isFogExp2), d: window.__dbg.scene.fog && window.__dbg.scene.fog.density }));
    const ok = n1 === n0 && st.is && (vis ? Math.abs(st.d - 1 / vis) < 1e-9 : st.d === 0); if (!ok) bad++;
    console.log((ok ? 'ok   ' : 'BAD  ') + `${name}: new shaders ${n1 - n0}, fog density ${st.d}, a pixel of the picture ${px0}`);
  }
  for (const e of errs) { console.log('PAGEERROR ' + e); bad++; }
  console.log(bad ? 'FAIL: the fog makes new shaders' : 'ok: fog on and off make no new shader');
  await b.close(); srv.close(); process.exit(bad ? 1 : 0); });
