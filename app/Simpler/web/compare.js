// (1.75.54) «Ottimizza poligoni»: the model before and after side by side, with one camera for both - turning or
// zooming one half turns the other (Luca: «sulle anteprime non si può agire con il mouse»). One WebGL context, the
// two halves drawn with the scissor. The models come from the engine as GLB (decimate/view → preview/part.glb), in
// Blender space (Z up, metres). Drawn only when something changed: nothing runs while the window waits.
import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
import { RoomEnvironment } from 'three/addons/environments/RoomEnvironment.js';

const host = window.chrome && window.chrome.webview;
const post = (m) => { if (host) host.postMessage(m); };
const $ = (id) => document.getElementById(id);

const box = $('view');
const renderer = new THREE.WebGLRenderer({ antialias: true, powerPreference: 'high-performance' });
renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
renderer.outputColorSpace = THREE.SRGBColorSpace;
renderer.toneMapping = THREE.ACESFilmicToneMapping;
renderer.toneMappingExposure = 1.0;
renderer.setScissorTest(true);
box.appendChild(renderer.domElement);

const camera = new THREE.PerspectiveCamera(35, 1, 0.01, 1000);
camera.up.set(0, 0, 1);
camera.position.set(6, -8, 4);
const controls = new OrbitControls(camera, renderer.domElement);
controls.enableDamping = true;
controls.dampingFactor = 0.15;
controls.screenSpacePanning = true;

const env = new THREE.PMREMGenerator(renderer).fromScene(new RoomEnvironment(), 0.04).texture;
function makeScene() {
  const s = new THREE.Scene();
  s.background = new THREE.Color(0x3a3d42);
  s.environment = env;
  s.environmentIntensity = 0.9;
  const sun = new THREE.DirectionalLight(0xffffff, 1.6);
  sun.position.set(4, -6, 9);
  s.add(sun);
  s.add(new THREE.HemisphereLight(0xdfe6f0, 0x50483e, 0.35).translateZ(0));
  return s;
}
const sides = {
  before: { scene: makeScene(), model: null, wire: [], tris: $('trisB'), busy: $('busyB') },
  after: { scene: makeScene(), model: null, wire: [], tris: $('trisA'), busy: $('busyA') },
};
let wireOn = false, framed = false, dirty = true, lastDraw = 0;

const fmt = (n) => n.toLocaleString(document.documentElement.lang === 'en' ? 'en-US' : 'it-IT');

function triangles(root) {
  let n = 0;
  root.traverse((o) => {
    if (!o.isMesh || !o.geometry) return;
    const g = o.geometry;
    const c = g.index ? g.index.count : (g.attributes.position ? g.attributes.position.count : 0);
    n += (c / 3) * (o.isInstancedMesh ? o.count : 1);
  });
  return Math.round(n);
}

function dispose(root) {
  root.traverse((o) => {
    if (o.geometry) o.geometry.dispose();
    const ms = Array.isArray(o.material) ? o.material : o.material ? [o.material] : [];
    for (const m of ms) {
      for (const k in m) if (m[k] && m[k].isTexture) m[k].dispose();
      m.dispose();
    }
  });
}

const WIRE = new THREE.MeshBasicMaterial({ color: 0x14223a, wireframe: true, transparent: true, opacity: 0.55, depthWrite: false });
function setWire(side) {
  const S = sides[side];
  for (const w of S.wire) w.parent && w.parent.remove(w);
  S.wire = [];
  if (!wireOn || !S.model) return;
  S.model.traverse((o) => {
    if (!o.isMesh || o.userData.wire) return;
    const ms = Array.isArray(o.material) ? o.material : [o.material];
    for (const m of ms) { m.polygonOffset = true; m.polygonOffsetFactor = 1; m.polygonOffsetUnits = 1; }
    const w = o.isInstancedMesh ? new THREE.InstancedMesh(o.geometry, WIRE, o.count) : new THREE.Mesh(o.geometry, WIRE);
    if (o.isInstancedMesh) w.instanceMatrix = o.instanceMatrix;
    w.userData.wire = true;
    w.renderOrder = 1;
    o.add(w);
    S.wire.push(w);
  });
}

