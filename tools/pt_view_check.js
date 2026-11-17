// Path tracing mode: a change from the app (epoch up, view still) keeps the old picture, shows every pass, makes no shaders;
// a move shows the real-time view without the «Switching to real time» box.
const { chromium } = require('playwright'); const http = require('http'), fs = require('fs'), path = require('path');
const root = process.argv[2] || '/tmp/lt/new'; const port = 9400 + Math.floor(Math.random() * 80);
const E = { epoch: 1, current: 1, version: 1, pass: 4, passes: 5, samples: 256 };
const JPG = Buffer.from('/9j/4AAQSkZJRgABAQEASABIAAD/2wBDAP//////////////////////////////////////////////////////////////////////////////////////wgALCAABAAEBAREA/8QAFBABAAAAAAAAAAAAAAAAAAAAAP/aAAgBAQABPxA=', 'base64');
const srv = http.createServer((q, r) => { const u = q.url.split('?')[0];
  if (u === '/eng/frame/info') { r.writeHead(200, { 'Content-Type': 'application/json' }); r.end(JSON.stringify(E)); return; }
  if (u === '/eng/frame') { r.writeHead(200, { 'Content-Type': 'image/jpeg' }); r.end(JPG); return; }
  if (u.startsWith('/eng/')) { r.writeHead(200, { 'Content-Type': 'application/json' }); r.end('{}'); return; }
  const f = path.join(root, decodeURIComponent(u)); fs.readFile(f, (e, d) => { if (e) { r.writeHead(404); r.end(); return; } r.writeHead(200, { 'Content-Type': f.endsWith('.js') ? 'text/javascript' : f.endsWith('.html') ? 'text/html' : 'application/octet-stream' }); r.end(d); }); }).listen(port, async () => {
  const b = await chromium.launch({ args: ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--ignore-gpu-blocklist'] });
  const pg = await b.newPage({ viewport: { width: 900, height: 600 } }); const logs = []; pg.on('console', (m) => logs.push(m.text()));
  await pg.goto(`http://localhost:${port}/viewer.html?test=1&glb=/scene.glb&engine=http://localhost:${port}/eng/`); await pg.waitForFunction(() => window.simplerLoaded, null, { timeout: 90000 });
  await pg.waitForTimeout(5000);
  await pg.evaluate(() => { const gl = window.__dbg.renderer.getContext(); window.__links = 0; const o = gl.linkProgram.bind(gl); gl.linkProgram = (p) => { window.__links++; return o(p); }; });
  const st = () => pg.evaluate(() => ({ on: document.querySelector('#cycles, img.cycles, img') && [...document.querySelectorAll('img')].some((i) => i.classList.contains('on')), badge: (document.getElementById('badge') || {}).textContent, busy: [...document.querySelectorAll('*')].filter((e) => /Switching to real time|Passaggio al tempo reale/.test(e.textContent) && e.children.length === 0 && e.offsetParent).length, links: window.__links }));
  let fail = 0; const ok = (c, m) => { console.log((c ? 'ok   ' : 'FAIL ') + m); if (!c) fail++; };
  await pg.evaluate(() => window.__dbg.onMessage({ type: 'mode', realistic: true })); await pg.waitForTimeout(2500);
  let s = await st(); ok(s.on, 'path tracing: the picture is shown · ' + s.badge);
  const l0 = s.links; const seen = [];
  E.current = 2;                                    // the app changed something (ambience): the engine starts again
  await pg.waitForTimeout(1500); s = await st(); ok(s.on, 'change from the app: the old picture stays · ' + s.badge); ok(!s.busy, 'no «Switching to real time» box');
  for (let p = 0; p < 5; p++) { E.epoch = 2; E.pass = p; E.version++; E.samples = [2, 8, 32, 256, 256][p]; E.prep = p < 4 ? { phase: 'Rendering the image', detail: 'sample 12 of 256', elapsed: 7 } : undefined; await pg.waitForTimeout(700); s = await st(); seen.push(s.badge); }
  console.log('      badges: ' + seen.join(' | '));
  ok(seen.every((x, i) => i === 4 || /[1-4]\/5 · sample 12 of 256 · 0:07$/.test(x)), 'the samples done and the time are shown while refining');
  ok(seen.filter((x) => /[1-4]\/5/.test(x)).length === 4 && /256/.test(seen[4]), 'every pass 1/5 … 4/5 and the end are shown');
  ok(s.links === l0, `no shader made while the picture is computed (${s.links - l0})`);
  // a move of the view: real-time view, no red box
  await pg.mouse.move(450, 300); await pg.mouse.down(); await pg.mouse.move(520, 320, { steps: 5 }); await pg.waitForTimeout(400);
  s = await st(); ok(!s.on, 'moving: the real-time view · ' + s.badge); ok(!s.busy, 'no «Switching to real time» box while moving');
  await pg.mouse.up();
  await pg.evaluate(() => window.__dbg.onMessage({ type: 'mode', realistic: false })); await pg.waitForTimeout(800);
  s = await st(); ok(!s.on, 'real time chosen: the picture goes · ' + s.badge);
  const bad = logs.filter((l) => /error|RangeError|TypeError/i.test(l)).slice(0, 5); if (bad.length) console.log('      console: ' + bad.join(' || '));
  console.log(fail ? `FAIL: ${fail}` : 'ALL OK'); await b.close(); srv.close(); process.exit(fail ? 1 : 0); });
