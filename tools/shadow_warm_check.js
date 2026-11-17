// Things that cast a shadow put in the scene (copies, leaves with holes): their shadow shaders must be prepared, not made inside a frame.
const { chromium } = require('playwright'); const http = require('http'), fs = require('fs'), path = require('path');
const root = process.argv[2] || '/tmp/lt/new'; const port = 9400 + Math.floor(Math.random() * 80);
const srv = http.createServer((q, r) => { const f = path.join(root, decodeURIComponent(q.url.split('?')[0])); fs.readFile(f, (e, d) => { if (e) { r.writeHead(404); r.end(); return; } r.writeHead(200, { 'Content-Type': f.endsWith('.js') ? 'text/javascript' : f.endsWith('.html') ? 'text/html' : 'application/octet-stream' }); r.end(d); }); }).listen(port, async () => {
  const b = await chromium.launch({ args: ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--ignore-gpu-blocklist'] });
  const pg = await b.newPage({ viewport: { width: 900, height: 600 } }); const logs = [];
  pg.on('pageerror', (e) => logs.push('PAGEERROR ' + e.message));
  await pg.exposeFunction('__hostLog', (t) => logs.push(String(t)));
  await pg.addInitScript(() => { window.chrome = window.chrome || {}; window.chrome.webview = { postMessage: (m) => { try { if (m && m.type === 'log') window.__hostLog(m.text); } catch (e) {} }, addEventListener() {}, removeEventListener() {} }; });
  await pg.goto(`http://localhost:${port}/viewer.html?test=1&glb=/scene.glb`); await pg.waitForFunction(() => window.simplerLoaded, null, { timeout: 90000 }); await pg.waitForTimeout(6000);
  const n0 = logs.length;
  await pg.evaluate(() => { const D = window.__dbg, gl = D.renderer.getContext(); window.__inFrame = 0; window.__links = { frame: 0, prep: 0 };
    const rr = D.renderer.render.bind(D.renderer); D.renderer.render = (...a) => { window.__inFrame++; try { return rr(...a); } finally { window.__inFrame--; } };
    const lp = gl.linkProgram.bind(gl); gl.linkProgram = (p) => { if (window.__inFrame > 0) window.__links.frame++; else window.__links.prep++; return lp(p); }; });
  const info = await pg.evaluate(() => { const D = window.__dbg, T = D.THREE; const at = D.orbit.target.clone();
    const tex = new T.DataTexture(new Uint8Array([255, 255, 255, 255, 0, 0, 0, 0, 0, 0, 0, 0, 255, 255, 255, 255]), 2, 2); tex.needsUpdate = true;
    const mk = (geo, mat, n, dx) => { const im = new T.InstancedMesh(geo, mat, n); const M = new T.Matrix4(); for (let i = 0; i < n; i++) { M.makeTranslation(at.x + dx + i * 0.6, at.y, at.z + 1 + i * 0.2); im.setMatrixAt(i, M); } im.castShadow = im.receiveShadow = true; im.frustumCulled = false; D.scene.add(im); return im; };
    mk(new T.BoxGeometry(0.4, 0.4, 0.4), Object.assign(new T.MeshStandardMaterial({ color: 0x8899aa }), { name: 'TestCopies' }), 5, -2);
    mk(new T.PlaneGeometry(0.6, 0.6), Object.assign(new T.MeshStandardMaterial({ color: 0x338833, map: tex, alphaTest: 0.5, side: T.DoubleSide }), { name: 'TestLeaves' }), 5, 2);
    const single = new T.Mesh(new T.PlaneGeometry(0.6, 0.6), Object.assign(new T.MeshStandardMaterial({ color: 0x338833, map: tex, alphaTest: 0.5, side: T.DoubleSide }), { name: 'TestLeaf' })); single.position.copy(at); single.position.z += 2; single.castShadow = true; D.scene.add(single);
    return { shadows: D.renderer.shadowMap.enabled, lights: D.lightList().filter((l) => l.castShadow && l.visible).length }; });
  for (let i = 0; i < 6; i++) { await pg.waitForTimeout(1500); await pg.evaluate((i) => { const D = window.__dbg; D.camera.position.x += 0.01 * (i % 2 ? 1 : -1); D.orbit.update(); D.onMessage({ type: 'select', ids: [] }); window.dispatchEvent(new Event('resize')); }, i); }
  const links = await pg.evaluate(() => ({ ...window.__links, depth: window.__dbg.renderer.info.programs.filter((p) => String(p.cacheKey).startsWith('depth')).length }));
  console.log(`   shaders made: ${links.prep} in the preparation, ${links.frame} inside a frame (shadow shaders in all: ${links.depth})`);
  const mine = logs.slice(n0).filter((l) => /inside a frame|slow frame|shaders ready|PAGEERROR|shadows:/.test(l));
  for (const l of mine) console.log('   ' + l.slice(0, 240));
  const bad = mine.filter((l) => /PAGEERROR|shaders for the shadows/.test(l) || (/inside a frame/.test(l) && /\(depth|\(distance/.test(l)));
  console.log(`   (shadows on: ${info.shadows}, lights with shadows: ${info.lights})`);
  if (links.frame > 0) bad.push('x');
  console.log(bad.length ? `FAIL: ${links.frame} shaders made inside a frame` : 'ok: the shadow shaders of copies and leaves are prepared before');
  await b.close(); srv.close(); process.exit(bad.length || !info.shadows || !info.lights ? 1 : 0); });