function frame() {
  const S = sides.before.model ? sides.before : sides.after;
  if (!S.model) return;
  const b = new THREE.Box3().setFromObject(S.model);
  if (b.isEmpty()) return;
  const c = b.getCenter(new THREE.Vector3());
  const r = Math.max(0.01, b.getSize(new THREE.Vector3()).length() / 2);
  const dist = r / Math.sin(THREE.MathUtils.degToRad(camera.fov) / 2) * 1.05;
  const dir = new THREE.Vector3(0.62, -0.72, 0.42).normalize();
  controls.target.copy(c);
  camera.position.copy(c).addScaledVector(dir, dist);
  camera.near = Math.max(0.001, dist / 500);
  camera.far = dist * 50;
  camera.updateProjectionMatrix();
  controls.minDistance = r * 0.02;
  controls.maxDistance = dist * 10;
  controls.update();
  dirty = true;
}

const loader = new GLTFLoader();
function load(side, url) {
  const S = sides[side];
  loader.load(url, (gltf) => {
    const root = gltf.scene;
    if (S.model) { S.scene.remove(S.model); dispose(S.model); }
    S.model = root;
    S.scene.add(root);
    const n = triangles(root);
    S.tris.textContent = fmt(n);
    setWire(side);
    if (!framed) { framed = true; frame(); }
    S.busy.classList.remove('on');
    dirty = true;
    const bb = new THREE.Box3().setFromObject(root);
    post({ type: 'loaded', side, triangles: n, size: bb.isEmpty() ? null : bb.getSize(new THREE.Vector3()).toArray().map((v) => +v.toFixed(2)) });
  }, undefined, (err) => {
    S.busy.classList.remove('on');
    post({ type: 'error', side, text: String(err && err.message || err) });
  });
}

function resize() {
  const w = box.clientWidth || 1, h = box.clientHeight || 1;
  renderer.setSize(w, h, false);
  camera.aspect = (w / 2) / h;
  camera.updateProjectionMatrix();
  dirty = true;
}
new ResizeObserver(resize).observe(box);
resize();

controls.addEventListener('change', () => { dirty = true; });
document.addEventListener('visibilitychange', () => { dirty = true; });
window.addEventListener('focus', () => { dirty = true; });
renderer.domElement.addEventListener('webglcontextlost', (e) => { e.preventDefault(); post({ type: 'error', side: 'before', text: 'WebGL context lost (graphics memory?)' }); });
renderer.domElement.addEventListener('webglcontextrestored', () => { dirty = true; post({ type: 'log', text: 'WebGL context restored' }); });
window.addEventListener('error', (e) => post({ type: 'log', text: 'compare error: ' + (e.message || e) }));
renderer.domElement.addEventListener('dblclick', frame);

function draw(now) {
  requestAnimationFrame(draw);
  if (controls.update()) dirty = true;      // (damping still moving)
  // (1.76.0) drawn again once a second even when nothing moved: WebView2 may drop the picture of a canvas that is not
  // redrawn (window covered, the main window busy) - Luca saw only slivers of the Qashqai in «Prima»
  if (!dirty && now - lastDraw < 1000) return;
  dirty = false;
  lastDraw = now;
  const w = box.clientWidth, h = box.clientHeight, half = Math.floor(w / 2);
  renderer.setViewport(0, 0, half, h); renderer.setScissor(0, 0, half, h);
  renderer.render(sides.before.scene, camera);
  renderer.setViewport(half, 0, w - half, h); renderer.setScissor(half, 0, w - half, h);
  renderer.render(sides.after.scene, camera);
}
draw();

if (host) host.addEventListener('message', (e) => {
  const m = e.data || {};
  if (m.type === 'texts') {
    $('nameB').textContent = m.before; $('nameA').textContent = m.after; $('hint').textContent = m.hint;
    if (m.lang) document.documentElement.lang = m.lang;
  } else if (m.type === 'model') {
    load(m.side, m.url);
  } else if (m.type === 'busy') {
    const b = sides[m.side].busy;
    b.textContent = m.text || '';
    b.classList.toggle('on', !!m.text);
  } else if (m.type === 'wire') {
    wireOn = !!m.on;
    setWire('before'); setWire('after');
    dirty = true;
  } else if (m.type === 'clear') {
    const S = sides[m.side];
    if (S.model) { S.scene.remove(S.model); dispose(S.model); S.model = null; S.tris.textContent = ''; dirty = true; }
  } else if (m.type === 'frame') {
    frame();
  }
});
post({ type: 'ready' });
// (for the check in a browser without the app: compare.html?before=URL&after=URL)
const q = new URLSearchParams(location.search);
if (q.get('before')) load('before', q.get('before'));
if (q.get('after')) load('after', q.get('after'));
