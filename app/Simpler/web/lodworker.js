// Levels of detail for the painted models (Distribuisci), made off the main thread so the view never stops.
// For every geometry of a model three lighter versions are made (about 30%, 8% and 2% of the triangles):
//  · foliage (many small loose pieces: leaves, blades of grass, needles): whole pieces are dropped (always the same
//    ones: a piece kept at 2% is also kept at 8% and 30%) and the remaining ones are enlarged around their centre,
//    so the crown keeps its volume and its colour from a distance. This is how vegetation LODs are usually made:
//    simplifying a leaf of two triangles is not possible, dropping leaves is;
//  · solid parts (trunk, branches, rocks, everything that is one connected surface) with meshoptimizer.
// Input: {key, position: Float32Array, index: Uint32Array|null, attrs: {name: {array, itemSize, normalized}}}
// Output: {key, tris: [t0, t1, t2, t3], levels: [{index, attrs?}]} - attrs only when the vertices changed.
import { MeshoptSimplifier } from './lib/meshopt/meshopt_simplifier.js';

const RATIOS = [0.3, 0.08, 0.02];
const MAX_GROW = 2.4;                       // a kept leaf grows at most this much

if (typeof self !== 'undefined') self.onmessage = async (ev) => {
  const job = ev.data;
  try {
    await MeshoptSimplifier.ready;
    self.postMessage(make(job));
  } catch (err) {
    self.postMessage({ key: job.key, error: String(err && err.message || err) });
  }
};

export function make({ key, position, index, attrs }) {
  const nv = position.length / 3;
  if (!index) { index = new Uint32Array(nv); for (let i = 0; i < nv; i++) index[i] = i; }
  const ntri = index.length / 3;
  // ---- loose pieces: vertices at the same place belong together (a leaf split by a UV seam is still one leaf)
  let lo = [Infinity, Infinity, Infinity], hi = [-Infinity, -Infinity, -Infinity];
  for (let v = 0; v < nv; v++) for (let a = 0; a < 3; a++) { const x = position[v * 3 + a]; if (x < lo[a]) lo[a] = x; if (x > hi[a]) hi[a] = x; }
  const diag = Math.hypot(hi[0] - lo[0], hi[1] - lo[1], hi[2] - lo[2]) || 1;
  const weld = weldByPosition(position, nv, diag * 1e-6, lo);
  const parent = new Int32Array(nv);
  for (let i = 0; i < nv; i++) parent[i] = i;
  const find = (x) => { while (parent[x] !== x) { parent[x] = parent[parent[x]]; x = parent[x]; } return x; };
  for (let t = 0; t < index.length; t += 3) {
    const a = find(weld[index[t]]), b = find(weld[index[t + 1]]), c = find(weld[index[t + 2]]);
    if (b !== a) parent[b] = a;
    const c2 = find(c);
    if (c2 !== a) parent[c2] = a;
  }
  const comp = new Int32Array(nv).fill(-1);
  const rootComp = new Int32Array(nv).fill(-1);
  let ncomp = 0;
  for (let v = 0; v < nv; v++) {
    const r = find(weld[v]);
    if (rootComp[r] < 0) rootComp[r] = ncomp++;
    comp[v] = rootComp[r];
  }
  const ctris = new Int32Array(ncomp);
  for (let t = 0; t < index.length; t += 3) ctris[comp[index[t]]]++;
  const cx = new Float64Array(ncomp), cy = new Float64Array(ncomp), cz = new Float64Array(ncomp), cn = new Int32Array(ncomp);
  for (let v = 0; v < nv; v++) { const c = comp[v]; cx[c] += position[v * 3]; cy[c] += position[v * 3 + 1]; cz[c] += position[v * 3 + 2]; cn[c]++; }
  for (let c = 0; c < ncomp; c++) { const n = Math.max(1, cn[c]); cx[c] /= n; cy[c] /= n; cz[c] /= n; }
  // a piece is "small" (a leaf) when it is a tiny share of the geometry; big pieces are solid parts
  const bigTris = Math.max(64, ntri * 0.01);
  let smallTris = 0, smallCount = 0;
  for (let c = 0; c < ncomp; c++) if (ctris[c] <= bigTris) { smallTris += ctris[c]; smallCount++; }
  const foliage = smallCount >= 40 && smallTris >= ntri * 0.3;
  const keepRank = new Float32Array(ncomp);       // stable random number per piece, from its position
  for (let c = 0; c < ncomp; c++) keepRank[c] = hash01(cx[c], cy[c], cz[c], c);

  // solid part of the index (or everything when it is not foliage)
  let solid = index;
  if (foliage) {
    let n = 0;
    for (let t = 0; t < index.length; t += 3) if (ctris[comp[index[t]]] > bigTris) n += 3;
    solid = new Uint32Array(n);
    n = 0;
    for (let t = 0; t < index.length; t += 3) if (ctris[comp[index[t]]] > bigTris) { solid[n++] = index[t]; solid[n++] = index[t + 1]; solid[n++] = index[t + 2]; }
  }
  const levels = [], tris = [ntri];
  let prev = solid, prevRatio = 1;
  for (let li = 0; li < RATIOS.length; li++) {
    const r = RATIOS[li];
    // each level simplified from the previous one (same vertices): faster, and the levels stay consistent
    const simple = prev.length ? simplify(prev, position, r / prevRatio, li) : new Uint32Array(0);
    prev = simple; prevRatio = r;
    if (!foliage) { levels.push({ index: simple }); tris.push(simple.length / 3); continue; }
    // foliage: keep the pieces with rank < r, enlarged; vertices copied (only the kept ones)
    const grow = Math.min(MAX_GROW, 1 / Math.sqrt(r));
    const remap = new Int32Array(nv).fill(-1);
    let nk = 0;
    const keepTri = [];
    for (let t = 0; t < index.length; t += 3) {
      const c = comp[index[t]];
      if (ctris[c] <= bigTris && keepRank[c] < r) keepTri.push(t);
    }
    const out = new Uint32Array(keepTri.length * 3 + simple.length);
    let o = 0;
    const scaled = [];
    for (const t of keepTri) for (let k = 0; k < 3; k++) {
      const v = index[t + k];
      if (remap[v] < 0) { remap[v] = nk++; scaled.push(v); }
      out[o++] = remap[v];
    }
    const nScaled = nk;
    for (let i = 0; i < simple.length; i++) {
      const v = simple[i];
      if (remap[v] < 0) { remap[v] = nk++; scaled.push(v); }
      out[o++] = remap[v];
    }
    const outAttrs = {};
    for (const [name, a] of Object.entries(attrs)) {
      const s = a.itemSize, src = a.array;
      const dst = new src.constructor(nk * s);
      for (let i = 0; i < nk; i++) { const v = scaled[i]; for (let k = 0; k < s; k++) dst[i * s + k] = src[v * s + k]; }
      if (name === 'position') {
        for (let i = 0; i < nScaled; i++) {
          const c = comp[scaled[i]];
          dst[i * 3] = cx[c] + (dst[i * 3] - cx[c]) * grow;
          dst[i * 3 + 1] = cy[c] + (dst[i * 3 + 1] - cy[c]) * grow;
          dst[i * 3 + 2] = cz[c] + (dst[i * 3 + 2] - cz[c]) * grow;
        }
      }
      outAttrs[name] = { array: dst, itemSize: s, normalized: !!a.normalized };
    }
    levels.push({ index: out, attrs: outAttrs });
    tris.push(out.length / 3);
  }
  return { key, tris, levels, foliage, pieces: ncomp };
}

