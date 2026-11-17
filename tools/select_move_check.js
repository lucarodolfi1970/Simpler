// Real-browser check on a real scene (a GLB from Luca's cache): selecting objects and moving the camera must not make shaders inside a frame
const { chromium } = require('playwright'); const http = require('http'), fs = require('fs'), path = require('path');
const root = process.env.WEB || '/tmp/lt/new'; const port = 9200 + Math.floor(Math.random() * 80);
const srv = http.createServer((q, r) => { const f = path.join(root, decodeURIComponent(q.url.split('?')[0])); fs.readFile(f, (e, d) => { if (e) { r.writeHead(404); r.end(); return; } r.writeHead(200, { 'Content-Type': f.endsWith('.js') ? 'text/javascript' : f.endsWith('.html') ? 'text/html' : 'application/octet-stream' }); r.end(d); }); }).listen(port, async () => {
  const b = await chromium.launch({ args: ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--ignore-gpu-blocklist'] });
  const pg = await b.newPage({ viewport: { width: 900, height: 600 } }); const logs = []; pg.on('console', (m) => logs.push(m.text())); pg.on('pageerror', (e) => logs.push('PAGEERROR ' + e.message));
  await pg.goto(`http://localhost:${port}/viewer.html?test=1&glb=/scene.glb`); await pg.waitForFunction(() => window.simplerLoaded, null, { timeout: 90000 });
  const wait = (ms) => pg.waitForTimeout(ms);
  const settle = async () => { for (let i = 0; i < 100; i++) { await wait(400); if (!(await pg.evaluate(() => window.__dbg.shaderPrep.busy)) && i > 3) return; } };
  await settle(); await wait(2000);
  await pg.evaluate(() => { window.__gaps = []; let last = performance.now(); const loop = () => { const n = performance.now(); window.__gaps.push(n - last); last = n; requestAnimationFrame(loop); }; requestAnimationFrame(loop);
    const gl = window.__dbg.renderer.getContext(); window.__links = 0; const o = gl.linkProgram.bind(gl); gl.linkProgram = (p) => { window.__links++; return o(p); }; });
  const ids = await pg.evaluate(() => [...window.__dbg.byId.keys()]);
  const res = [];
  const act = async (name, fn) => { const s0 = await pg.evaluate(() => ({ links: window.__links, n: window.__gaps.length, progs: window.__dbg.renderer.info.programs.map((p) => p.cacheKey) })); const l0 = logs.length; await fn(); await wait(1500);
    const r = await pg.evaluate((s0) => { const g = window.__gaps.slice(s0.n); const now = window.__dbg.renderer.info.programs; return { links: window.__links - s0.links, maxGap: Math.round(Math.max(0, ...g)), made: now.filter((p) => !s0.progs.includes(p.cacheKey)).map((p) => p.name + ' | ' + String(p.cacheKey).slice(0, 110)) }; }, s0);
    const slow = logs.slice(l0).filter((l) => /slow frame|shaders ready/.test(l)).map((l) => l.replace(/^\[to host\] /, '').slice(0, 150));
    res.push({ name, ...r, slow }); };
  for (const id of ids) await act('select ' + id, () => pg.evaluate((id) => window.__dbg.onMessage({ type: 'select', ids: [id], primary: id }), id));
  await act('select two', () => pg.evaluate((ids) => window.__dbg.onMessage({ type: 'select', ids: ids.slice(0, 2), primary: ids[0] }), ids));
  await act('snapshot (thumbnail of a scene)', () => pg.evaluate(() => window.__dbg.onMessage({ type: 'snapshot', id: 't1', w: 320, h: 200 })));
  await act('snapshot again', () => pg.evaluate(() => window.__dbg.onMessage({ type: 'snapshot', id: 't2', w: 1280, h: 800, q: 0.95 })));
  await act('deselect', () => pg.evaluate(() => window.__dbg.onMessage({ type: 'select', ids: [] })));
  for (let k = 0; k < 4; k++) await act('orbit/move camera #' + k, () => pg.evaluate((k) => { const D = window.__dbg; D.camera.position.x += 3; D.camera.position.y -= 2 * k; D.orbit.update(); D.onMessage({ type: 'ping' }); }, k));
  let bad = 0;
  for (const r of res) { const flag = r.links > 0; if (flag) bad++; console.log((flag ? 'SLOW ' : 'ok   ') + r.name + ': programs linked ' + r.links + ', longest frame gap ' + r.maxGap + ' ms' + (r.slow.length ? '  | ' + r.slow.join(' | ') : '')); for (const m of r.made || []) console.log('      new program: ' + m); }
  console.log(bad ? `FAIL: ${bad} actions made shaders or stopped the view` : 'ok: selecting and moving make no shaders');
  process.exitCode = bad ? 1 : 0; await b.close(); srv.close(); });
