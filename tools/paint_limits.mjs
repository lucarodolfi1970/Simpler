import * as THREE from '../app/Simpler/web/lib/three.module.js';
import fs from 'fs';
const src = fs.readFileSync(new URL('../app/Simpler/web/viewer.js', import.meta.url), 'utf8');
function fn(name) {
  const i = src.indexOf('function ' + name + '(');
  if (i < 0) throw new Error(name);
  let j = src.indexOf('{', i), d = 0, k = j;
  for (; k < src.length; k++) { if (src[k] === '{') d++; else if (src[k] === '}') { d--; if (!d) break; } }
  return src.slice(i, k + 1);
}
const consts = src.slice(src.indexOf('const PAINT_DAB_MAX'), src.indexOf('let paintAlive = 0;') + 'let paintAlive = 0;'.length);
const code = [consts, ...['mulberry','paintResetItems','paintLocalReset','pickModel','itemAngle','itemScale','gridKey','gridAdd','gridNear','gridRebuild','hitNormal','paintMaxItems','paintLimitInfo','paintApplyStroke','seasonHash','paintSeasons','seasonOf','scatterLocalSet'].map(fn)].join('\n');
const ground = new THREE.Mesh(new THREE.PlaneGeometry(400, 400), new THREE.MeshBasicMaterial());
ground.updateMatrixWorld();
const env = `
const _up = new THREE.Vector3(0,0,1), _pr = new THREE.Raycaster(), _sx = new THREE.Matrix4(), _sv = new THREE.Vector3();
const posts = []; const post = (m) => posts.push(m);
const paint = { radius: 10.55, spacing: 0.171, spacingRand: 0.752, scale: 1, scaleRand: 0.2, rot: 0, rotRand: 1, align: false,
  palette: [{ model: 'grass', weight: 1 }], items: [], grid: new Map(), seed: 1234, local: null };
let protoTris = 0;
const protoForModel = (m) => protoTris ? { state: 'ready', tris: [protoTris, 1, 1, 1] } : null;
const ensureProto = () => {}; const byId = new Map(); const scatter = { sets: new Map(), dirty: false }; const invalidate = () => {};
const paintSurfaces = () => [ground];
${code}
return { paint, posts, run(n, tris) { protoTris = tris; paintResetItems();
  const t0 = performance.now(); let tl = 0;
  for (let i = 0; i < n; i++) { paintApplyStroke({ p: [i * 3.7 % 200 - 100, Math.floor(i * 3.7 / 200) * 20 - 100, 0], n: [0,0,1], r: paint.radius, e: 0 }, i);
    const a = performance.now(); scatterLocalSet('', paint.items, paint.local); tl += performance.now() - a; }
  return { items: paint.items.length, alive: paintAlive, ms: performance.now() - t0, localMs: tl, blocks: scatter.sets.get('').blocks.map(b => b.count) }; },
  erase(p, r) { paintApplyStroke({ p, n: [0,0,1], r, e: 1 }, 0); scatterLocalSet('', paint.items, paint.local); return { alive: paintAlive, blocks: scatter.sets.get('').blocks.map(b => b.count) }; } };`;
const T = new Function('THREE', 'ground', env)(THREE, ground);
// (1.78.4, Luca: a brush of 10.55 m with a distance of 0.17 m made 120,806 pieces of a grass of 8,176 triangles in a
// few seconds and the view froze) the same brush: at most PAINT_DAB_MAX per touch, the distribution held by its
// triangles, the view's arrays only grow by the new pieces, an erase still works
const bad = [];
// (15/11) the limit of a distribution is the number of its pieces (300,000), whatever the triangles of the model: 60 touches
// of a heavy model give 120,000 pieces as a light one (before: held at 30,500, and a tree of 125,000 triangles at 2,000)
const a = T.run(60, 125000);
if (a.alive !== 120000) bad.push(`heavy model: ${a.alive} pieces (expected 60 x 2000)`);
if (T.posts.some((p) => p.state === 'total')) bad.push('a message of limit before the limit');
if (a.localMs > 400) bad.push(`view arrays ${a.localMs.toFixed(0)} ms for 60 touches`);
T.posts.length = 0;
const b = T.run(60, 1000);
if (b.alive !== 120000) bad.push(`light model: ${b.alive} pieces (expected 60 x 2000)`);
const dab = T.posts.find((p) => p.state === 'dab');
if (!dab || !(dab.spacing > 0.2 && dab.spacing < 0.26)) bad.push(`suggested distance ${dab && dab.spacing}`);
const full = T.run(170, 8176);
if (full.alive !== 300000) bad.push(`at the limit: ${full.alive} pieces (expected 300,000)`);
if (!T.posts.some((p) => p.state === 'total' && p.count === 300000)) bad.push('no message at the limit');
T.run(60, 1000);
const c = T.erase([-100, -100, 0], 5);
if (!(c.alive < b.alive && c.blocks[0] === c.alive)) bad.push(`erase: ${JSON.stringify(c)}`);
console.log(bad.length ? 'FAIL ' + bad.join('; ') : `ok heavy ${a.alive}, light ${b.alive}, ${a.ms.toFixed(0)}+${b.ms.toFixed(0)} ms`);
process.exit(bad.length ? 1 : 0);