function simplify(index, position, ratio, level) {
  const target = Math.max(3, Math.floor(index.length * ratio / 3) * 3);
  const err = [0.01, 0.03, 0.08][level];
  let [out] = MeshoptSimplifier.simplify(index, position, 3, target, err, ['Prune']);
  if (out.length > target * 2.5) {
    // the surface does not simplify enough without breaking it (noisy scans, many tiny details): sloppy mode
    [out] = MeshoptSimplifier.simplifySloppy(index, position, 3, null, target, err * 2);
  }
  return out;
}

function weldByPosition(p, nv, eps, lo) {
  // open addressing table on the quantized position
  let size = 1;
  while (size < nv * 2) size <<= 1;
  const table = new Int32Array(size).fill(-1);
  const out = new Int32Array(nv);
  const inv = 1 / eps;
  const qx = new Int32Array(nv), qy = new Int32Array(nv), qz = new Int32Array(nv);
  for (let v = 0; v < nv; v++) {
    const x = Math.round((p[v * 3] - lo[0]) * inv) | 0, y = Math.round((p[v * 3 + 1] - lo[1]) * inv) | 0, z = Math.round((p[v * 3 + 2] - lo[2]) * inv) | 0;
    qx[v] = x; qy[v] = y; qz[v] = z;
    let h = (Math.imul(x, 73856093) ^ Math.imul(y, 19349663) ^ Math.imul(z, 83492791)) & (size - 1);
    for (;;) {
      const w = table[h];
      if (w < 0) { table[h] = v; out[v] = v; break; }
      if (qx[w] === x && qy[w] === y && qz[w] === z) { out[v] = w; break; }
      h = (h + 1) & (size - 1);
    }
  }
  return out;
}

function hash01(x, y, z, c) {
  let h = Math.imul((x * 1e4) | 0, 374761393) ^ Math.imul((y * 1e4) | 0, 668265263) ^ Math.imul((z * 1e4) | 0, 2147483647) ^ Math.imul(c, 1274126177);
  h = Math.imul(h ^ (h >>> 13), 1274126177);
  h ^= h >>> 16;
  return (h >>> 0) / 4294967296;
}
