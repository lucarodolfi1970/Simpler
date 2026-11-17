// The plane sector of the move gizmo, seen almost edge-on, must keep the size of the gizmo (it grew over the rotation arcs)
const { chromium } = require('playwright'); const http = require('http'), fs = require('fs'), path = require('path');
const root = process.env.WEB || '/tmp/lt/new'; const port = 9300 + Math.floor(Math.random() * 80);
const srv = http.createServer((q, r) => { const f = path.join(root, decodeURIComponent(q.url.split('?')[0])); fs.readFile(f, (e, d) => { if (e) { r.writeHead(404); r.end(); return; } r.writeHead(200, { 'Content-Type': f.endsWith('.js') ? 'text/javascript' : f.endsWith('.html') ? 'text/html' : 'application/octet-stream' }); r.end(d); }); });
srv.listen(port, async () => {
  const b = await chromium.launch({ args: ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--ignore-gpu-blocklist'] });
  const pg = await b.newPage({ viewport: { width: 900, height: 600 } }); const logs = []; pg.on('pageerror', (e) => logs.push('PAGEERROR ' + e.message));
  await pg.goto(`http://localhost:${port}/viewer.html?test=1&glb=/scene.glb`); await pg.waitForFunction(() => window.simplerLoaded, null, { timeout: 90000 });
  await pg.waitForTimeout(3000);
  const ids = await pg.evaluate(() => [...window.__dbg.byId.keys()]);
  await pg.evaluate((id) => window.__dbg.onMessage({ type: 'select', ids: [id], primary: id }), ids[0]);
  await pg.waitForTimeout(600);
  let bad = 0;
  for (const [dist, deg] of [[1.5, 8], [4, 6], [40, 9], [3, 45]]) {
    const r = await pg.evaluate(([dist, deg]) => { const D = window.__dbg, T = D.THREE, g = D.gizmo, a = deg * Math.PI / 180;
      const p = D.pivot.getWorldPosition(new T.Vector3());
      D.camera.position.set(p.x + dist * Math.cos(a), p.y, p.z + dist * Math.sin(a)); D.orbit.target.copy(p); D.orbit.update(); D.camera.updateMatrixWorld(true);
      D.renderer.render(D.scene, D.camera);
      const out = {};
      for (const part of ['gizmo', 'picker']) { const ch = g._gizmo[part].translate.children; const x = ch.find((h) => h.name === 'Y'), xy = ch.find((h) => h.name === 'XY');
        out[part] = { axis: Math.abs(x.scale.x), sector: Math.abs(xy.scale.x), visible: xy.visible }; }
      return out; }, [dist, deg]);
    for (const part of ['gizmo', 'picker']) { const o = r[part]; const ok = o.visible && Math.abs(o.sector / o.axis - 1) < 1e-3; if (!ok) bad++;
      console.log((ok ? 'ok   ' : 'BAD  ') + `camera at ${dist} m, ${deg}° above the plane, ${part}: axis size ${o.axis.toFixed(3)}, sector size ${o.sector.toFixed(3)}, visible ${o.visible}`); }
  }
  for (const l of logs) console.log(l);
  console.log(bad ? 'FAIL: the plane sector has not the size of the gizmo' : 'ok: the plane sector keeps the size of the gizmo');
  process.exitCode = bad ? 1 : 0; await b.close(); srv.close(); });
