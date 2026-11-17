// Simpler real-time viewport (three.js, WebGL in WebView2).
// The scene comes from the engine as GLB (Blender space: Z-up, metres). Selection, gizmo, lights and camera
// run here at full frame rate; the host (Simpler.exe) forwards changes to the Blender engine.
// "Path tracing" mode overlays the progressive Cycles image rendered by the engine from the same camera.
import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { TransformControls } from 'three/addons/controls/TransformControls.js';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
import { RoomEnvironment } from 'three/addons/environments/RoomEnvironment.js';
import { mergeGeometries } from 'three/addons/utils/BufferGeometryUtils.js';

// (1.75.49) The fog as in the path tracing (ambience.py, _fog_tau): exp(-optical depth / visibility) along the ray,
// from the start distance, through the profile of a low fog (dense up to h, fading over H above) - instead of the
// exp(-(d/V)^2) of three.js. fogShape = (h, H, start, haze above / dense fog); H 0 = fog everywhere. A few operations per pixel: the
// same cost in SmartView. A Float32Array is shared, not copied, by the uniforms of every material.
const FOG_SHAPE = new Float32Array([1e7, 0, 0, 0]);
THREE.ShaderChunk.fog_pars_vertex = '#ifdef USE_FOG\n\tvarying vec3 vFogView;\n#endif';
THREE.ShaderChunk.fog_vertex = '#ifdef USE_FOG\n\tvFogView = mvPosition.xyz;\n#endif';
THREE.ShaderChunk.fog_pars_fragment = `#ifdef USE_FOG
	uniform vec3 fogColor;
	varying vec3 vFogView;
	uniform vec4 fogShape;
	#ifdef FOG_EXP2
		uniform float fogDensity;
	#else
		uniform float fogNear;
		uniform float fogFar;
	#endif
	float simplerFogF( float z, float h, float H ) { return min( z, h ) + H * ( 1.0 - exp( - max( z - h, 0.0 ) / H ) ); }
#endif`;
THREE.ShaderChunk.fog_fragment = `#ifdef USE_FOG
	float fogDist = length( vFogView );
	#ifdef FOG_EXP2
		float fogH = fogShape.y > 0.0 ? fogShape.x : 1e7;
		float fogFall = max( fogShape.y, 0.5 );
		float fogDz = ( vec4( vFogView, 0.0 ) * viewMatrix ).z / max( fogDist, 1e-6 );
		float fogZs = cameraPosition.z + fogShape.z * fogDz;
		float fogZp = cameraPosition.z + fogDist * fogDz;
		float fogDZ = fogZp - fogZs;
		float fogRatio = abs( fogDZ ) < 0.05 ? exp( - max( 0.5 * ( fogZp + fogZs ) - fogH, 0.0 ) / fogFall )
			: ( simplerFogF( fogZp, fogH, fogFall ) - simplerFogF( fogZs, fogH, fogFall ) ) / fogDZ;
		float fogFactor = 1.0 - exp( - fogDensity * max( fogDist - fogShape.z, 0.0 ) * ( fogRatio + fogShape.w ) );
	#else
		float fogFactor = smoothstep( fogNear, fogFar, fogDist );
	#endif
	gl_FragColor.rgb = mix( gl_FragColor.rgb, fogColor, fogFactor );
#endif`;
// Fog before tone mapping (three.js applies it after): the haze then has the same colour as in the path tracing,
// where it is added to the image in scene-linear light (Ambiente, ambience.py)
for (const sh of Object.values(THREE.ShaderLib)) {
  if (sh.uniforms && sh.uniforms.fogColor) sh.uniforms.fogShape = { value: FOG_SHAPE };   // (shared by every material)
  if (!sh.fragmentShader || !sh.fragmentShader.includes('#include <fog_fragment>') || !sh.fragmentShader.includes('#include <tonemapping_fragment>')) continue;
  const f = sh.fragmentShader.replace(/\n\s*#include <fog_fragment>/, '');
  sh.fragmentShader = f.replace('#include <tonemapping_fragment>', '#include <fog_fragment>\n\t#include <tonemapping_fragment>');
}
import { computeBoundsTree, disposeBoundsTree, acceleratedRaycast } from './lib/bvh/index.module.js';

// search trees for raycasts on big meshes (three-mesh-bvh): built only where needed (the surfaces under the brush)
THREE.BufferGeometry.prototype.computeBoundsTree = computeBoundsTree;
THREE.BufferGeometry.prototype.disposeBoundsTree = disposeBoundsTree;
THREE.Mesh.prototype.raycast = acceleratedRaycast;

THREE.Object3D.DEFAULT_UP.set(0, 0, 1); // Blender is Z-up

// ------------------------------------------------------------------ why a shader was made inside a frame
// (15/11, Luca: «non ragionare sul caso particolare») the rule of the view is: NO shader is made inside a frame, they are all
// prepared before (prepareShaders). When one is made in a frame anyway, the log now says WHY, for any material of any project:
// which shader of the same material had been prepared, and what is different in the one the frame asked for (a light more, a
// shadow, the fog, the tone, instances, transmission…), or that the material had no shader at all. The causes are few and each
// one is a rule to fix once, not a material to fix.
const _PK_PARAMS = ['precision', 'outputColorSpace', 'envMapMode', 'envMapCubeUVHeight', 'mapUv', 'alphaMapUv', 'lightMapUv', 'aoMapUv', 'bumpMapUv',
  'normalMapUv', 'displacementMapUv', 'emissiveMapUv', 'metalnessMapUv', 'roughnessMapUv', 'anisotropyMapUv', 'clearcoatMapUv', 'clearcoatNormalMapUv',
  'clearcoatRoughnessMapUv', 'iridescenceMapUv', 'iridescenceThicknessMapUv', 'sheenColorMapUv', 'sheenRoughnessMapUv', 'specularMapUv', 'specularColorMapUv',
  'specularIntensityMapUv', 'transmissionMapUv', 'thicknessMapUv', 'combine', 'fogExp2', 'sizeAttenuation', 'morphTargetsCount', 'morphAttributeCount',
  'sunLights', 'dirLights', 'pointLights', 'spotLights', 'spotLightMaps', 'hemiLights', 'rectAreaLights', 'sunLightShadows', 'dirLightShadows',
  'pointLightShadows', 'spotLightShadows', 'spotLightShadowsWithMaps', 'lightProbes', 'shadowMapType', 'toneMapping', 'clippingPlanes', 'clipIntersection',
  'depthPacking'];
const _PK_BITS1 = ['instancing', 'instancingColor', 'instancingMorph', 'matcap', 'envMap', 'normalMapObjectSpace', 'normalMapTangentSpace', 'clearcoat',
  'iridescence', 'alphaTest', 'vertexColors', 'vertexAlphas', 'vertexUv1s', 'vertexUv2s', 'vertexUv3s', 'vertexTangents', 'anisotropy', 'alphaHash', 'batching',
  'dispersion', 'batchingColor', 'gradientMap', 'packedNormalMap', 'vertexNormals', 'retroreflection'];
const _PK_BITS2 = ['fog', 'useFog', 'flatShading', 'logarithmicDepthBuffer', 'reversedDepthBuffer', 'skinning', 'morphTargets', 'morphNormals', 'morphColors',
  'premultipliedAlpha', 'shadowMapEnabled', 'doubleSided', 'flipSided', 'useDepthPacking', 'dithering', 'transmission', 'sheen', 'opaque', 'pointsUvs',
  'decodeVideoTexture', 'decodeVideoTextureEmissive', 'alphaToCoverage', 'lightProbeGrids', 'hasPositionAttribute'];
function _pkSplit(key) {
  const a = String(key || '').split(',');
  let i = a.findIndex((x) => x === 'highp' || x === 'mediump' || x === 'lowp');
  if (i < 0) return null;
  const n = _PK_PARAMS.length;
  return { head: a.slice(0, i).join(','), params: a.slice(i, i + n), m1: +a[i + n] || 0, m2: +a[i + n + 1] || 0, tail: a.slice(i + n + 3).join(',') };
}
function _pkDiff(ka, kb) {
  const A = _pkSplit(ka), B = _pkSplit(kb);
  if (!A || !B) return null;
  const out = [];
  if (A.head !== B.head) out.push('kind or defines');
  for (let i = 0; i < _PK_PARAMS.length; i++) if (A.params[i] !== B.params[i]) out.push(`${_PK_PARAMS[i]} ${A.params[i] || '-'}→${B.params[i] || '-'}`);
  const bits = (x, y, names) => { for (let i = 0; i < names.length; i++) { const p = (x >>> i) & 1, q = (y >>> i) & 1; if (p !== q) out.push((q ? '+' : '−') + names[i]); } };
  bits(A.m1, B.m1, _PK_BITS1); bits(A.m2, B.m2, _PK_BITS2);
  if (A.tail !== B.tail) out.push('own part of the material (rain, snow, tone, foliage…)');
  return out;
}
// (15/11) a shader of a material with no name: what is drawn with it (the object, its parent), so the log names the thing
function shaderOwner(pr) {
  const who = [];
  try {
    scene.traverse((o) => {
      if (who.length >= 3 || !o.material) return;
      for (const m of (Array.isArray(o.material) ? o.material : [o.material])) {
        if (!m) continue;
        const mp = renderer.properties.get(m);
        if (mp.currentProgram === pr || (mp.programs && [...mp.programs.values()].includes(pr))) {
          who.push((o.name || o.type) + (o.parent ? ' in ' + (o.parent.name || o.parent.type) : '') + ' [' + m.type + (m.fog === false ? '' : ', fog') + (o.visible ? '' : ', hidden') + ']');
          break;
        }
      }
    });
  } catch { }
  return who.length ? ' - used by: ' + who.join('; ') : ' - used by nothing in the scene (a pass of the view: outline, sky, thumbnail)';
}
function shaderWhy(made, before) {
  const gl = renderer.getContext();
  const lines = [];
  for (const pr of made.slice(0, 4)) {
    let size = 0;
    try { size = (gl.getShaderSource(pr.fragmentShader) || '').length; } catch { }
    const name = String(pr.name || '(no name: sky, shadow, outline or helper)'), kind = String(pr.cacheKey || '').split(',')[0];
    let best = null;
    for (const q of before) {
      // (15/11: a material with no name is compared with the others with no name of its kind - before, never compared)
      if (q.name !== pr.name || (!pr.name && String(q.cacheKey || '').split(',')[0] !== kind)) continue;
      const d = _pkDiff(q.cacheKey, pr.cacheKey);
      if (d && (!best || d.length < best.length)) best = d;
    }
    lines.push(`«${name}» (${kind}, ${Math.round(size / 1000)} kB)` + (best ? (best.length ? ' differs from the prepared one in: ' + best.slice(0, 10).join(', ') : ' same key as a prepared one (made again)')
      : ' had NO shader prepared') + (pr.name ? '' : shaderOwner(pr)));
  }
  return lines;
}

// Every change that can make three.js prepare a new shader (a material changed - needsUpdate -, a mesh with a material
// never drawn added, a material swapped) marks _shaderRev; the next frame prepares the shaders in the background
// (prepareShaders) instead of drawing, so the page never freezes inside a frame (1.67.4, logs of Luca: «slow frame:
// 12156 ms, 16 new shaders» right after a model was put in the scene)
let _shaderRev = 0, _shaderRevSeen = 0, _inCompile = false, _shaderNew = false, _addRev = 0;   // (_inCompile: three.js itself flips needsUpdate there)
// (1.75.25) SmartView: speed before faithfulness (Luca). While it is on no shader is made for the lit materials:
// - a material changed in a way that needs a new shader keeps the one it has (_smartPending), made at the exit;
// - a mesh whose material has no shader yet (a model put in the scene, a material swapped) is drawn meanwhile with a
//   plain stand-in (its colour and image, no light: made in milliseconds, see smartStandIns); the real one at the exit;
// - a selected car of a distribution stays drawn as a copy, only an invisible twin of it takes the outline and the
//   clicks (scatterSelection).
// Turning SmartView off puts everything back and prepares the shaders once, with «Occupato».
let _smartOn = false;
const _smartPending = new Set(), _smartSwapped = new Set();
// (1.77.0) the foliage materials with a season (useFoliage): their leaves gone throw no shadow (foliageShadows)
const FOL = { mats: new Set(), dirty: false };
// (15/11) a material put in place of another: never let pass without a check (see marksPassable)
function shadersDirty() { _shaderRev++; _shaderNew = true; _revWho('shadersDirty'); if (FOL.mats.size) FOL.dirty = true; }
// (15/11, Luca's log: «slow frame: 30103 ms … differs from the prepared one in: own part of the material (rain, snow…)» after the
// rain was turned on) the marks «let pass» after 3 checks with nothing new (1.75.3: something marks its materials at every
// frame) were let pass blindly: the rain marking every material of the scene passed too, and their shaders were made inside
// the frame. Now a mark passes only if it comes from a material known to mark for nothing (it was among those of a check that
// found nothing new) AND the shader it has is still the one for its own part (rain, snow, tone…). Anything else is prepared.
const _marked = new Set(), _idleMarkers = new Set();
function marksPassable() {
  for (const m of _marked) {
    if (!_idleMarkers.has(m)) return false;
    let pr = null, key = '';
    try { pr = renderer.properties.get(m).currentProgram; key = m.customProgramCacheKey ? String(m.customProgramCacheKey()) : ''; } catch { return false; }
    if (pr && key && !String(pr.cacheKey).includes(key)) return false;
  }
  return true;
}
// (1.75.3) who asks for new shaders, for the «perf:» line of the log: a scene drawn at exactly half the screen's rate
// even when still (Qashqai: 30 fps, max ≈ 690) is a frame preparing shaders every other frame
const _revStat = { n: 0, who: new Map() };
function _revWho(kind, obj) {
  _revStat.n++;
  if (_revStat.who.size > 6) return;
  let where = '';
  try { where = (new Error().stack || '').split('\n').slice(2, 5).map((l) => l.trim().replace(/^at /, '').replace(/\(?https?:[^)]*\/([^/]+:\d+):\d+\)?/, '$1')).join(' < '); } catch { }
  const key = kind + (obj && (obj.name || obj.type) ? ' ' + (obj.name || obj.type) : '') + ' @ ' + where;
  _revStat.who.set(key, (_revStat.who.get(key) || 0) + 1);
}
// (1.75.9) lines and sprites (light helpers, labels): built-in shaders made in a moment inside the frame - they never
// stop the view with «Aggiornamento dei materiali» (touching a light did, 3 s in a big scene)
function cheapMat(x) { return !!(x && (x.isLineBasicMaterial || x.isLineDashedMaterial || x.isSpriteMaterial || x.userData.smartCheap)); }
function needsProgram(m) {
  if (!m) return false;
  const ms = Array.isArray(m) ? m : [m];
  try {
    for (const x of ms) { if (x && x.isMaterial && !cheapMat(x) && !renderer.properties.get(x).currentProgram) return true; }
  } catch { return true; }      // (the renderer not made yet, while the page starts: the first frame prepares them anyway)
  return false;
}
{
  const MP = THREE.Material.prototype;
  Object.defineProperty(MP, 'needsUpdate', { configurable: true, set(v) {
    if (v !== true) return;
    if (_smartOn && !_inCompile && !cheapMat(this)) { _smartPending.add(this); return; }     // (SmartView: at the exit)
    this.version++; if (!_inCompile && !cheapMat(this)) { _shaderRev++; _marked.add(this); _revWho('needsUpdate', this); }
  } });
  const OP = THREE.Object3D.prototype, plainAdd = OP.add;
  OP.add = function (...objs) {
    const r = plainAdd.apply(this, objs);
    _addRev++;                       // (something added somewhere: smartShadows looks through the scene again)
    for (const o of objs) {
      if (!o || !o.isObject3D) continue;
      let need = false;
      o.traverse((c) => { if (!need && (c.isMesh || c.isPoints || c.isLine) && needsProgram(c.material)) need = true; });
      if (need) { _shaderRev++; _shaderNew = true; _revWho('add', o); break; }
    }
    return r;
  };
}
// ------------------------------------------------------------------ Pioggia: wet surfaces and puddles (rain.py)
// The same formulas as the path tracing (rain.py, top of the file), added to every lit material of the scene when
// the rain is on: the shader is built again once when it goes on or off, its sliders only change the uniforms
// below (shared by all materials: nothing else is rebuilt). The water of a puddle is a mirror layer on top, with
// the sky (environment) and the sun in it, as the coat of Cycles. Off: nothing is added, nothing costs.
const WET = {
  on: false, map: null,
  u: { wetP: { value: new THREE.Vector4(0, 0, 1 / 12, 0.3) }, wetQ: { value: new THREE.Vector4(0, 0, 0.3, 0) },
    wetMap: { value: new THREE.DataTexture(new Uint8Array([0, 0, 0, 255]), 1, 1) },
    wetS: { value: new THREE.Vector4(0, 0, 1, 0) }, wetZ: { value: new THREE.Vector4(0, 1, 0.5, 0) },
    wetSh: { value: new THREE.DataTexture(new Uint8Array([0, 0, 0, 255]), 1, 1) },
    wetPF: { value: new THREE.Vector4(0, 0, 1, 0) }, wetPZ: { value: new THREE.Vector4(0, 1, 0, 0) },
    wetPaint: { value: new THREE.DataTexture(new Uint8Array([0, 0, 0, 255]), 1, 1) },
    wetSn: { value: new THREE.Vector4(0, 0.3, 0.3, 0) }, wetSo: { value: new THREE.Vector4(0, 0, 0, 0) },
    wetSPF: { value: new THREE.Vector4(0, 0, 1, 0) }, wetSPZ: { value: new THREE.Vector4(0, 1, 0.5, 0) },
    wetSPaint: { value: new THREE.DataTexture(new Uint8Array([0, 0, 0, 255]), 1, 1) },
    wetB: { value: new THREE.Vector4(0, 0.5, 0.3, 0.4) }, wetB2: { value: new THREE.Vector4(0, 0, 0, 0) },
    wetC: { value: new THREE.Vector4(0, 0, 0, 0.3) },
    wetL: { value: new THREE.Vector4(0, 0, 0.05, 0) } },     // (the snow line over the sea: on, from, to)     // (the shore of the sea: on, level, top of the wet band, softness)
  paintRev: -1, paint: null,
  outdoor: true, shelterRev: -1, polling: false, dry: new Set(), nosnow: new Set(), swapped: new Set(), dryClones: new Map(), origOf: new WeakMap(),
};
WET.u.wetMap.value.needsUpdate = true;
WET.u.wetSh.value.needsUpdate = true;
WET.u.wetPaint.value.needsUpdate = true;
WET.u.wetSPaint.value.needsUpdate = true;
const WET_VERT = `
{ vec4 wetW = vec4( transformed, 1.0 );
#ifdef USE_BATCHING
  wetW = batchingMatrix * wetW;
#endif
#ifdef USE_INSTANCING
  wetW = instanceMatrix * wetW;
#endif
  vWetPos = ( modelMatrix * wetW ).xyz; }
  // «Sempre asciutto» of a part of a library model (export_job.py: _wetdry) and of an instance (wetDry), as a code:
  // 1 = no rain and no snow, 2 = no rain, 3 = no snow; x = no rain, y = no snow
  { float wd = floor( _wetdry + 0.5 );
    vWetDry = vec2( step( 0.5, wd ) * step( wd, 2.5 ), step( 0.5, wd ) * ( step( wd, 1.5 ) + step( 2.5, wd ) ) );
#ifdef USE_INSTANCING
    float wi = floor( wetDry + 0.5 );
    vWetDry = max( vWetDry, vec2( step( 0.5, wi ) * step( wi, 2.5 ), step( 0.5, wi ) * ( step( wi, 1.5 ) + step( 2.5, wi ) ) ) );
#endif
  }`;
// «Neve vecchia» (rain.py, top: old snow): stains from the map at two other scales, a duller white; edge = where the
// snow thins out, pressed = footprints and tyres of the mantle
const SNOW_AGED = `
vec3 snowAged( sampler2D mp, vec3 base, vec2 xy, float a, float edge, float pressed ) {
  if ( a <= 0.0 ) return base;
  float n2 = 0.45 * texture2D( mp, xy * 0.31 + vec2( 0.23, 0.87 ) ).r + 0.55 * texture2D( mp, xy * 0.071 + vec2( 0.55, 0.29 ) ).r;
  float t0 = 1.0 - 0.55 * a;
  float d = a * min( 0.75 * smoothstep( t0, t0 + 0.25, n2 ) + 0.5 * edge + 0.6 * pressed, 1.0 );
  return mix( mix( base, vec3( 0.80, 0.79, 0.76 ), 0.6 * a ), vec3( 0.42, 0.38, 0.33 ), 0.55 * d );
}
`;
// the slope of the rings of the rain (ripples.py): on the water materials (ringsPatch) and in the puddles (WET)
const RINGS_FN = `#ifndef RINGS_FN_DONE
#define RINGS_FN_DONE
vec2 ringHash2( vec2 p ) { return fract( sin( vec2( dot( p, vec2( 127.1, 311.7 ) ), dot( p, vec2( 269.5, 183.3 ) ) ) ) * 43758.5453 ); }
vec2 ringHash2b( vec2 p ) { return fract( sin( vec2( dot( p, vec2( 419.2, 371.9 ) ), dot( p, vec2( 157.3, 233.1 ) ) ) ) * 43758.5453 ); }
// P = (rain, amount, size, strength): the slope of the rings (per metre)
vec2 ringsGradP( vec2 xy, vec4 P ) {
  float cell = 0.15 + 0.6 * P.z;
  float dens = P.y * ( 0.25 + 0.75 * P.x ) * 0.9;
  vec2 g = vec2( 0.0 );
  for ( int L = 0; L < 3; L++ ) {
    float sc = L == 0 ? 1.0 : ( L == 1 ? 0.73 : 1.37 );
    vec2 of = L == 0 ? vec2( 0.0 ) : ( L == 1 ? vec2( 17.31, 5.17 ) : vec2( -9.43, 23.71 ) );
    float s = cell * sc;
    vec2 q = xy / s + of;
    vec2 c0 = floor( q );
    float best = 1e9; vec2 bp = c0; vec2 bc = c0;
    for ( int j = -1; j <= 1; j++ ) for ( int i = -1; i <= 1; i++ ) {
      vec2 c = c0 + vec2( float( i ), float( j ) );
      vec2 fp = c + 0.5 * ringHash2( c );
      float d = length( q - fp );
      if ( d < best ) { best = d; bp = fp; bc = c; }
    }
    vec2 r = ringHash2b( bc );
    if ( r.y >= dens ) continue;
    float t = fract( r.x + 0.37 * float( L ) );
    float x = best - ( 0.04 + 0.26 * t ), w = 0.035 + 0.03 * t, k = 6.283185 / 0.09;
    float e = exp( -( x / w ) * ( x / w ) ), A = ( 1.0 - t ) * ( 1.0 - t );
    float dh = A * e * ( -k * sin( k * x ) - 2.0 * x / ( w * w ) * cos( k * x ) );
    g += dh * ( q - bp ) / max( best, 1e-5 ) / s;
  }
  return g * ( 0.002 * P.w * cell / 0.45 );
}
#endif
`;
// «Gocce sulle superfici» (rain._drops_nodes): the same drops as the path tracing - cells over x, y on what faces up,
// over (u, z / 1.5) on the sides, the runs down the sides; a dome each, its slope bends the normal (and the water
// layer: wetWater, wetN). wetB = (amount, size, «Gocce grandi», «Rivoli»), wetB2 = (film, rain of the rings, rings, -)
const WET_DROPS_FN = `
#ifdef WET_BEADS
vec2 wbH2( vec2 p ) { return fract( sin( vec2( dot( p, vec2( 127.1, 311.7 ) ), dot( p, vec2( 269.5, 183.3 ) ) ) ) * 43758.5453 ); }
vec3 wbH3( vec2 p ) { return fract( sin( vec3( dot( p, vec2( 419.2, 371.9 ) ), dot( p, vec2( 157.3, 233.1 ) ), dot( p, vec2( 311.7, 97.3 ) ) ) ) * 43758.5453 ); }
void wbLayer( vec2 X, float size, float prob, vec2 sc, vec2 off, float radk, inout float h, inout vec2 g ) {
  vec2 q = X / ( size * sc ) + off; vec2 c0 = floor( q ); float d = 1e9; vec2 fp = c0; vec2 bc = c0;
  for ( int j = -1; j <= 1; j++ ) for ( int i = -1; i <= 1; i++ ) {
    vec2 c = c0 + vec2( float( i ), float( j ) ); vec2 p = c + wbH2( c ); float dd = length( q - p );
    if ( dd < d ) { d = dd; fp = p; bc = c; }
  }
  vec3 r = wbH3( bc );
  if ( r.z >= prob ) return;
  float R = ( 0.25 + 0.2 * r.x ) * radk; float e = d / R;
  if ( e >= 1.0 ) return;
  float root = sqrt( 1.0 - e * e ); float hh = 0.55 * R * size * root;
  if ( hh <= h ) return;
  h = hh; g = -0.55 * e / max( root, 0.2 ) / max( d, 1e-4 ) * ( q - fp ) / sc;
}
float wetDrops( vec3 P, vec3 n, sampler2D mp, out vec3 G ) {
  float q = wetB.x, c = 0.006 + 0.024 * wetB.y, radk = 0.6 + 0.4 * q;
  float hu = 0.0; vec2 gu = vec2( 0.0 );
  wbLayer( P.xy, c, q * ( wetB.z + 0.3 ), vec2( 1.0 ), vec2( 0.0 ), radk, hu, gu );
  wbLayer( P.xy, c * 0.5, q, vec2( 1.0 ), vec2( 13.1, 7.7 ), radk, hu, gu );
  float ln = max( length( n.xy ), 1e-4 );
  float U = ( n.x * P.y - n.y * P.x ) / ln; vec2 ud = vec2( -n.y, n.x ) / ln;
  float hs = 0.0; vec2 gs = vec2( 0.0 );
  wbLayer( vec2( U, P.z ), c * 0.6, q, vec2( 1.0, 1.5 ), vec2( 3.7, 11.3 ), radk, hs, gs );
  float sr = c * 4.0;
  float xs = U / sr + ( texture2D( mp, vec2( U / ( sr * 6.0 ), P.z * 1.5 ) * 0.05 ).r - 0.5 ) * 0.8;
  float idx = floor( xs ); float ef = ( fract( xs ) - 0.5 ) / 0.06;
  float on = step( fract( sin( idx * 12.9898 ) * 43758.5453 ), wetB.w * q * 0.7 )
    * smoothstep( 0.48, 0.56, texture2D( mp, vec2( idx * 3.1, P.z * 4.0 ) * 0.05 ).r );
  if ( on > 0.0 && abs( ef ) < 1.0 ) {
    float rr = sqrt( 1.0 - ef * ef ); float hr = rr * sr * 0.03 * on;
    if ( hr > hs ) { hs = hr; gs = vec2( -0.5 * ef / max( rr, 0.2 ) * on, 0.0 ); }
  }
  float wall = 1.0 - smoothstep( 0.55, 0.85, n.z );
  G = mix( vec3( gu, 0.0 ), vec3( gs.x * ud, gs.y ), wall );
  return mix( hu, hs, wall );
}
#endif
#ifdef WET_PRINGS
` + RINGS_FN + `
#endif
`;
const WET_PARS = `uniform vec4 wetP; uniform vec4 wetQ; uniform sampler2D wetMap; varying vec3 vWetPos; varying vec2 vWetDry;
uniform vec4 wetS; uniform vec4 wetZ; uniform sampler2D wetSh; uniform vec4 wetPF; uniform vec4 wetPZ; uniform sampler2D wetPaint;
uniform vec4 wetSn; uniform vec4 wetSo; uniform vec4 wetSPF; uniform vec4 wetSPZ; uniform sampler2D wetSPaint;
uniform vec4 wetB; uniform vec4 wetB2; uniform vec4 wetC; uniform vec4 wetL;
float wetPud = 0.0; float wetWater = 0.0; vec3 wetN = vec3( 0.0, 0.0, 1.0 ); vec3 wetDirect = vec3( 0.0 );
` + SNOW_AGED + WET_DROPS_FN;
// wetP = (wetness, puddles, 1 / tile size, look), wetQ = (offset x, offset y, edge softness, painted softness); the shelter (the scene
// seen from above): wetS = (x0, y0, 1 / size, on), wetZ = (lowest, height range, threshold); the puddles painted by
// hand: wetPF = (x0, y0, 1 / size, on), wetPZ = (lowest, height range), wetPaint RGB = added, taken away, height
const WET_SURFACE = `
{ vec3 wn = inverseTransformDirection( nonPerturbedNormal, viewMatrix );
  float nz = wn.z;
  float wR0 = roughnessFactor;
  float cover = 0.0;
  if ( wetS.w > 0.0 ) {
    vec2 su = ( vWetPos.xy - wetS.xy ) * wetS.z;
    if ( su.x >= 0.0 && su.x <= 1.0 && su.y >= 0.0 && su.y <= 1.0 ) {
      // (1.75.17) five points as in rain.py: the edge of a dry patch fades instead of a hard line
      float rr = ( 0.12 + 0.5 * wetQ.z ) * wetS.z;
      for ( int k = 0; k < 13; k++ ) {
        // (the centre and three rings of four, turned 0°, 30°, 60°: rain.SH_TAPS)
        float ring = k == 0 ? 0.0 : float( ( k - 1 ) / 4 + 1 );
        float ang = radians( ( ring - 1.0 ) * 30.0 + 90.0 * float( ( k - 1 ) - 4 * ( ( k - 1 ) / 4 ) ) );
        vec2 o = k == 0 ? vec2( 0.0 ) : ( ring / 3.0 ) * rr * vec2( cos( ang ), sin( ang ) );
        vec2 sk = clamp( su + o, 0.0, 1.0 );
        float v = texture2D( wetSh, sk ).r;
        float hgt = wetZ.x + v * wetZ.y - ( v < 1e-4 ? 1e6 : 0.0 );
        cover += smoothstep( wetZ.z, wetZ.z + 0.3, hgt - vWetPos.z ) / 13.0;
      }
    }
  }
  // «Sempre asciutto»: per instance (wetDry), per part (_wetdry) or per object (WET_KEEP_*: the copy of its material)
  float keep = ( 1.0 - vWetDry.x ) * WET_KEEP_R;          // the rain
  float keepS = ( 1.0 - vWetDry.y ) * WET_KEEP_S;         // the snow
  float openW = ( 1.0 - cover * ( 0.5 + 0.5 * smoothstep( 0.3, 0.9, nz ) ) ) * keep;
  float w = ( 1.0 - pow2( 1.0 - wetP.x ) ) * ( 0.25 + 0.75 * smoothstep( -0.3, 0.7, nz ) ) * openW * WET_UNGLASS;
  // the shore of the sea (ocean.coast_band, as rain.py): wet up to where the waves run, also under a shelter
  if ( wetC.x > 0.0 ) w = max( w, ( 1.0 - smoothstep( wetC.z - wetC.w, wetC.z, vWetPos.z ) ) * keep * WET_UNGLASS );
#if defined( WET_DECAL ) || ( !defined( USE_INSTANCING ) && !defined( USE_ALPHATEST ) && !defined( USE_ALPHAMAP ) && !defined( USE_ALPHAHASH ) )
  float flatUp = smoothstep( 0.9, 0.98, nz ) * ( 1.0 - cover ) * keep * WET_UNGLASS;
  float flatP = smoothstep( 0.9, 0.98, nz ) * keep * WET_UNGLASS;      // (a painted puddle goes also under a shelter)
  vec2 pv = vec2( 0.0 );
  if ( wetPF.w > 0.0 && wetSn.w < 0.5 ) {          // (while it snows the painted puddles wait)
    vec2 pu = ( vWetPos.xy - wetPF.xy ) * wetPF.z;
    if ( pu.x >= 0.0 && pu.x <= 1.0 && pu.y >= 0.0 && pu.y <= 1.0 ) {
      vec3 pt = texture2D( wetPaint, pu ).rgb;
      pv = pt.rg * ( 1.0 - smoothstep( 0.4, 0.8, abs( vWetPos.z - ( wetPZ.x + pt.b * wetPZ.y ) ) ) );
    }
  }
  float e = 0.01 + 0.3 * wetQ.z;
  if ( wetP.y > 0.0 ) {
    float n = texture2D( wetMap, vWetPos.xy * wetP.z + wetQ.xy ).r;
    float t = 1.0 - 0.55 * wetP.y;
    float fl = flatUp * min( wetP.y * 50.0, 1.0 ) * ( 1.0 - pv.g );
    wetPud = smoothstep( t - e, t + e, n ) * fl;
    w = max( w, smoothstep( t - e - 0.12, t, n ) * fl );
  }
  float ep = 0.02 + 0.43 * wetQ.w;                      // «Sfumatura pennello»
  wetPud = max( wetPud, smoothstep( 0.5 - ep, 0.5 + ep, pv.r ) * flatP );
  w = max( w, smoothstep( 0.05, 0.5, pv.r ) * flatP );
  float film = 0.85 * smoothstep( 0.5, 1.0, wetP.x ) * flatUp * ( 1.0 - pv.g );
  wetWater = max( wetPud, film );
  w = max( w, film );
#endif
  w = clamp( w, 0.0, 1.0 );
  float por = smoothstep( 0.2, 0.9, roughnessFactor ) * ( 1.0 - metalnessFactor );
  diffuseColor.rgb *= ( 1.0 - 0.6 * w * por ) * mix( 1.0, 0.15 + 0.6 * wetP.w, wetPud );
  roughnessFactor = mix( roughnessFactor, min( roughnessFactor, 0.05 + 0.2 * por ), w );
  wetN = nonPerturbedNormal;
  // the snow (rain.py, top): wetSn = (amount, «Sulle pareti», edge softness, snowing), wetSo = (shift of its pattern, age);
  // painted by hand: wetSPF = (x0, y0, 1 / size, on), wetSPZ = (lowest, height range, painted softness)
  if ( wetSn.w > 0.5 && WET_UNGLASS > 0.5 ) {
    // (1.76.45, rain.py SNOW_NS v25) the 8 m map turned and pushed around by two big ones: no repeats in rows
    float snMid = texture2D( wetMap, vWetPos.xy * 0.027 + 0.5 * wetSo.xy + vec2( 0.71, 0.13 ) ).r;
    vec2 snR2 = vec2( 0.602 * vWetPos.x + 0.799 * vWetPos.y, -0.799 * vWetPos.x + 0.602 * vWetPos.y );
    float snBig = texture2D( wetMap, snR2 * 0.0061 + vec2( 0.29, 0.83 ) ).r;
    vec2 snR1 = vec2( 0.799 * vWetPos.x - 0.602 * vWetPos.y, 0.602 * vWetPos.x + 0.799 * vWetPos.y );
    float snFine = texture2D( wetMap, snR1 * 0.125 + wetSo.xy + vec2( 0.37, 0.61 ) + 1.6 * vec2( snMid - 0.5, snBig - 0.5 ) ).r;
    float ns = 0.5 + 1.27 * ( 0.3 * snFine + 0.35 * snMid + 0.35 * snBig - 0.5 );
    float ts = 1.0 - 1.15 * wetSn.x, es = 0.02 + 0.3 * wetSn.z, wlo = 0.75 - 0.95 * wetSn.y;
    // (1.76.12) the slope shaken by the same map at a third scale, as rain.py v23 and snow.py: no straight-sided
    // patches, no crests «a dente di sega» where the mesh is coarse
    float nzs = nz + 0.35 * ( texture2D( wetMap, vWetPos.xy * 0.06 + vec2( 0.23, 0.47 ) ).r - 0.5 );
    float sF = smoothstep( wlo, wlo + 0.3, nzs );
    float sS = smoothstep( ts - es, ts + es, ns ) * sF * ( 1.0 - cover ) * keepS * min( wetSn.x * 50.0, 1.0 );
    if ( wetSPF.w > 0.0 ) {
      vec2 qu = ( vWetPos.xy - wetSPF.xy ) * wetSPF.z;
      if ( qu.x >= 0.0 && qu.x <= 1.0 && qu.y >= 0.0 && qu.y <= 1.0 ) {
        vec3 qt = texture2D( wetSPaint, qu ).rgb;
        float qm = 1.0 - smoothstep( 0.4, 0.8, abs( vWetPos.z - ( wetSPZ.x + qt.b * wetSPZ.y ) ) );
        float eq = 0.02 + 0.43 * wetSPZ.z;
        sS = max( sS * ( 1.0 - qt.g * qm ), smoothstep( 0.5 - eq, 0.5 + eq, qt.r * qm ) * sF * keepS );
      }
    }
    // the sea (ocean.snow_line): no snow under it nor where its waves run
    if ( wetL.x > 0.0 ) sS *= smoothstep( wetL.y, wetL.z, vWetPos.z );
    vec3 sCol = snowAged( wetMap, vec3( 0.88, 0.90, 0.93 ), vWetPos.xy, wetSo.z, 1.0 - smoothstep( 0.35, 0.95, sS ), 0.0 );
    diffuseColor.rgb = mix( diffuseColor.rgb, sCol, sS );
    roughnessFactor = mix( roughnessFactor, 0.55 - 0.12 * wetSo.z, sS );
    metalnessFactor *= 1.0 - sS;
    normal = normalize( mix( normal, nonPerturbedNormal, sS ) );
  }
  // the rings of the falling rain on the water of the puddles (as ripples.py on the water materials)
#ifdef WET_PRINGS
  if ( wetB2.y > 0.0 && wetB2.z > 0.0 && wetWater > 0.0 && wetSn.w < 0.5 ) {
    vec2 rg = ringsGradP( vWetPos.xy, vec4( wetB2.y, wetB2.z, 0.35, 1.2 ) ) * wetWater * smoothstep( 0.8, 0.95, nz );
    wetN = normalize( wetN + ( viewMatrix * vec4( -rg, 0.0, 0.0 ) ).xyz );
  }
#endif
  // «Velo d'acqua»: a thin layer of water on what is smooth and does not soak
  if ( wetSn.w < 0.5 ) {
    float por0 = smoothstep( 0.2, 0.9, wR0 ) * ( 1.0 - metalnessFactor );
    wetWater = max( wetWater, wetB2.x * w * ( 1.0 - por0 ) * ( 1.0 - smoothstep( 0.3, 0.6, wR0 ) ) * 0.6 );
  }
  // the drops lying on the surface
#ifdef WET_BEADS
  if ( wetB.x > 0.0 && wetP.x > 0.0 && wetSn.w < 0.5 ) {
    float autoD = max( 1.0 - smoothstep( 0.35, 0.65, wR0 ), 1.0 - WET_UNGLASS );
    float fD = WET_DROPS > 1.5 ? 1.0 : ( WET_DROPS > 0.5 ? autoD : 0.0 );
    float cD = 0.006 + 0.024 * wetB.y;
    // (far away the drops are smaller than a pixel: they fade instead of flickering)
    float fw = length( fwidth( vWetPos ) );
    float where = fD * smoothstep( 0.3, 0.6, openW ) * smoothstep( -0.35, -0.05, nz ) * ( 1.0 - smoothstep( cD * 0.25, cD * 0.8, fw ) );
    if ( where > 0.0 ) {
      vec3 G;
      float H = wetDrops( vWetPos, wn, wetMap, G ) * where;
      vec3 Gt = ( G - wn * dot( G, wn ) ) * where;
      vec3 dv = ( viewMatrix * vec4( -Gt, 0.0 ) ).xyz;
      normal = normalize( normal + dv );
      wetN = normalize( wetN + dv );
      wetWater = max( wetWater, smoothstep( 0.0, 0.0002, H ) );
#if !defined( USE_ALPHATEST ) && !defined( USE_ALPHAMAP ) && !defined( USE_ALPHAHASH )
      // (a window made by transparency: the drops on it are water, not as clear as the glass)
      // (only where the surface is there at all: the empty part of a decal or of a leaf picture stays empty)
      diffuseColor.a = max( diffuseColor.a, 0.9 * smoothstep( 0.0, 0.0002, H ) * step( 0.01, diffuseColor.a ) );
#endif
    }
  }
#endif
  }
`;
// the sun (and every lamp) in the water: a sharp highlight with its shadow (the light already carries it)
const WET_DIRECT = `
void RE_Direct_Wet( const in IncidentLight directLight, const in vec3 geometryPosition, const in vec3 geometryNormal, const in vec3 geometryViewDir, const in vec3 geometryClearcoatNormal, const in PhysicalMaterial material, inout ReflectedLight reflectedLight ) {
  RE_Direct_Physical( directLight, geometryPosition, geometryNormal, geometryViewDir, geometryClearcoatNormal, material, reflectedLight );
  if ( wetWater > 0.0 ) {
    vec3 L = directLight.direction; vec3 H = normalize( L + geometryViewDir );
    float dotNL = saturate( dot( wetN, L ) ), dotNV = saturate( dot( wetN, geometryViewDir ) ), dotNH = saturate( dot( wetN, H ) );
    float a = 0.0025;
    wetDirect += wetWater * dotNL * directLight.color * F_Schlick( vec3( 0.02 ), 1.0, saturate( dot( geometryViewDir, H ) ) )
      * V_GGX_SmithCorrelated( a, dotNL, dotNV ) * D_GGX( a, dotNH );
  }
}
#undef RE_Direct
#define RE_Direct RE_Direct_Wet
`;
const WET_WATER = `
if ( wetWater > 0.0 ) {
  vec3 wv = normalize( vViewPosition );
  float f = 0.02 + 0.98 * pow( 1.0 - saturate( dot( wetN, wv ) ), 5.0 );
  vec3 wenv = vec3( 0.0 );
#ifdef USE_ENVMAP
  wenv = getIBLRadiance( wv, wetN, 0.0 );
#endif
  outgoingLight = outgoingLight * ( 1.0 - wetWater * f ) + wetWater * ( f * wenv + wetDirect );
}
`;
// Acqua ghiacciata (ice.py): a water material that freezes while it snows - the same map of the distance from the
// shore (GET rain/ice.bin) and the same front, colour, roughness and transparency as the path tracing; the noise of
// the front from the map of the rain (no cracks nor bubbles here)
const ICE = { by: new Map() };
const ICE_PARS = `uniform sampler2D iceMap; uniform vec4 iceF; uniform vec4 iceP; uniform sampler2D iceNoise; varying vec3 vIcePos;
float iceK = 0.0; float iceT = 1.0;
`;
const ICE_SURFACE = `
{ vec2 iu = clamp( ( vIcePos.xy - iceF.xy ) * iceF.z, 0.0, 1.0 );
  float dist = texture2D( iceMap, iu ).r;
  float a = iceP.x;
  float jag = ( texture2D( iceNoise, vIcePos.xy * 0.03 ).r - 0.5 ) * 0.5 + ( texture2D( iceNoise, vIcePos.xy * 0.12 ).r - 0.5 ) * 0.2
    + ( texture2D( iceNoise, vIcePos.xy * 0.5 ).r - 0.5 ) * 0.08;
  float f = a * 1.4 - dist + jag * min( a * 4.0, 1.0 ) - 0.04 * ( 1.0 - a );
  iceK = smoothstep( -0.01, 0.01, f );
  float rim = iceK * ( 1.0 - smoothstep( 0.0, 0.05, f ) );
  float milky = 1.0 - iceP.y;
  float dn = texture2D( iceNoise, vIcePos.xy * 0.6 ).r + 0.45 * smoothstep( 0.8, 1.0, 1.0 - dist );
  float dust = smoothstep( 0.58, 0.72, dn ) * min( iceP.w * 1.5, 1.0 ) * 0.9;
  vec3 col = mix( vec3( 0.78, 0.89, 0.95 ), vec3( 0.90, 0.94, 0.97 ), milky );
  col = mix( col, vec3( 0.95, 0.97, 0.98 ), rim * 0.6 );
  col = mix( col, vec3( 0.88, 0.90, 0.93 ), dust );
  float rough = mix( mix( 0.03, 0.4, milky ) + rim * 0.2, 0.62, dust );
  iceT = mix( 1.0, 0.45, milky ) * ( 1.0 - 0.36 * rim ) * ( 1.0 - dust );
  diffuseColor.rgb = mix( diffuseColor.rgb, col, iceK );
  roughnessFactor = mix( roughnessFactor, rough, iceK );
}
`;
function icePatch(m, sh) {
  const e = m.userData.ice;
  if (!e || sh.fragmentShader.includes('iceK')) return;
  sh.uniforms.iceMap = e.u.iceMap; sh.uniforms.iceF = e.u.iceF; sh.uniforms.iceP = e.u.iceP; sh.uniforms.iceNoise = WET.u.wetMap;
  sh.vertexShader = 'varying vec3 vIcePos;\n' + sh.vertexShader.replace('#include <project_vertex>',
    '#include <project_vertex>\n  vIcePos = ( modelMatrix * vec4( transformed, 1.0 ) ).xyz;');
  sh.fragmentShader = ICE_PARS + sh.fragmentShader
    .replace('#include <lights_physical_fragment>', ICE_SURFACE + '#include <lights_physical_fragment>')
    .replace('#include <transmission_fragment>', THREE.ShaderChunk.transmission_fragment
      .replace('material.transmission = transmission;', 'material.transmission = transmission * mix( 1.0, iceT, iceK );'));
}
async function iceSync(list) {
  list = list || [];
  const names = new Set(list.map((e) => e.name));
  let changed = false;
  for (const e of list) {
    let it = ICE.by.get(e.name);
    if (!it) {
      it = { file: '', u: { iceMap: { value: null }, iceF: { value: new THREE.Vector4() }, iceP: { value: new THREE.Vector4() } } };
      ICE.by.set(e.name, it); changed = true;
    }
    if (it.file !== e.file) {
      const buf = await (await fetch(engineUrl + 'rain/ice.bin?f=' + encodeURIComponent(e.file), { cache: 'no-store' })).arrayBuffer();
      const t = new THREE.DataTexture(new Uint16Array(buf), e.n, e.n, THREE.RedFormat, THREE.HalfFloatType);
      t.magFilter = t.minFilter = THREE.LinearFilter; t.generateMipmaps = false;
      t.wrapS = t.wrapT = THREE.ClampToEdgeWrapping; t.needsUpdate = true;
      if (it.u.iceMap.value) it.u.iceMap.value.dispose();
      it.u.iceMap.value = t; it.file = e.file;
    }
    it.u.iceF.value.set(e.x0, e.y0, 1 / e.size, 1);
    it.u.iceP.value.set(e.amount, e.clear, e.bubbles, e.snow);
  }
  for (const [name, it] of [...ICE.by]) {
    if (!names.has(name)) { if (it.u.iceMap.value) it.u.iceMap.value.dispose(); ICE.by.delete(name); changed = true; }
  }
  // the materials of those waters (by name), and those that are no longer frozen
  scene.traverse((o) => {
    if (!o.material) return;
    for (const m of (Array.isArray(o.material) ? o.material : [o.material])) {
      if (!m.isMeshStandardMaterial) continue;
      const it = ICE.by.get(m.name) || null;
      if ((m.userData.ice || null) !== it) { if (it) m.userData.ice = it; else delete m.userData.ice; m.needsUpdate = true; changed = true; }
    }
  });
  if (changed || list.length) invalidate();
}
// Cerchi della pioggia (ripples.py): while the drops fall, the water of a material «Acqua» gets the rings of the rain
// - the same cells (nearest point, randomness 0.5), ages, radii and crests as the path tracing, on the normal only;
// on what faces up, not under a shelter (the shelter map of the rain)
const RINGS = { by: new Map() };
const RINGS_PARS = `uniform vec4 ringP; uniform vec4 ringS; uniform vec4 ringZ; uniform sampler2D ringSh; varying vec3 vRingPos;
` + RINGS_FN;
const RINGS_SURFACE = `
{ vec3 rw = inverseTransformDirection( nonPerturbedNormal, viewMatrix );
  float up = smoothstep( 0.8, 0.95, rw.z );
  if ( up > 0.0 && ringP.x > 0.0 ) {
    float cover = 0.0;
    if ( ringS.w > 0.0 ) {
      vec2 su = ( vRingPos.xy - ringS.xy ) * ringS.z;
      if ( su.x >= 0.0 && su.x <= 1.0 && su.y >= 0.0 && su.y <= 1.0 ) {
        float v = texture2D( ringSh, su ).r;
        float hgt = ringZ.x + v * ringZ.y - ( v < 1e-4 ? 1e6 : 0.0 );
        cover = smoothstep( ringZ.z + 0.45, ringZ.z + 0.75, hgt - vRingPos.z );   // (the water is lifted in the map)
      }
    }
    float cell = 0.15 + 0.6 * ringP.z;
    vec2 g = ringsGradP( vRingPos.xy, ringP ) * up * ( 1.0 - cover );
    normal = normalize( normal + ( viewMatrix * vec4( -g.x, -g.y, 0.0, 0.0 ) ).xyz );
  } }
`;
function ringsPatch(m, sh) {
  const e = m.userData.rings;
  if (!e || sh.fragmentShader.includes('vRingPos') || !sh.fragmentShader.includes('#include <normal_fragment_maps>')) return;
  sh.uniforms.ringP = e.u.ringP; sh.uniforms.ringS = WET.u.wetS; sh.uniforms.ringZ = WET.u.wetZ; sh.uniforms.ringSh = WET.u.wetSh;
  sh.vertexShader = 'varying vec3 vRingPos;\n' + sh.vertexShader.replace('#include <project_vertex>',
    '#include <project_vertex>\n  vRingPos = ( modelMatrix * vec4( transformed, 1.0 ) ).xyz;');
  sh.fragmentShader = RINGS_PARS + sh.fragmentShader
    .replace('#include <normal_fragment_maps>', '#include <normal_fragment_maps>\n' + RINGS_SURFACE);
}
function ringsSync(list) {
  list = list || [];
  const names = new Set(list.map((e) => e.name));
  let changed = false;
  for (const e of list) {
    let it = RINGS.by.get(e.name);
    if (!it) { it = { u: { ringP: { value: new THREE.Vector4() } } }; RINGS.by.set(e.name, it); changed = true; }
    const v = it.u.ringP.value;
    if (v.x !== e.rain || v.y !== e.amount || v.z !== e.size || v.w !== e.strength) { v.set(e.rain, e.amount, e.size, e.strength); changed = true; }
  }
  for (const name of [...RINGS.by.keys()]) if (!names.has(name)) { RINGS.by.delete(name); changed = true; }
  // (also with no change of the list: a water material made or edited meanwhile gets its rings - as iceSync)
  if (!changed && !RINGS.by.size) return;
  scene.traverse((o) => {
    if (!o.material) return;
    for (const m of (Array.isArray(o.material) ? o.material : [o.material])) {
      if (!m.isMeshStandardMaterial) continue;
      const it = RINGS.by.get(m.name) || null;
      if ((m.userData.rings || null) !== it) { if (it) m.userData.rings = it; else delete m.userData.rings; m.needsUpdate = true; }
    }
  });
  invalidate();
}
function wetIsWater(m) {
  const w = m && m.userData && m.userData.simpler_water;
  if (!w) return false;
  try { return !!(typeof w === 'string' ? JSON.parse(w) : w).on; } catch { return false; }
}
// glass and clear plastic: only the drops lying on them, while «Gocce sulle superfici» is on (never the water)
function wetGlass(m) { return !!(m && m.transmission > 0.5); }
// «Sempre asciutto» of the copy of a material (wetDryApply): 0 = none, 1 = no rain and no snow, 2 = no rain, 3 = no snow
function wetDryCode(m) { const d = m && m.userData && m.userData.dry; return d === true ? 1 : (d | 0); }
function wetFits(m) {
  if (!(m && m.isMeshStandardMaterial) || wetDryCode(m) === 1) return false;
  if (!wetGlass(m)) return true;
  return WET.beads && !wetIsWater(m) && (m.userData && m.userData.simpler_rain_drops) !== 'off';
}
function wetDropsMode(m) { const v = m.userData && m.userData.simpler_rain_drops; return v === 'off' ? '0.0' : v === 'on' ? '2.0' : '1.0'; }
function wetPatch(m, sh) {
  if (sh.fragmentShader.includes('RE_Direct_Wet') || !sh.fragmentShader.includes('#include <lights_physical_fragment>')) return;
  sh.uniforms.wetP = WET.u.wetP; sh.uniforms.wetQ = WET.u.wetQ; sh.uniforms.wetMap = WET.u.wetMap;
  sh.uniforms.wetS = WET.u.wetS; sh.uniforms.wetZ = WET.u.wetZ; sh.uniforms.wetSh = WET.u.wetSh;
  sh.uniforms.wetPF = WET.u.wetPF; sh.uniforms.wetPZ = WET.u.wetPZ; sh.uniforms.wetPaint = WET.u.wetPaint;
  sh.uniforms.wetSn = WET.u.wetSn; sh.uniforms.wetSo = WET.u.wetSo;
  sh.uniforms.wetSPF = WET.u.wetSPF; sh.uniforms.wetSPZ = WET.u.wetSPZ; sh.uniforms.wetSPaint = WET.u.wetSPaint;
  sh.uniforms.wetB = WET.u.wetB; sh.uniforms.wetB2 = WET.u.wetB2; sh.uniforms.wetC = WET.u.wetC; sh.uniforms.wetL = WET.u.wetL;
  sh.vertexShader = 'varying vec3 vWetPos;\nvarying vec2 vWetDry;\nattribute float _wetdry;\n#ifdef USE_INSTANCING\nattribute float wetDry;\n#endif\n' + sh.vertexShader.replace('#include <project_vertex>', '#include <project_vertex>\n' + WET_VERT);
  sh.fragmentShader = (m.userData.wetDecal ? '#define WET_DECAL\n' : '')
    + '#define WET_KEEP_R ' + (wetDryCode(m) === 1 || wetDryCode(m) === 2 ? '0.0' : '1.0') + '\n#define WET_KEEP_S ' + (wetDryCode(m) === 1 || wetDryCode(m) === 3 ? '0.0' : '1.0') + '\n'
    + '#define WET_DROPS ' + wetDropsMode(m) + '\n#define WET_UNGLASS ' + (wetGlass(m) ? '0.0' : '1.0') + '\n'
    + (WET.beads ? '#define WET_BEADS\n' : '') + (WET.prings ? '#define WET_PRINGS\n' : '')
    + WET_PARS + sh.fragmentShader
    .replace('#include <lights_physical_pars_fragment>', '#include <lights_physical_pars_fragment>\n' + WET_DIRECT)
    .replace('#include <lights_physical_fragment>', WET_SURFACE + '#include <lights_physical_fragment>')
    .replace('#include <opaque_fragment>', WET_WATER + '#include <opaque_fragment>');
}
// Every material passes here (its own onBeforeCompile, if any, first): the rain needs no change anywhere else,
// and materials made later (a model just imported) get it too
{
  const P = THREE.Material.prototype, baseCompile = P.onBeforeCompile;
  Object.defineProperty(P, 'onBeforeCompile', {
    configurable: true,
    get() {
      const own = this._ownCompile;
      if (!this._wetCompile || this._wetFor !== own) {
        this._wetFor = own;
        this._wetCompile = (sh, r) => {
          if (this._inWetCompile) return;      // called again from inside its own function: patch once only
          this._inWetCompile = true;
          try { (own || baseCompile).call(this, sh, r); } finally { this._inWetCompile = false; }
          if (WET.on && wetFits(this)) wetPatch(this, sh);
          if (this.userData && this.userData.ice) icePatch(this, sh);
          if (this.userData && this.userData.rings) ringsPatch(this, sh);
        };
      }
      return this._wetCompile;
    },
    set(f) { this._ownCompile = f; },
  });
  Object.defineProperty(P, 'customProgramCacheKey', {
    configurable: true,
    get() {
      // (a function chaining the wrapper itself would call it again: the second call answers '', no recursion)
      return this._wetKey || (this._wetKey = () => { if (this._inWetKey) return ''; this._inWetKey = true; try { return (this._ownKey ? this._ownKey.call(this) : (this._ownCompile ? this._ownCompile.toString() : ''))
        + (WET.on && wetFits(this) ? (this.userData.wetDecal ? '|wetd' : '|wet') + wetDropsMode(this) + (wetGlass(this) ? 'g' : '') + (WET.beads ? 'b' : '') + (WET.prings ? 'r' : '') + (wetDryCode(this) ? 'k' + wetDryCode(this) : '') : '') + (this.userData && this.userData.ice ? '|ice' : '') + (this.userData && this.userData.rings ? '|rings' : ''); } finally { this._inWetKey = false; } });
    },
    set(f) { this._ownKey = f; },
  });
}
function wetSet(info) {
  const st = info && info.state;
  const outside = st && (st.mode === 'sky' || st.mode === 'hdri');
  const c = (v, lo, hi, d) => Math.max(lo, Math.min(hi, Number.isFinite(+v) ? +v : d));
  // the snow: while it snows the rain is suspended (its settings kept), as in rain.py
  const sn = outside ? (st.snow || {}) : null;
  const snow = sn ? c(sn.amount, 0, 1, 0) : 0;
  if (info && info.rainPainted !== undefined) WET.painted = !!info.rainPainted;
  if (info && info.snowPainted !== undefined) WET.spainted = !!info.snowPainted;
  const rr = outside && st.rain ? st.rain : null;
  // (the drops that fall: it rains with them, and the wetness follows their intensity - raindrops.wet_from_drops)
  const drops = !!rr && !!rr.drop && c(rr.dropAmount, 0, 1, 0.5) > 0 && !(sn && sn.fall && c(sn.fallAmount, 0, 1, 0.5) > 0);
  const dropWet = drops && rr.dropWet !== false ? 0.3 + 0.55 * c(rr.dropAmount, 0, 1, 0.5) : 0;
  const raining = !!rr && (c(rr.wet, 0, 1, 0) > 0 || c(rr.puddles, 0, 1, 0) > 0 || !!WET.painted || drops);
  // (as rain.settings: it snows above 0, or with snow painted by hand while the rain has nothing on)
  const snowing = !!sn && (snow > 0 || (!!WET.spainted && !raining));
  WET.snowing = snowing;
  WET.u.wetSn.value.set(snow, sn ? c(sn.walls, 0, 1, 0.3) : 0.3, sn ? c(sn.soft, 0, 1, 0.3) : 0.3, snowing ? 1 : 0);
  WET.u.wetSo.value.set(sn ? c(sn.offX, -1, 1, 0) : 0, sn ? c(sn.offY, -1, 1, 0) : 0, sn ? c(sn.age, 0, 1, 0) : 0, 0);
  WET.u.wetSPZ.value.z = sn ? c(sn.paintSoft, 0, 1, 0.5) : 0.5;
  const r = rr || (snowing ? {} : null);
  const wet = r && !snowing ? Math.max(c(r.wet, 0, 1, 0), dropWet) : 0, pud = r && !snowing ? c(r.puddles, 0, 1, 0) : 0;
  // (the flakes that fall: snowfall.py - asked to the engine also with no snow on the ground)
  const falling = !!sn && !!sn.fall && c(sn.fallAmount, 0, 1, 0.5) > 0;
  // the shore of the sea (Paesaggio > Oceano > Costa): wet whatever the rain
  const band = info && info.ocean && info.ocean.on && info.ocean.band;
  WET.u.wetC.value.set(band ? 1 : 0, band ? band[0] : 0, band ? band[1] : 0, band ? band[2] : 0.3);
  const sline = info && info.ocean && info.ocean.on && info.ocean.snowLine;
  WET.u.wetL.value.set(sline ? 1 : 0, sline ? sline[0] : 0, sline ? sline[1] : 0.05, 0);
  const on = snowing || raining || falling || !!band;
  WET.outdoor = snowing ? sn.outdoor !== false : (!r || r.outdoor !== false);
  if (!WET.outdoor) WET.u.wetS.value.w = 0;
  // «Gocce sulle superfici», «Velo d'acqua», the rings in the puddles (rain.settings: beads, rk, ramount)
  const beadsOn = !!rr && !snowing && rr.beads !== false && c(rr.beadAmount, 0, 1, 0.5) > 0 && wet > 0;
  WET.u.wetB.value.set(beadsOn ? c(rr.beadAmount, 0, 1, 0.5) : 0, rr ? c(rr.beadSize, 0, 1, 0.5) : 0.5,
    rr ? c(rr.beadBig, 0, 1, 0.3) : 0.3, rr ? c(rr.beadRivul, 0, 1, 0.4) : 0.4);
  WET.u.wetB2.value.set(rr && !snowing ? c(rr.beadFilm, 0, 1, 0.5) : 0, drops && !snowing ? c(rr.dropAmount, 0, 1, 0.5) : 0,
    rr ? c(rr.puddleRings, 0, 1, 0.5) : 0, 0);
  // (the drops and the rings in the puddles are in the shaders only while they are on: a lighter shader, made faster,
  // the rest of the time - glass is in the rain only with the drops)
  const pRings = WET.u.wetB2.value.y > 0 && WET.u.wetB2.value.z > 0;
  const turningOff = WET.on && !on;
  if (beadsOn !== !!WET.beads || pRings !== !!WET.prings) {
    WET.beads = beadsOn; WET.prings = pRings;
    // (made again only if the rain stays on: when it goes off they are made once below - before 1.67.5 twice, the
    // first time for nothing; the next frame prepares them in the background: tick, _shaderRev)
    if (WET.on && !turningOff) wetMaterialsChanged();
  }
  if (r) {
    WET.u.wetP.value.set(wet, pud, 1 / (2.5 * Math.pow(24, c(r.size, 0, 1, 0.5))), c(r.look, 0, 1, 0.3));
    WET.u.wetQ.value.set(c(r.offX, -1, 1, 0), c(r.offY, -1, 1, 0), c(r.soft, 0, 1, 0.3), c(r.paintSoft, 0, 1, 0.5));
  } else WET.u.wetP.value.set(0, 0, WET.u.wetP.value.z, WET.u.wetP.value.w);     // (no rain: nothing wet, whatever shader)
  if (on && !WET.map && engineUrl) {
    WET.map = new THREE.TextureLoader().load(engineUrl + 'rain/mask.png?v=1', (t) => {
      t.wrapS = t.wrapT = THREE.RepeatWrapping;
      t.colorSpace = THREE.NoColorSpace;
      t.anisotropy = 8;
      t.needsUpdate = true;
      WET.u.wetMap.value = t;
      invalidate();
    }, undefined, () => { WET.map = null; });
  }
  if (on !== WET.on) {
    WET.on = on;
    WET.gen = (WET.gen || 0) + 1;              // (an answer of rain/info asked before this change is not applied: wetPoll)
    // first the clean-up (the originals back in place of the «Sempre asciutto» copies), then every material once
    if (!on) { WET.dry.clear(); WET.nosnow.clear(); wetDryApply(); mantleSync(null); flakesSync(null); dropsSync(null); ringsSync([]); iceSync([]); snowState(false, false); }
    wetMaterialsChanged();
  }
  if (on && !WET.polling) wetPoll();
  invalidate();
}
// every material of the scene and the kept «Sempre asciutto» copies: their shader is made again (in the background:
// tick prepares them before drawing)
function wetMaterialsChanged() {
  scene.traverse((o) => { if (o.material) (Array.isArray(o.material) ? o.material : [o.material]).forEach((m) => { if (m.isMeshStandardMaterial) m.needsUpdate = true; }); });
  for (const byCode of WET.dryClones.values()) for (const c of byCode.values()) c.needsUpdate = true;
}
// ---- the flakes that fall (snowfall.py): the same flakes as the path tracing, from rain/snowfall.bin (position, radius,
// speed). Each is a small quad facing the camera, stretched along its movement on the screen for the «Mosso» (the
// same shutter time as the path tracing), round and soft; tiny far flakes keep at least 0.7 px and fade instead. Lit
// in the vertex shader by the sky, the suns and the 8 nearest lamps (a lamp lights the flakes around it at night).
const FLAKES = { rev: -1, mesh: null, mat: null };
// the raindrops that fall and their splashes (raindrops.py): the same quads from rain/raindrops.bin, a paler tint and
// fainter as their «Trasparenza» grows (clear water shows little of itself)
const DROPS = { rev: -1, mesh: null, mat: null };
const FLAKE_LIGHTS = 8;
function flakesMat() {
  if (!FLAKES.mat) FLAKES.mat = fallMat([0.85, 0.87, 0.9]);
  return FLAKES.mat;
}
function fallMat(tint) {
  const lp = [], lc = [];
  for (let i = 0; i < FLAKE_LIGHTS; i++) { lp.push(new THREE.Vector4()); lc.push(new THREE.Vector3()); }
  return new THREE.ShaderMaterial({
    uniforms: { uBlur: { value: 0 }, uPx: { value: 500 }, uAmb: { value: new THREE.Vector3(0.5, 0.5, 0.5) }, uLP: { value: lp }, uLC: { value: lc },
      uTint: { value: new THREE.Vector3(tint[0], tint[1], tint[2]) }, uAlpha: { value: 1 }, uFwd: { value: 0 } },
    vertexShader: `
      attribute vec4 iPR; attribute vec3 iVel;
      uniform float uBlur; uniform float uPx; uniform vec3 uAmb;
      uniform vec4 uLP[${FLAKE_LIGHTS}]; uniform vec3 uLC[${FLAKE_LIGHTS}]; uniform vec3 uTint; uniform float uFwd;
      varying vec2 vQ; varying float vL; varying float vA; varying vec3 vCol;
      void main() {
        vec4 c = viewMatrix * vec4(iPR.xyz, 1.0);
        vec3 v = mat3(viewMatrix) * iVel * uBlur;
        float ml = length(v.xy);
        vec2 a = ml > 1e-6 ? v.xy / ml : vec2(0.0, 1.0);
        vec2 b = vec2(-a.y, a.x);
        float r = iPR.w, z = max(-c.z, 1e-3);
        float rpx = r * uPx / z;
        // (at least 1.2 px wide - smaller ones fade with their size, not with its square; a streak keeps at least
        // a third of the brightness of the flake: in the path tracing a smeared flake is still seen)
        float rr = rpx < 1.2 ? r * 1.2 / max(rpx, 1e-6) : r;
        float fade = rpx < 1.2 ? max(rpx / 1.2, 0.12) : 1.0;
        float L = rr + 0.5 * ml;
        // (the corner in the plane of the screen, made in world space: camera right and up from the view matrix)
        vec2 o = a * position.y * L + b * position.x * rr;
        vec3 right = vec3(viewMatrix[0][0], viewMatrix[1][0], viewMatrix[2][0]);
        vec3 up = vec3(viewMatrix[0][1], viewMatrix[1][1], viewMatrix[2][1]);
        vec3 wp = iPR.xyz + right * o.x + up * o.y;
        vQ = position.xy; vL = L / rr; vA = fade * max(rr / L, 0.35);
        vec3 E = uAmb;
        for (int i = 0; i < ${FLAKE_LIGHTS}; i++) {
          if (uLP[i].w <= 0.0) continue;
          vec3 d = uLP[i].xyz - iPR.xyz;
          float d2 = max(dot(d, d), 0.01);
          float win = uLP[i].w < 1e8 ? clamp(1.0 - pow(d2 / (uLP[i].w * uLP[i].w), 2.0), 0.0, 1.0) : 1.0;
          // (irradiance / π: what a white flake sends back; a drop of water sends more forward - lit from behind by a
          // lamp it glows, as the rain around a street lamp at night: uFwd)
          float fw = uFwd > 0.0 ? 1.0 + uFwd * 4.0 * pow(max(dot(-d / sqrt(d2), normalize(cameraPosition - iPR.xyz)), 0.0), 3.0) : 1.0;
          E += uLC[i] / d2 * win * 0.3183 * fw;
        }
        vCol = uTint * E;
        gl_Position = projectionMatrix * viewMatrix * vec4(wp, 1.0);
      }`,
    fragmentShader: `
      uniform float uAlpha;
      varying vec2 vQ; varying float vL; varying float vA; varying vec3 vCol;
      void main() {
        float dy = max(abs(vQ.y) * vL - (vL - 1.0), 0.0);
        float k = length(vec2(vQ.x, dy));
        float al = (1.0 - smoothstep(0.55, 1.0, k)) * vA * uAlpha;
        if (al < 0.003) discard;
        gl_FragColor = vec4(vCol, al);
        #include <tonemapping_fragment>
        #include <colorspace_fragment>
      }`,
    // (both sides: the quad is turned by the direction of the movement on the screen, which may flip its winding -
    // with one side only most flakes were never drawn)
    transparent: true, depthWrite: false, toneMapped: true, side: THREE.DoubleSide,
  });
}
function flakesClear() {
  if (FLAKES.mesh) { scene.remove(FLAKES.mesh); FLAKES.mesh.geometry.dispose(); FLAKES.mesh = null; }
}
function dropsClear() {
  if (DROPS.mesh) { scene.remove(DROPS.mesh); DROPS.mesh.geometry.dispose(); DROPS.mesh = null; }
}
async function dropsSync(m) {
  if (!m) {
    if (DROPS.mesh) { dropsClear(); DROPS.rev = -1; invalidate(); }
    return;
  }
  if (m.rev === DROPS.rev) return;
  const buf = await (await fetch(engineUrl + 'rain/raindrops.bin?f=' + encodeURIComponent(m.file), { cache: 'no-store' })).arrayBuffer();
  const head = new Uint32Array(buf, 0, 2);
  if (head[0] !== 0x31504452) return;
  const n = head[1], hf = new Float32Array(buf, 8, 2);
  const g = fallGeometry(new Float32Array(buf, 16, n * 7), n);
  dropsClear();
  const dropsNew = !DROPS.mat;
  if (!DROPS.mat) { DROPS.mat = fallMat([0.8, 0.83, 0.87]); DROPS.mat.uniforms.uFwd.value = 1; }
  DROPS.mat.uniforms.uBlur.value = hf[0];
  DROPS.mat.uniforms.uAlpha.value = 0.85 - 0.6 * hf[1];        // (clear water: fainter)
  const mesh = new THREE.Mesh(g, DROPS.mat);
  mesh.frustumCulled = false;
  mesh.renderOrder = 5;
  mesh.userData.helper = true;
  mesh.raycast = () => {};
  mesh.name = 'raindrops';
  scene.add(mesh);
  mesh.visible = !viewLight.flakes && !_smartOn;
  DROPS.mesh = mesh;
  DROPS.rev = m.rev;
  if (dropsNew) prepareShaders(tr('Aggiornamento dei materiali nella vista'));
  viewLog(`raindrops: ${n} in the view (blur ${hf[0].toFixed(3)} s)`);
  invalidate();
}
function fallGeometry(data, n) {
  const g = new THREE.InstancedBufferGeometry();
  g.setAttribute('position', new THREE.BufferAttribute(new Float32Array([-1, -1, 0, 1, -1, 0, 1, 1, 0, -1, 1, 0]), 3));
  g.setIndex([0, 1, 2, 0, 2, 3]);
  const ib = new THREE.InstancedInterleavedBuffer(data, 7);
  g.setAttribute('iPR', new THREE.InterleavedBufferAttribute(ib, 4, 0));
  g.setAttribute('iVel', new THREE.InterleavedBufferAttribute(ib, 3, 4));
  g.instanceCount = n;
  return g;
}
async function flakesSync(m) {
  if (!m) {
    if (FLAKES.mesh) { flakesClear(); FLAKES.rev = -1; invalidate(); }
    return;
  }
  if (m.rev === FLAKES.rev) return;
  const buf = await (await fetch(engineUrl + 'rain/snowfall.bin?f=' + encodeURIComponent(m.file), { cache: 'no-store' })).arrayBuffer();
  const head = new Uint32Array(buf, 0, 2);
  if (head[0] !== 0x314C4653) return;
  const n = head[1], blur = new Float32Array(buf, 8, 1)[0];
  const data = new Float32Array(buf, 12, n * 7);
  const g = new THREE.InstancedBufferGeometry();
  g.setAttribute('position', new THREE.BufferAttribute(new Float32Array([-1, -1, 0, 1, -1, 0, 1, 1, 0, -1, 1, 0]), 3));
  g.setIndex([0, 1, 2, 0, 2, 3]);
  const ib = new THREE.InstancedInterleavedBuffer(data, 7);
  g.setAttribute('iPR', new THREE.InterleavedBufferAttribute(ib, 4, 0));
  g.setAttribute('iVel', new THREE.InterleavedBufferAttribute(ib, 3, 4));
  g.instanceCount = n;
  flakesClear();
  const mat = flakesMat();
  mat.uniforms.uBlur.value = blur;
  const mesh = new THREE.Mesh(g, mat);
  mesh.frustumCulled = false;
  mesh.renderOrder = 5;
  mesh.userData.helper = true;
  mesh.raycast = () => {};
  mesh.name = 'snow flakes';
  scene.add(mesh);
  mesh.visible = !viewLight.flakes && !_smartOn;
  FLAKES.mesh = mesh;
  FLAKES.rev = m.rev;
  viewLog(`flakes: ${n} in the view (blur ${blur.toFixed(3)} s)`);
  invalidate();
}
const _flP = new THREE.Vector3();
function flakesUniforms() {
  const mats = [FLAKES.mesh && FLAKES.mat, DROPS.mesh && DROPS.mat].filter(Boolean);
  if (!mats.length) return;
  const u = mats[0].uniforms;
  u.uPx.value = 0.5 * (renderer.domElement.height || 600) * camera.projectionMatrix.elements[5];
  // the sky and the suns (directional): what lights a flake from everywhere; then the nearest lamps
  // a flake is lit from all around: by the sky (its mean light above the horizon, as the snow on the ground gets it)
  // and by the suns and the moon (about a quarter: half of it faces them, at a slant)
  const ei = scene.environmentIntensity || 0;
  const sky = amb.active && amb.skyMean ? amb.skyMean : [0.55, 0.55, 0.55];
  const A = [sky[0] * ei * 0.9, sky[1] * ei * 0.9, sky[2] * ei * 0.9];
  const cand = [];
  // (the lights Simpler knows - those of the scene, the lamps of distributions, the key light - not a walk through
  // the whole scene at every frame: a city has thousands of objects)
  const all = [key, ...[...lights.values()].map((L) => L.light), ...distLamps.pool.point, ...distLamps.pool.spot];
  for (const o of all) {
    if (!o || !o.isLight || !(o.intensity > 0) || !isVisible(o)) continue;
    if (o.isDirectionalLight) { const k = o.intensity * 0.25 / Math.PI; A[0] += o.color.r * k; A[1] += o.color.g * k; A[2] += o.color.b * k; continue; }
    if (o.isPointLight || o.isSpotLight) {
      o.getWorldPosition(_flP);
      cand.push({ p: _flP.clone(), c: o.color, i: o.intensity, r: o.distance > 0 ? o.distance : 1e9, d: _flP.distanceToSquared(camera.position) });
    }
  }
  cand.sort((a, b) => a.d - b.d);
  u.uAmb.value.set(A[0], A[1], A[2]);
  for (let i = 0; i < FLAKE_LIGHTS; i++) {
    const l = cand[i];
    if (!l) { u.uLP.value[i].w = 0; continue; }
    u.uLP.value[i].set(l.p.x, l.p.y, l.p.z, l.r);
    u.uLC.value[i].copy(l.c).multiplyScalar(l.i);
  }
  for (const m of mats.slice(1)) {            // (the drops lit as the flakes: the same numbers)
    const v = m.uniforms;
    v.uPx.value = u.uPx.value; v.uAmb.value.copy(u.uAmb.value);
    for (let i = 0; i < FLAKE_LIGHTS; i++) { v.uLP.value[i].copy(u.uLP.value[i]); v.uLC.value[i].copy(u.uLC.value[i]); }
  }
}

// «Nascondi la neve» (snow.set_hidden): a reminder in the view, and the app told whether it snows with a mantle and
// whether it is hidden (the menu of the right button shows «Nascondi la neve» / «Mostra la neve»)
const _snowState = { present: false, hidden: false };
function snowState(present, hidden) {
  const el = document.getElementById('snowHidden');
  if (el) { el.textContent = tr('Neve nascosta'); el.classList.toggle('on', present && hidden); }
  if (present === _snowState.present && hidden === _snowState.hidden) return;
  _snowState.present = present; _snowState.hidden = hidden;
  post({ type: 'snowState', present, hidden });
}
// (1.75.9) SmartView (the orange button of the app): the engine computes nothing of the view by itself and the app
// keeps the shadows off; here only the reminder (what the engine has not made again simply does not come)
// (1.75.9) the shadows in SmartView: never the shadow level (off/on made every shader of the scene again - SmartView
// was slower than without, Luca): the shadows only faded to 0 and their maps no longer drawn - nothing to rebuild
const SMART = { on: false, saved: new Map(), sig: null, base: new Set(), hidden: new Set(), fillers: [] };
// (1.76.50, audit) the lights Simpler knows every time (a few), the whole scene only when something was added to it
// since the last look: a walk through every object of a big scene twice a second was SmartView's own cost
function smartShadows() {
  if (!SMART.on) return;
  const off = (o) => {
    if (!o || !o.isLight || !o.castShadow || !o.shadow) return;
    if (!SMART.saved.has(o)) SMART.saved.set(o, o.shadow.intensity);
    o.shadow.intensity = 0;
  };
  for (const o of lightList()) off(o);
  if (SMART.addRev !== _addRev) { SMART.addRev = _addRev; scene.traverse(off); }
  renderer.shadowMap.autoUpdate = false;
}
// stand-ins: one per material, shared by every mesh using it
const _standIns = new WeakMap();
function standInOf(x) {
  if (!x || !x.isMaterial || cheapMat(x)) return x;
  let st = _standIns.get(x);
  if (st) return st;
  st = new THREE.MeshBasicMaterial({
    color: x.color ? x.color.clone() : new THREE.Color(0.8, 0.8, 0.8), map: x.map || null, alphaMap: x.alphaMap || null,
    transparent: !!x.transparent, opacity: x.opacity ?? 1, alphaTest: x.alphaTest || 0, side: x.side ?? THREE.FrontSide,
    vertexColors: !!x.vertexColors,
  });
  if (x.emissive && x.emissiveIntensity > 0 && (x.emissive.r + x.emissive.g + x.emissive.b) > 0) st.color.add(x.emissive.clone().multiplyScalar(Math.min(1, x.emissiveIntensity)));
  st.name = x.name;
  st.userData.smartCheap = true; st.userData.dry = true; st.userData.smartOf = x;
  _standIns.set(x, st);
  return st;
}
function smartStandIns() {
  let n = 0;
  scene.traverse((m) => {
    if (!(m.isMesh || m.isPoints) || m.userData.helper || !m.material) return;
    if (!needsProgram(m.material)) return;
    const orig = m.material;
    m.material = Array.isArray(orig) ? orig.map(standInOf) : standInOf(orig);
    m.userData.smartOrig = orig; m.userData.smartSwap = m.material;
    _smartSwapped.add(m); n++;
  });
  if (n) viewLog(`smartview: ${n} meshes drawn with plain stand-ins until SmartView is off`);
}
function smartRestore() {
  for (const m of _smartSwapped) {
    if (m.userData.smartSwap && m.material === m.userData.smartSwap) m.material = m.userData.smartOrig;   // (not if swapped since)
    delete m.userData.smartOrig; delete m.userData.smartSwap;
  }
  const n = _smartSwapped.size, k = _smartPending.size;
  _smartSwapped.clear();
  for (const x of _smartPending) x.needsUpdate = true;
  _smartPending.clear();
  for (const [node, g] of [...scatter.shown]) if (g.userData.smart) { node.remove(g); scatter.shown.delete(node); }
  scatterSelection();
  // the copies of the parts back to their own materials before the preparation, so that it makes their shaders
  for (const P of scatter.protos.values()) for (const part of P.parts || []) for (const m of part.meshes || []) if (m) m.material = part.mat;
  scatter.dirty = true;
  if (n || k) viewLog(`smartview off: ${n} stand-ins back to their materials, ${k} materials to update`);
  shadersDirty(); _shaderNew = true;
}
function setSmartView(on) {
  const was = SMART.on;
  SMART.on = !!on;
  _smartOn = SMART.on;
  if (FLAKES.mesh) FLAKES.mesh.visible = !viewLight.flakes && !_smartOn;      // (falling flakes and drops: not needed
  if (DROPS.mesh) DROPS.mesh.visible = !viewLight.flakes && !_smartOn;        // to set up the scene, a lot to draw)
  if (SMART.on && !was) {
    SMART.at = 0; SMART.addRev = -1; smartShadows();
    SMART.sig = _lightSig;          // (the set the shaders were made for)
    SMART.base = new Set(lightList().filter((x) => x && x.isLight && isVisible(x)));
    for (const [node, g] of [...scatter.shown]) if (!g.userData.smart) { node.remove(g); scatter.shown.delete(node); }
    scatterSelection();
    invalidate();
  } else if (was && !SMART.on) {
    smartRestore();
    for (const o of SMART.hidden) o.visible = true;
    SMART.hidden.clear();
    for (const f of SMART.fillers) { scene.remove(f); if (f.dispose) f.dispose(); }
    SMART.fillers = []; SMART.sig = null;
    for (const [o, v] of SMART.saved) o.shadow.intensity = v;
    SMART.saved.clear();
    renderer.shadowMap.autoUpdate = true;
    renderer.shadowMap.needsUpdate = true;
    invalidate();
  }
  const el = document.getElementById('smartView');
  if (el) { el.textContent = tr('SmartView · vista ferma'); el.classList.toggle('on', !!on); }
}
// The snow mantle (snow.py): a sheet with the thickness of the snow, made by the engine, drawn here as it is (GET
// rain/mantle.bin: vertices, indices, positions, normals, triangles). Not clicked, never wet.
// «MNT3» then groups: the sheet of the ground and of the models, and the mantles of the models of distributions with
// the matrices of their copies (drawn with instancing: 80 cars cost one); the sheet with the sculpted snow also
// carries how pressed the snow is at every vertex (snowsculpt.py): greyer and smoother, as in the path tracing (snow.py
// TRODDEN)
const MANTLE = { rev: -1, meshes: [], mat: null, dirty: false, k: 1, drawn: -1 };
// its material: the trodden snow (compact) greyer and smoother, the old snow (snowAged) with the stains of the
// materials (the same map and uniforms: WET.u); attributes missing in a group read 0
function mantleMat() {
  if (MANTLE.mat) return MANTLE.mat;
  const m = new THREE.MeshStandardMaterial({ roughness: 0.55, metalness: 0 });
  m.color.setRGB(0.88, 0.90, 0.93);
  m.userData.dry = true;           // (the rain and the snow of the materials leave it alone)
  m.onBeforeCompile = (sh) => {
    sh.uniforms.wetMap = WET.u.wetMap; sh.uniforms.wetSo = WET.u.wetSo;
    sh.vertexShader = 'attribute float compact;\nattribute float thin;\nvarying float vCompact;\nvarying float vThin;\nvarying vec3 vSnowW;\n'
      + sh.vertexShader.replace('#include <project_vertex>', `#include <project_vertex>
  vCompact = compact; vThin = thin;
  { vec4 sw = vec4( transformed, 1.0 );
#ifdef USE_INSTANCING
    sw = instanceMatrix * sw;
#endif
    vSnowW = ( modelMatrix * sw ).xyz; }`);
    sh.fragmentShader = 'uniform sampler2D wetMap;\nuniform vec4 wetSo;\nvarying float vCompact;\nvarying float vThin;\nvarying vec3 vSnowW;\n' + SNOW_AGED + sh.fragmentShader
      .replace('#include <color_fragment>', `#include <color_fragment>
  diffuseColor.rgb = snowAged( wetMap, mix( diffuseColor.rgb, vec3( 0.70, 0.73, 0.78 ), vCompact * 0.7 ), vSnowW.xy, wetSo.z, vThin, vCompact );`)
      .replace('#include <roughnessmap_fragment>', `#include <roughnessmap_fragment>
  roughnessFactor = mix( mix( roughnessFactor, 0.35, vCompact ), 0.35, 0.6 * wetSo.z );`);
  };
  m.customProgramCacheKey = () => 'snowMantle2';
  return (MANTLE.mat = m);
}
function mantleClear() {
  for (const m of MANTLE.meshes) { scene.remove(m); m.geometry.dispose(); if (m.isInstancedMesh) m.dispose(); }
  MANTLE.meshes = [];
}
async function mantleSync(m) {
  if (!m) {
    if (MANTLE.meshes.length) { mantleClear(); MANTLE.rev = -1; invalidate(); }
    return;
  }
  if (m.rev === MANTLE.rev) return;
  const buf = await (await fetch(engineUrl + 'rain/mantle.bin?f=' + encodeURIComponent(m.file), { cache: 'no-store' })).arrayBuffer();
  const mat = mantleMat();
  mantleClear();
  const head = new Uint32Array(buf, 0, 2), v3 = head[0] === 0x33544E4D;
  let off = 8;
  for (let gi = 0; gi < head[1]; gi++) {
    const h = new Uint32Array(buf, off, v3 ? 4 : 3), nv = h[0], ni = h[1], nm = h[2], nc = v3 ? h[3] : 0;
    off += v3 ? 16 : 12;
    const g = new THREE.BufferGeometry();
    g.setAttribute('position', new THREE.BufferAttribute(new Float32Array(buf, off, nv * 3), 3)); off += nv * 12;
    g.setAttribute('normal', new THREE.BufferAttribute(new Float32Array(buf, off, nv * 3), 3)); off += nv * 12;
    g.setIndex(new THREE.BufferAttribute(new Uint32Array(buf, off, ni), 1)); off += ni * 4;
    g.computeBoundingSphere();
    let mesh;
    if (nm) {
      mesh = new THREE.InstancedMesh(g, mat, nm);
      const all = new Float32Array(buf.slice(off, off + nm * 64)); off += nm * 64;
      mesh.instanceMatrix.array.set(all);
      mesh.instanceMatrix.needsUpdate = true;
      // (the copies are chosen at every view: mantleLod - only those big enough on the screen)
      mesh.userData.all = all;
      mesh.userData.tris = ni / 3;
      mesh.frustumCulled = false;
    } else mesh = new THREE.Mesh(g, mat);
    if (nc & 1) { g.setAttribute('compact', new THREE.BufferAttribute(new Float32Array(buf, off, nv), 1)); off += nv * 4; }
    if (nc & 2) { g.setAttribute('thin', new THREE.BufferAttribute(new Float32Array(buf, off, nv), 1)); off += nv * 4; }
    mesh.castShadow = mesh.receiveShadow = true;
    mesh.userData.helper = true;
    mesh.raycast = () => {};
    mesh.name = 'snow mantle';
    scene.add(mesh);
    MANTLE.meshes.push(mesh);
  }
  MANTLE.rev = m.rev;
  MANTLE.dirty = true;
  sculptPreviewClear();
  invalidate();
}
// The mantle of the distributions in the real-time view: drawn whole on every copy it was 2.685 million triangles in
// a forest of Luca. As the trees themselves (scatterUpdate), only the copies big enough on the screen get it - from
// MANTLE_MIN of the height of the view (times the automatic LOD of the trees), the biggest first, within
// MANTLE_TRIS; the far ones keep the white of their materials. The path tracing has all of them.
const MANTLE_MIN = 0.12;
const MANTLE_TRIS = 30e6;
const _mcam = new THREE.Matrix4(), _mproj = new THREE.Matrix4(), _mf = new THREE.Frustum(), _mpm = new THREE.Matrix4();
const _msph = new THREE.Sphere(), _mm = new THREE.Matrix4();
function mantleLod() {
  const inst = MANTLE.meshes.filter((m) => m.isInstancedMesh && m.userData.all);
  if (!inst.length) return;
  const moved = !_mcam.equals(camera.matrixWorld) || !_mproj.equals(camera.projectionMatrix);
  if (!moved && !MANTLE.dirty && MANTLE.k === scatter.k) return;
  MANTLE.dirty = false; MANTLE.k = scatter.k;
  _mcam.copy(camera.matrixWorld); _mproj.copy(camera.projectionMatrix);
  _mf.setFromProjectionMatrix(_mpm.multiplyMatrices(camera.projectionMatrix, camera.matrixWorldInverse));
  const tanHalf = Math.tan(THREE.MathUtils.degToRad(camera.fov) / 2);
  const minS = MANTLE_MIN * Math.max(1, scatter.k || 1);
  const recs = [];
  for (const mesh of inst) {
    const g = mesh.geometry;
    if (!g.boundingSphere) g.computeBoundingSphere();
    const bs = g.boundingSphere, all = mesh.userData.all, n = all.length / 16;
    for (let i = 0; i < n; i++) {
      _mm.fromArray(all, i * 16);
      _msph.center.copy(bs.center).applyMatrix4(_mm);
      _msph.radius = bs.radius * _mm.getMaxScaleOnAxis();
      if (!_mf.intersectsSphere(_msph)) continue;
      const d = Math.max(_msph.center.distanceTo(camera.position), 1e-4);
      const sz = _msph.radius / (d * tanHalf);
      if (sz < minS) continue;
      recs.push({ mesh, i, sz });
    }
  }
  recs.sort((a, b) => b.sz - a.sz);
  const count = new Map(inst.map((m) => [m, 0]));
  let tris = 0, drawn = 0;
  for (const r of recs) {
    const t = r.mesh.userData.tris;
    if (tris + t > MANTLE_TRIS && drawn) break;
    const c = count.get(r.mesh);
    r.mesh.instanceMatrix.array.set(r.mesh.userData.all.subarray(r.i * 16, r.i * 16 + 16), c * 16);
    count.set(r.mesh, c + 1);
    tris += t; drawn++;
  }
  for (const m of inst) { m.count = count.get(m); m.instanceMatrix.needsUpdate = true; }
  const total = inst.reduce((a, m) => a + m.userData.all.length / 16, 0);
  if (drawn !== MANTLE.drawn) {
    MANTLE.drawn = drawn;
    viewLog(`snow mantle of distributions: ${drawn} of ${total} copies, ${(tris / 1e6).toFixed(1)} M triangles`);
  }
}
// The shelter map and the «Sempre asciutto» objects come from the engine (GET rain/info): asked again every 1.5 s
// while it rains - the engine makes the map again a moment after the geometry changes (rain.idle)
async function wetPoll() {
  WET.polling = true;
  try {
    while (WET.on && engineUrl) {
      const gen = WET.gen;
      const stale = () => WET.gen !== gen || !WET.on;    // (the rain turned off or changed while waiting: not applied)
      try {
        const inf = await (await fetch(engineUrl + 'rain/info', { cache: 'no-store' })).json();
        if (stale()) continue;
        // (1.79.0) copies of distributions pressed into the sculpted snow (snow.press_update): their points again
        if (inf.pressRev !== undefined && inf.pressRev !== WET.pressRev) {
          const first = WET.pressRev === undefined;
          WET.pressRev = inf.pressRev;
          if (!first) for (const [g, set] of scatter.sets) if (g && !set.local) scatterFetchSet(g, (scatter.syncRev.get(g) || set.rev) + '#p' + inf.pressRev);
        }
        const m = WET.outdoor ? inf.shelter : null;
        if (!m) WET.u.wetS.value.w = 0;
        else if (m.rev !== WET.shelterRev) {
          const buf = await (await fetch(engineUrl + 'rain/shelter.bin?f=' + encodeURIComponent(m.file + '.bin'), { cache: 'no-store' })).arrayBuffer();
          const t = new THREE.DataTexture(new Uint16Array(buf), m.n, m.n, THREE.RedFormat, THREE.HalfFloatType);
          t.magFilter = t.minFilter = THREE.LinearFilter; t.generateMipmaps = false;
          t.wrapS = t.wrapT = THREE.ClampToEdgeWrapping; t.needsUpdate = true;
          const old = WET.u.wetSh.value;
          WET.u.wetSh.value = t;
          if (old && old.image && old.image.width > 1) old.dispose();
          WET.shelterRev = m.rev;
          WET.u.wetS.value.set(m.x0, m.y0, 1 / m.size, 1);
          WET.u.wetZ.value.set(m.zmin, m.zr, m.lo, 0);
          invalidate();
        } else if (WET.outdoor) WET.u.wetS.value.w = 1;
        await wetPaintFetch(inf.paint);
        if (stale()) continue;
        await wetPaintFetch(inf.snowPaint, 'snow');
        if (stale()) continue;
        await mantleSync(inf.mantle);
        if (stale()) continue;
        await flakesSync(inf.snowfall);
        if (stale()) continue;
        await dropsSync(inf.raindrops);
        if (stale()) continue;
        ringsSync(inf.rings);
        if (inf.ocean && OCEAN.info && inf.ocean.rev && inf.ocean.rev !== OCEAN.rev && inf.ocean.rev !== OCEAN.info.rev) {
          OCEAN.info.rev = inf.ocean.rev;      // (the coast measured again after an object moved: ocean.idle_coast)
          // (1.76.30) and its map with it: before the view kept the old one, and where the object had been the
          // water stayed «land» - transparent, the bottom under it looked like ground that was not there (Luca)
          if ('coastMap' in inf.ocean) { OCEAN.info.coastMap = inf.ocean.coastMap; oceanCoastMap(OCEAN.info.coast ? inf.ocean.coastMap : null); }
          oceanFetch();
        }
        await iceSync(inf.ice);
        if (stale()) continue;
        snowState(!!inf.snowMantle, !!inf.snowHidden);
        const dry = new Set(inf.dry || []), nosnow = new Set(inf.nosnow || inf.dry || []);
        const diff = (a, b) => a.size !== b.size || [...a].some((x) => !b.has(x));
        const changed = diff(dry, WET.dry) || diff(nosnow, WET.nosnow);
        WET.dry = dry; WET.nosnow = nosnow;
        wetDryApply();
        if (changed) { scatter.dirty = true; invalidate(300); }     // (the pieces of distributions: per instance)
      } catch { /* the engine is busy or restarting: next time */ }
      await new Promise((r) => { WET.pollWake = r; setTimeout(r, 1500); });
    }
  } finally { WET.polling = false; }
}
// ---- puddles painted by hand (rain.paint_stroke): the map of the engine, and the strokes drawn here at once while
// the mouse moves (the same brush), replaced by the engine's map when it has made the stroke
// two maps of the same kind: the puddles (rain) and the snow painted by hand (snow)
const PAINT_LAYERS = {
  rain: { data: 'paint', rev: 'paintRev', tex: 'wetPaint', F: 'wetPF', Z: 'wetPZ' },
  snow: { data: 'spaint', rev: 'spaintRev', tex: 'wetSPaint', F: 'wetSPF', Z: 'wetSPZ' },
};
async function wetPaintFetch(m, layer = 'rain') {
  const Ly = PAINT_LAYERS[layer];
  if (!m) {
    if (WET[Ly.data]) { WET[Ly.data] = null; WET.u[Ly.F].value.w = 0; invalidate(); }
    WET[Ly.rev] = -1;
    return;
  }
  if (m.rev === WET[Ly.rev] || WET.stroke) return;
  const buf = new Uint8Array(await (await fetch(engineUrl + 'rain/paint.bin?f=' + encodeURIComponent(m.file + '.bin'), { cache: 'no-store' })).arrayBuffer());
  const n = m.n, rgba = new Uint8Array(n * n * 4);
  for (let i = 0, j = 0; i < n * n; i++, j += 3) { rgba[i * 4] = buf[j]; rgba[i * 4 + 1] = buf[j + 1]; rgba[i * 4 + 2] = buf[j + 2]; rgba[i * 4 + 3] = 255; }
  const t = new THREE.DataTexture(rgba, n, n, THREE.RGBAFormat, THREE.UnsignedByteType);
  t.magFilter = t.minFilter = THREE.LinearFilter; t.generateMipmaps = false; t.wrapS = t.wrapT = THREE.ClampToEdgeWrapping;
  t.needsUpdate = true;
  const old = WET.u[Ly.tex].value;
  WET.u[Ly.tex].value = t;
  if (old && old.image && old.image.width > 1) old.dispose();
  WET[Ly.data] = { ...m, data: rgba, tex: t };
  WET[Ly.rev] = m.rev;
  WET.u[Ly.F].value.set(m.x0, m.y0, 1 / m.size, 1);
  WET.u[Ly.Z].value.x = m.z0; WET.u[Ly.Z].value.y = m.zr;
  invalidate();
}
function smooth01(e0, e1, x) { const t = Math.max(0, Math.min(1, (x - e0) / (e1 - e0))); return t * t * (3 - 2 * t); }
// one dab of the brush into the map drawn here (the same as rain.paint_stroke: soft edge from half the radius)
function puddleStamp(p, r, add, layer = 'rain') {
  const P = WET[PAINT_LAYERS[layer].data];
  if (!P) return false;
  const n = P.n, cell = P.size / n, D = P.data;
  const i0 = Math.max(0, Math.floor((p.x - r - P.x0) / cell)), i1 = Math.min(n, Math.floor((p.x + r - P.x0) / cell) + 2);
  const j0 = Math.max(0, Math.floor((p.y - r - P.y0) / cell)), j1 = Math.min(n, Math.floor((p.y + r - P.y0) / cell) + 2);
  if (i0 >= i1 || j0 >= j1) return false;
  const hz = Math.round(Math.max(0, Math.min(1, (p.z - P.z0) / P.zr)) * 255);
  for (let j = j0; j < j1; j++) {
    const cy = P.y0 + (j + 0.5) * cell;
    for (let i = i0; i < i1; i++) {
      const cx = P.x0 + (i + 0.5) * cell;
      const f = 1 - smooth01(0.5, 1, Math.hypot(cx - p.x, cy - p.y) / r);
      if (f <= 0) continue;
      const k = (j * n + i) * 4;
      let a = D[k] / 255, g = D[k + 1] / 255;
      if (add) { a = Math.max(a, f); g *= 1 - f; } else { g = Math.max(g, f); a *= 1 - f; }
      D[k] = Math.round(a * 255); D[k + 1] = Math.round(g * 255);
      if (f > 0.02) D[k + 2] = hz;
    }
  }
  P.tex.needsUpdate = true;
  return true;
}
// the brush of the puddles (Pioggia > Avanzate > Pennello): left button paints, Shift (or «Togli») takes away,
// [ and ] change the size, Esc stops. The right button still turns the view.
// The same brush sculpts the snow (Neve > Avanzate > Scolpisci, layer 'sculpt': snowsculpt.py): the path drawn here
// as a line while the mouse moves, the engine makes the mantle again and the line goes when it arrives.
// The same brush paints the dirt (Materiale > Sporco > Avanzate, layer 'dirt': dirtpaint.py) on any surface: its
// points carry the normal, and the materials painted on are sent with the stroke (their painted dirt goes on).
const puddle = { on: false, mode: 'add', radius: 1, painting: false, pts: [], last: null, layer: 'rain', sculpt: null,
  preset: 'uniforme', strength: 1, mats: new Set() };
function setPuddleBrush(msg) {
  const wasTerrain = puddle.on && puddle.layer === 'terrain';
  puddle.on = !!msg.on;
  puddle.layer = ['snow', 'sculpt', 'dirt', 'terrain'].includes(msg.layer) ? msg.layer : 'rain';   // (the same brush paints the snow: Neve > Avanzate)
  if (msg.terrain) terrainSculptSet(msg.terrain);
  // (1.76.44) «Scultura» left (switched off, another panel, path tracing): its strokes to the engine, once
  if (wasTerrain && !(puddle.on && puddle.layer === 'terrain')) terrainSculptCommit();
  puddle.preset = msg.preset || 'uniforme';
  puddle.strength = Math.max(0.02, Math.min(1, +msg.strength || 1));
  puddle.mode = msg.mode === 'remove' ? 'remove' : 'add';
  puddle.sculpt = msg.sculpt || null;
  puddle.radius = Math.max(0.05, Math.min(puddleMaxRadius(), +msg.radius || 1));
  if (!puddle.on) { puddle.painting = false; brush.visible = false; }
  setGizmosEnabled(!locked && !selectMode && !paint.on && !puddle.on);
  renderer.domElement.style.cursor = puddle.on ? 'crosshair' : '';
}
// (1.75.52) the arrow of the mouse is hidden only while the ring of the brush is there to see: on the sky, or a brush
// of a few cm seen from far (a few pixels), the crosshair stays - before, the mouse «vanished» in the view (Luca,
// «Dipingi lo sporco» of 4.85 cm left on, the cathedral seen whole)
function brushCursor(hit, radius) {
  let px = 0;
  if (hit) {
    const d = Math.max(1e-4, camera.position.distanceTo(hit.point));
    px = radius / (d * Math.tan(THREE.MathUtils.degToRad(camera.fov) / 2)) * (renderer.domElement.clientHeight || 1) / 2;
  }
  const c = hit && px >= 8 ? 'none' : 'crosshair';
  if (renderer.domElement.style.cursor !== c) renderer.domElement.style.cursor = c;
}
// (1.78.4, Luca: «il cerchio per dipingere così chiaro sulla neve non si vede») the brushes used on the snow in strong
// colours: white and pale blue vanished on the white mantle
const SNOW_BRUSH = 0x1e7bff, SCULPT_BRUSH = 0x8a4dff;
function placePuddleBrush(hit, removing) {
  brushCursor(hit, puddle.layer === 'sculpt' ? sculptReach() : puddle.radius);
  if (!hit) { brush.visible = false; return; }
  brush.visible = true;
  brush.position.copy(hit.point).addScaledVector(hit.normal, puddle.radius * 0.01);
  brush.quaternion.setFromUnitVectors(_up, hit.normal);
  brush.scale.setScalar(puddle.radius);
  if (puddle.layer === 'sculpt') brush.scale.setScalar(sculptReach());
  const col = puddle.layer === 'terrain' ? (removing ? 0xe0a070 : 0xd9c08a) : removing ? BRUSH_RED : puddle.layer === 'snow' ? SNOW_BRUSH : puddle.layer === 'sculpt' ? SCULPT_BRUSH : puddle.layer === 'dirt' ? 0xb08a5e : 0x4fb3ff;
  brushMat.color.set(col); brushFill.color.set(col);
}
// how wide the sculpting brush is on the ground: its radius, a footprint, the two tyres
function sculptReach() {
  const s = puddle.sculpt || {};
  if (s.mode === 'steps') return 0.25 * (+s.size || 1);
  if (s.mode === 'tyres') return (+s.gauge || 1.5) / 2 + (+s.width || 0.2) / 2;
  return puddle.radius;
}
function sculptStep() {
  const s = puddle.sculpt || {};
  return s.mode === 'steps' || s.mode === 'tyres' ? 0.08 : Math.max(0.02, puddle.radius * 0.25);
}
const SCULPT = { line: null, timer: 0 };
function sculptPreviewClear() {
  if (!SCULPT.line) return;
  scene.remove(SCULPT.line); SCULPT.line.geometry.dispose(); SCULPT.line = null;
  clearTimeout(SCULPT.timer);
  invalidate();
}
function sculptPreviewDraw() {
  const pts = puddle.pts.map((p) => new THREE.Vector3(p[0], p[1], p[2] + 0.03));
  if (pts.length < 2) pts.push(pts[0].clone().add(new THREE.Vector3(0.01, 0, 0)));
  if (!SCULPT.line) {
    SCULPT.line = new THREE.Line(new THREE.BufferGeometry(), new THREE.LineBasicMaterial({ color: 0x5f8fc0, depthTest: false, transparent: true, opacity: 0.9 }));
    SCULPT.line.userData.helper = true; SCULPT.line.raycast = () => {}; SCULPT.line.renderOrder = 999;
    scene.add(SCULPT.line);
  }
  SCULPT.line.geometry.dispose();
  SCULPT.line.geometry = new THREE.BufferGeometry().setFromPoints(pts);
  invalidate();
}
function puddleDab(hit) {
  const p = hit.point;
  if (puddle.layer === 'terrain') { terrainDab(p); puddle.last = p.clone(); return; }
  if (puddle.layer === 'dirt') {
    const nn = hit.normal;
    puddle.pts.push([+p.x.toFixed(3), +p.y.toFixed(3), +p.z.toFixed(3), +nn.x.toFixed(3), +nn.y.toFixed(3), +nn.z.toFixed(3)]);
    if (hit.mat) puddle.mats.add(hit.mat);
    if (dirtStamp(p, nn, puddle.radius, !puddle.removing, puddle.preset, puddle.strength)) invalidate(200);
    puddle.last = p.clone();
    return;
  }
  puddle.pts.push([+p.x.toFixed(3), +p.y.toFixed(3), +p.z.toFixed(3)]);
  if (puddle.layer === 'sculpt') sculptPreviewDraw();
  else if (puddleStamp(p, puddle.radius, !puddle.removing, puddle.layer)) invalidate(200);
  puddle.last = p.clone();
}
// «Sempre asciutto»: its meshes get a copy of their materials that the rain leaves alone (the materials are shared
// with other objects); taken back when the switch goes off. Again at every poll: an edited material comes back dry.
function wetDryClone(m, code) {
  if (!m || !m.isMeshStandardMaterial) return m;
  const orig = WET.origOf.get(m) || m;
  if (!code) return orig;
  let byCode = WET.dryClones.get(orig);
  if (!byCode) WET.dryClones.set(orig, byCode = new Map());
  let c = byCode.get(code);
  if (!c) {
    c = orig.clone();
    c.onBeforeCompile = orig._ownCompile; c.customProgramCacheKey = orig._ownKey; c.onBeforeRender = orig.onBeforeRender;
    c.userData.dry = code;
    // (the same rings and ice as the original, not frozen copies of them)
    if (orig.userData.rings) c.userData.rings = orig.userData.rings;
    if (orig.userData.ice) c.userData.ice = orig.userData.ice;
    WET.origOf.set(c, orig);
    byCode.set(code, c);
  }
  return c;
}
// the code of an object (or of the group of a distribution) from the two lists of the engine: no rain, no snow
function wetIdCode(id) {
  const r = WET.dry.has(id), s = WET.nosnow.has(id);
  return r && s ? 1 : r ? 2 : s ? 3 : 0;
}
function wetNodeDry(node) {
  let r = false, s = false;
  for (let o = node; o; o = o.parent) {
    const id = o.userData && o.userData.simpler_id;
    if (id) { r = r || WET.dry.has(id); s = s || WET.nosnow.has(id); }
  }
  return r && s ? 1 : r ? 2 : s ? 3 : 0;
}
function wetDryApply() {
  const want = new Map();
  for (const id of new Set([...WET.dry, ...WET.nosnow])) {
    const node = byId.get(id);
    if (node) for (const mesh of ownMeshes(node)) { const c = wetNodeDry(mesh); if (c) want.set(mesh, c); }
  }
  let changed = false;
  for (const mesh of WET.swapped) {
    if (want.has(mesh)) continue;
    const back = (m) => (m && WET.origOf.get(m)) || m;
    mesh.material = Array.isArray(mesh.material) ? mesh.material.map(back) : back(mesh.material);
    // (the original may have missed a change of the rain while it was out of the scene: its shader looked at again)
    for (const m of (Array.isArray(mesh.material) ? mesh.material : [mesh.material])) if (m) m.needsUpdate = true;
    WET.swapped.delete(mesh); changed = true;
  }
  for (const [mesh, code] of want) {
    const cur = mesh.material;
    const next = Array.isArray(cur) ? cur.map((m) => wetDryClone(m, code)) : wetDryClone(cur, code);
    if (Array.isArray(cur) ? next.some((m, i) => m !== cur[i]) : next !== cur) { mesh.material = next; changed = true; shadersDirty(); }
    WET.swapped.add(mesh);
  }
  if (changed) invalidate();
}

const CM = 0.01;
const host = window.chrome && window.chrome.webview ? window.chrome.webview : null;
const params = new URLSearchParams(location.search);
const LANG = (params.get('lang') || 'it').startsWith('en') ? 'en' : 'it';
const EN = {
  'Caricamento della vista 3D…': 'Loading the 3D view…', 'Preparazione dei modelli per la vista…': 'Preparing the models for the view…', 'Preparazione della vista 3D…': 'Preparing the 3D view…',
  'materiali e texture': 'materials and textures', '{0} di {1} MB': '{0} of {1} MB', '{0} di {1}': '{0} of {1}', 'Anteprima non caricata: ': 'Preview not loaded: ',
  'No': 'Off', 'Media': 'Medium', 'Alta': 'High', 'Ultra': 'Ultra', 'Ombre': 'Shadows',
  'Mondo': 'World', 'Locale': 'Local', 'Centro': 'Center', 'Base': 'Base', 'Origine': 'Origin', 'Snap': 'Snap', 'Appoggia': 'Drop',
  'Assi del mondo (Q per cambiare)': 'World axes (Q to switch)', "Assi dell'oggetto (Q per cambiare)": 'Object axes (Q to switch)',
  'Gizmo al centro 3D dell\'oggetto: rotazioni e scale attorno al suo cuore': 'Gizmo at the 3D centre of the object: rotations and scaling around its heart',
  'Centro 3D': '3D centre', 'Base (piedi)': 'Base (feet)', 'Manuale': 'Manual',
  'Gizmo nel pivot spostato a mano (gizmo viola). Centro 3D, Base e Origine lo ignorano finché non clicchi di nuovo qui': 'Gizmo at the pivot moved by hand (violet gizmo). 3D centre, Base and Origin ignore it until you click here again',
  'Gizmo al centro della base, nel punto più basso dell\'oggetto (i piedi di un personaggio): comodo per appoggiarlo su una superficie e ruotarlo sul posto': 'Gizmo at the centre of the base, at the lowest point of the object (the feet of a character): handy to set it on a surface and turn it on the spot',
  "Gizmo nell'origine dell'oggetto, dove l'aveva messa il programma che l'ha creato": "Gizmo at the object's origin, where the program that made it put it",
  'Passaggio al tempo reale': 'Switching to real time',
  'Scatti di spostamento e del 10% di scala (tieni premuto Ctrl mentre trascini per invertire)': 'Snapping of moves and 10% scale steps (hold Ctrl while dragging to invert)',
  'Scatti di rotazione: clic per cambiare (5° → 15° → 45° → 1° → spenti). Ctrl mentre ruoti li inverte': 'Rotation snapping: click to change (5° → 15° → 45° → 1° → off). Ctrl while rotating inverts it', 'libera': 'free',
  'copia': 'copy', 'appoggiato': 'on surface',
  'Occupato · attendi': 'Busy · please wait', 'Aggiornamento delle luci nella vista': 'Updating the lights in the view', 'Aggiornamento delle ombre nella vista': 'Updating the shadows in the view', 'Aggiornamento dei materiali nella vista': 'Updating the materials in the view', 'Preparazione del cielo': 'Preparing the sky', 'Il motore sta lavorando': 'The engine is working', 'Preparazione della vista 3D': 'Preparing the 3D view',
  'Sagome': 'Clay', 'triangoli': 'triangles', '{0} pezzi': '{0} pieces', 'LOD automatico': 'automatic LOD', 'ferma': 'still',
  'Vista ferma: niente da ridisegnare, la scheda video è libera. Si ridisegna da sola appena muovi la vista o cambi qualcosa.': 'Still view: nothing to redraw, the video card is free. It redraws by itself as soon as you move the view or change something.',
  'fps: fotogrammi mostrati, al massimo quanti ne fa lo schermo al secondo (60 Hz = 60): la vista si ferma lì apposta, come ogni pagina web, per non togliere la scheda video al path tracing e non scaldarla per niente. max ≈: quanti fotogrammi al secondo la scheda riuscirebbe a disegnare con questa scena (un fotogramma ogni {0} ms). Se il max scende sotto 30, prova la vista Sagome.': 'fps: frames shown, at most as many as the screen shows per second (60 Hz = 60): the view stops there on purpose, like every web page, so it does not take the video card away from path tracing nor heat it for nothing. max ≈: how many frames per second the card could draw with this scene (one frame every {0} ms). If max drops under 30, try the Clay view.',
  'Appoggia la selezione sulla superficie sottostante': 'Drop the selection onto the surface below',
  'Rettangolo': 'Box', 'Lazo': 'Lasso', 'Salva immagine': 'Save image',
  'Salva in un file l\'immagine della vista come è ora: il path tracing raggiunto finora, o la vista in tempo reale': 'Save to a file the picture of the view as it is now: the path tracing reached so far, or the real-time view',
  'Selezione a rettangolo: tieni premuto il tasto sinistro e trascina; viene selezionato ciò che sta dentro. Ctrl o Maiusc aggiungono, Alt toglie. Clicca di nuovo (o Esc) per tornare a muovere la vista':
    'Box select: hold the left button and drag; what is inside gets selected. Ctrl or Shift add, Alt removes. Click again (or Esc) to go back to moving the view',
  'Selezione a lazo: tieni premuto il tasto sinistro e disegna una forma; viene selezionato ciò che sta dentro. Ctrl o Maiusc aggiungono, Alt toglie. Clicca di nuovo (o Esc) per tornare a muovere la vista':
    'Lasso select: hold the left button and draw a shape; what is inside gets selected. Ctrl or Shift add, Alt removes. Click again (or Esc) to go back to moving the view',
  'Ombre spente nella vista in tempo reale (più veloce)': 'Shadows off in the real-time view (faster)',
  'Qualità ombre in tempo reale: mappa {0}×{0}': 'Real-time shadow quality: {0}×{0} map',
  'Neve nascosta': 'Snow hidden',
  'SmartView · vista ferma': 'SmartView · view on hold',
  'Tempo reale': 'Real time', 'Tempo reale (in movimento)': 'Real time (moving)',
  'Path tracing · {0} campioni ✓': 'Path tracing · {0} samples ✓', 'Path tracing · ✓ finito · {0} campioni': 'Path tracing · ✓ done · {0} samples', 'Path tracing · passaggio {0}/{1} · sto affinando…': 'Path tracing · pass {0}/{1} · refining…', 'Path tracing · passaggio {0}/{1}': 'Path tracing · pass {0}/{1}',
  'Path tracing · calcolo…': 'Path tracing · computing…', 'Path tracing non riuscito: {0}': 'Path tracing failed: {0}',
  'Path tracing · {0}': 'Path tracing · {0}', 'memoria {0}': 'memory {0}', '≈ {0} rimanenti': '≈ {0} left', 'Path tracing · in preparazione…': 'Path tracing · getting ready…',
};
function tr(s, ...args) {
  let out = LANG === 'en' && EN[s] !== undefined ? EN[s] : s;
  args.forEach((a, i) => { out = out.split('{' + i + '}').join(String(a)); });
  return out;
}
const post = (msg) => { if (host) host.postMessage(msg); else console.log('[to host]', JSON.stringify(msg)); };
const AXIS_COLORS = { X: 0xff5c6c, Y: 0x6fdc8c, Z: 0x5b9dff };
const WARM = 0xf2b54b;
let selectMode = '';                 // box / lasso selection in the view: '' | 'rect' | 'lasso'

// ------------------------------------------------------------------ renderer & scene
const container = document.getElementById('view');
const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true, preserveDrawingBuffer: !!params.get('test') });
renderer.setPixelRatio(window.devicePixelRatio);
// (1.75.4) three.js itself sets needsUpdate on the double-sided transmissive materials (glass) at every frame
// (renderTransmissionPass: back side, then front side) - not a change of the scene: inside a render it never asks
// for new shaders in the background (log of Luca, Qashqai: 15 000 requests in 10 s from «Vetro.007», 30 fps)
{
  const plainRender = renderer.render.bind(renderer);
  renderer.render = (...args) => {
    const was = _inCompile;
    _inCompile = true;
    try { return plainRender(...args); } finally { _inCompile = was; }
  };
}
renderer.toneMapping = THREE.AgXToneMapping;
renderer.toneMappingExposure = 1.0;
renderer.shadowMap.enabled = true; // updated by the shadow-quality setting once the page is ready
// (14/11, found with Luca's log) three.js r186 has no PCFSoftShadowMap any more: at the first shadow drawn it changed the
// type to PCFShadowMap by itself. The type is part of the key of every shader: all the shaders made before that first
// shadow (the whole preparation at the opening of a project) were thrown away and made again - one full round more,
// tens of seconds, at every opening. The same shadows as before (it was already PCF on screen), asked for from the start
renderer.shadowMap.type = THREE.PCFShadowMap;
container.appendChild(renderer.domElement);
renderer.domElement.tabIndex = 0;
// the video card was reset (a frame too long for the driver, e.g. many new shaders at once): the drawing would stay
// empty for good. The app restarts the viewer and shows the same scene again.
renderer.domElement.addEventListener('webglcontextlost', () => { try { post({ type: 'contextLost' }); } catch {} });

const scene = new THREE.Scene();
scene.fog = new THREE.FogExp2(0x000000, 0);          // (always there, at density 0 with no fog: see noFog)
scene.background = new THREE.Color(0x141c2c);
const pmrem = new THREE.PMREMGenerator(renderer);
scene.environment = pmrem.fromScene(new RoomEnvironment(), 0.04).texture;
scene.environmentIntensity = 0.65;

// Fallback lighting, used only while the scene has no lights of its own.
const fallback = new THREE.Group();
const key = new THREE.DirectionalLight(0xffffff, 1.6);
key.position.set(-2, -3, 4);
key.castShadow = true;
key.shadow.mapSize.set(2048, 2048);
key.shadow.bias = -0.0002;
key.shadow.normalBias = 0.002;
fallback.add(key, key.target);
scene.add(fallback);
// (1.76.50) the soft light of the fallback always there, only dimmed to 0 when the scene has lights: added and taken
// away (a scene going from no lights to one, a sun replaced) it changed the set of lights of every shader - three.js
// made them all again, 73 times «Aggiornamento delle luci» and 164 s in Luca's logs
const fallbackHemi = new THREE.HemisphereLight(0xdfe8ff, 0x2a2420, 0.35);
scene.add(fallbackHemi);
function setFallback() {
  // (14/11: the fallback sun used to be hidden when the scene has lights of its own: one light WITH shadows more or less in
  // every shader, 30 times «Aggiornamento delle luci» in one day of Luca's log. It stays in the scene, only at power 0 - and
  // without drawing its shadow map)
  const on = lights.size === 0;
  fallbackHemi.intensity = on ? 0.35 : 0;
  key.intensity = on ? 1.6 : 0;
  key.shadow.autoUpdate = on;
  if (on) key.shadow.needsUpdate = true;
}

// ------------------------------------------------------------------ Ambiente (physical sky of the engine)
// The engine path traces a small 360° picture of its sky (ambience.py, in the preview Blender): here it is the
// background and the light of the scene (PMREM), the sun disc is drawn at the sun's place, the haze is a fog with
// the colour of the horizon, the exposure follows the automatic exposure of the engine. Nothing of this costs
// anything per frame: one texture, one small disc.
const amb = { active: false, rev: -1, loading: 0, tex: null, env: null, disc: null, dir: new THREE.Vector3(0, 0, 1), info: null, horizon: null };
const AMB_ROT = new THREE.Euler(Math.PI / 2, 0, 0);       // the equirect is "Y up" for three.js, the scene Z up
const ROOM_ENV = scene.environment;
function setAmbience(info) {
  amb.info = info;
  wetSet(info);
  oceanSet(info && info.ocean, true);
  const on = !!(info && info.state && (info.state.mode === 'sky' || info.state.mode === 'hdri'));
  if (!on) {
    amb.loading++;
    if (amb.active) {
      amb.active = false;
      scene.background = new THREE.Color(0x141c2c);
      scene.backgroundRotation.set(0, 0, 0);
      scene.environment = ROOM_ENV;
      scene.environmentRotation.set(0, 0, 0);
      scene.environmentIntensity = lights.size ? 0.15 : 0.65;
      noFog();
      renderer.toneMappingExposure = 1.0;
      if (amb.disc) amb.disc.visible = false;
      if (amb.night) amb.night.visible = false;
      amb.rev = -1;
    }
    invalidate();
    return;
  }
  amb.active = true;
  if (info.rev !== amb.rev) {
    // a new sky: exposure, haze and sun change together with it when its picture arrives (no flash meanwhile)
    amb.rev = info.rev;
    amb.pending = info;
    if (!amb.tex) ambApply(info);
    ambLoadSky();
    return;
  }
  ambApply(info);
}
// ------------------------------------------------------------------ Paesaggio > Oceano (ocean.py)
// The sea made by the engine with Blender's Ocean modifier: the surface as the engine evaluates it for the view
// (a grid fine near the scene and wider to the horizon, the far waves faded into the flat sea), from ocean/mesh -
// positions and foam at every change, the triangles only when the grid changed. Drawn as the path tracing draws it
// (ocean.py, _material): an opaque water (Fresnel, index 1.333: the sky in it), deep colour, brighter in the crests,
// lacy foam (the mask of the modifier broken up by a noise), rougher where it foams. Out of the rain and the snow
// (userData.dry), out of the boxes of the scene (not under root), never picked.
const OCEAN = { rev: '', topo: '', mesh: null, mat: null, info: null, loading: false, again: false, shallow: false,
  u: { oDeep: { value: new THREE.Vector3() }, oCrest: { value: new THREE.Vector3() }, oH: { value: 1 },
    oCoast: { value: new THREE.Vector4(0, 1, 5, 0) }, oEdge: { value: 0.3 },     // (lines of the shore, their band (m), clarity (m), clear water on)
    // the far waves (ocean._slopes): the map of the slopes of one tile, laid where the grid has faded the waves out
    // (oFarA: tile, 0.5/N, lo, on; oFarB: centre x, y, r0, d0; oFarC: growth per metre past r0, roughness far,
    // distance where the map gives way to it from - to)
    oSlope: { value: null }, oFarA: { value: new THREE.Vector4(100, 0.002, 1, 0) }, oFarB: { value: new THREE.Vector4() },
    oFarC: { value: new THREE.Vector4(0.057, 0.3, 2000, 8000) },
    // the short waves (ocean._detail): their map, its tile (oDetA: tile, 0.5/N, roughness they make far, on) and
    // where they give way to that roughness (oDetB: from - to, m)
    oDetail: { value: null }, oDetA: { value: new THREE.Vector4(2.5, 0.002, 0.3, 0) }, oDetB: { value: new THREE.Vector2(150, 600) },
    // (1.76.27) the coast on a map of square cells (ocean._raster_image: foam of the coast, depth, distance from the
    // shore, coded as oData), read where it reaches instead of the points of the grid - between the long rows of the
    // grid far from the centre the coast came out in straight bands (Luca: «la schiuma della costa è dritta»).
    // oCMapA: x0, y0, 1 / size, on
    oCMap: { value: null }, oCMapA: { value: new THREE.Vector4(0, 0, 1, 0) } },
  slopeRev: '', detailRev: '', coastRev: '' };
const OCEAN_PARS = `
uniform vec3 oDeep; uniform vec3 oCrest; uniform float oH; uniform vec4 oCoast; uniform float oEdge;
uniform sampler2D oSlope; uniform vec4 oFarA; uniform vec4 oFarB; uniform vec4 oFarC;
uniform sampler2D oDetail; uniform vec4 oDetA; uniform vec2 oDetB;
uniform sampler2D oCMap; uniform vec4 oCMapA;
varying vec4 vOD; varying vec3 vOP;
float oHash( vec2 p ) { p = fract( p * vec2( 123.34, 456.21 ) ); p += dot( p, p + 45.32 ); return fract( p.x * p.y ); }
float oNoise( vec2 p ) {
  vec2 i = floor( p ), f = fract( p ); f = f * f * ( 3.0 - 2.0 * f );
  return mix( mix( oHash( i ), oHash( i + vec2( 1.0, 0.0 ) ), f.x ), mix( oHash( i + vec2( 0.0, 1.0 ) ), oHash( i + vec2( 1.0 ) ), f.x ), f.y );
}
float oFbm( vec2 p ) { return 0.5 * oNoise( p ) + 0.3 * oNoise( p * 2.03 + 7.1 ) + 0.2 * oNoise( p * 4.11 + 3.7 ); }
// (1.76.21) a map of slopes laid without repeating (as ocean._antitile): a grid of triangles about half a tile wide,
// every corner with its own random shift of the map, the three corners blended with sharpened weights and the sum
// scaled back to the spread of one map (the waves keep their contrast); the gradients of the tile coordinates for
// every sample, so the shift does not change the mip level. Before, the tile (208 m for «Mosso», 6.5 m for the short
// waves) repeated in rows and diagonals to the horizon (Luca: «guarda che pattern ripetuto ha l'oceano»).
vec2 oH2( vec2 p ) { return fract( sin( vec2( dot( p, vec2( 127.1, 311.7 ) ), dot( p, vec2( 269.5, 183.3 ) ) ) ) * 43758.5453 ); }
vec3 oTile( sampler2D t, vec2 uv, float px ) {
  vec2 gx = dFdx( uv ), gy = dFdy( uv );
  vec2 s = vec2( uv.x - 0.57735027 * uv.y, 1.15470054 * uv.y ) * 2.0;
  vec2 b = floor( s ), f = s - b;
  bool up = f.x + f.y > 1.0;
  vec2 v1 = up ? b + 1.0 : b;
  vec2 v2 = up ? b + vec2( 0.0, 1.0 ) : b + vec2( 1.0, 0.0 );
  vec2 v3 = up ? b + vec2( 1.0, 0.0 ) : b + vec2( 0.0, 1.0 );
  vec3 w = up ? vec3( f.x + f.y - 1.0, 1.0 - f.x, 1.0 - f.y ) : vec3( 1.0 - f.x - f.y, f.x, f.y );
  w = w * w; w = w * w; w /= w.x + w.y + w.z;
  vec3 a1 = textureGrad( t, uv + oH2( v1 ) + px, gx, gy ).xyz;
  vec3 a2 = textureGrad( t, uv + oH2( v2 ) + px, gx, gy ).xyz;
  vec3 a3 = textureGrad( t, uv + oH2( v3 ) + px, gx, gy ).xyz;
  vec3 m = w.x * a1 + w.y * a2 + w.z * a3;
  // (x, y: the slope, its contrast kept; z: the third channel - the foam of the far map - a plain weighted mean)
  return vec3( ( m.xy * 2.0 - 1.0 ) / sqrt( dot( w, w ) ), m.z );
}
`;
// per point (ocean.mesh_bytes): foam of the sea, foam of the coast, depth (-2 .. 30 m, negative on land), distance
// from the shore / 12 m.
// As ocean._material: the sea foam, the coast foam (a denser lace), the lines along the shore, the clear shallow
// water - here as transparency (the bottom drawn under it, the bright reflections kept), not the refraction of
// the path tracing.
function oceanMaterial() {
  const m = new THREE.MeshPhysicalMaterial({ color: 0xffffff, roughness: 0.04, metalness: 0, ior: 1.333, specularIntensity: 1 });
  m.userData.dry = true;
  m.onBeforeCompile = (sh) => {
    Object.assign(sh.uniforms, OCEAN.u);
    sh.vertexShader = 'attribute vec4 oData;\nvarying vec4 vOD;\nvarying vec3 vOP;\n' + sh.vertexShader
      .replace('#include <begin_vertex>', '#include <begin_vertex>\nvOD = oData; vOP = position;');
    sh.fragmentShader = OCEAN_PARS + sh.fragmentShader
      .replace('#include <color_fragment>', `#include <color_fragment>
  float oCr = smoothstep( -0.1 * oH, 0.6 * max( oH, 0.05 ), vOP.z ) * 0.75;
  diffuseColor.rgb = mix( oDeep, oCrest, oCr );
  vec4 oD = vOD;
  if ( oCMapA.w > 0.0 ) {
    vec2 oCu = ( vOP.xy - oCMapA.xy ) * oCMapA.z;
    // (1.76.31) only where the map is finer than the grid (oCMapA.w: its cell): a coast as long as a whole terrain
    // has cells of 3 m, coarser than the grid near the scene - there the points stay (as ocean._material)
    float oSpG = oFarB.w > 0.0 ? oFarB.w + oFarC.x * max( 0.0, max( abs( vOP.x - oFarB.x ), abs( vOP.y - oFarB.y ) ) - oFarB.z ) : 1e6;
    if ( oCu.x >= 0.0 && oCu.y >= 0.0 && oCu.x <= 1.0 && oCu.y <= 1.0 )
      oD.yzw = mix( oD.yzw, texture2D( oCMap, oCu ).rgb, smoothstep( oCMapA.w, 2.0 * oCMapA.w, oSpG ) );
  }
  float oN = 0.5 + ( oFbm( vOP.xy * 5.0 ) - 0.5 ) * 0.43;    // (the spread of Blender's noise: σ 0.057 against 0.132, measured)
  // (1.76.21) where the grid has grown wide (its rows in front of a camera: 1 m across, 30 m along) the foam of the
  // far map instead of the one of the points - drawn between them it was long white streaks (as ocean._material)
  float oSp = oFarB.w + oFarC.x * max( 0.0, max( abs( vOP.x - oFarB.x ), abs( vOP.y - oFarB.y ) ) - oFarB.z );
  float oFar = smoothstep( oFarA.z, 2.0 * oFarA.z, oSp ) * oFarA.w;
  vec3 oFS = oFarA.w > 0.0 ? oTile( oSlope, vOP.xy / oFarA.x, oFarA.y ) : vec3( 0.0 );
  float oFoamF = smoothstep( 0.15, 0.9, mix( vOD.x, oFS.z, oFar ) * clamp( oN * 3.8 - 1.6, 0.0, 1.0 ) ) * 0.8;
  float oGate = mix( 0.35, 1.0, smoothstep( -0.1 * oH, 0.4 * max( oH, 0.05 ), vOP.z ) );      // (more on the crests)
  float oPatch = mix( 0.45, 1.0, smoothstep( 0.35, 0.65, 0.5 + ( oFbm( vOP.xy * 0.18 ) - 0.5 ) * 0.43 ) );
  // (1.76.22) the surf as foam: white patches with sharp edges and holes, the amount of surf how much of the water
  // is white (as ocean._material: a field cut at a level the amount lowers) - before, a soft grey veil (Luca)
  float oZA = ( oFbm( vOP.xy * 0.7 + vec2( 11.3, -4.7 ) ) - 0.5 ) / 0.132;
  float oZB = ( oN - 0.5 ) / 0.057;
  float oFld = 0.55 * oZA + 0.85 * oZB + 1.2 * ( oGate - 0.675 ) / 0.325;
  float oCut = oFld - ( 2.2 - 4.4 * oD.y * oPatch );
  oFoamF = max( oFoamF, smoothstep( -0.3, 0.3, oCut ) * ( 0.5 + 0.45 * smoothstep( 0.3, 1.6, oCut ) ) * smoothstep( 0.0, 0.08, oD.y ) );
  float oShore = oD.w * 12.0;
  float oBroken = smoothstep( 0.42, 0.58, 0.5 + ( oFbm( vOP.xy * 0.18 ) - 0.5 ) * 0.43 );
  oFoamF = max( oFoamF, ( 1.0 - smoothstep( 0.0, oCoast.y, oShore ) ) * smoothstep( 0.75, 0.97, 0.5 + 0.5 * sin( oShore * 7.0 + oN * 40.0 ) ) * oBroken * oCoast.x );
  float oDepth = oD.z * 32.0 - 2.0;                         // (negative on land: its height over the sea)
  float oT = ( 1.0 - smoothstep( 0.35 * oCoast.z, oCoast.z, oDepth ) ) * ( 1.0 - oFoamF ) * oCoast.w;
  diffuseColor.rgb = mix( diffuseColor.rgb, oCrest * 1.4, oT * 0.6 );
  diffuseColor.rgb = mix( diffuseColor.rgb, vec3( 0.82, 0.86, 0.88 ), oFoamF );`)
      .replace('#include <roughnessmap_fragment>', `#include <roughnessmap_fragment>
  roughnessFactor = mix( roughnessFactor, 0.55, max( oFoamF, ( 1.0 - smoothstep( 0.0, 0.3, oDepth ) ) * 0.6 * step( 0.001, oCoast.x + oCoast.w ) ) );
  // the far waves (as ocean._material): where the grid has faded them, their slopes from the map; farther, where
  // they are smaller than a pixel, the roughness of the open sea
  // (at a grazing angle the eye sees only the faces turned to it: short waves and roughness give way - ocean._material)
  float oGz = smoothstep( 0.03, 0.35, abs( dot( normalize( vViewPosition ), normalize( vNormal ) ) ) );
  float oG = smoothstep( oFarC.z, oFarC.w, length( vViewPosition ) ) * oFarA.w * oGz;
  roughnessFactor = mix( roughnessFactor, max( roughnessFactor, oFarC.y ), oG );
  float oGd = smoothstep( oDetB.x, oDetB.y, length( vViewPosition ) ) * oDetA.w * oGz;
  roughnessFactor = mix( roughnessFactor, max( roughnessFactor, oDetA.z ), oGd );`)
      .replace('#include <normal_fragment_maps>', `#include <normal_fragment_maps>
  if ( oFarA.w > 0.0 ) {
    vec3 oM = vec3( oFS.xy, sqrt( max( 0.0, 1.0 - dot( oFS.xy, oFS.xy ) ) ) );
    float oW = smoothstep( oFarA.z, 2.0 * oFarA.z, oSp ) * ( 1.0 - smoothstep( oFarC.z, oFarC.w, length( vViewPosition ) ) );
    normal = normalize( mix( normal, normalize( mat3( viewMatrix ) * oM ), oW ) );
  }
  // (1.76.33) near what the sea touches, the water more broken (the path tracing raises it in true shape there:
  // ocean._fade_group; here only its light, so the view stays light) - oCoast.y: the band of the shore
  if ( oCoast.x + oCoast.w > 0.0 && oShore < oCoast.y * 1.6 ) {
    float oEb = ( 1.0 - smoothstep( 0.0, oCoast.y * 1.6, oShore ) ) * min( 1.0, oH * 4.0 );
    vec2 oEg = vec2( oFbm( vOP.xy * 1.4 + vec2( 0.31, 0.0 ) ) - oFbm( vOP.xy * 1.4 - vec2( 0.31, 0.0 ) ),
                     oFbm( vOP.xy * 1.4 + vec2( 0.0, 0.31 ) ) - oFbm( vOP.xy * 1.4 - vec2( 0.0, 0.31 ) ) ) * 1.6;
    normal = normalize( normal + mat3( viewMatrix ) * vec3( oEg, 0.0 ) * oEb );
  }
  if ( oDetA.w > 0.0 ) {
    vec2 oDm = oTile( oDetail, vOP.xy / oDetA.x, oDetA.y ).xy;
    float oWd = ( 1.0 - smoothstep( oDetB.x, oDetB.y, length( vViewPosition ) ) )
      * smoothstep( 0.03, 0.35, abs( dot( normalize( vViewPosition ), normalize( vNormal ) ) ) );
    normal = normalize( normal + mat3( viewMatrix ) * vec3( oDm.xy, 0.0 ) * oWd );
  }`)
      .replace('#include <opaque_fragment>', `
  float oA = 1.0;
  if ( oCoast.w > 0.0 ) {
    float oCos = max( abs( dot( geometryViewDir, normal ) ), 0.2 );
    oA = mix( 1.0, 1.0 - exp( - oDepth * 2.5 / max( oCoast.z, 0.1 ) / oCos ), oT );
  }
  // (plain alpha blending: three.js blends after the tone mapping, so adding the reflection to the bottom
  // (premultiplied) went white on light sand; where the reflection is bright it stays, as the eye sees it)
  oA = max( oA, min( 1.0, dot( outgoingLight - totalDiffuse, vec3( 0.3, 0.59, 0.11 ) ) * 2.0 ) * oT );
  // the edge of the water: the thinnest film fades into the wet sand (as ocean._material, _edge)
  if ( oCoast.x + oCoast.w > 0.0 ) oA *= smoothstep( 0.0, oEdge, oDepth + vOP.z );
  gl_FragColor = vec4( outgoingLight, oA );`);
  };
  m.customProgramCacheKey = () => 'ocean14';
  return m;
}
function oceanSet(o, fromAmb) {
  OCEAN.info = o && o.on ? o : null;
  // (a change from the panel: the shore band of the wet shaders follows - from the Ambiente it is already there)
  if (!fromAmb && amb.info) { amb.info.ocean = o; wetSet(amb.info); }
  if (!OCEAN.info) {
    if (OCEAN.mesh) { scene.remove(OCEAN.mesh); OCEAN.mesh.geometry.dispose(); OCEAN.mesh = null; OCEAN.rev = ''; OCEAN.topo = ''; invalidate(); }
    return;
  }
  OCEAN.u.oDeep.value.fromArray(o.deep || [0.004, 0.025, 0.045]);
  OCEAN.u.oCrest.value.fromArray(o.crest || [0.02, 0.14, 0.16]);
  OCEAN.u.oH.value = +o.height || 0;
  if (OCEAN.mat) OCEAN.mat.roughness = 0.015 + 0.06 * (+o.ripples || 0);
  if (OCEAN.mesh) OCEAN.mesh.position.z = +o.level || 0;
  oceanCoast(o);
  oceanFar(o.far);
  oceanCoastMap(o.coast ? o.coastMap : null);
  if (o.rev !== OCEAN.rev) oceanFetch();
  invalidate();
}
function oceanCoast(o) {
  const H = +o.height || 0, coast = !!o.coast;
  OCEAN.u.oEdge.value = +o.edge || 0.3;
  OCEAN.u.oCoast.value.set(coast ? 0.5 * (+o.coastFoam || 0) : 0, 1.5 * (0.4 + 0.6 * H), +o.clear || 5, o.shallow ? 1 : 0);
  const shallow = !!o.shallow || coast;      // (the edge of the water fades out too: transparent with the coast on)
  if (OCEAN.mat && OCEAN.mat.transparent !== shallow) { OCEAN.mat.transparent = shallow; OCEAN.mat.needsUpdate = true; }
}
function oceanFar(f) {
  const u = OCEAN.u;
  if (!f || !f.on || !f.rev) { u.oFarA.value.w = 0; u.oDetA.value.w = 0; return; }
  u.oFarA.value.set(f.S, 0.5 / f.N, f.lo, u.oSlope.value ? 1 : 0);
  u.oFarB.value.set(f.cx, f.cy, f.r0, f.d0);
  u.oFarC.value.set(f.grow / (1 + f.grow), f.rough, f.g0, f.g1);
  u.oDetA.value.set(f.L || 2.5, 0.5 / f.N, f.roughD || 0, u.oDetail.value && f.drev ? 1 : 0);
  u.oDetB.value.set(60 * (f.L || 2.5), 240 * (f.L || 2.5));
  if (f.drev && f.drev !== OCEAN.detailRev) {
    OCEAN.detailRev = f.drev;
    oceanTex(`${engineUrl}ocean/slopes?which=detail&rev=${f.drev}`, () => OCEAN.detailRev === f.drev, (t) => {
      const old = u.oDetail.value; u.oDetail.value = t; u.oDetA.value.w = 1; if (old) old.dispose();
    }, () => { OCEAN.detailRev = ''; });
  }
  if (f.rev === OCEAN.slopeRev) return;
  OCEAN.slopeRev = f.rev;
  oceanTex(`${engineUrl}ocean/slopes?rev=${f.rev}`, () => OCEAN.slopeRev === f.rev, (t) => {
    const old = u.oSlope.value; u.oSlope.value = t; u.oFarA.value.w = 1; if (old) old.dispose();
  }, () => { OCEAN.slopeRev = ''; });
}
function oceanCoastMap(c) {
  const u = OCEAN.u;
  if (!c || !c.rev || !(c.size > 0)) { u.oCMapA.value.w = 0; return; }
  const cell = c.cell || c.size / (c.n || 1024);
  u.oCMapA.value.set(c.x0, c.y0, 1 / c.size, u.oCMap.value && OCEAN.coastRev === c.rev ? cell : 0);
  if (c.rev === OCEAN.coastRev) return;
  OCEAN.coastRev = c.rev;
  u.oCMapA.value.w = 0;           // (the grid's points until the new map is in: never the old map at the new place)
  oceanTex(`${engineUrl}ocean/slopes?which=coast&rev=${c.rev}`, () => OCEAN.coastRev === c.rev, (t) => {
    t.wrapS = t.wrapT = THREE.ClampToEdgeWrapping;
    t.generateMipmaps = false; t.minFilter = THREE.LinearFilter; t.anisotropy = 1; t.needsUpdate = true;
    const old = u.oCMap.value; u.oCMap.value = t; u.oCMapA.value.w = c.cell || c.size / (c.n || 1024); if (old) old.dispose();
  }, () => { OCEAN.coastRev = ''; });
}
function oceanTex(url, still, use, fail) {
  new THREE.TextureLoader().load(url, (t) => {
    if (!still()) { t.dispose(); return; }
    t.wrapS = t.wrapT = THREE.RepeatWrapping;
    t.colorSpace = THREE.NoColorSpace;
    t.anisotropy = 8;
    use(t);
    invalidate();
  }, undefined, fail);
}
async function oceanFetch() {
  if (OCEAN.loading) { OCEAN.again = true; return; }
  OCEAN.loading = true;
  try {
    const r = await fetch(`${engineUrl}ocean/mesh?topo=${encodeURIComponent(OCEAN.mesh ? OCEAN.topo : '')}`);
    if (!r.ok) return;
    const buf = await r.arrayBuffer();
    const dv = new DataView(buf);
    if (buf.byteLength < 16 || dv.getUint32(0, true) !== 0x324E434F) return;      // 'OCN2'
    const n = dv.getUint32(4, true), ni = dv.getUint32(8, true), nr = dv.getUint32(12, true);
    let off = 16;
    const rev = new TextDecoder().decode(new Uint8Array(buf, off, nr)); off += nr + ((4 - nr % 4) % 4);
    const topo = new TextDecoder().decode(new Uint8Array(buf, off, 64)).replace(/\0+$/, ''); off += 64;
    const pos = new Float32Array(buf, off, n * 3); off += n * 12;
    const data = new Uint8Array(buf, off, n * 4); off += n * 4;
    const idx = ni ? new Uint32Array(buf, off, ni) : null;
    if (!OCEAN.info) return;
    oceanBuild(pos, data, idx, topo);
    OCEAN.rev = rev;
  } catch (e) { console.error('ocean', e); }
  finally {
    OCEAN.loading = false;
    const retry = OCEAN.again;       // (a change arrived meanwhile, or the triangles are needed: never a loop on errors)
    OCEAN.again = false;
    if (retry && OCEAN.info) oceanFetch();
  }
}
function oceanBuild(pos, data, idx, topo) {
  let g = OCEAN.mesh && OCEAN.mesh.geometry;
  const same = g && !idx && g.attributes.position.count * 3 === pos.length;
  if (!same) {
    if (!idx) { OCEAN.topo = ''; OCEAN.again = true; return; }      // (the view lost its triangles: asked again with them)
    g = new THREE.BufferGeometry();
    g.setAttribute('position', new THREE.BufferAttribute(new Float32Array(pos), 3));
    g.setAttribute('oData', new THREE.BufferAttribute(new Uint8Array(data), 4, true));
    g.setIndex(new THREE.BufferAttribute(new Uint32Array(idx), 1));
    if (!OCEAN.mat) { OCEAN.mat = oceanMaterial(); if (OCEAN.info) oceanCoast(OCEAN.info); }
    const old = OCEAN.mesh;
    OCEAN.mesh = new THREE.Mesh(g, OCEAN.mat);
    OCEAN.mesh.frustumCulled = false;
    OCEAN.mesh.receiveShadow = true;
    OCEAN.mesh.raycast = () => {};
    OCEAN.mesh.name = 'Simpler Oceano';
    scene.add(OCEAN.mesh);
    if (old) { scene.remove(old); old.geometry.dispose(); }
    OCEAN.topo = topo;
  } else {
    g.attributes.position.array.set(pos); g.attributes.position.needsUpdate = true;
    g.attributes.oData.array.set(data); g.attributes.oData.needsUpdate = true;
  }
  g.computeVertexNormals();
  OCEAN.mesh.position.z = OCEAN.info ? +OCEAN.info.level || 0 : 0;
  OCEAN.mat.roughness = 0.015 + 0.06 * (+(OCEAN.info && OCEAN.info.ripples) || 0);
  shadersDirty();
  invalidate();
}
// (15/11, Luca's log: «shaders ready in 19755 ms (104 new)» and «slow frame: 57199 ms … fogExp2 true→false, −fog» after the fog
// was taken to 0) with or without fog three.js wants a different shader for EVERY material: turning the fog on or off made
// them all again. The view always has its fog, at density 0 when there is none (nothing drawn changes: the factor is 0):
// the shaders are the same with and without fog, in every project
function noFog() {
  if (scene.fog && scene.fog.isFogExp2) scene.fog.density = 0; else scene.fog = new THREE.FogExp2(0x000000, 0);
  FOG_SHAPE[0] = 1e7; FOG_SHAPE[1] = 0; FOG_SHAPE[2] = 0; FOG_SHAPE[3] = 0;
}
function ambApply(info) {
  renderer.toneMappingExposure = Math.pow(2, info.evTotal || 0);
  if (info.sun) {
    amb.dir.fromArray(info.sun.dir).normalize();
    ambDisc(info.sun);
  }
  const V = info.fog ? info.fog.visibility : 0;
  if (V > 0) {
    // (three.js hands the fog colour to the shader in the output colour space; here the fog is mixed in before the
    // tone mapping, in linear light: given "as sRGB", the shader receives exactly these linear values)
    const c = new THREE.Color().setRGB(...info.fog.color, THREE.SRGBColorSpace);
    if (scene.fog && scene.fog.isFogExp2) { scene.fog.color.copy(c); scene.fog.density = 1 / V; } else scene.fog = new THREE.FogExp2(c, 1 / V);
    FOG_SHAPE[0] = info.fog.height ?? 1e7; FOG_SHAPE[1] = info.fog.height != null ? (info.fog.falloff || 1) : 0;
    FOG_SHAPE[2] = info.fog.start || 0; FOG_SHAPE[3] = info.fog.haze2 || 0;     // (+ the haze above a low fog)
  } else noFog();
  // (the colour of the sky at the horizon for a fog everywhere: objects melt into it; a low fog keeps its own colour,
  // the sky above it stays clear - as in the path tracing)
  if (amb.horizon && V > 0 && scene.fog && !(info.fog && info.fog.height != null)) scene.fog.color.setRGB(...amb.horizon, THREE.SRGBColorSpace);
  ambNight(info.night);
  invalidate();
}
function ambDisc(sun) {
  if (!amb.disc) {
    amb.disc = new THREE.Mesh(new THREE.CircleGeometry(1, 48), new THREE.MeshBasicMaterial({ color: 0xffffff, fog: false, depthWrite: false }));
    amb.disc.userData.helper = true;
    amb.disc.raycast = () => {};
    amb.disc.frustumCulled = false;
    amb.disc.renderOrder = -1;
    scene.add(amb.disc);
  }
  const half = THREE.MathUtils.degToRad(Math.max(0.05, sun.size || 0.545)) / 2;
  if (sun.disc) {
    // the colour a photo shows (ambience.sun_disc_display, as in Cycles): orange and red at the horizon
    const k = Math.pow(2, -((amb.info && amb.info.ev) || 0));
    amb.disc.material.color.setRGB(sun.disc[0] * k, sun.disc[1] * k, sun.disc[2] * k, THREE.LinearSRGBColorSpace);
  } else {
    // radiance of the disc = irradiance / solid angle (HDRI sun: burnt white-yellow)
    const k = 1 / Math.max(1e-6, 2 * Math.PI * (1 - Math.cos(half)));
    amb.disc.material.color.setRGB(sun.rgb[0] * k, sun.rgb[1] * k, sun.rgb[2] * k, THREE.LinearSRGBColorSpace);
  }
  amb.disc.userData.half = half;
  amb.disc.visible = amb.dir.z > -0.02 && Math.max(...sun.rgb) > 0;
}
// ---- night sky: the real stars and the moon (ambience._night_sky in Cycles, the same formulas): drawn here sharp
// on a sphere around the camera, added to the baked sky (which has them at 0, night_k)
const NIGHT_VS = `varying vec3 vDir;
void main() { vDir = position; gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0); }`;
const NIGHT_FS = `uniform sampler2D starsTex, moonTex; uniform vec3 P, A, B, mM, mR, mU; uniform float lst, starsK, cover, sinR,
radius, lx, lz, disc, halo, earthshine, moonOn, starsOn; varying vec3 vDir;
const float PI = 3.14159265;
void main() {
  vec3 d = normalize(vDir), col = vec3(0.0);
  if (starsOn > 0.5) {
    float dec = asin(clamp(dot(d, P), -1.0, 1.0)), ha = atan(dot(d, B), dot(d, A));
    vec2 uv = vec2(0.5 - lst / (2.0 * PI) + ha / (2.0 * PI), 0.5 + dec / PI);
    vec3 t = texture2D(starsTex, uv).rgb;
    col += t * t * starsK * smoothstep(-0.01, 0.06, d.z) * (1.0 - 0.8 * cover);
  }
  if (moonOn > 0.5) {
    float cm = dot(d, mM), x = dot(d, mR) / sinR, y = dot(d, mU) / sinR, rho2 = x * x + y * y, rho = sqrt(rho2);
    float mask = clamp((1.0 - rho) / 0.02, 0.0, 1.0) * step(0.0, cm);
    if (mask > 0.0) {
      float z = sqrt(max(0.0, 1.0 - rho2));
      vec2 tu = vec2(0.5 + atan(x, z) / (2.0 * PI), 0.5 + asin(clamp(y, -1.0, 1.0)) / PI);
      float shade = max(x * lx + z * lz, 0.0) + earthshine;
      col += texture2D(moonTex, tu).rgb * shade * mask * disc;
    }
    if (halo > 0.0) {
      float t = max(acos(clamp(cm, -1.0, 1.0)) - radius, 0.0) / radians(3.0);
      col += vec3(0.8, 0.86, 1.0) * exp(-t) * halo * (1.0 - mask);
    }
  }
  gl_FragColor = vec4(col, 1.0);
  #include <tonemapping_fragment>
  #include <colorspace_fragment>
}`;
function ambNight(n) {
  const on = !!(amb.active && n && n.ready);
  if (!on) { if (amb.night) amb.night.visible = false; return; }
  if (!amb.night) {
    const mat = new THREE.ShaderMaterial({
      vertexShader: NIGHT_VS, fragmentShader: NIGHT_FS, side: THREE.BackSide, transparent: true, depthWrite: false,
      blending: THREE.AdditiveBlending, fog: false, toneMapped: true,
      uniforms: { starsTex: { value: null }, moonTex: { value: null }, P: { value: new THREE.Vector3() }, A: { value: new THREE.Vector3() },
        B: { value: new THREE.Vector3() }, mM: { value: new THREE.Vector3() }, mR: { value: new THREE.Vector3() }, mU: { value: new THREE.Vector3() },
        lst: { value: 0 }, starsK: { value: 0 }, cover: { value: 0 }, sinR: { value: 0.01 }, radius: { value: 0.01 }, lx: { value: 0 },
        lz: { value: 1 }, disc: { value: 0 }, halo: { value: 0 }, earthshine: { value: 0 }, moonOn: { value: 0 }, starsOn: { value: 0 } },
    });
    amb.night = new THREE.Mesh(new THREE.SphereGeometry(1, 64, 32), mat);
    amb.night.userData.helper = true; amb.night.raycast = () => {}; amb.night.frustumCulled = false; amb.night.renderOrder = -1;
    scene.add(amb.night);
  }
  const U = amb.night.material.uniforms, key = JSON.stringify(n.rev || '');
  if (amb.nightKey !== key && engineUrl) {
    amb.nightKey = key;
    const load = (f, color) => new THREE.TextureLoader().loadAsync(engineUrl + 'ambience/night/file?f=' + f + '&r=' + encodeURIComponent(key)).then((t) => {
      t.colorSpace = color ? THREE.SRGBColorSpace : THREE.NoColorSpace;
      t.wrapS = THREE.RepeatWrapping; t.wrapT = THREE.ClampToEdgeWrapping;
      t.minFilter = THREE.LinearFilter; t.magFilter = THREE.LinearFilter; t.generateMipmaps = false; t.anisotropy = 1;
      return t;
    });
    load('stars', false).then((t) => { if (U.starsTex.value) U.starsTex.value.dispose(); U.starsTex.value = t; invalidate(); }).catch(() => {});
    load('moon', true).then((t) => { if (U.moonTex.value) U.moonTex.value.dispose(); U.moonTex.value = t; invalidate(); }).catch(() => {});
  }
  U.P.value.fromArray(n.P); U.A.value.fromArray(n.A); U.B.value.fromArray(n.B);
  U.lst.value = n.lst; U.starsK.value = n.stars || 0; U.cover.value = n.cover || 0;
  const m = n.moon;
  U.moonOn.value = m ? 1 : 0;
  if (m) {
    U.mM.value.fromArray(m.m); U.mR.value.fromArray(m.r); U.mU.value.fromArray(m.u);
    U.sinR.value = m.sinR; U.radius.value = m.radius; U.lx.value = m.lx; U.lz.value = m.lz;
    U.disc.value = m.disc; U.halo.value = m.halo; U.earthshine.value = m.earthshine;
  }
  const show = () => { U.starsOn.value = U.starsTex.value && (n.stars || 0) > 0 ? 1 : 0; if (!U.moonTex.value) U.moonOn.value = 0; };
  show();
  amb.night.onBeforeRender = () => { show(); amb.night.position.copy(camera.position); amb.night.scale.setScalar(camera.far * 0.95); amb.night.updateMatrixWorld(); };
  amb.night.visible = true;
  invalidate();
}
function ambPlaceDisc() {
  if (!amb.active || !amb.disc || !amb.disc.visible) return;
  const D = camera.far * 0.9;
  amb.disc.position.copy(camera.position).addScaledVector(amb.dir, D);
  amb.disc.scale.setScalar(D * Math.tan(amb.disc.userData.half));
  amb.disc.lookAt(camera.position);
}
async function ambLoadSky() {
  if (!engineUrl) return;
  const my = ++amb.loading;
  busyWarn.sky = my;               // «Occupato · attendi» while the picture of the new sky is made (a few seconds)
  try {
    const job = await (await fetch(engineUrl + 'ambience/bake', { cache: 'no-store' })).json();
    let st = null;
    for (let i = 0; i < 600; i++) {
      st = await (await fetch(engineUrl + 'ambience/sky?id=' + job.id, { cache: 'no-store' })).json();
      if (my !== amb.loading) return;
      if (st.state !== 'running') break;
      await new Promise((r) => setTimeout(r, i < 10 ? 150 : 400));
    }
    if (!st || st.state !== 'done') return;
    const buf = await (await fetch(engineUrl + 'ambience/sky.bin?f=' + encodeURIComponent(st.file), { cache: 'no-store' })).arrayBuffer();
    if (my !== amb.loading || !amb.active) return;
    const W = st.stats.w || 1024, H = st.stats.h || 512;
    const hf = new Uint16Array(buf);
    // the mean light of the sky above the horizon (the flakes that fall are lit by it: flakesUniforms)
    {
      let r = 0, g = 0, b = 0, n = 0;
      const half = THREE.DataUtils.fromHalfFloat;
      for (let y = 0; y < H / 2; y += 4) for (let x = 0; x < W; x += 8) {
        const o = (y * W + x) * 4; r += half(hf[o]); g += half(hf[o + 1]); b += half(hf[o + 2]); n++;
      }
      // (rows from the top or the bottom: whichever half is brighter is the sky - the ground is darker)
      let r2 = 0, g2 = 0, b2 = 0, n2 = 0;
      for (let y = Math.ceil(H / 2); y < H; y += 4) for (let x = 0; x < W; x += 8) {
        const o = (y * W + x) * 4; r2 += half(hf[o]); g2 += half(hf[o + 1]); b2 += half(hf[o + 2]); n2++;
      }
      amb.skyMean = (r + g + b) / Math.max(n, 1) >= (r2 + g2 + b2) / Math.max(n2, 1)
        ? [r / Math.max(n, 1), g / Math.max(n, 1), b / Math.max(n, 1)] : [r2 / Math.max(n2, 1), g2 / Math.max(n2, 1), b2 / Math.max(n2, 1)];
    }
    const tex = new THREE.DataTexture(hf, W, H, THREE.RGBAFormat, THREE.HalfFloatType);
    tex.mapping = THREE.EquirectangularReflectionMapping;
    tex.colorSpace = THREE.LinearSRGBColorSpace;
    tex.magFilter = THREE.LinearFilter; tex.minFilter = THREE.LinearFilter; tex.generateMipmaps = false;
    tex.needsUpdate = true;
    const env = pmrem.fromEquirectangular(tex).texture;
    if (amb.tex) amb.tex.dispose();
    if (amb.env) amb.env.dispose();
    amb.tex = tex; amb.env = env;
    // background from the PMREM too (half floats, linear): the equirect → cube conversion of three.js keeps
    // 8 bits and darkens the sky against the haze
    scene.background = env;
    scene.backgroundBlurriness = 0;
    scene.backgroundRotation.copy(AMB_ROT);
    scene.environment = env;
    scene.environmentRotation.copy(AMB_ROT);
    scene.environmentIntensity = 1;
    if (st.stats.horizon) amb.horizon = st.stats.horizon;
    amb.loadedRev = amb.rev;
    if (amb.pending) { ambApply(amb.pending); amb.pending = null; }
    invalidate(600);
  } catch (e) { console.warn('sky', e); }
  finally { if (busyWarn.sky === my) busyWarn.sky = 0; }
}

const camera = new THREE.PerspectiveCamera(35, 1, 0.001, 1000);
camera.position.set(1.6, -2.8, 1.2);
const orbit = new OrbitControls(camera, renderer.domElement);
orbit.target.set(0, 0, 0.3);
orbit.enableDamping = false; // stops exactly when the mouse stops: Cycles can start right away
orbit.screenSpacePanning = true;
orbit.mouseButtons = { LEFT: null, MIDDLE: null, RIGHT: THREE.MOUSE.ROTATE };   // (middle: our own pan, see navigation)
orbit.enableZoom = false; // the wheel walks forward/back (see navigation)
orbit.update();

// Two gizmos, like Twinmotion/D5: "transform" = arrows to move + quarter arcs to rotate (two three.js controls on the
// same pivot), "scale" = handles with cubes. `gizmo` is the control in use (the last one pressed).
const GIZMO_SIZE = 0.85;
const gMove = new TransformControls(camera, renderer.domElement);
const gRot = new TransformControls(camera, renderer.domElement);
const gScale = new TransformControls(camera, renderer.domElement);
gMove.setMode('translate'); gRot.setMode('rotate'); gScale.setMode('scale');
gRot.showE = false; gRot.showXYZE = false;              // only the three arcs (no screen ring, no free rotation)
const gizmos = [gMove, gRot, gScale];
let gizmo = gMove;
let gizmoTool = 'transform';
for (const g of gizmos) { g.setSize(GIZMO_SIZE); scene.add(g.getHelper()); }
styleGizmo();
const gizmoAxis = () => gizmos.some((g) => g.object && g.enabled && g.axis);
const gizmoDragging = () => gizmos.some((g) => g.dragging);
function setGizmosEnabled(on) { for (const g of gizmos) g.enabled = on; }

// ------------------------------------------------------------------ pivot placed by hand (the violet gizmo)
// The app's button turns it on: the gizmo of the model (the top of its hierarchy) turns violet and moving it moves
// only the gizmo; turned off, that place is kept as the model's own pivot (engine: simpler_pivot, in its own space)
// and from then on the gizmo of that model stands there, whatever Centro / Base / Origine says.
let pivotEdit = false;
const PIVOT_VIOLET = new THREE.Color(0xb36bff);
function tintGizmo(on) {
  // (the defaults of three.js: red, green, blue, yellow when grabbed)
  if (on) gMove.setColors(PIVOT_VIOLET, PIVOT_VIOLET, PIVOT_VIOLET, 0xffe066);
  else gMove.setColors(0xff0000, 0x00ff00, 0x0000ff, 0xffff00);
}
function modelRootOf(id) {
  let top = byId.get(id), o = top;
  for (; o && o !== root; o = o.parent) if (o.userData && o.userData.simpler_id && !lights.has(o.userData.simpler_id)) top = o;
  return top && top.userData ? top.userData.simpler_id : '';
}
function setPivotEdit(on) {
  if (on) {
    const rid = primary ? modelRootOf(primary) : '';
    if (!rid) { post({ type: 'pivotEditOff', reason: 'nothing' }); return; }
    pivotEdit = true;
    if (selection.length !== 1 || primary !== rid) { applySelection([rid], rid); post({ type: 'pick', ids: [rid], primary: rid, material: '' }); }
  } else {
    pivotEdit = false;
  }
  tintGizmo(pivotEdit);
  placePivot();
  attachGizmos(selection.length && !partMats ? pivot : null);
  invalidate();
}
function attachGizmos(obj) {
  for (const g of gizmos) g.detach();
  if (!obj) return;
  if (pivotEdit) { gMove.attach(obj); return; }          // placing the pivot: only the arrows (violet)
  if (gizmoTool === 'scale') gScale.attach(obj);
  else { gMove.attach(obj); gRot.attach(obj); }
}
function setGizmoTool(mode) {
  gizmoTool = mode === 'scale' ? 'scale' : 'transform';
  const obj = gMove.object || gRot.object || gScale.object;
  attachGizmos(obj || null);
}

let root = new THREE.Group();
scene.add(root);
const byId = new Map();

// ------------------------------------------------------------------ gizmo styling
// Thicker rings than the three.js defaults: easier to see and to grab.
function styleGizmo() {
  for (const ctl of gizmos) {
    const g = ctl._gizmo;
    if (!g) continue;
    g.traverse((o) => {
      if (o.isMesh && o.geometry && o.geometry.type === 'TorusGeometry' && o.geometry.parameters.tube < 0.01) {
        const p = o.geometry.parameters;
        o.geometry.dispose();
        o.geometry = new THREE.TorusGeometry(p.radius, 0.018, 4, p.tubularSegments, p.arc);
      }
    });
  }
  // In the style of Twinmotion: three axes from the centre (only towards +), a yellow centre to move freely, and
  // three rotation bands joining the tips of the axes (X between +Y and +Z, Y between +Z and +X, Z between +X and +Y),
  // fixed in their quadrant. The scale gizmo: three axes with a cube at the end and a grey centre.
  const R = 0.47;                                 // the bands meet the axes just before the arrow heads (0.5)
  const basis = {                                 // band in the XY plane (from +X to +Y) -> its place
    Z: new THREE.Matrix4(),
    X: new THREE.Matrix4().makeBasis(new THREE.Vector3(0, 1, 0), new THREE.Vector3(0, 0, 1), new THREE.Vector3(1, 0, 0)),
    Y: new THREE.Matrix4().makeBasis(new THREE.Vector3(0, 0, 1), new THREE.Vector3(1, 0, 0), new THREE.Vector3(0, 1, 0)),
  };
  const band = (tube, flat, name) => {
    const geo = new THREE.TorusGeometry(R, tube, 8, 36, Math.PI / 2);
    geo.scale(1, 1, flat);                        // a flat ribbon, not a pipe
    geo.applyMatrix4(basis[name]);
    return geo;
  };
  for (const [part, tube, flat] of [['gizmo', 0.024, 0.4], ['picker', 0.07, 1]]) {
    for (const h of gRot._gizmo[part].rotate.children) {
      if (!basis[h.name]) continue;
      h.geometry.dispose();
      h.geometry = band(tube, flat, h.name);
    }
  }
  // plane sectors of the move gizmo: transparent fill only when hovered (stronger while dragging)
  const mg = gMove._gizmo, mgUpdate = mg.updateMatrixWorld.bind(mg);
  mg.updateMatrixWorld = function (force) {
    mgUpdate(force);
    // the plane sectors stay usable when seen almost edge-on: three.js hides them below 0.2 (about 12°), Simpler only
    // below 0.05 (about 3°), where the thin sector is still there to grab between the two axes
    if (this.mode === 'translate' && this.eye) {
      const q = this.space === 'local' && this.worldQuaternion ? this.worldQuaternion : _gfNoRot;
      for (const grp of [this.gizmo.translate, this.picker.translate]) {
        for (const h of grp.children) {
          const n = h.name === 'XY' ? 2 : h.name === 'YZ' ? 0 : h.name === 'XZ' ? 1 : -1;
          if (n < 0 || h.visible) continue;
          const d = Math.abs(_gfAxis.set(n === 0 ? 1 : 0, n === 1 ? 1 : 0, n === 2 ? 1 : 0).applyQuaternion(q).dot(this.eye));
          // (15/11, Luca: «l'area azzurra è uscita fuori dal bordo… si sposta e basta») the sector came back at size 1
          // instead of the size of the gizmo on screen: near the camera it grew over the arcs and took every press
          if (d >= 0.05) { h.visible = true; h.scale.setScalar(gizmoScreenFactor(this)); h.updateMatrixWorld(true); }
        }
      }
    }
    if (this.mode === 'translate') { gizmoFlipSigns(this); gizmoFlipApply([this.gizmo.translate, this.picker.translate]); }
    for (const h of this.gizmo.translate.children) {
      if (!h.userData.planeFill) continue;
      const on = this.enabled && this.axis === h.name;
      h.material.color.copy(h.material._color);
      h.material.opacity = on ? (this.dragging ? 0.38 : 0.26) : 0;
    }
  };
  // three.js turns the rotation handles towards the eye every frame: here they stay in their quadrant
  const giz = gRot._gizmo, origUpdate = giz.updateMatrixWorld.bind(giz), noRot = new THREE.Quaternion();
  giz.updateMatrixWorld = function (force) {
    origUpdate(force);
    if (this.mode !== 'rotate') return;
    const q = this.space === 'local' && this.worldQuaternion ? this.worldQuaternion : noRot;
    for (const grp of [this.gizmo.rotate, this.picker.rotate]) {
      for (const h of grp.children) {
        if (!basis[h.name]) continue;
        h.quaternion.copy(q);
        h.updateMatrixWorld(true);
      }
    }
    gizmoFlipSigns(this);
    gizmoFlipApply([this.gizmo.rotate, this.picker.rotate]);
  };
  // move: plane handles as quarter sectors (see below); scale: no plane handles; no handles on the negative side
  const axisOf = { X: 'x', Y: 'y', Z: 'z' };
  const planeBasis = {                            // sector in the XY plane (from +X to +Y) -> its plane
    XY: new THREE.Matrix4(),
    YZ: new THREE.Matrix4().makeBasis(new THREE.Vector3(0, 1, 0), new THREE.Vector3(0, 0, 1), new THREE.Vector3(1, 0, 0)),
    XZ: new THREE.Matrix4().makeBasis(new THREE.Vector3(1, 0, 0), new THREE.Vector3(0, 0, 1), new THREE.Vector3(0, -1, 0)),
  };
  const PLANE_COLOR = { XY: 0x3a6dff, YZ: 0xff3352, XZ: 0x37e05a };   // the band that closes it: Z blue, X red, Y green
  for (const [ctl, mode] of [[gMove, 'translate'], [gScale, 'scale']]) {
    for (const part of ['gizmo', 'picker']) {
      const group = ctl._gizmo[part][mode];
      for (const h of [...group.children]) {
        if (['XY', 'YZ', 'XZ'].includes(h.name)) {
          if (mode !== 'translate') { group.remove(h); continue; }
          // move on a plane: the quarter enclosed by two axes and their rotation band (Twinmotion). Invisible until
          // the mouse is over it, then filled with the colour of the band that closes it.
          const geo = new THREE.RingGeometry(0.1, R - 0.075, 24, 1, 0, Math.PI / 2);
          geo.applyMatrix4(planeBasis[h.name]);
          h.geometry.dispose();
          h.geometry = geo;
          h.position.set(0, 0, 0);
          if (part === 'picker') { h.material = h.material.clone(); h.material.side = THREE.DoubleSide; }   // (grabbed from both sides)
          if (part === 'gizmo') {
            h.material = new THREE.MeshBasicMaterial({ color: PLANE_COLOR[h.name], transparent: true, opacity: 0, side: THREE.DoubleSide,
                                                       depthTest: false, depthWrite: false, toneMapped: false, fog: false });
            h.material._color = h.material.color.clone();
            h.userData.planeFill = true;
          }
          continue;
        }
        if (axisOf[h.name]) {
          h.geometry.computeBoundingBox();
          const c = h.geometry.boundingBox.getCenter(new THREE.Vector3());
          if (c[axisOf[h.name]] < -0.05) group.remove(h);
        }
        if (h.name === 'XYZ' && part === 'gizmo' && h.material) {
          h.material = h.material.clone();
          h.material.color.set(mode === 'translate' ? 0xd8d23a : 0x8a9099);   // yellow centre: move freely · grey: scale all
          h.material.opacity = 1;
          h.material.transparent = false;
          h.material._color = h.material.color.clone();
          h.material._opacity = 1;
        }
        // move: slimmer axis pickers (three.js uses wide cones that would cover the plane sectors)
        if (part === 'picker' && mode === 'translate' && axisOf[h.name] && h.parent === group) {
          const geo = new THREE.CylinderGeometry(0.075, 0.075, 0.6, 6);
          if (h.name === 'X') { geo.rotateZ(-Math.PI / 2); geo.translate(0.3, 0, 0); }
          if (h.name === 'Y') geo.translate(0, 0.3, 0);
          if (h.name === 'Z') { geo.rotateX(Math.PI / 2); geo.translate(0, 0, 0.3); }
          h.geometry.dispose();
          h.geometry = geo;
          continue;
        }
        // axis lines a little thicker (three.js draws them as thin as a hair)
        if (part === 'gizmo' && axisOf[h.name] && h.geometry.type === 'CylinderGeometry' && h.geometry.parameters.radiusTop > 0.005 && h.geometry.parameters.radiusTop < 0.01) {
          const p = h.geometry.parameters;
          h.geometry.computeBoundingBox();
          const box = h.geometry.boundingBox;
          const geo = new THREE.CylinderGeometry(0.014, 0.014, p.height, 8);
          // same place and direction as the original line (along its axis, from 0 to its length)
          const c = box.getCenter(new THREE.Vector3());
          if (h.name === 'X') geo.rotateZ(-Math.PI / 2);
          if (h.name === 'Z') geo.rotateX(Math.PI / 2);
          geo.translate(c.x, c.y, c.z);
          h.geometry.dispose();
          h.geometry = geo;
        }
      }
    }
  }
}

// The axes of the move/rotate gizmo point to the side of the camera: an arrow going away from the eye ended behind
// the other two and was hard to grab. Each axis (with its bands and plane sectors) is mirrored when its + side
// looks away; a small dead zone keeps it from flickering, and it never changes during a drag.
const gizmoSign = new THREE.Vector3(1, 1, 1);
const _gfAxis = new THREE.Vector3(), _gfNoRot = new THREE.Quaternion();
// the size three.js gives to every handle of a gizmo (the same on screen at any distance)
function gizmoScreenFactor(gz) {
  const cam = gz.camera;
  const f = cam.isOrthographicCamera ? (cam.top - cam.bottom) / cam.zoom
    : gz.worldPosition.distanceTo(gz.cameraPosition) * Math.min(1.9 * Math.tan(Math.PI * cam.fov / 360) / cam.zoom, 7);
  return f * gz.size / 4;
}
function gizmoFlipSigns(gz) {
  if (gz.dragging || !gz.eye) return;
  const q = gz.space === 'local' && gz.worldQuaternion ? gz.worldQuaternion : _gfNoRot;
  for (let i = 0; i < 3; i++) {
    const d = _gfAxis.set(i === 0 ? 1 : 0, i === 1 ? 1 : 0, i === 2 ? 1 : 0).applyQuaternion(q).dot(gz.eye);
    if (d < -0.08) gizmoSign.setComponent(i, -1);
    else if (d > 0.08) gizmoSign.setComponent(i, 1);
  }
}
function gizmoFlipApply(groups) {
  if (gizmoSign.x > 0 && gizmoSign.y > 0 && gizmoSign.z > 0) return;
  for (const grp of groups) {
    for (const h of grp.children) {
      if (Math.abs(h.scale.x) < 1e-8) continue;           // (hidden by three.js: axis looking at the camera)
      h.scale.multiply(gizmoSign);
      h.updateMatrixWorld(true);
    }
  }
}

// Arrows and arcs may overlap on screen: the one nearer to the mouse takes the press, the other waits.
const _gzRay = new THREE.Raycaster();
function _gzHits(ctl, e, part = 'picker') {
  if (!ctl.object || !ctl.enabled) return [];
  const r = renderer.domElement.getBoundingClientRect();
  _gzRay.setFromCamera(new THREE.Vector2(((e.clientX - r.left) / r.width) * 2 - 1, -((e.clientY - r.top) / r.height) * 2 + 1), camera);
  return _gzRay.intersectObject(ctl._gizmo[part][ctl.mode], true).filter((h) => h.object.visible);
}
function pickerDistance(ctl, e) { const h = _gzHits(ctl, e); return h.length ? h[0].distance : Infinity; }
let _gzWaiting = null;
// who takes the press when both controls are under the mouse: a plane sector of the move gizmo wins, unless the
// pointer is right on the drawn ribbon of a rotation band (the band pickers are wider than the ribbons)
function _gzWinner(e) {
  const hm = _gzHits(gMove, e), hr = _gzHits(gRot, e);
  if (!hm.length || !hr.length) return null;
  const name = hm[0].object.name;
  const plane = ['XY', 'YZ', 'XZ'].includes(name);
  if (plane) {
    // (1.75.0) a plane seen almost edge-on (under ~12°): its sector and the rotation band of the same plane fall on the
    // same thin line - the band took every press and the sector could not be grabbed (Luca: a ship seen from a few
    // degrees above the sea). There the sector wins: the move on the plane is what such a view is for
    const n = name === 'XY' ? 2 : name === 'YZ' ? 0 : 1;
    const q = gMove.space === 'local' && gMove.worldQuaternion ? gMove.worldQuaternion : _gfNoRot;
    const d = gMove.eye ? Math.abs(_gfAxis.set(n === 0 ? 1 : 0, n === 1 ? 1 : 0, n === 2 ? 1 : 0).applyQuaternion(q).dot(gMove.eye)) : 1;
    if (d < 0.2) return gMove;
    return _gzHits(gRot, e, 'gizmo').length ? gRot : gMove;
  }
  return hm[0].distance <= hr[0].distance ? gMove : gRot;
}
renderer.domElement.addEventListener('pointerdown', (e) => {
  if (e.button !== 0 || gizmoTool !== 'transform') return;
  const w = _gzWinner(e);
  if (w) { _gzWaiting = w === gMove ? gRot : gMove; _gzWaiting.enabled = false; }
}, true);
// the same rule for the highlight while hovering: only the control that would take the press lights up
renderer.domElement.addEventListener('pointermove', (e) => {
  if (gizmoTool !== 'transform' || gizmoDragging() || e.buttons) return;
  const w = _gzWinner(e);
  const loser = w === gMove ? gRot : w === gRot ? gMove : null;
  if (loser && loser.axis) loser.axis = null;
}, false);
window.addEventListener('pointerup', () => { if (_gzWaiting) { _gzWaiting.enabled = !locked && !selectMode; _gzWaiting = null; } });

// ------------------------------------------------------------------ resize
function resize() {
  const w = container.clientWidth, h = container.clientHeight;
  if (!w || !h) return;
  renderer.setSize(w, h, false);
  camera.aspect = w / h;
  camera.updateProjectionMatrix();
  post({ type: 'size', width: Math.round(w * devicePixelRatio), height: Math.round(h * devicePixelRatio) });
  cameraChanged();
}
new ResizeObserver(resize).observe(container);

// ------------------------------------------------------------------ loading the scene
const loader = new GLTFLoader();
// small progress pill at the bottom (next to the mode badge): the view stays usable while the engine works
const taskEl = document.getElementById('task');
const taskText = document.getElementById('taskText');
const taskFill = document.getElementById('taskFill');
const taskPct = document.getElementById('taskPct');
const taskDetail = document.getElementById('taskDetail');
let _busyPosted = false;
// (1.75.43) green notice for a few seconds (e.g. «Video AI creato e salvato in Elaborazioni AI»)
let _toastTimer = 0;
function showToast(text, seconds = 3) {
  const el = document.getElementById('doneToast');
  if (!el || !text) return;
  el.textContent = text;
  el.classList.add('on');
  requestAnimationFrame(() => el.classList.add('show'));
  clearTimeout(_toastTimer);
  _toastTimer = setTimeout(() => { el.classList.remove('show'); setTimeout(() => el.classList.remove('on'), 400); }, seconds * 1000);
}
function setBusy(text, fraction = null, detail = '') {
  taskEl.classList.toggle('on', !!text);
  // the app shows the busy arrow while the view works too (models of a distribution arriving, a part loading...)
  if (_busyPosted !== !!text) { _busyPosted = !!text; post({ type: 'viewBusy', on: _busyPosted }); }
  if (!text) return;
  taskText.textContent = text;
  taskDetail.textContent = detail || '';
  const known = fraction !== null && fraction !== undefined;
  taskEl.classList.toggle('indeterminate', !known);
  taskFill.style.width = known ? Math.round(fraction * 100) + '%' : '';
  taskPct.textContent = known ? Math.round(fraction * 100) + '%' : '';
}
// «Occupato · attendi» (red, blinking, over the view): shown while Simpler works on something you must wait for - the
// engine busy with a command or a computation of its own (GET busy, answered at once even then), the app waiting
// for the engine, the panels locked, or this view preparing itself. Only after 0.4 s (quick commands do not
// flicker), and it stays until all of them are over. The busy cursor (hourglass) goes with it, here and in the app.
const busyWarn = { engine: null, since: 0, appWorking: false, appText: '', shown: false, labels: new Set() };
const shaderPrep = { busy: false, again: '' };     // (prepareShaders: the shaders made in the background)
// The view's own requests to the engine still waiting (models of a distribution, parts, pictures of decals...): any
// of them waiting more than 0.4 s counts as «busy» too. (fetch wrapped once: the questions that only follow the
// state - busy, frames of the path tracing, rain info, the sky - do not count.)
const viewWaits = new Map();
{
  const plain = window.fetch.bind(window);
  let n = 0;
  window.fetch = (input, init) => {
    const url = typeof input === 'string' ? input : (input && input.url) || '';
    let eu = '';
    try { eu = engineUrl; } catch { /* (not declared yet while the page starts) */ }
    if (!eu || !url.startsWith(eu) || /\/api\/(busy|frame|rain\/info|ambience\/(sky|bake))/.test(url)) return plain(input, init);
    const id = ++n;
    viewWaits.set(id, performance.now());
    return plain(input, init).finally(() => viewWaits.delete(id));
  };
}
// The engine is asked on its other name (localhost instead of 127.0.0.1): the browser opens at most 6 connections
// per address, and while the view loads they are all taken by models and parts - the question about the busy state
// waited behind them and the sign went off in the middle of a loading. The sign itself is updated every 0.2 s on
// its own clock, whatever the answers do.
async function busyPoll() {
  setInterval(busyTick, 200);
  for (;;) {
    if (engineUrl) {
      const ctl = new AbortController();
      const timer = setTimeout(() => ctl.abort(), 1500);
      try {
        const url = engineUrl.replace('//127.0.0.1:', '//localhost:') + 'busy';
        const st = await (await fetch(url, { cache: 'no-store', signal: ctl.signal })).json();
        busyWarn.engine = st && st.busy ? st : null;
        busyWarn.engineAt = performance.now();
      } catch { /* no answer in time: the last state stays until the next one */ }
      clearTimeout(timer);
    }
    await new Promise((r) => setTimeout(r, 250));
  }
}
function busyTick() {
  const now = performance.now();
  const viewTask = taskEl.classList.contains('on') && !working.owner;
  let viewWait = false;
  for (const t0 of viewWaits.values()) if (now - t0 >= 400) { viewWait = true; break; }
  const engine = busyWarn.engine && now - (busyWarn.engineAt || 0) < 4000 ? busyWarn.engine : null;
  const sky = !!busyWarn.sky && amb.active;
  const hold = !!busyWarn.hold, prep = shaderPrep.busy;     // (prep: shaders made in the background - after 0.4 s)
  const any = !!engine || busyWarn.appWorking || (locked && !lockedByWindow) || viewTask || viewWait || sky || hold || prep;
  if (any) { if (!busyWarn.since) busyWarn.since = now; busyWarn.lastStart = busyWarn.since; busyWarn.lastAny = now; }
  // on after 0.4 s of work; off only after 0.7 s without any (a pause between two models does not make it blink off)
  const show = busyWarn.shown ? now - (busyWarn.lastAny || 0) < 700 : any && (hold || now - busyWarn.since >= 400);
  if (!any && !show) busyWarn.since = 0;
  if (show && any) {
    const base = engine ? engine.what : busyWarn.appWorking ? busyWarn.appText : viewTask ? taskText.textContent
      : viewWait ? tr('Preparazione della vista 3D') : sky ? tr('Preparazione del cielo') : hold ? busyWarn.holdWhat
      : prep ? (shaderPrep.why || tr('Preparazione della vista 3D')) : '';
    if (base) busyWarn.labels.add(base.replace(/…$/, ''));
    const what = engine ? engine.what + (engine.secs >= 1 ? ' · ' + Math.round(engine.secs) + ' s' : '') : base;
    document.getElementById('busyTitle').textContent = tr('Occupato · attendi');
    document.getElementById('busyWhat').textContent = what || '';
  }
  if (show !== busyWarn.shown) {
    busyWarn.shown = show;
    document.getElementById('busyWarn').classList.toggle('on', show);
    document.body.classList.toggle('ebusy', show);
    // (when it goes off: how long it lasted and what it was, for the log of the waits in app.log)
    post({ type: 'engineBusy', on: show, secs: show ? 0 : (busyWarn.lastAny - busyWarn.lastStart) / 1000, what: show ? '' : [...busyWarn.labels].join(' · ') });
    if (!show) { busyWarn.labels.clear(); busyWarn.since = 0; }
  }
}
let lastSync = null;
const working = { owner: false };
// the models of a distribution arrive one by one from the engine (paint/proto: a few seconds each for big models):
// the pill says so, otherwise the view shows only the green cones and seems stuck
const protoBusy = { total: 0, done: 0, owner: false };
function protoProgress(name) {
  if (protoBusy.done >= protoBusy.total) {
    if (protoBusy.owner) setBusy('');
    protoBusy.total = protoBusy.done = 0; protoBusy.owner = false;
    return;
  }
  if (!protoBusy.owner && taskEl.classList.contains('on')) return;     // another task is shown: it has the pill
  protoBusy.owner = true;
  setBusy(tr('Preparazione dei modelli per la vista…'), protoBusy.done / protoBusy.total,
          tr('{0} di {1}', protoBusy.done + 1, protoBusy.total) + (name ? ' · ' + name : ''));
}

// objects deleted in the app: kept (out of the scene) so that undo shows them again without a new export
const graveyard = new Map();
let locked = false;   // a long operation is running in the app: no picking, no gizmo
let lockedByWindow = false;   // (only a library window open: locked, but nothing is working - no «Occupato»)

function clearScene() {
  for (const id of [...lights.keys()]) removeLight(id);
  scatterReset();
  scene.remove(root);
  disposeTree(root, true);
  for (const n of graveyard.values()) disposeTree(n, true);
  graveyard.clear();
  root = new THREE.Group();
  scene.add(root);
  byId.clear();
}

async function loadScene(url, big) {
  const t0 = performance.now();
  protoFails.clear();                 // (a new preparation of the view: the models that failed are tried again)
  let gltf;
  // very big scenes: free the old one first, two copies in memory can crash the view
  if (big) { clearScene(); selectionHelpers.forEach((h) => scene.remove(h)); selectionHelpers = []; attachGizmos(null); }
  try {
    gltf = await loader.loadAsync(url, (ev) => {
      if (ev.lengthComputable && ev.total > 0) setBusy(tr('Caricamento della vista 3D…'), ev.loaded / ev.total, tr('{0} di {1} MB', (ev.loaded / 1048576).toFixed(1), (ev.total / 1048576).toFixed(1)));
    });
    setBusy(tr('Preparazione della vista 3D…'), null, tr('materiali e texture'));
    await new Promise((res) => setTimeout(res, 0));
  } catch (err) {
    setBusy('');
    post({ type: 'error', message: tr('Anteprima non caricata: ') + err });
    return;
  }
  for (const id of [...lights.keys()]) removeLight(id);
  scene.remove(root);
  disposeTree(root, true);
  for (const n of graveyard.values()) disposeTree(n, true);
  graveyard.clear();
  lights.clear();
  knownMaterials.clear();
  exportMaterials.clear();
  rtMaterials.clear();
  root = gltf.scene;
  indexMaterials(root);
  byId.clear();
  let meshes = 0;
  root.traverse((o) => {
    const id = o.userData && o.userData.simpler_id;
    if (id) byId.set(id, o);
    if (o.isMesh) {
      meshes++;
      o.castShadow = o.receiveShadow = !o.userData.volNoShadow;    // (a volume: no shadow of its surface)
    }
    if (o.isInstancedMesh) o.userData.gltfInstances = true;    // copies merged by the export: see adoptInstances
    // glTF lights (if any) are replaced by ours, built from the engine data
    // (14/11, measured on Luca's card: a shader costs 0,1 s with 2 lights, 0,2 s with 8, 0,6 s with 24) the light of the file stayed in
    // the scene at power 0 and three.js counted it in EVERY shader: each light of the project was counted twice, the number of
    // lights of the shaders changed with every project and with every light added (all the shaders made again, never found in the
    // cache of the card). Out of every layer: three.js no longer sees it; its children (our light, its icon) are not touched
    if (o.isLight) { o.intensity = 0; o.castShadow = false; o.layers.disableAll(); }
  });
  scene.add(root);
  if (lastSync) applySync(lastSync);
  fitShadow();
  applySelection(selection, primary);
  setBusy('');
  prepareShaders(tr('Preparazione della vista 3D'));   // build all shaders now (in the background), not at the first frame
  post({ type: 'loaded', objects: byId.size, meshes, ms: Math.round(performance.now() - t0) });
  clearTimeout(loadScene.diag); loadScene.diag = setTimeout(() => viewDiag('20 s after loading'), 20000);
}

// (1.76.50, audit) the materials of a view that goes away are freed some seconds later, not at once: three.js
// throws a material's shader away with its last material, and the view loaded again a moment later (open, a new
// preparation) made the same shaders again - the terrain's alone 5-6 s each time in Luca's logs. Kept a while, the
// new materials find their shaders ready. Geometries and textures (the memory) are freed at once.
const _matGrave = new Set();
let _matGraveTimer = 0;
function matGraveFlush() {
  _matGraveTimer = 0;
  if (shaderPrep.busy) { _matGraveTimer = setTimeout(matGraveFlush, 5000); return; }
  // (a material still drawn - shared with the new view - stays: freed now it would be made again in a frame)
  scene.traverse((o) => { if (o.material) for (const m of (Array.isArray(o.material) ? o.material : [o.material])) _matGrave.delete(m); });
  for (const m of _matGrave) m.dispose();
  _matGrave.clear();
}
function disposeTree(obj, later) {
  obj.traverse((o) => {
    if (o.geometry) o.geometry.dispose();
    const mats = o.material ? (Array.isArray(o.material) ? o.material : [o.material]) : [];
    for (const m of mats) {
      for (const k in m) if (m[k] && m[k].isTexture) m[k].dispose();
      if (later) _matGrave.add(m); else m.dispose();
    }
  });
  if (later && _matGrave.size) { clearTimeout(_matGraveTimer); _matGraveTimer = setTimeout(matGraveFlush, 30000); }
}

// World-space bounding box of the real geometry under obj (helpers, lights and hidden parts excluded).
const _tmpBox = new THREE.Box3();
function boxOf(obj, skipFloor) {
  const box = new THREE.Box3();
  obj.updateWorldMatrix(true, true);
  obj.traverse((o) => {
    const set = o.userData.simpler_id && scatter.sets.get(o.userData.simpler_id);
    if (set && isVisible(o)) box.union(setBox(set));
    if (o.userData.paintPiece && !scatter.shown.has(o) && isVisible(o)) {
      // a painted piece: the box of its model
      const P = protoOf(o);
      if (P && P.state === 'ready') for (const part of P.parts) {
        if (!part.geom.boundingBox) part.geom.computeBoundingBox();
        box.union(_tmpBox.copy(part.geom.boundingBox).applyMatrix4(_sm4.multiplyMatrices(o.matrixWorld, part.rel)));
      }
      return;
    }
    if (!o.isMesh || o.userData.helper || !isVisible(o)) return;
    if (skipFloor && isFloor(o)) return;
    if (o.isInstancedMesh) {
      if (!o.boundingBox) o.computeBoundingBox();
      _tmpBox.copy(o.boundingBox);
    } else {
      if (!o.geometry.boundingBox) o.geometry.computeBoundingBox();
      _tmpBox.copy(o.geometry.boundingBox);
    }
    box.union(_tmpBox.applyMatrix4(o.matrixWorld));
  });
  return box;
}

function isFloor(o) {
  // only the floor itself: objects placed inside the floor group in the tree are not floor
  for (; o; o = o.parent) {
    if (o.userData && o.userData.simpler_id) return /^(pavimento|floor|suolo|ground)/i.test(o.name || '');
  }
  return false;
}

function isVisible(o) {
  for (; o; o = o.parent) if (!o.visible) return false;
  return true;
}

function sceneRadius() {
  const box = boxOf(root, true);
  return box.isEmpty() ? 1 : Math.max(box.getSize(new THREE.Vector3()).length() / 2, 0.01);
}

let _shadowBox = null;          // box of the scene for the shadows (kept: computing it walks the whole scene)
const _farC = new THREE.Vector3(), _farS = new THREE.Vector3();
function fitShadow() {
  const box = boxOf(root, true);
  _shadowBox = box.isEmpty() ? null : box.clone();
  if (box.isEmpty()) return;
  const r = Math.max(box.getSize(new THREE.Vector3()).length() / 2, 0.05);
  refitShadows();
  updateLightHelpers(Math.max(sceneRadius(), 0.01));
}
// Where the shadow maps are spent. A map covering the whole scene is too coarse for small things (rings, cups,
// a chair on a large terrain: one texel is bigger than the object and its shadow disappears), so when the view
// looks at a part of the scene the maps cover that part (around the point looked at, a bit wider than the view).
function shadowRegion() {
  const box = _shadowBox;
  if (!box) return null;
  const c = box.getCenter(new THREE.Vector3());
  const r = Math.max(box.getSize(new THREE.Vector3()).length() / 2, 0.05);
  const dist = camera.position.distanceTo(orbit.target);
  const half = Math.tan(THREE.MathUtils.degToRad(camera.fov) / 2) * dist * Math.max(1, camera.aspect);
  const rv = Math.max(half * 2.2, 0.01);
  if (rv >= r * 0.8) return { c, r, R: r };
  return { c: box.clampPoint(orbit.target, new THREE.Vector3()), r: rv, R: r };
}
let _shadowRefit = 0;
function refitShadows() {
  const g = shadowRegion();
  if (!g) return;
  const { c, r, R } = g;
  key.target.position.copy(c);
  key.position.copy(c).add(new THREE.Vector3(-0.45, -0.65, 0.9).normalize().multiplyScalar(R * 6));
  key.target.updateMatrixWorld();
  const s = key.shadow.camera;
  s.left = s.bottom = -r * 1.6; s.right = s.top = r * 1.6;
  s.near = Math.max(0.001, R * 6 - R * 2.5); s.far = R * 6 + R * 2.5;
  s.updateProjectionMatrix();
  key.shadow.normalBias = (3.2 * r / key.shadow.mapSize.x) * 1.2;
  for (const L of lights.values()) fitLightShadow(L, R, g);
  invalidate();
}
function refitShadowsSoon() { clearTimeout(_shadowRefit); _shadowRefit = setTimeout(refitShadows, 120); }

// ------------------------------------------------------------------ lights (built from the engine data)
const lights = new Map(); // id -> { node, kind, data, light, helper, sprite }
const MAX_SHADOW_LIGHTS = 4;

function kelvinToRGB(k) {
  // Tanner Helland's approximation, sRGB 0-1
  const t = Math.min(40000, Math.max(1000, k)) / 100;
  let r, g, b;
  if (t <= 66) { r = 255; g = 99.4708025861 * Math.log(t) - 161.1195681661; }
  else { r = 329.698727446 * Math.pow(t - 60, -0.1332047592); g = 288.1221695283 * Math.pow(t - 60, -0.0755148492); }
  if (t >= 66) b = 255; else if (t <= 19) b = 0; else b = 138.5177312231 * Math.log(t - 10) - 305.0447927307;
  const c = (v) => Math.min(255, Math.max(0, v)) / 255;
  return new THREE.Color().setRGB(c(r), c(g), c(b), THREE.SRGBColorSpace);
}

let _iconTexture = null;
function iconTexture() {
  if (_iconTexture) return _iconTexture;
  const s = 64, cv = document.createElement('canvas');
  cv.width = cv.height = s;
  const g = cv.getContext('2d');
  g.translate(s / 2, s / 2);
  g.strokeStyle = '#f2b54b'; g.fillStyle = 'rgba(10,18,34,0.85)'; g.lineWidth = 4;
  g.beginPath(); g.arc(0, 0, 14, 0, Math.PI * 2); g.fill(); g.stroke();
  g.fillStyle = '#f2b54b'; g.beginPath(); g.arc(0, 0, 6, 0, Math.PI * 2); g.fill();
  g.lineWidth = 3.5; g.lineCap = 'round';
  for (let i = 0; i < 8; i++) {
    const a = i * Math.PI / 4;
    g.beginPath(); g.moveTo(Math.cos(a) * 19, Math.sin(a) * 19); g.lineTo(Math.cos(a) * 27, Math.sin(a) * 27); g.stroke();
  }
  _iconTexture = new THREE.CanvasTexture(cv);
  _iconTexture.colorSpace = THREE.SRGBColorSpace;
  return _iconTexture;
}

function lineMaterial(opacity = 0.9) {
  return new THREE.LineBasicMaterial({ color: WARM, transparent: true, opacity, depthTest: false });
}
function noRaycast(o) { o.traverse((c) => { c.raycast = () => {}; c.userData.helper = true; }); return o; }

function circlePoints(radius, z, n = 48) {
  const pts = [];
  for (let i = 0; i < n; i++) {
    const a0 = (i / n) * Math.PI * 2, a1 = ((i + 1) / n) * Math.PI * 2;
    pts.push(Math.cos(a0) * radius, Math.sin(a0) * radius, z, Math.cos(a1) * radius, Math.sin(a1) * radius, z);
  }
  return pts;
}
function segments(points, opacity) {
  const geo = new THREE.BufferGeometry();
  geo.setAttribute('position', new THREE.Float32BufferAttribute(points, 3));
  return new THREE.LineSegments(geo, lineMaterial(opacity));
}

function buildHelper(L, r) {
  if (L.helper) { L.node.remove(L.helper); L.helper.traverse((o) => o.geometry && o.geometry.dispose()); }
  const h = new THREE.Group();
  const d = L.data;
  // helpers live under the light node: compensate its scale so they keep their real size
  const ws = new THREE.Vector3(); L.node.getWorldScale(ws);
  const len = Math.max(r * 0.9, 0.02);
  if (L.kind === 'spot') {
    const half = THREE.MathUtils.degToRad((d.coneAngle || 45) / 2);
    const R = Math.tan(Math.min(half, 1.45)) * len;
    const pts = [];
    for (let i = 0; i < 4; i++) { const a = i * Math.PI / 2; pts.push(0, 0, 0, Math.cos(a) * R, Math.sin(a) * R, -len); }
    h.add(segments(pts, 0.85));
    h.add(segments(circlePoints(R, -len), 0.85));
    const inner = R * (1 - Math.min(1, d.blend || 0));
    if (inner > 0.001 && (d.blend || 0) > 0.01) h.add(segments(circlePoints(inner, -len), 0.35));
  } else if (L.kind === 'point') {
    const rad = Math.max((d.radius || 0) * CM, r * 0.03);
    h.add(segments(circlePoints(rad, 0), 0.8));
    const ring = segments(circlePoints(rad, 0), 0.8); ring.rotation.x = Math.PI / 2; h.add(ring);
    const ring2 = segments(circlePoints(rad, 0), 0.8); ring2.rotation.y = Math.PI / 2; h.add(ring2);
  } else if (L.kind === 'area') {
    const w = (d.width || 50) * CM / 2, hh = (d.height || 50) * CM / 2;
    const disk = d.shape === 'DISK' || d.shape === 'ELLIPSE';
    if (disk) { const c = segments(circlePoints(1, 0), 0.9); c.scale.set(w, hh, 1); h.add(c); }
    else h.add(segments([-w, -hh, 0, w, -hh, 0, w, -hh, 0, w, hh, 0, w, hh, 0, -w, hh, 0, -w, hh, 0, -w, -hh, 0], 0.9));
    h.add(segments([0, 0, 0, 0, 0, -len * 0.5], 0.6));
  } else if (L.kind === 'sun') {
    h.add(segments([0, 0, 0, 0, 0, -len, 0, 0, -len, len * 0.08, 0, -len * 0.85, 0, 0, -len, -len * 0.08, 0, -len * 0.85], 0.9));
  }
  h.scale.set(1 / (ws.x || 1), 1 / (ws.y || 1), 1 / (ws.z || 1));
  noRaycast(h);
  h.traverse((o) => { o.renderOrder = 998; });
  L.helper = h;
  h.visible = !d.ambience;
  L.node.add(h);
}

// The emitting surface of an area light "visible to camera" (LED strips): Cycles shows it in the image, so does
// the view. One-sided like in Cycles (it faces -Z, where the light goes); not pickable through the scene raycast.
function buildGlow(L, color) {
  if (L.glow) { L.node.remove(L.glow); L.glow.geometry.dispose(); L.glow.material.dispose(); L.glow = null; }
  const d = L.data;
  if (L.kind !== 'area' || !d.visibleCamera || !(d.power > 0)) return;
  const w = (d.width || 50) * CM, h = (d.height || 50) * CM;
  const disk = d.shape === 'DISK' || d.shape === 'ELLIPSE';
  const geo = disk ? new THREE.CircleGeometry(0.5, 48) : new THREE.PlaneGeometry(1, 1);
  const c = color.clone();
  const m = Math.max(c.r, c.g, c.b) || 1;
  c.multiplyScalar(1 / m);                      // full brightness: the surface of a lit LED is burnt white-ish
  const mat = new THREE.MeshBasicMaterial({ color: c, side: THREE.FrontSide, toneMapped: false });
  // (Luca: «sposto l'auto di un metro e parte il box rosso»: a car with area lights seen by the camera (its tail lamps)
  // rebuilds this surface at every move of the car, a new material every time = «a mesh with no shader» = the whole
  // view prepared again (1 s and the red box). A plain unlit colour: its shader is made in a moment inside the frame,
  // like the lines and the icons of the lights)
  mat.userData.smartCheap = true;
  const glow = new THREE.Mesh(geo, mat);
  const ws = new THREE.Vector3(); L.node.getWorldScale(ws);
  glow.scale.set(w / (ws.x || 1), h / (ws.y || 1), 1);
  glow.rotation.y = Math.PI;                    // plane normal +Z -> -Z
  glow.userData.helper = true; glow.userData.glow = true;
  glow.raycast = () => {};
  L.glow = glow;
  L.node.add(glow);
}

function makeLight(kind) {
  let light;
  if (kind === 'point') light = new THREE.PointLight(0xffffff, 1, 0, 2);
  else if (kind === 'sun') light = new THREE.DirectionalLight(0xffffff, 1);
  else light = new THREE.SpotLight(0xffffff, 1, 0, Math.PI / 4, 0.25, 2);
  // three.js puts spot and directional lights one unit "up" from their node (Object3D.DEFAULT_UP, here +Z, i.e.
  // behind a light pointing along -Z): the light must sit exactly on the node, or a spot / area light is 1 m behind
  // the real one (dimmer, and its shadow camera misses the objects close to it: no shadows on small scenes)
  light.position.set(0, 0, 0);
  if (light.target) { light.target.position.set(0, 0, -1); light.add(light.target); }
  if (kind === 'sun') light.position.set(0, 0, 0);
  light.shadow.bias = -0.0002;
  light.shadow.normalBias = 0.002;
  light.shadow.mapSize.set(1024, 1024);
  return light;
}

// colour, intensity, cone and reach of a three.js light from the light of the engine (core.light_json): the lights
// of the scene and the lamps inside the models of distributions (distLamps) the same way
function lightParams(light, kind, data) {
  const color = new THREE.Color().fromArray(data.color || [1, 1, 1]);
  if (data.kelvin) color.multiply(kelvinToRGB(data.kelvin));
  light.color.copy(color);
  const W = data.lit === false ? 0 : (data.power || 0);     // (switched off, or daytime for a dusk-to-dawn lamp)
  // Blender units -> three.js photometric units, same 1/π convention for diffuse in both renderers
  if (kind === 'sun') light.intensity = W;                       // W/m²
  else if (kind === 'area') light.intensity = W / Math.PI;       // on-axis intensity of a lambertian emitter
  else light.intensity = W / (4 * Math.PI);                      // point & spot: W -> W/sr
  if (kind === 'spot') {
    light.angle = Math.min(Math.PI / 2 - 0.01, THREE.MathUtils.degToRad((data.coneAngle || 45) / 2));
    light.penumbra = Math.min(1, Math.max(0, data.blend || 0));
  } else if (kind === 'area') {
    light.angle = THREE.MathUtils.degToRad(80);
    light.penumbra = 1;
  }
  if (kind === 'point' || kind === 'spot') light.shadow.radius = 1 + Math.min(12, (data.radius || 0) * 0.4);
  // reach (as in the path tracing: the light fades to nothing at that distance; three.js uses the same window)
  if (light.isPointLight || light.isSpotLight) light.distance = data.range > 0 ? data.range : 0;
  return color;
}

function updateLight(id, kind, data) {
  const node = byId.get(id);
  if (!node || !data) return;
  let L = lights.get(id);
  if (L && (L.kind !== kind || L.node !== node)) { removeLight(id); L = null; }
  if (!L) {
    L = { node, kind, data, light: makeLight(kind) };
    node.add(L.light);
    const sprite = new THREE.Sprite(new THREE.SpriteMaterial({ map: iconTexture(), depthTest: false, sizeAttenuation: false }));
    sprite.scale.set(0.045, 0.045, 1);
    sprite.renderOrder = 999;
    sprite.userData.pickId = id;
    sprite.userData.helper = true;
    L.sprite = sprite;
    node.add(sprite);
    lights.set(id, L);
  }
  L.data = data;
  // the sun and the moon of the Ambiente are moved from its panel (time, north): no icon, no lines, not clickable
  L.sprite.visible = !data.ambience;
  L.sprite.raycast = data.ambience ? () => {} : THREE.Sprite.prototype.raycast;
  const light = L.light;
  const color = lightParams(light, kind, data);
  // picture projected by a spot (three.js draws it through the shadow map of the light: it needs its shadows)
  if (light.isSpotLight) {
    const want = data.goboImage || '';
    if ((L.goboName || '') !== want) {
      L.goboName = want;
      if (light.map) { light.map.dispose(); light.map = null; }
      if (want && engineUrl) {
        new THREE.TextureLoader().load(engineUrl + 'texture?image=' + encodeURIComponent(want) + '&px=512', (t) => {
          if (L.goboName !== want) { t.dispose(); return; }
          t.colorSpace = THREE.SRGBColorSpace;
          light.map = t;
          invalidate(400);
        });
      }
    }
  }
  buildHelper(L, Math.max(sceneRadius(), 0.01));
  buildGlow(L, color);
  fitLightShadow(L, Math.max(sceneRadius(), 0.05));
  _budget.dirty = true; lightBudget();
  refreshShadowBudget();
  setFallback();
  if (!amb.active) scene.environmentIntensity = lights.size ? 0.15 : 0.65;
}

// the lights of the scene that the real-time shaders know: per kind, the strongest and nearest ones (the lamps of the distributions
// have their own places, see distLampsUpdate). The others are switched off IN THE VIEW only (icon, helper, path tracing unchanged).
// (14/11 sera, MEASURED on Luca's RTX 4080 with a test page: one shader costs 0,6 s with the 24 lights of the first budget, 0,2 s with 8,
// 0,1 s with 2 - the time is the lights. Luca: «nella vista realtime non me ne frega delle luci, sono disposto a rinunciare a qualche
// qualità».) The real-time view now knows 12 lights: 4 suns (2 with shadow: the sun and the stand-in), 4 points (no shadow), 4 spots
// (1 with shadow). The other lights of the scene stay as icons and light only the path tracing
const RT_BUDGET = { PointLight: 2, SpotLight: 2 };
const RT_SHADOWS = { DirectionalLight: 1, PointLight: 0, SpotLight: 1 };
const _budget = { cam: new THREE.Vector3(1e9, 0, 0), dirty: true };
const _bw = new THREE.Vector3();
function lightBudget() {
  if (SMART.on || !lights.size) return;
  if (!_budget.dirty && camera.position.distanceToSquared(_budget.cam) < 1) return;
  _budget.dirty = false; _budget.cam.copy(camera.position);
  const by = {};
  for (const L of lights.values()) {
    const o = L.light;
    if (!o || !o.isLight) continue;
    if (!o.isPointLight && !o.isSpotLight) { o.visible = true; continue; }       // (suns: few, and the sun of the Ambiente must stay)
    o.getWorldPosition(_bw);
    L.score = (o.intensity > 0 ? o.intensity : 0) / (1 + _bw.distanceToSquared(camera.position));
    (by[o.type] = by[o.type] || []).push(L);
  }
  let changed = false;
  for (const t of Object.keys(by)) {
    const list = by[t].sort((a, b) => b.score - a.score);
    const n = RT_BUDGET[t] || 4;
    list.forEach((L, i) => { const v = i < n; if (L.light.visible !== v) { L.light.visible = v; changed = true; } });
  }
  if (changed) { refreshShadowBudget(); invalidate(); }
}

function refreshShadowBudget() {
  // (14/11) the shadows: the slot depends on the settings and the place in the budget of the light, never on its power (a lamp that
  // is off keeps its slot and only stops drawing its shadow map) and no more than RT_SHADOWS of each kind: the number of lights
  // with shadows in the shaders never changes - three.js made every shader again when it did (9-48 s at each day-night)
  let n = 0;
  const kinds = {};
  const order = [...lights.values()].sort((a, b) => (b.score || 0) - (a.score || 0));
  for (const L of order) {
    const t = L.light.type;
    const room = L.light.visible !== false && (kinds[t] || 0) < (RT_SHADOWS[t] ?? 1) && n < MAX_SHADOW_LIGHTS;
    const want = (L.data.shadow !== false || !!L.data.goboImage) && room;
    L.light.castShadow = want;
    if (want) {
      n++; kinds[t] = (kinds[t] || 0) + 1;
      const sh = L.light.shadow;
      if (L.light.intensity > 0) {
        if (sh.autoUpdate === false) { sh.autoUpdate = true; sh.needsUpdate = true; }
      } else {
        if (sh.autoUpdate !== false) sh.autoUpdate = false;
        if (!sh.map) sh.needsUpdate = true;       // (its map is made once, so the shader has one to read)
      }
    }
  }
}

function fitLightShadow(L, r, region) {
  // Tight near/far and a normal bias of about one shadow-map texel: no "striped" acne on large scenes.
  const cam = L.light.shadow.camera;
  const size = shadowSettings().map;
  if (L.light.shadow.mapSize.x !== size) {
    L.light.shadow.mapSize.set(size, size);
    if (L.light.shadow.map) { L.light.shadow.map.dispose(); L.light.shadow.map = null; }
  }
  const g = region || shadowRegion() || { c: boxOf(root, true).getCenter(new THREE.Vector3()), r, R: r };
  const c = g.c, rr = g.r, R = Math.max(g.R, rr);
  if (L.kind === 'sun') {
    // a directional light renders its shadow from its own position: place it out of the scene, along its axis;
    // the map covers the region looked at, the depth range the whole scene (things outside still cast)
    const dir = new THREE.Vector3(0, 0, 1).applyQuaternion(L.node.getWorldQuaternion(new THREE.Quaternion()));
    const worldPos = c.clone().add(dir.multiplyScalar(R * 4));
    L.light.position.copy(L.node.worldToLocal(worldPos));
    L.light.updateMatrixWorld(true);
    L.light.target.position.copy(L.light.worldToLocal(c.clone()));
    L.light.target.updateMatrixWorld(true);
    cam.left = cam.bottom = -rr * 1.2; cam.right = cam.top = rr * 1.2;
    cam.near = Math.max(0.001, R * 4 - R * 2.2); cam.far = R * 4 + R * 2.2;
    L.light.shadow.normalBias = (2.4 * rr / size) * 1.5;
  } else {
    const pos = L.node.getWorldPosition(new THREE.Vector3());
    const D = Math.max(pos.distanceTo(c), rr * 0.05);
    // depth range only around the region (a long range with a close light gives striped "acne" on the floor)
    cam.near = Math.max(0.0005, Math.min(D - rr * 1.6, D * 0.5), D * 0.08);
    cam.far = D + Math.min(R, rr * 3) * 1.6;
    let half = L.kind === 'point' ? Math.PI / 4 : Math.min(L.light.angle || 0.8, 1.4);
    if (L.kind !== 'point' && L.light.angle) {
      // spots (and area lights, drawn as wide spots): the shadow camera only as wide as needed to see the region
      // around the point looked at, not the whole 160° of a soft panel - much finer shadows for small objects
      const axis = new THREE.Vector3(0, 0, -1).applyQuaternion(L.node.getWorldQuaternion(new THREE.Quaternion()));
      const toC = c.clone().sub(pos);
      const off = toC.lengthSq() > 0 ? axis.angleTo(toC.normalize()) : 0;
      const need = D > rr ? (off + Math.asin(Math.min(1, rr * 1.3 / D))) * 1.1 : Math.PI;
      L.light.shadow.focus = Math.max(0.05, Math.min(1, need / L.light.angle));
      half = Math.min(half, L.light.angle * L.light.shadow.focus);
    } else L.light.shadow.focus = 1;
    // texel at the distance of the region; a little more than one (wide soft lights graze the floor: acne)
    L.light.shadow.normalBias = (2 * D * Math.tan(half) / size) * (L.kind === 'point' ? 1.2 : 2.2);
  }
  L.light.shadow.bias = -0.00005;
  cam.updateProjectionMatrix();
}

// ------------------------------------------------------------------ real-time shadow quality
const SHADOW_LEVELS = { off: { map: 512, label: tr('No') }, media: { map: 1024, label: tr('Media') }, alta: { map: 2048, label: tr('Alta') }, ultra: { map: 4096, label: tr('Ultra') } };
let shadowLevel = 'alta';
try { const v = localStorage.getItem('simpler.shadows'); if (v && SHADOW_LEVELS[v]) shadowLevel = v; } catch { /* storage unavailable */ }
function shadowSettings() { return SHADOW_LEVELS[shadowLevel]; }
function setShadowLevel(level) {
  shadowLevel = level;
  try { localStorage.setItem('simpler.shadows', level); } catch { /* storage unavailable */ }
  renderer.shadowMap.enabled = level !== 'off';
  root.traverse((o) => { if (o.material) (Array.isArray(o.material) ? o.material : [o.material]).forEach((m) => { m.needsUpdate = true; }); });
  prepareShaders(tr('Aggiornamento delle ombre nella vista'));
  const r = Math.max(sceneRadius(), 0.05);
  key.shadow.mapSize.set(shadowSettings().map, shadowSettings().map);
  if (key.shadow.map) { key.shadow.map.dispose(); key.shadow.map = null; }
  for (const L of lights.values()) fitLightShadow(L, r);
  updateViewbar();
}

function updateLightHelpers(r) { for (const L of lights.values()) buildHelper(L, r); }

// sun placed by time of day / north / date / latitude while a slider moves (same formulas as the engine, scene_ops.sun_vector)
function sunVector(hour, north, day, lat) {
  const r = Math.PI / 180, phi = lat * r;
  const dec = 23.44 * r * Math.sin((360 / 365) * (day - 81) * r);
  const h = 15 * (hour - 12) * r;
  const east = -Math.cos(dec) * Math.sin(h);
  const nrt = Math.sin(dec) * Math.cos(phi) - Math.cos(dec) * Math.cos(h) * Math.sin(phi);
  const up = Math.sin(dec) * Math.sin(phi) + Math.cos(dec) * Math.cos(h) * Math.cos(phi);
  const t = north * r;
  return new THREE.Vector3(Math.cos(t) * east + Math.sin(t) * nrt, -Math.sin(t) * east + Math.cos(t) * nrt, up).normalize();
}
function previewSun(id, p) {
  const L = lights.get(id), node = byId.get(id);
  if (!L || !node) return;
  const v = sunVector(p.hour, p.north, p.day, p.lat);
  const qw = new THREE.Quaternion().setFromUnitVectors(new THREE.Vector3(0, 0, 1), v);   // +Z looks at the sun
  const pq = new THREE.Quaternion();
  if (node.parent) node.parent.getWorldQuaternion(pq);
  node.quaternion.copy(pq.invert().multiply(qw));
  node.updateMatrixWorld(true);
  const el = Math.asin(Math.max(-1, Math.min(1, v.z))) * 180 / Math.PI;
  const x = Math.max(0, Math.min(1, (el + 1) / 4));
  L.light.intensity = (L.data.power || 0) * x * x * (3 - 2 * x) * (p.k ?? 1);
  // the sun disc of the Ambiente moves with it (its colour and the sky follow when the slider is let go)
  if (amb.active && amb.info && amb.info.sun && amb.info.sunId === id) {
    amb.dir.copy(v);
    ambDisc({ ...amb.info.sun, dir: v.toArray(), elev: el });
  }
  fitShadow();
  invalidate();
}

function removeLight(id) {
  const L = lights.get(id);
  if (!L) return;
  L.node.remove(L.light, L.sprite);
  if (L.helper) L.node.remove(L.helper);
  if (L.glow) { L.node.remove(L.glow); L.glow.geometry.dispose(); L.glow.material.dispose(); }
  if (L.light.dispose) L.light.dispose();
  lights.delete(id);
  _budget.dirty = true;
}

// ------------------------------------------------------------------ sync from the engine (transforms, visibility, lights)
// Objects sharing their shape (instances) with the same parent are merged by Blender's glTF export into one
// InstancedMesh (EXT_mesh_gpu_instancing): their own nodes are gone, so they could not be clicked, moved by the
// view, or switched on at dusk (6 headlight spheres of a car: drawn, but "as if they did not exist"). Each copy
// is found again from its place (the world matrix the engine sends) and becomes a mesh of its own (same geometry
// and material, shared); the copies found leave the InstancedMesh. Very big sets stay instanced (draw calls).
const ADOPT_MAX = 500;
function adoptInstances(items) {
  const key = (x, y, z) => Math.round(x * 2000) + ',' + Math.round(y * 2000) + ',' + Math.round(z * 2000);
  const want = new Map();
  for (const it of items) {
    if (byId.get(it.id) || it.dr || it.pm || !Array.isArray(it.matrix) || it.matrix.length !== 16 || it.light) continue;
    const m = it.matrix;
    const k = key(m[12], m[13], m[14]);
    if (!want.has(k)) want.set(k, []);
    want.get(k).push(it);
  }
  if (!want.size) return;
  const ims = [];
  root.traverse((o) => { if (o.isInstancedMesh && o.userData.gltfInstances && o.count > 0 && o.count <= ADOPT_MAX) ims.push(o); });
  const im4 = new THREE.Matrix4(), w = new THREE.Matrix4(), mw = new THREE.Matrix4();
  for (const im of ims) {
    im.updateMatrixWorld(true);
    const keep = [];
    for (let i = 0; i < im.count; i++) {
      im.getMatrixAt(i, im4);
      w.multiplyMatrices(im.matrixWorld, im4);
      const e = w.elements;
      const list = want.get(key(e[12], e[13], e[14]));
      let it = null;
      if (list) for (let j = 0; j < list.length; j++) {
        mw.fromArray(list[j].matrix);
        if (matricesCloseTol(mw, w, 1e-4)) { it = list[j]; list.splice(j, 1); break; }
      }
      if (!it) { keep.push(im4.clone()); continue; }
      const mesh = new THREE.Mesh(im.geometry, im.material);
      mesh.name = it.id;
      mesh.userData.simpler_id = it.id;
      mesh.userData.adopted = true;
      mesh.castShadow = im.castShadow; mesh.receiveShadow = im.receiveShadow;
      // the copies' parent: the instanced node itself when it is an object of the scene (the exporter puts the
      // instancing on the common parent), otherwise its parent
      (im.userData.simpler_id ? im : (im.parent || root)).add(mesh);
      setWorldMatrix(mesh, mw.fromArray(it.matrix));
      byId.set(it.id, mesh);
    }
    if (keep.length !== im.count) {
      keep.forEach((m, i) => im.setMatrixAt(i, m));
      im.count = keep.length;
      im.instanceMatrix.needsUpdate = true;
      im.boundingBox = null; im.boundingSphere = null;
      if (keep.length) { im.computeBoundingBox(); im.computeBoundingSphere(); }
    }
  }
}
function matricesCloseTol(a, b, tol) {
  for (let i = 0; i < 16; i++) if (Math.abs(a.elements[i] - b.elements[i]) > tol * Math.max(1, Math.abs(b.elements[i]))) return false;
  return true;
}

function applySync(objects) {
  const seen = new Set();
  {
    const ds = (objects || []).filter((it) => it.dr);
    if (ds.length) viewLog(`sync: ${ds.length} decals (${ds.filter((it) => byId.get(it.id)).length} with a node already)`);
  }
  adoptInstances(objects || []);
  for (const it of objects || []) {
    let o = byId.get(it.id);
    if (!o && it.dr) o = decalNode(it.id);
    if (!o && it.pm && it.pr) o = scatterPlaceholder(it.id, it.pm, (it.parent && byId.get(it.parent)) || root, it.pg, it.pk);
    if (!o) continue;
    if (it.rev) { scatter.syncRev.set(it.id, it.rev); scatterFetchSet(it.id, it.rev); }
    if (it.pm && it.pr) {
      o.userData.paintGen = !!it.pg;
      if (!o.userData.paintPiece) scatterAdopt(o, it.pm, it.pg, it.pk);
      else if ((it.pk || '') !== (o.userData.protoKey || '')) {
        // the piece looks different (a material, a part moved or hidden): its prototype changes
        o.userData.prevKey = o.userData.protoKey; o.userData.protoKey = it.pk || '';
        const g = scatter.shown.get(o);
        if (g) { o.remove(g); scatter.shown.delete(o); }
        nodeProto(o); scatterSelection(); scatter.dirty = true;
      }
    }
    if (!it.pr) o.userData.noScatter = !!it.ns;
    const pvKey = Array.isArray(it.pv) && it.pv.length === 3 ? it.pv.join(',') : '';
    if (pvKey) o.userData.customPivot = new THREE.Vector3().fromArray(it.pv);
    else if (o.userData.customPivot && !(pivotEdit && it.id === primary)) delete o.userData.customPivot;
    // (1.78.4) the pivot of a library model is where its pieces touch the surface in the distributions: when it
    // changes the view asks again where the pieces stand in the model (P.place), keeping the old one meanwhile
    if (it.pm && (o.userData.pvKey || '') !== pvKey) {
      if (o.userData.pvKey !== undefined) protoReplace(it.pm);
      o.userData.pvKey = pvKey;
    }
    o.userData.openModel = !!it.op;
    if (o.userData.paintPiece && o.visible !== (it.visible !== false)) scatter.dirty = true;
    o.visible = it.visible !== false;
    if (it.matrix && it.matrix.length === 16) {
      const m = new THREE.Matrix4().fromArray(it.matrix);
      o.updateMatrixWorld(true);
      if (!matricesClose(m, o.matrixWorld)) setWorldMatrix(o, m);
    }
    if (it.light) { updateLight(it.id, it.kind, it.light); seen.add(it.id); }
    if (it.dr) ensureDecal(it.id, it.dr, o);
  }
  for (const id of [...lights.keys()]) if (!seen.has(id)) removeLight(id);
  scatter.dirty = true;
  setFallback();
  if (!amb.active) scene.environmentIntensity = lights.size ? 0.15 : 0.65;
}

// ------------------------------------------------------------------ decals
// A decal is drawn here from the geometry the engine makes (GET decal/mesh: the surface of the piece inside its box,
// in the decal's own space, with the UV of the box and the fade at the depth limits) and its picture (GET decal/png).
// It is fetched again when its revision changes (sizes, values, its place on the piece).
// a line in the app's log (app.log): what goes wrong in the view, where the user can send it
const _viewLogged = new Set();
function viewLog(text) {
  if (_viewLogged.has(text) || _viewLogged.size > 200) return;
  _viewLogged.add(text);
  post({ type: 'log', text: String(text).slice(0, 400) });
}
// what the view has of the scene (app.log): after each load and when «Ridisegna la vista» is pressed
function viewDiag(why) {
  const st = {}; let parts = 0, partial = 0;
  for (const P of new Set(scatter.protos.values())) {
    st[P.state] = (st[P.state] || 0) + 1;
    for (const p of P.parts || []) { parts++; if ((p.levels || []).length < 4) partial++; }
  }
  let meshes = 0; root.traverse((o) => { if (o.isMesh) meshes++; });
  const gl = renderer.getContext();
  let lit = 0, shadows = 0;
  for (const L of lights.values()) { if (L.light.intensity > 0) lit++; if (L.light.castShadow) shadows++; }
  post({ type: 'log', text: `diag (${why}): lights ${lights.size} (${lit} lit, ${shadows} with shadows), lamps of distributions ${distLamps.all.length} lit (${distLamps.used} drawn as lights), flakes ${FLAKES.mesh ? FLAKES.mesh.geometry.instanceCount + ' (light ' + FLAKES.mat.uniforms.uAmb.value.x.toFixed(3) + ')' : 'none'}, exposure ${renderer.toneMappingExposure.toFixed(3)}` });
  post({ type: 'log', text: `diag (${why}): ${meshes} meshes in the scene file, ${scatter.nodes.size} library pieces (${scatter.drawn || 0} drawn), `
    + `models ${Object.entries(st).map(([k, v]) => k + ' ' + v).join(', ') || 'none'}, ${parts} parts (${partial} without lighter levels yet), `
    + `${scatter.sets.size} distributions, ${renderer.info.render.triangles} triangles, GL error ${gl.getError()}` });
  try { const p = camera.position, t = orbit.target; post({ type: 'log', text: `diag (${why}): camera at ${p.x.toFixed(2)}, ${p.y.toFixed(2)}, ${p.z.toFixed(2)} m, looking at ${t.x.toFixed(2)}, ${t.y.toFixed(2)}, ${t.z.toFixed(2)} m` }); } catch { }
}
window.addEventListener('error', (ev) => viewLog('view error: ' + (ev.error && ev.error.stack ? ev.error.stack : ev.message)));
window.addEventListener('unhandledrejection', (ev) => viewLog('view error: ' + (ev.reason && ev.reason.stack ? ev.reason.stack : ev.reason)));
function decalNode(id) {
  const node = new THREE.Object3D();
  node.name = id;
  node.userData.simpler_id = id;
  root.add(node);
  byId.set(id, node);
  return node;
}
const decalLoads = new Map();
const decalTex = new THREE.TextureLoader();
function ensureDecal(id, rev, node) {
  if (!node || !engineUrl || node.userData.decalRev === rev || decalLoads.get(id) === rev) return;
  decalLoads.set(id, rev);
  (async () => {
    try {
      const t0 = performance.now();
      const m = await (await fetch(engineUrl + 'decal/mesh?id=' + encodeURIComponent(id), { cache: 'no-store' })).json();
      if (decalLoads.get(id) !== rev) return;
      if (byId.get(id) !== node) {
        // the node was replaced meanwhile (the view loaded again): the decal goes on the new one, not lost
        decalLoads.delete(id);
        ensureDecal(id, rev, byId.get(id));
        return;
      }
      if (m.error || !(m.p && m.p.length)) {
        viewLog(`decal ${id}: ${m.error ? 'engine error: ' + m.error : 'no surface inside its box'} (${Math.round(performance.now() - t0)} ms)`);
        if (m.error) { decalLoads.delete(id); return; }
      }
      if (performance.now() - t0 > 3000) viewLog(`decal ${id}: geometry after ${Math.round((performance.now() - t0) / 1000)} s`);
      const n = m.f ? m.f.length : 0;
      const geo = new THREE.BufferGeometry();
      geo.setAttribute('position', new THREE.Float32BufferAttribute(m.p || [], 3));
      geo.setAttribute('uv', new THREE.Float32BufferAttribute(m.uv || [], 2));
      const col = new Float32Array(n * 4);
      for (let i = 0; i < n; i++) { const f = Math.min(1, m.f[i] || 0); col[i * 4] = col[i * 4 + 1] = col[i * 4 + 2] = 1; col[i * 4 + 3] = Math.max(0, 1 - f * f * f * f); }
      geo.setAttribute('color', new THREE.BufferAttribute(col, 4));
      geo.computeVertexNormals();
      const d = m.decal || {};
      const url = (map) => engineUrl + 'decal/png?id=' + encodeURIComponent(id) + (map ? '&map=' + map : '') + '&v=' + rev;
      const load = async (map, srgb) => {
        const t = await decalTex.loadAsync(url(map));
        t.colorSpace = srgb ? THREE.SRGBColorSpace : THREE.NoColorSpace;
        t.wrapS = t.wrapT = THREE.ClampToEdgeWrapping;
        t.anisotropy = 8;
        return t;
      };
      const tex = await load('', true);
      const has = new Set(d.has || []);
      const t = Array.isArray(d.tint) ? d.tint : [1, 1, 1];
      const order = Math.max(0, d.order || 0);
      const common = { map: tex, color: new THREE.Color(t[0], t[1], t[2]), transparent: true, depthWrite: false,
        polygonOffset: true, polygonOffsetFactor: -2 - order, polygonOffsetUnits: -4 - 2 * order, side: THREE.DoubleSide };
      let mat;
      if (d.mode === 'multiply') {
        // a stain: what is under it times the picture (white = nothing); the fade at the depth limits goes to white
        mat = new THREE.MeshBasicMaterial({ ...common, blending: THREE.CustomBlending, blendEquation: THREE.AddEquation,
          blendSrc: THREE.DstColorFactor, blendDst: THREE.ZeroFactor, toneMapped: false });
      } else {
        mat = new THREE.MeshStandardMaterial({ ...common, vertexColors: true,
          opacity: Math.max(0, Math.min(1, d.opacity ?? 1)), roughness: d.rough ?? 0.6, metalness: d.metal ?? 0 });
        if (d.mode === 'opacity' && has.has('opacity')) mat.alphaMap = await load('opacity', false);
        if (has.has('normal')) {
          mat.normalMap = await load('normal', false);
          const ns = Math.max(0, d.nstr ?? 1);
          mat.normalScale.set(ns, d.ndx ? -ns : ns);      // DirectX normal maps: green upside down
        }
        if (has.has('roughness')) { mat.roughnessMap = await load('roughness', false); mat.roughness = 1; }
        if (has.has('metalness')) { mat.metalnessMap = await load('metalness', false); mat.metalness = 1; }
        if ((d.emit || 0) > 0) {
          // with an emission map only its light parts glow (a neon writing), otherwise the whole picture
          mat.emissive = new THREE.Color(t[0], t[1], t[2]);
          mat.emissiveMap = has.has('emission') ? await load('emission', true) : tex;
          mat.emissiveIntensity = d.emit;
        }
      }
      mat.userData.wetDecal = true;         // (puddles go over it, as over the ground under it: rain.py)
      // outside the box the picture is not repeated nor stretched: those pixels are dropped (as "clip" in Blender)
      mat.onBeforeCompile = (sh) => {
        sh.fragmentShader = sh.fragmentShader.replace('#include <map_fragment>',
          'if (vMapUv.x < 0.0 || vMapUv.x > 1.0 || vMapUv.y < 0.0 || vMapUv.y > 1.0) discard;\n#include <map_fragment>');
      };
      if (decalLoads.get(id) !== rev || byId.get(id) !== node) {
        geo.dispose(); mat.dispose();
        if (decalLoads.get(id) === rev) { decalLoads.delete(id); ensureDecal(id, rev, byId.get(id)); }
        return;
      }
      const old = node.children.find((c) => c.userData.decalMesh);
      if (old) { node.remove(old); old.geometry.dispose(); for (const k of ['map', 'alphaMap', 'normalMap', 'roughnessMap', 'metalnessMap']) if (old.material[k]) old.material[k].dispose();
        if (old.material.emissiveMap && old.material.emissiveMap !== old.material.map) old.material.emissiveMap.dispose(); old.material.dispose(); }
      const mesh = new THREE.Mesh(geo, mat);
      mesh.userData.decalMesh = true;
      mesh.castShadow = false; mesh.receiveShadow = true;
      mesh.renderOrder = 10 + order;
      node.add(mesh);
      node.userData.decalRev = rev;
      // (Luca: «le decal del pavimento non si vedono più dopo aver riaperto il progetto») done: the guard of this fetch goes away.
      // Left in the map it kept the view from drawing the decal on the NEW node made when the scene is loaded again
      // (open: first the placeholders, then the exported scene): same revision, so «already loading» - never drawn.
      if (decalLoads.get(id) === rev) decalLoads.delete(id);
      {
        let par = [], x = node;
        while (x && par.length < 6) { par.push((x.name || x.type) + (x.visible ? '' : ' (hidden)')); x = x.parent; }
        let fa = 0; for (let i = 0; i < n; i++) fa += col[i * 4 + 3];
        const box = new THREE.Box3().setFromObject(mesh);
        viewLog(`decal ${id}: ${n / 3 | 0} triangles, mode ${d.mode || 'alpha'}, opacity ${d.opacity ?? 1}, mean visibility ${n ? (fa / n).toFixed(2) : '-'}, ` +
                `size ${box.isEmpty() ? '-' : box.getSize(new THREE.Vector3()).toArray().map((v) => v.toFixed(2)).join('×')} m, node visible ${isVisible(node)}, under ${par.join(' < ')}`);
      }
      invalidate(300);
    } catch (err) {
      decalLoads.delete(id);
      console.log('[Simpler] decal not loaded', id, err);
      viewLog(`decal ${id} not loaded: ${err && err.message ? err.message : err}`);
    }
  })();
}

// Structure changes that need no new geometry (deleted objects, new lights and groups, new parents) are
// applied here in place: re-exporting a very big model would take minutes. Returns false if a full reload is needed.
let needReason = '';
function applyStructure(list, removed, closed) {
  const want = new Map((list || []).map((o) => [o.id, o]));
  // library models closed again: their pieces leave the view; the sync that follows puts the placeholder back (drawn
  // from the prototype)
  for (const id of closed || []) {
    const node = byId.get(id);
    if (!node) continue;
    node.traverse((c) => { const cid = c.userData && c.userData.simpler_id; if (cid) { byId.delete(cid); removeLight(cid); } });
    if (node.parent) node.parent.remove(node);
  }
  // objects merged in the export (instances) have no node of their own: removing one needs a new export
  for (const id of removed || []) if (!byId.has(id) && !graveyard.has(id)) { needReason = 'removed object without node ' + id; return false; }
  const parentNode = (o) => (o.parent ? byId.get(o.parent) : root);
  // 1. new nodes (lights, groups), parents first
  // missing nodes: new objects, or old ones without a node of their own (instances: nothing to do)
  // painted pieces: a placeholder for each piece (drawn by the scatter), nothing for the parts inside a piece
  let pending = (list || []).filter((o) => !byId.has(o.id) && !(o.pm && !o.pr && !graveyard.has(o.id)) && (o.isNew !== false || graveyard.has(o.id)));
  for (let guard = 0; pending.length && guard < 64; guard++) {
    const next = [];
    for (const o of pending) {
      const p = parentNode(o);
      if (!p) { next.push(o); continue; }
      let node = graveyard.get(o.id);
      if (node) graveyard.delete(o.id);
      else if (o.pm && o.pr) { scatterPlaceholder(o.id, o.pm, p, o.pg, o.pk); continue; }
      else {
        if (!['point', 'spot', 'area', 'sun', 'light', 'group', 'camera', 'decal'].includes(o.kind)) { needReason = 'new ' + o.kind + ' ' + o.id; return false; }   // geometry we do not have
        node = new THREE.Object3D();
        node.name = o.id;
        node.userData.simpler_id = o.id;
      }
      p.add(node);
      byId.set(o.id, node);
      if (node.userData.paintPiece) scatterAdopt(node, node.userData.paintModel);
    }
    if (next.length === pending.length) { needReason = 'parent not found for ' + next.map((o) => o.id).join(','); return false; }
    pending = next;
  }
  if (pending.length) { needReason = 'parents not found'; return false; }
  // 2. new parents (keeping the place in the world; the sync that follows sets the exact matrix)
  const ownerId = (node) => { for (let p = node.parent; p; p = p.parent) { if (p === root) return ''; if (p.userData && p.userData.simpler_id) return p.userData.simpler_id; } return ''; };
  for (const o of want.values()) {
    const node = byId.get(o.id);
    if (!node || ownerId(node) === (o.parent || '')) continue;
    const p = parentNode(o);
    if (!p) continue;      // parent without a node of its own (merged instances): positions come from the sync anyway
    p.attach(node);
  }
  // 3. deleted objects
  for (const [id, node] of [...byId]) {
    if (want.has(id)) continue;
    removeLight(id);
    byId.delete(id);
    if (node.parent) node.parent.remove(node);
    graveyard.set(id, node);
    // (1.78.5, Luca: «ho eliminato l'auto, nella treeview non c'è ma nella viewport si vede») a library model or a
    // painted piece is drawn by the scatter from its prototype: its instances are rebuilt only when the scatter is
    // dirty, so with the camera still the deleted model stayed on the screen until it was touched
    node.traverse((c) => { if (scatter.nodes.has(c)) scatter.dirty = true; });
  }
  // (1.79, Luca: «di nuovo!!! modello eliminato, nella treeview non c'è ma è ancora visibile») a node of an object
  // no longer in the scene that the view did not have under its id (a second node for the same object, left by an
  // addition): it stays drawn and selectable until the next whole preparation - it goes now, and the log says it
  const stray = [];
  root.traverse((c) => {
    const cid = c !== root && c.userData && c.userData.simpler_id;
    if (cid && !want.has(cid) && byId.get(cid) !== c && graveyard.get(cid) !== c) stray.push(c);
  });
  for (const c of stray) {
    if (!c.parent) continue;
    c.parent.remove(c);
    c.traverse((x) => { if (scatter.nodes.has(x)) { scatter.nodes.delete(x); scatter.dirty = true; } });
  }
  if ((removed || []).length || stray.length) {
    // (Luca: «di nuovo il modello eliminato che resta nella vista») whatever the scatter drew for a removed object
    // is rebuilt in any case - at once and twice more - and the log says what it still holds, so a new case can be seen
    scatter.dirty = true;
    for (const t of [250, 1200]) setTimeout(() => { scatter.dirty = true; invalidate(200); }, t);
    const held = [...scatter.nodes].filter((n) => !n.userData.ghost && byId.get(n.userData.simpler_id) !== n).length;
    post({ type: 'log', text: `structure: ${(removed || []).length} removed (${(removed || []).slice(0, 6).join(',')}), `
      + `${stray.length} stray nodes of removed objects taken away${stray.length ? ' (' + [...new Set(stray.map((c) => c.userData.simpler_id))].slice(0, 6).join(',') + ')' : ''}, `
      + `scatter holds ${scatter.nodes.size} pieces (${held} of removed objects), selection ${selection.length}` });
    invalidate(300);
  }
  selection = selection.filter((id) => byId.has(id));
  applySelection(selection, byId.has(primary) ? primary : selection[selection.length - 1]);
  setFallback();
  return true;
}

// Duplicates made in the app: copy the nodes the view already has (shared geometry, no export).
function applyClones(copies) {
  const inverse = new Map(Object.entries(copies || {}).map(([n, src]) => [src, n]));
  const tops = Object.entries(copies || {}).filter(([, src]) => {
    const node = byId.get(src);
    const pid = node ? ownerOf(node) : '';
    return !(pid && inverse.has(pid));      // the copy of a parent brings its children with it
  });
  for (const [, src] of tops) {
    const node = byId.get(src);
    if (!node || !node.parent) { needReason = 'duplicate of an object without node'; return false; }
    const copy = node.clone(true);
    // drop light objects, icons and helpers copied with the node: the sync rebuilds them for the new ids
    const junk = [];
    copy.traverse((o) => { if (o !== copy && (o.isLight || o.userData.helper || o.isSprite)) junk.push(o); });
    junk.forEach((o) => o.parent && o.parent.remove(o));
    copy.traverse((o) => {
      const sid = o.userData && o.userData.simpler_id;
      if (!sid) return;
      o.userData = { ...o.userData, simpler_id: inverse.get(sid) || '' };
      if (o.userData.simpler_id) byId.set(o.userData.simpler_id, o);
    });
    node.parent.add(copy);
  }
  return true;
}

function ownerOf(node) {
  for (let p = node.parent; p; p = p.parent) { if (p === root) return ''; if (p.userData && p.userData.simpler_id) return p.userData.simpler_id; }
  return '';
}

// Materials changed in the app: built here from their values, no export. Materials edited in Simpler's material
// editor ("simpler") carry every channel, with their maps loaded from the engine (GET texture), so even textured
// edits show at once.
const rtMaterials = new Map();
const rtMaterialSet = new WeakSet();   // (materials built here from PBR values, not from the export)
const texCache = new Map();
const TEX_PX = 1024;
// (1.78.4) rev: which picture the name means now (from the engine). Generic names of imported plants («color map.015»)
// come back for another picture: kept by name alone, one plant's leaves showed another plant's picture
function loadImage(name, rev, px) {
  const key = (rev ? name + '|' + rev : name) + (px ? '@' + px : '');
  if (texCache.has(key)) return texCache.get(key);
  const pr = new Promise((resolve, reject) => {
    const img = new Image();
    img.crossOrigin = 'anonymous';
    img.onload = () => { resolve(img); invalidate(800); };
    const url = engineUrl + 'texture?image=' + encodeURIComponent(name) + '&px=' + (px || TEX_PX) + (rev ? '&r=' + rev : '');
    // (Luca: «ficus tree senza materiale») a picture the browser cannot show (BMP, TGA, big TIFF) comes as a copy the
    // engine makes in the background: not there yet at the first asking - asked again a few times (1.5 to 24 s apart)
    let tries = 0;
    // (a failed load is not kept: a texture missing at the opening and linked again later loads at the next try)
    img.onerror = (e) => {
      if (tries < 5 && texCache.get(key) === pr) { const t = ++tries; setTimeout(() => { img.src = url + '&try=' + t; }, 750 * 2 ** t); return; }
      if (texCache.get(key) === pr) texCache.delete(key); reject(e);
    };
    img.src = url;
  });
  texCache.set(key, pr);
  return pr;
}
// grey map baked for three.js: chosen channel, inverted if asked, blended with the slider value by its strength
// (three.js multiplies roughness/metalness by the map's G/B channel: the baked map carries the final value)
function bakeScalar(img, m, value) {
  const c = document.createElement('canvas');
  c.width = img.naturalWidth; c.height = img.naturalHeight;
  const g = c.getContext('2d', { willReadFrequently: true });
  g.drawImage(img, 0, 0);
  const d = g.getImageData(0, 0, c.width, c.height);
  const ch = { R: 0, G: 1, B: 2, A: 3 }[m.channel || ''];
  const s = Math.max(0, Math.min(1, m.strength ?? 1)), v = Math.round(255 * Math.max(0, Math.min(1, value)));
  for (let i = 0; i < d.data.length; i += 4) {
    let x = ch === undefined ? Math.round((d.data[i] + d.data[i + 1] + d.data[i + 2]) / 3) : d.data[i + ch];
    if (m.invert) x = 255 - x;
    x = Math.round(v * (1 - s) + x * s);
    d.data[i] = d.data[i + 1] = d.data[i + 2] = x; d.data[i + 3] = 255;
  }
  g.putImageData(d, 0, 0);
  return c;
}
function makeTexture(src, color, uv, scale = 1) {
  const t = src instanceof HTMLCanvasElement ? new THREE.CanvasTexture(src) : new THREE.Texture(src);
  t.flipY = false;                          // same convention as the glTF from the engine
  t.wrapS = t.wrapT = THREE.RepeatWrapping;
  t.colorSpace = color ? THREE.SRGBColorSpace : THREE.NoColorSpace;
  t.anisotropy = 8;
  if (uv && (uv.mode || 'uv') === 'uv') {
    const k = uv.scale || 1, st = uv.stretch || [1, 1];
    // (1.75.60) the map's own scale (a glossiness map over many tiles): the coordinates of the material divided by
    // it, as Cycles (matedit _Builder.image)
    const s = scale > 0 ? scale : 1;
    t.repeat.set(k * st[0] / s, k * st[1] / s);
    // as Cycles (matedit _Builder.coords: Location = -offset × scale); v counts from the top here (glTF), from the
    // bottom in Cycles: the 1 - repeat keeps the two in step also with a scale that is not a whole number
    t.offset.set(-(uv.offset?.[0] || 0) * k * st[0] / s, 1 - (k * st[1] - (uv.offset?.[1] || 0) * k * st[1]) / s);
    t.rotation = -(uv.rotation || 0) * Math.PI / 180;
  }
  t.needsUpdate = true;
  return t;
}
// «Rompi la ripetizione» (Randomize UV) in the real-time view: as in Cycles (matedit._antitile) two layers of
// Voronoi zones, each zone showing the texture shifted (and turned) at random; the second layer, with its cells
// elsewhere, shows near the edges of the first. Same idea, not the same random pattern as Cycles.
function antitileGLSL(uv) {
  const rot = uv.antitileRotate !== false;
  return `uniform float atCell; uniform float atBlend;
vec3 atHash(vec2 p) { vec3 q = vec3(dot(p, vec2(127.1, 311.7)), dot(p, vec2(269.5, 183.3)), dot(p, vec2(419.2, 371.9))); return fract(sin(q) * 43758.5453); }
void atVoronoi(vec2 x, out vec2 cellId, out float edge) {
  vec2 n = floor(x), f = fract(x), mg = vec2(0.0), mr = vec2(0.0); float md = 8.0;
  for (int j = -1; j <= 1; j++) for (int i = -1; i <= 1; i++) {
    vec2 g = vec2(float(i), float(j)); vec2 r = g + atHash(n + g).xy - f; float d = dot(r, r);
    if (d < md) { md = d; mr = r; mg = g; }
  }
  md = 8.0;
  for (int j = -1; j <= 1; j++) for (int i = -1; i <= 1; i++) {
    vec2 g = mg + vec2(float(i), float(j)); vec2 r = g + atHash(n + g).xy - f;
    if (dot(mr - r, mr - r) > 1e-5) md = min(md, dot(0.5 * (mr + r), normalize(r - mr)));
  }
  cellId = n + mg; edge = md;
}
vec4 atLayer(sampler2D t, vec2 uv, vec2 sh, bool rot, vec2 dx, vec2 dy, out float edge) {
  vec2 id; atVoronoi(uv / atCell + sh, id, edge);
  vec3 r = atHash(id + 0.37);
  vec2 q = uv, gx = dx, gy = dy;
  if (rot) { float a = r.z * 6.2831853; mat2 R = mat2(cos(a), sin(a), -sin(a), cos(a)); q = R * q; gx = R * gx; gy = R * gy; }
  return textureGrad(t, q + r.xy * 7.31, gx, gy);
}
vec4 atTexR(sampler2D t, vec2 uv, bool rot) {
  vec2 dx = dFdx(uv), dy = dFdy(uv); float e1, e2;
  vec4 a = atLayer(t, uv, vec2(0.0), rot, dx, dy, e1);
  vec4 b = atLayer(t, uv, vec2(0.5 + 13.7 / atCell, 0.5 + 5.3 / atCell), rot, dx, dy, e2);
  return mix(b, a, smoothstep(0.0, atBlend, e1));
}
vec4 atTex(sampler2D t, vec2 uv) { return atTexR(t, uv, ${rot ? 'true' : 'false'}); }
vec4 atTexN(sampler2D t, vec2 uv) { return atTexR(t, uv, false); }   // normal maps: only shifted (the light stays right)
`;
}
function antitileUniforms(sh, uv) {
  sh.uniforms.atCell = { value: Math.max(0.5, uv.cellRepeats || 3) };
  sh.uniforms.atBlend = { value: Math.max(0.02, Math.min(0.5, uv.antitileBlend ?? 0.25)) * 0.4 };
}
function useAntitileUV(m, uv) {
  m.onBeforeCompile = (sh) => {
    antitileUniforms(sh, uv);
    const chunk = (name, from, to) => { sh.fragmentShader = sh.fragmentShader.replace(`#include <${name}>`, THREE.ShaderChunk[name].replaceAll(from, to)); };
    sh.fragmentShader = antitileGLSL(uv) + sh.fragmentShader;
    chunk('map_fragment', 'texture2D( map, vMapUv )', 'atTex( map, vMapUv )');
    chunk('roughnessmap_fragment', 'texture2D( roughnessMap, vRoughnessMapUv )', 'atTex( roughnessMap, vRoughnessMapUv )');
    chunk('metalnessmap_fragment', 'texture2D( metalnessMap, vMetalnessMapUv )', 'atTex( metalnessMap, vMetalnessMapUv )');
    chunk('emissivemap_fragment', 'texture2D( emissiveMap, vEmissiveMapUv )', 'atTex( emissiveMap, vEmissiveMapUv )');
    chunk('alphamap_fragment', 'texture2D( alphaMap, vAlphaMapUv )', 'atTex( alphaMap, vAlphaMapUv )');
    chunk('normal_fragment_maps', 'texture2D( normalMap, vNormalMapUv )', 'atTexN( normalMap, vNormalMapUv )');
  };
  m.customProgramCacheKey = () => 'at1' + (uv.antitileRotate !== false ? 'r' : 's');
}
// «Centra ogni pezzo» (matedit.piece_attributes): the separate pieces of a geometry - faces that touch, by position
// (one geometry here is one material of a mesh, as the pieces of the engine) - and the middle of each, as attributes
// _simpler_pc (position) and _simpler_puv (UV, flipped as glTF). Once per geometry, when it is first drawn with such
// a material.
function piecesOf(g) {
  if (!g || g.userData.pieces || !g.attributes.position) return;
  g.userData.pieces = true;
  const pos = g.attributes.position, n = pos.count, uvA = g.attributes.uv;
  const node = new Int32Array(n), keyOf = new Map();
  for (let i = 0; i < n; i++) {
    const k = Math.round(pos.getX(i) * 1e4) + ',' + Math.round(pos.getY(i) * 1e4) + ',' + Math.round(pos.getZ(i) * 1e4);
    let id = keyOf.get(k);
    if (id === undefined) { id = keyOf.size; keyOf.set(k, id); }
    node[i] = id;
  }
  const parent = new Int32Array(keyOf.size).map((_, i) => i);
  const root = (a) => { while (parent[a] !== a) { parent[a] = parent[parent[a]]; a = parent[a]; } return a; };
  const join = (a, b) => { a = root(a); b = root(b); if (a !== b) parent[a] = b; };
  const idx = g.index, tri = idx ? idx.count : n;
  for (let t = 0; t + 2 < tri; t += 3) {
    const a = idx ? idx.getX(t) : t, b = idx ? idx.getX(t + 1) : t + 1, c = idx ? idx.getX(t + 2) : t + 2;
    join(node[a], node[b]); join(node[a], node[c]);
  }
  const lo = new Map(), hi = new Map(), ulo = new Map(), uhi = new Map();
  const comp = new Int32Array(n);
  for (let i = 0; i < n; i++) {
    const r = root(node[i]); comp[i] = r;
    const p = [pos.getX(i), pos.getY(i), pos.getZ(i)];
    const l = lo.get(r), h = hi.get(r);
    if (!l) { lo.set(r, p.slice()); hi.set(r, p.slice()); } else for (let k = 0; k < 3; k++) { l[k] = Math.min(l[k], p[k]); h[k] = Math.max(h[k], p[k]); }
    if (uvA) {
      const u = [uvA.getX(i), uvA.getY(i)], ul = ulo.get(r), uh = uhi.get(r);
      if (!ul) { ulo.set(r, u.slice()); uhi.set(r, u.slice()); } else for (let k = 0; k < 2; k++) { ul[k] = Math.min(ul[k], u[k]); uh[k] = Math.max(uh[k], u[k]); }
    }
  }
  const pc = new Float32Array(n * 3), puv = new Float32Array(n * 2);
  for (let i = 0; i < n; i++) {
    const r = comp[i], l = lo.get(r), h = hi.get(r);
    for (let k = 0; k < 3; k++) pc[i * 3 + k] = (l[k] + h[k]) / 2;
    if (uvA) { const ul = ulo.get(r), uh = uhi.get(r); puv[i * 2] = (ul[0] + uh[0]) / 2; puv[i * 2 + 1] = (ul[1] + uh[1]) / 2; }
  }
  g.setAttribute('_simpler_pc', new THREE.BufferAttribute(pc, 3));
  g.setAttribute('_simpler_puv', new THREE.BufferAttribute(puv, 2));
}
// UV with «Centra ogni pezzo»: the UV of each piece from the middle of its own UV, as Cycles (uv - middle). glTF
// counts v from the top: v' = v - middle + 1 keeps the same coordinate as Cycles (also with a scale not whole)
function usePieceUV(m) {
  // the material's OWN functions (antitile), never the rain wrappers the properties return: chaining a wrapper made
  // the wrapper call itself (endless recursion: the view stopped drawing) and the rain patch applied twice
  const prev = m._ownCompile, prevKey = m._ownKey;
  m.onBeforeCompile = (sh, r) => {
    if (prev) prev.call(m, sh, r);
    sh.vertexShader = 'attribute vec2 _simpler_puv;\n' + sh.vertexShader.replace('#include <uv_vertex>',
      'vec2 simplerPieceUv = vec2(uv.x - _simpler_puv.x, uv.y - _simpler_puv.y + 1.0);\n' +
      THREE.ShaderChunk.uv_vertex.replace(/\b[A-Z_]*MAP_UV\b/g, 'simplerPieceUv'));
  };
  m.onBeforeRender = (r, sc, cam, geometry) => piecesOf(geometry);
  m.customProgramCacheKey = () => 'pc1' + (prevKey ? prevKey.call(m) : '');
}
// box / planar / cylindrical / spherical projections: approximated here with a triplanar projection
function useTriplanar(m, uv) {
  const k = 100 / Math.max(0.1, uv.sizeCm || 100), st = uv.stretch || [1, 1];
  const world = uv.space === 'world';
  // Box in world space: as Cycles (matedit coords) the world position turned back by the object's rotation, and the
  // object's own normal: the projection follows the object's orientation (before: world normal here, object normal
  // in Cycles - a turned object showed the texture differently, smeared in the path tracing)
  const turned = world && (uv.mode || 'uv') === 'box';
  const per = !!uv.perPiece;      // «Centra ogni pezzo»: measured from the middle of each piece (piecesOf)
  const rot = (uv.rotation || 0) * Math.PI / 180, off = uv.offset || [0, 0];
  const blend = Math.max(0.01, Math.min(1, uv.blend ?? 0.2));
  const at = !!uv.antitile;
  m.onBeforeCompile = (sh) => {
    if (at) antitileUniforms(sh, uv);
    sh.uniforms.triK = { value: new THREE.Vector2(k * st[0], k * st[1]) };
    sh.uniforms.triKz = { value: k };
    sh.uniforms.triRot = { value: rot };
    sh.uniforms.triOff = { value: new THREE.Vector3(off[0] || 0, off[1] || 0, off[2] || 0) };
    sh.uniforms.triSharp = { value: 1 / blend };
    sh.vertexShader = (per ? 'attribute vec3 _simpler_pc;\n' : '') + 'varying vec3 vTriPos;\nvarying vec3 vTriNrm;\n' + sh.vertexShader.replace('#include <project_vertex>',
      '#include <project_vertex>\n' + (per
        ? 'vTriPos = (transformed - _simpler_pc) * vec3(length(modelMatrix[0].xyz), length(modelMatrix[1].xyz), length(modelMatrix[2].xyz)); vTriNrm = objectNormal;'
        : turned
        ? `{ mat4 triM = modelMatrix;
#ifdef USE_INSTANCING
  triM = modelMatrix * instanceMatrix;
#endif
  mat3 triR = mat3(normalize(triM[0].xyz), normalize(triM[1].xyz), normalize(triM[2].xyz));
  vTriPos = transpose(triR) * (triM * vec4(transformed, 1.0)).xyz;
  vTriNrm = transpose(triR) * normalize(mat3(triM) * objectNormal); }`
        : world
        ? `{ mat4 triM = modelMatrix;
#ifdef USE_INSTANCING
  triM = modelMatrix * instanceMatrix;
#endif
  vTriPos = (triM * vec4(transformed, 1.0)).xyz; vTriNrm = normalize(mat3(triM) * objectNormal); }`
        : 'vTriPos = transformed * vec3(length(modelMatrix[0].xyz), length(modelMatrix[1].xyz), length(modelMatrix[2].xyz)); vTriNrm = objectNormal;'));
    // same as Cycles: the Mapping node works on the 3D coordinates (scale, rotation around Z, offset), then the box
    // projection reads, per face: X (±y, z), Y (∓x, z), Z (∓y, x) - the sign from the side the face looks at
    // (checked against Cycles renders: without this the floor showed the texture turned by 90°)
    const fn = `varying vec3 vTriPos;\nvarying vec3 vTriNrm;\nuniform vec2 triK; uniform float triKz; uniform float triRot; uniform vec3 triOff; uniform float triSharp;
vec4 triSample(sampler2D t) {
  vec3 n = normalize(vTriNrm);
  vec3 w = pow(abs(n), vec3(triSharp)); w /= (w.x + w.y + w.z + 1e-5);
  vec3 p = vTriPos * vec3(triK, triKz);
  float c = cos(triRot), s = sin(triRot);
  vec3 q = vec3(c * p.x - s * p.y + triOff.x, s * p.x + c * p.y + triOff.y, p.z + triOff.z);
  vec2 ux = vec2(n.x < 0.0 ? -q.y : q.y, q.z);
  vec2 uy = vec2(n.y > 0.0 ? -q.x : q.x, q.z);
  vec2 uz = vec2(n.z > 0.0 ? -q.y : q.y, q.x);
  // (textures here have flipY = false, the glTF convention: v counts from the top, in Cycles from the bottom)
  return TRI_TEX(t, vec2(ux.x, -ux.y)) * w.x + TRI_TEX(t, vec2(uy.x, -uy.y)) * w.y + TRI_TEX(t, vec2(uz.x, -uz.y)) * w.z;
}\n`.replace(/TRI_TEX/g, at ? 'atTex' : 'texture2D');
    // the chunks are still #include lines here: expanded by hand with the texture lookups replaced
    const chunk = (name, from, to) => { sh.fragmentShader = sh.fragmentShader.replace(`#include <${name}>`, THREE.ShaderChunk[name].replace(from, to)); };
    sh.fragmentShader = (at ? antitileGLSL(uv) : '') + fn + sh.fragmentShader;
    chunk('map_fragment', 'texture2D( map, vMapUv )', 'triSample( map )');
    chunk('roughnessmap_fragment', 'texture2D( roughnessMap, vRoughnessMapUv )', 'triSample( roughnessMap )');
    chunk('metalnessmap_fragment', 'texture2D( metalnessMap, vMetalnessMapUv )', 'triSample( metalnessMap )');
    chunk('emissivemap_fragment', 'texture2D( emissiveMap, vEmissiveMapUv )', 'triSample( emissiveMap )');
    chunk('alphamap_fragment', 'texture2D( alphaMap, vAlphaMapUv )', 'triSample( alphaMap )');
  };
  if (per) m.onBeforeRender = (r, sc, cam, geometry) => piecesOf(geometry);
  m.customProgramCacheKey = () => 'tri3' + (per ? 'p' : turned ? 't' : world ? 'w' : 'o') + (at ? (uv.antitileRotate !== false ? 'ar' : 'as') : '');
}
// «Sporco» (grunge, 1.69.0) in the real-time view: the dirt picture projected from three sides in the world (metres)
// (as matedit._Builder.grunge), mixed into the colour and the roughness just before the normals (after every map,
// also the triplanar ones that expand their own chunks); relief and normal map are the path tracing's only.
// ---- «Dipingi lo sporco» (dirtpaint.py): three maps over a cube around what was painted, one per direction a surface
// faces (along X: u = y, v = z; along Y: u = x, v = z; along Z: u = x, v = y), stacked in one texture n wide and 3 n
// high: R = amount, G B = depth (16 bits). A surface takes the dirt of its map where its depth matches (within tol).
// The strokes are drawn here at once while the mouse moves (dirtStamp: the same brushes as the engine), the engine's
// maps replace them when the stroke is made.
// pending: the strokes sent and not made by the engine yet - drawn again over every map that arrives meanwhile (before,
// the map of the previous stroke wiped what was being painted: «painting over it takes it away», 1.73.9)
const DIRT = { info: null, data: null, n: 0, E: null, Eload: null, asked: false, pending: [],
  u: { dpTex: { value: null }, dpO: { value: new THREE.Vector3() }, dpInv: { value: 1 }, dpTol: { value: 0 }, dpOn: { value: 0 }, dpN: { value: 1 } } };
function dirtAsk() {
  if (DIRT.asked) return;
  DIRT.asked = true;
  fetch(engineUrl + 'dirt/info', { cache: 'no-store' }).then((r) => r.json()).then((j) => dirtFetch(j.info)).catch(() => { DIRT.asked = false; });
}
async function dirtFetch(m) {
  if (!m) { DIRT.info = null; DIRT.data = null; DIRT.u.dpOn.value = 0; invalidate(); return; }
  if (DIRT.info && DIRT.info.rev === m.rev && DIRT.info.file === m.file) return;
  const buf = new Uint8Array(await (await fetch(engineUrl + 'dirt/paint.bin?f=' + encodeURIComponent(m.file + '.bin'), { cache: 'no-store' })).arrayBuffer());
  const n = m.n, rgba = new Uint8Array(n * 3 * n * 4);
  for (let i = 0, j = 0; i < 3 * n * n; i++, j += 3) { rgba[i * 4] = buf[j]; rgba[i * 4 + 1] = buf[j + 1]; rgba[i * 4 + 2] = buf[j + 2]; rgba[i * 4 + 3] = 255; }
  const t = new THREE.DataTexture(rgba, n, 3 * n, THREE.RGBAFormat, THREE.UnsignedByteType);
  t.magFilter = t.minFilter = THREE.LinearFilter; t.generateMipmaps = false; t.wrapS = t.wrapT = THREE.ClampToEdgeWrapping;
  t.needsUpdate = true;
  const old = DIRT.u.dpTex.value;
  DIRT.u.dpTex.value = t;
  if (old) old.dispose();
  DIRT.info = m; DIRT.data = rgba; DIRT.n = n;
  DIRT.u.dpO.value.set(m.x0, m.y0, m.z0); DIRT.u.dpInv.value = 1 / m.size; DIRT.u.dpTol.value = m.tol / m.size;
  DIRT.u.dpN.value = n; DIRT.u.dpOn.value = 1;
  if (m.pattern && !DIRT.Eload) DIRT.Eload = dirtPattern(m.pattern);
  dirtRestamp();
  invalidate();
}
function dirtRestamp() {
  const now = performance.now();
  DIRT.pending = DIRT.pending.filter((s) => now - s.t < 60000);      // (a stroke never answered: not for ever)
  const again = DIRT.pending.slice();
  if (puddle.painting && puddle.layer === 'dirt' && puddle.pts.length)
    again.push({ pts: puddle.pts, radius: puddle.radius, add: !puddle.removing, preset: puddle.preset, strength: puddle.strength });
  for (const s of again)
    for (const p of s.pts) dirtStamp(new THREE.Vector3(p[0], p[1], p[2]), new THREE.Vector3(p[3], p[4], p[5]), s.radius, s.add, s.preset, s.strength);
}
// Simpler's dirt picture, 4 × 4 averaged (512²) and equalised: as dirtpaint._pattern (rows from the top)
function dirtPattern(name) {
  return new Promise((resolve) => {
    const img = new Image();
    img.crossOrigin = 'anonymous';
    img.onload = () => {
      const w = img.width, h = img.height, c = document.createElement('canvas');
      c.width = w; c.height = h;
      const g = c.getContext('2d', { willReadFrequently: true });
      g.drawImage(img, 0, 0);
      const px = g.getImageData(0, 0, w, h).data, W = w / 4, H = h / 4, v = new Uint8Array(W * H), hist = new Float64Array(256);
      for (let y = 0; y < H; y++) for (let x = 0; x < W; x++) {
        let sum = 0;
        for (let dy = 0; dy < 4; dy++) for (let dx = 0; dx < 4; dx++) sum += px[((y * 4 + dy) * w + x * 4 + dx) * 4];
        const q = Math.floor(sum / 16 + 0.5);
        v[y * W + x] = q; hist[q]++;
      }
      const cdf = new Float32Array(256);
      let acc = 0;
      for (let i = 0; i < 256; i++) { cdf[i] = (acc + hist[i] / 2) / v.length; acc += hist[i]; }
      const E = new Float32Array(W * H);
      for (let i = 0; i < E.length; i++) E[i] = cdf[v[i]];
      DIRT.E = { E, W, H };
      resolve();
    };
    img.onerror = () => resolve();
    img.src = engineUrl + 'texture?image=' + encodeURIComponent(name) + '&px=4096';
  });
}
function dirtE(u, v, scale) {
  const P = DIRT.E;
  if (!P) return 0.5;
  const fu = u / scale - Math.floor(u / scale), fv = v / scale - Math.floor(v / scale);
  return P.E[(Math.floor(fv * P.H) % P.H) * P.W + (Math.floor(fu * P.W) % P.W)];
}
function dirtBrush(f, u, v, preset) {
  if (preset === 'frastagliato') return f > 0 ? smooth01(0.45, 0.6, f + 0.7 * (dirtE(u, v, 2.0) - 0.5)) : 0;
  if (preset === 'macchie') return f * smooth01(0.62, 0.78, dirtE(u, v, 3.0));
  return f * (0.45 + 0.55 * dirtE(u, v, 0.6));
}
const DIRT_AXES = [[1, 2, 0], [0, 2, 1], [0, 1, 2]];
// one dab drawn here (as dirtpaint.stroke); false when there are no maps yet (the first stroke: the engine makes them)
function dirtStamp(p, nrm, r, add, preset, k) {
  if (!DIRT.data || !DIRT.info) return false;
  const M = DIRT.info, n = DIRT.n, cell = M.size / n, D = DIRT.data, o = [M.x0, M.y0, M.z0], P = [p.x, p.y, p.z];
  const an = [Math.abs(nrm.x), Math.abs(nrm.y), Math.abs(nrm.z)];
  const a = an[0] >= an[1] && an[0] >= an[2] ? 0 : an[1] >= an[2] ? 1 : 2;
  const [iu, iv, idp] = DIRT_AXES[a], rr = r * 1.3;
  const i0 = Math.max(0, Math.floor((P[iu] - rr - o[iu]) / cell)), i1 = Math.min(n, Math.floor((P[iu] + rr - o[iu]) / cell) + 2);
  const j0 = Math.max(0, Math.floor((P[iv] - rr - o[iv]) / cell)), j1 = Math.min(n, Math.floor((P[iv] + rr - o[iv]) / cell) + 2);
  if (i0 >= i1 || j0 >= j1) return false;
  const dep = Math.max(0, Math.min(65535, Math.round((P[idp] - o[idp]) / M.size * 65535)));
  for (let j = j0; j < j1; j++) {
    const cv = o[iv] + (j + 0.5) * cell;
    for (let i = i0; i < i1; i++) {
      const cu = o[iu] + (i + 0.5) * cell;
      const dist = Math.hypot(cu - P[iu], cv - P[iv]) / r;
      const f = 1 - smooth01(0.5, 1, dist);
      const q = ((a * n + j) * n + i) * 4;
      let A = D[q] / 255;
      if (add) {
        const b = dirtBrush(f, cu, cv, preset) * k;
        if (dist < 1.3 && (A <= 0 || b >= A)) { D[q + 1] = dep >> 8; D[q + 2] = dep & 255; }   // (as dirtpaint.stroke)
        A = Math.max(A, b);
      } else A *= 1 - k * f;
      D[q] = Math.round(Math.max(0, Math.min(1, A)) * 255);
    }
  }
  DIRT.u.dpTex.value.needsUpdate = true;
  return true;
}
const _grBlack = (() => { const t = new THREE.DataTexture(new Uint8Array([0, 0, 0, 255]), 1, 1); t.needsUpdate = true; return t; })();
function useGrunge(m, g) {
  const prev = m._ownCompile, prevKey = m._ownKey;       // (the material's own functions, never the rain wrappers)
  const un = {
    grTex: { value: _grBlack }, grCol: { value: _grBlack }, grHasCol: { value: 0 },
    grAmt: { value: g.amount || 0 }, grOpa: { value: g.opacity ?? 1 }, grScale: { value: 100 / Math.max(0.1, g.sizeCm || 50) },
    grRough: { value: g.roughness ?? 0.3 }, grRand: { value: g.randomize === false ? 0 : 1 }, grInv: { value: g.invert ? 1 : 0 },
    grColor: { value: new THREE.Vector3(...(g.color || [0.09, 0.075, 0.06])) },
    // «Seme casuale»: the picture shifted elsewhere, as Cycles (matedit.grunge_seed_offset)
    grSeed: { value: new THREE.Vector3(...[0.7548776662, 0.5698402910, 0.4142135624].map((k) => { const v = (g.seed || 0) * k; return (v - Math.trunc(v)) * 37; })) },
  };
  const tex = (name, color, slot) => loadImage(name).then((img) => {
    const t = new THREE.Texture(img);
    t.flipY = false; t.wrapS = t.wrapT = THREE.RepeatWrapping; t.anisotropy = 8;
    t.colorSpace = color ? THREE.SRGBColorSpace : THREE.NoColorSpace;
    t.needsUpdate = true;
    un[slot].value = t;
    if (slot === 'grCol') un.grHasCol.value = 1;
    invalidate();
  }).catch(() => {});
  if (g.paint) { Object.assign(un, DIRT.u); dirtAsk(); }
  if (g.mask) tex(g.mask, false, 'grTex');
  if (g.colorMap) tex(g.colorMap, true, 'grCol');
  m.onBeforeCompile = (sh, r) => {
    if (prev) prev.call(m, sh, r);
    Object.assign(sh.uniforms, un);
    sh.vertexShader = 'varying vec3 vGrP;\nvarying vec3 vGrN;\nvarying vec3 vGrO;\n' + sh.vertexShader
      .replace('#include <beginnormal_vertex>', `#include <beginnormal_vertex>
#ifdef USE_INSTANCING
vGrN = mat3(modelMatrix) * mat3(instanceMatrix) * objectNormal;
#else
vGrN = mat3(modelMatrix) * objectNormal;
#endif`)
      .replace('#include <begin_vertex>', `#include <begin_vertex>
// (in the world, in metres, as Cycles since 1.69.1: models made in inches had their dirt far too small)
#ifdef USE_INSTANCING
vGrP = (modelMatrix * instanceMatrix * vec4(position, 1.0)).xyz;
vGrO = (modelMatrix * instanceMatrix * vec4(0.0, 0.0, 0.0, 1.0)).xyz;
#else
vGrP = (modelMatrix * vec4(position, 1.0)).xyz;
vGrO = modelMatrix[3].xyz;
#endif`);
    sh.fragmentShader = `uniform sampler2D grTex; uniform sampler2D grCol; uniform float grHasCol, grAmt, grOpa, grScale, grRough, grRand, grInv; uniform vec3 grSeed;
uniform vec3 grColor;
` + (g.paint ? `uniform sampler2D dpTex; uniform vec3 dpO; uniform float dpInv, dpTol, dpOn, dpN;
// the dirt painted by hand (dirtpaint.DirtGroup): map a seen along its axis, where the depth matches
float dpAxis(float a, float u, float v, float d) {
  if (u <= 0.0 || u >= 1.0 || v <= 0.0 || v >= 1.0) return 0.0;
  float amt = texture2D(dpTex, vec2(u, (a + v) / 3.0)).r;
  vec3 t = texelFetch(dpTex, ivec2(int(u * dpN), int((a + v) * dpN)), 0).rgb;
  float stored = t.g * (255.0 * 256.0 / 65535.0) + t.b * (255.0 / 65535.0);
  return abs(d - stored) < dpTol ? amt : 0.0;
}
` : '') + `
varying vec3 vGrP; varying vec3 vGrN; varying vec3 vGrO;
` + sh.fragmentShader
      .replace('#include <normal_fragment_begin>', `vec3 grQ = (vGrP + grRand * fract(vGrO * vec3(0.1031, 0.1030, 0.0973)) * 37.0 + grSeed) * grScale;   // (as Cycles)
vec3 grW = pow(abs(normalize(vGrN)), vec3(4.0)); grW /= max(1e-5, grW.x + grW.y + grW.z);
float grT = texture2D(grTex, vec2(grQ.y, -grQ.z)).r * grW.x + texture2D(grTex, vec2(grQ.x, -grQ.z)).r * grW.y + texture2D(grTex, vec2(grQ.x, -grQ.y)).r * grW.z;
if (grInv > 0.5) grT = 1.0 - grT;
float grPaint = 0.0;
${g.paint ? `if (dpOn > 0.5) { vec3 dc = (vGrP - dpO) * dpInv;
  grPaint = dpAxis(0.0, dc.y, dc.z, dc.x) * grW.x + dpAxis(1.0, dc.x, dc.z, dc.y) * grW.y + dpAxis(2.0, dc.x, dc.y, dc.z) * grW.z; }` : ''}
float grMask = clamp(grT * grAmt * 2.0 + grPaint, 0.0, 1.0) * grOpa;
vec3 grD = grColor;
if (grHasCol > 0.5) grD *= texture2D(grCol, vec2(grQ.y, -grQ.z)).rgb * grW.x + texture2D(grCol, vec2(grQ.x, -grQ.z)).rgb * grW.y + texture2D(grCol, vec2(grQ.x, -grQ.y)).rgb * grW.z;
diffuseColor.rgb = mix(diffuseColor.rgb, grD, grMask);
roughnessFactor = clamp(roughnessFactor + grMask * grRough, 0.0, 1.0);
#include <normal_fragment_begin>`);
  };
  m.customProgramCacheKey = () => 'gr1' + (g.paint ? 'p' : '') + (prevKey ? prevKey.call(m) : '');
}
function simplerMaterial(p, m) {
  const uv = p.uv || {};
  const maps = p.maps || {};
  const tri = (uv.mode || 'uv') !== 'uv';
  if (tri) useTriplanar(m, uv);
  else if (uv.antitile) useAntitileUV(m, uv);
  if (!tri && uv.perPiece) usePieceUV(m);
  // three.js needs a uv set to enable maps even with the triplanar projection (uv0 of the mesh)
  const assign = (slot, promise) => promise.then((tex) => { m[slot] = tex; m.needsUpdate = true; }).catch(() => {});
  if (maps.color) assign('map', loadImage(maps.color.image, maps.color.rev).then((img) => makeTexture(img, true, uv)));
  if (maps.roughness) { m.roughness = 1; assign('roughnessMap', loadImage(maps.roughness.image, maps.roughness.rev).then((img) => makeTexture(bakeScalar(img, maps.roughness, p.roughness ?? 0.5), false, uv, maps.roughness.scale))); }
  if (maps.metallic) { m.metalness = 1; assign('metalnessMap', loadImage(maps.metallic.image, maps.metallic.rev).then((img) => makeTexture(bakeScalar(img, maps.metallic, p.metallic ?? 0), false, uv, maps.metallic.scale))); }
  if (maps.normal && !tri) {
    const k = p.normalStrength ?? 1;
    m.normalScale = new THREE.Vector2(k, p.directx ? -k : k);
    assign('normalMap', loadImage(maps.normal.image, maps.normal.rev).then((img) => makeTexture(img, false, uv, maps.normal.scale)));
  }
  if (maps.bump && (p.bumpStrength || 0) > 0 && !tri) {
    m.bumpScale = p.bumpStrength * 2;
    assign('bumpMap', loadImage(maps.bump.image, maps.bump.rev).then((img) => makeTexture(bakeScalar(img, maps.bump, 0), false, uv, maps.bump.scale)));
  }
  if (maps.emission) assign('emissiveMap', loadImage(maps.emission.image, maps.emission.rev).then((img) => makeTexture(img, true, uv)));
  if (maps.alpha) {
    if (p.alphaCutout === false) { m.transparent = true; m.alphaTest = 0.01; m.depthWrite = false; }
    else { m.transparent = false; m.alphaTest = 0.5; }
    assign('alphaMap', loadImage(maps.alpha.image, maps.alpha.rev).then((img) => makeTexture(bakeScalar(img, maps.alpha, 1), false, uv)));
  }
  m.specularIntensity = Math.min(1, (p.specular ?? 0.5) * 2);
  m.clearcoatRoughness = p.coatRoughness ?? 0.03;
  if ((p.sheen || 0) > 0) {
    m.sheen = p.sheen; m.sheenRoughness = p.sheenRoughness ?? 0.5;
    const sc = p.sheenColor || [1, 1, 1]; m.sheenColor = new THREE.Color().setRGB(sc[0], sc[1], sc[2]);
  }
  if ((p.transmission || 0) > 0) {
    m.thickness = p.thin ? 0 : 0.02;
    if (p.dispersion) m.dispersion = 5;      // three.js has dispersion for transmission: a hint of the colours
  }
  if ((p.emissionStrength || 0) > 0) {
    const e = p.emission || [1, 1, 1], b = kelvinToRGB(p.kelvin || 6500);
    m.emissive = new THREE.Color().setRGB(e[0] * b.r, e[1] * b.g, e[2] * b.b);
    m.emissiveIntensity = p.emissionStrength;
  }
  if (p.macro && tri) useMacro(m, p.macro, uv);
  if (p.grunge && ((p.grunge.amount || 0) > 0 || p.grunge.paint) && (p.grunge.opacity ?? 1) > 0) useGrunge(m, p.grunge);
  if (p.blend && tri && (p.blend.partners || []).length && (p.blend.width || 0) > 0) useEdgeBlend(m, p.blend, uv);
  // (1.76.41: the relief of the rock alone, colours off - nothing to do in the view)
  if (p.reliefColor && p.reliefColor.image) useReliefColor(m, p.reliefColor);
  if (p.tone && (p.tone.streaks || p.tone.bands || p.tone.ridges || p.tone.wet)) useTone(m, p.tone);
  if (p.foliage) useFoliage(m, p.foliage);
  if (p.fabric) useFabric(m, p.fabric, uv, tri);
  if (p.interior && p.interior.image) useInterior(m, p.interior);
}
// «Interni» (1.79.0, Luca: «parallax room») in the view: as matedit.interior in Cycles - in the space of the object,
// the face along X or Y, the cell of the point, the ray from the eye into the box of the cell, the point it hits
// projected as the camera of the room's picture saw it; the room is light coming out of the glass.
const _inSc = new THREE.Vector3(), _inLo = new THREE.Vector3();
function useInterior(m, it) {
  const kc = kelvinToRGB(it.kelvin || 3000);
  const un = { inMap: { value: _grBlack }, inSize: { value: new THREE.Vector3(it.w || 4, it.h || 3, it.d || 4) },
               inBright: { value: it.bright ?? 0.4 }, inBack: { value: it.back || 0.5 }, inFlat: { value: it.flat || 0.7 },
               inNight: { value: it.night || 0 }, inShare: { value: it.share ?? 0.6 }, inKel: { value: new THREE.Vector3(kc.r, kc.g, kc.b) },
               inMin: { value: new THREE.Vector3() }, inScale: { value: new THREE.Vector3(1, 1, 1) }, inUp: { value: new THREE.Vector2(2, 1) }, inAtlas: { value: it.atlas ? 1 : 0 },
               inLay: { value: new THREE.Vector2(...(it.layers || [1 / 3, 2 / 3])) }, inEdge: { value: it.edge || 0.002 } };
  // (1.79.0) the rooms start from the lowest corner of each object (matedit.interior_pass): its box, per object drawn
  const prevBR = m.onBeforeRender;
  m.onBeforeRender = (_r, _s, _c, geo, ...rest) => {
    if (prevBR) prevBR.call(m, _r, _s, _c, geo, ...rest);
    if (!geo.boundingBox) geo.computeBoundingBox();
    // (Luca: «su un piano non si vede niente») up = the axis of the object nearest to the up of the scene, with its sign
    // (matedit.interior_pass); the floors from its lowest side
    const ob = rest[0];
    let up = 2, sg = 1;
    if (ob && ob.matrixWorld) {
      const e = ob.matrixWorld.elements;
      const zs = [0, 1, 2].map((i) => e[4 * i + 2] / Math.max(1e-9, Math.hypot(e[4 * i], e[4 * i + 1], e[4 * i + 2])));
      up = [0, 1, 2].reduce((a, i) => (Math.abs(zs[i]) > Math.abs(zs[a]) ? i : a), 0);
      sg = zs[up] >= 0 ? 1 : -1;
    }
    _inLo.copy(geo.boundingBox.min);
    if (sg < 0) _inLo.setComponent(up, geo.boundingBox.max.getComponent(up));
    if (!un.inMin.value.equals(_inLo)) { un.inMin.value.copy(_inLo); m.uniformsNeedUpdate = true; }
    if (un.inUp.value.x !== up || un.inUp.value.y !== sg) { un.inUp.value.set(up, sg); m.uniformsNeedUpdate = true; }
    // (Luca: «questi sono cubi molto grandi») the space of the object in metres of the scene: its scale
    // («Si adatta al modello»: the scale the object had when it was switched on - matedit.interior_pass - stays the one
    // of the rooms, so scaling it later stretches them)
    const ref = it.stretch && it.refs && ob && ob.userData ? it.refs[ob.userData.simpler_id] : null;
    if (ref) {
      _inSc.set(ref[0], ref[1], ref[2]);
      if (!un.inScale.value.equals(_inSc)) { un.inScale.value.copy(_inSc); m.uniformsNeedUpdate = true; }
    } else if (ob && ob.getWorldScale) {
      ob.getWorldScale(_inSc); _inSc.set(Math.max(Math.abs(_inSc.x), 1e-6), Math.max(Math.abs(_inSc.y), 1e-6), Math.max(Math.abs(_inSc.z), 1e-6));
      if (!un.inScale.value.equals(_inSc)) { un.inScale.value.copy(_inSc); m.uniformsNeedUpdate = true; }
    }
  };
  // (a room picture in the 3×3 cross: each wall a third of it - read bigger than the other maps)
  loadImage(it.image, it.rev, it.atlas ? 2048 : 0).then((img) => {
    const t = new THREE.Texture(img);
    t.flipY = true; t.colorSpace = THREE.SRGBColorSpace; t.wrapS = t.wrapT = THREE.ClampToEdgeWrapping; t.anisotropy = 8; t.needsUpdate = true;
    // (the wall read jumps from tile to tile: without mipmaps, or their choice draws lines at the corners of the room)
    if (it.atlas) { t.generateMipmaps = false; t.minFilter = THREE.LinearFilter; }
    un.inMap.value = t; invalidate();
  }).catch(() => {});
  const prev = m._ownCompile, prevKey = m._ownKey;
  m.onBeforeCompile = (sh, r) => {
    if (prev) prev.call(m, sh, r);
    Object.assign(sh.uniforms, un);
    sh.vertexShader = 'varying vec3 vInP;\nvarying vec3 vInN;\nvarying vec3 vInC;\n' + sh.vertexShader.replace('#include <begin_vertex>', `#include <begin_vertex>
vInP = transformed; vInN = objectNormal;
mat4 inMw = modelMatrix;
#ifdef USE_INSTANCING
inMw = modelMatrix * instanceMatrix;
#endif
vInC = (inverse(inMw) * vec4(cameraPosition, 1.0)).xyz;`);
    sh.fragmentShader = sh.fragmentShader.replace('void main() {', `uniform sampler2D inMap; uniform vec3 inSize; uniform float inBright, inBack, inFlat, inNight, inShare;
uniform vec3 inKel; uniform vec3 inMin; uniform vec3 inScale; uniform vec2 inUp; uniform float inAtlas, inEdge; uniform vec2 inLay;
varying vec3 vInP;
// a room picture in the 3×3 cross (matedit.INTERIOR_TILES): tile (column, row from the bottom) read at a, b
// the axes turned so that Z is the axis of the object that is up in the scene (as matedit.interior: right-handed)
vec3 inTurn(vec3 v) {
  if (inUp.x < 0.5) return vec3(v.y, v.z * inUp.y, v.x * inUp.y);
  if (inUp.x < 1.5) return vec3(v.z, v.x * inUp.y, v.y * inUp.y);
  return vec3(v.x, v.y * inUp.y, v.z * inUp.y);
}
vec4 inTile(vec2 cr, vec2 ab) { return texture2D(inMap, (cr + clamp(ab, inEdge, 1.0 - inEdge)) / 3.0); }
vec3 inRoom(vec3 h, vec2 f, vec3 d, float tx, float ty, float tz, float t) {
  float hz = clamp(h.z, 0.0, 1.0);
  vec4 c;
  if (tz < min(tx, ty)) c = inTile(vec2(1.0, 1.0), h.xy);
  else if (tx < ty) c = d.x > 0.0 ? inTile(vec2(2.0, 1.0), vec2(1.0 - hz, h.y)) : inTile(vec2(0.0, 1.0), vec2(hz, h.y));
  else c = d.y > 0.0 ? inTile(vec2(1.0, 2.0), vec2(h.x, 1.0 - hz)) : inTile(vec2(1.0, 0.0), vec2(h.x, hz));
  vec3 col = c.rgb;
  // the two rows of furniture (behind, then front) and the frame of the window, by their transparency
  for (int i = 1; i >= 0; i--) {
    float k = i == 1 ? inLay.y : inLay.x, tk = k / d.z;
    vec2 l = f + d.xy * tk;
    if (tk < t && l.x > 0.0 && l.x < 1.0 && l.y > 0.0 && l.y < 1.0) {
      vec4 lc = inTile(i == 1 ? vec2(0.0, 0.0) : vec2(2.0, 0.0), l);
      col = mix(col, lc.rgb, lc.a);
    }
  }
  vec4 fr = inTile(vec2(0.0, 2.0), f);
  return mix(col, fr.rgb, fr.a);
} varying vec3 vInN; varying vec3 vInC;
// the white noise of Cycles (hash_float3_to_float, Jenkins lookup3): the same rooms lit in the view and in the render
uint inRot(uint x, int k) { return (x << k) | (x >> (32 - k)); }
float inHash(vec3 v) {
  uint a = 0xdeadbeefu + 25u, b = a, c = a;
  c += floatBitsToUint(v.z); b += floatBitsToUint(v.y); a += floatBitsToUint(v.x);
  c ^= b; c -= inRot(b, 14); a ^= c; a -= inRot(c, 11); b ^= a; b -= inRot(a, 25); c ^= b; c -= inRot(b, 16);
  a ^= c; a -= inRot(c, 4); b ^= a; b -= inRot(a, 14); c ^= b; c -= inRot(b, 24);
  return float(c) / 4294967295.0;
}
void main() {`).replace('#include <emissivemap_fragment>', `#include <emissivemap_fragment>
{
  vec3 N = inTurn(normalize(vInN / inScale)), R = inTurn(normalize((vInP - vInC) * inScale)), P = inTurn((vInP - inMin) * inScale);
  if (abs(N.z) < inFlat) {
    bool ux = abs(N.x) > abs(N.y);
    float sx = sign(N.x), sy = sign(N.y);
    float u = ux ? P.y * sx : -P.x * sy;
    float ru = ux ? R.y * sx : -R.x * sy;
    float rw = ux ? -R.x * sx : -R.y * sy;
    vec2 cuv = vec2(u / inSize.x, P.z / inSize.y);
    vec2 f = fract(cuv);
    vec3 d = vec3(ru / inSize.x + 1e-6, R.z / inSize.y + 1e-6, max(rw / inSize.z, 1e-4));
    float tx = ((d.x > 0.0 ? 1.0 : 0.0) - f.x) / d.x, ty = ((d.y > 0.0 ? 1.0 : 0.0) - f.y) / d.y, tz = 1.0 / d.z;
    float t = min(min(tx, ty), tz);
    vec3 h = vec3(f, 0.0) + d * t;
    float s = 1.0 / (1.0 + h.z * (1.0 / inBack - 1.0));
    vec2 iuv = 0.5 + (h.xy - 0.5) * s;
    vec3 room = inAtlas > 0.5 ? inRoom(h, f, d, tx, ty, tz, t) : texture2D(inMap, iuv).rgb;
    float lit = inNight > 0.0 && inHash(vec3(floor(cuv), (ux ? 2.0 : 0.0) + (ux ? sx : sy))) < inShare ? inNight : 0.0;
    totalEmissiveRadiance += room * (vec3(inBright) + inKel * lit);
  }
}`);
  };
  m.customProgramCacheKey = () => 'in5' + (prevKey ? prevKey.call(m) : '');
}
// «Tessuto» (1.77.1) in the view: as matedit.fabric_color in Cycles - the fuzz only where its mask is white (three's
// sheenColorMap), the tint laid by its mask (on the colour map's coordinates), a thin cloth seen through and more
// opaque edge on, the sun through it as for the leaves.
function useFabric(m, f, uv, tri) {
  if (f.fuzzMask && (m.sheen || 0) > 0) {
    loadImage(f.fuzzMask.image, f.fuzzMask.rev).then((img) => { m.sheenColorMap = makeTexture(bakeScalar(img, f.fuzzMask, 1), false, uv, f.fuzzMask.scale); m.needsUpdate = true; invalidate(); }).catch(() => {});
  }
  const un = { faSee: { value: f.thin ? (f.see ?? 0.6) : 0 }, faEdge: { value: f.edge ?? 0.6 }, faTr: { value: f.thin ? (f.light ?? 0.5) : 0 },
               faTint: { value: _grBlack }, faHasT: { value: 0 }, faTintCol: { value: new THREE.Vector3(...(f.tint || [1, 1, 1])) } };
  if (f.tintMask && !tri) {
    loadImage(f.tintMask.image, f.tintMask.rev).then((img) => { un.faTint.value = makeTexture(bakeScalar(img, f.tintMask, 1), false, uv, f.tintMask.scale); un.faHasT.value = 1; invalidate(); }).catch(() => {});
  }
  if (f.thin) { m.transparent = true; m.depthWrite = false; if (m.alphaTest > 0) m.alphaTest = 0.01; }
  const prev = m._ownCompile, prevKey = m._ownKey;
  m.onBeforeCompile = (sh, r) => {
    if (prev) prev.call(m, sh, r);
    Object.assign(sh.uniforms, un);
    sh.fragmentShader = sh.fragmentShader.replace('void main() {', `uniform float faSee, faEdge, faTr, faHasT; uniform sampler2D faTint; uniform vec3 faTintCol;
void main() {`).replace('#include <normal_fragment_maps>', `#include <normal_fragment_maps>
#if defined( USE_MAP )
if (faHasT > 0.5) { float tm = texture2D(faTint, vMapUv).g; diffuseColor.rgb = mix(diffuseColor.rgb, diffuseColor.rgb * faTintCol, tm); }
#endif
if (faSee > 0.0) { float faF = 1.0 - abs(dot(normalize(normal), normalize(vViewPosition)));
  diffuseColor.a *= clamp(1.0 - faSee * (1.0 - faEdge * faF), 0.0, 1.0); }`).replace('#include <lights_fragment_end>', `#include <lights_fragment_end>
#if NUM_DIR_LIGHTS > 0
if (faTr > 0.0) { float faBl = max(dot(-normal, directionalLights[0].direction), 0.0);
  reflectedLight.directDiffuse += diffuseColor.rgb * directionalLights[0].color * faBl * faTr * 0.5; }
#endif`);
  };
  m.customProgramCacheKey = () => 'fa1' + (prevKey ? prevKey.call(m) : '');
}
// «Fogliame» (1.77.0) in the view: as matedit.foliage_color in Cycles - variation per plant and per leaf, the season
// (each leaf its own moment: a slow noise over the plant, the leaf's random, the plant's random; gold or red ramp;
// gone past «drop»), the back of the leaf lighter, the sun through the leaf. The leaf here is a cell of 7 cm of the
// plant (Cycles: each separate piece): the same character, not the same leaves. «Scuro all'interno»: path tracing only.
// The leaves gone cast no shadow either (foliageShadows: a depth material of their own, the same test).
const FOL_GLSL = `
float foHash(vec3 p) { p = fract(p * 0.3183099 + vec3(0.71, 0.113, 0.419)); p *= 17.0; return fract(p.x * p.y * p.z * (p.x + p.y + p.z)); }
float foNoise(vec3 x) { vec3 i = floor(x); vec3 f = fract(x); f = f * f * (3.0 - 2.0 * f);
  return mix(mix(mix(foHash(i), foHash(i + vec3(1, 0, 0)), f.x), mix(foHash(i + vec3(0, 1, 0)), foHash(i + vec3(1, 1, 0)), f.x), f.y),
             mix(mix(foHash(i + vec3(0, 0, 1)), foHash(i + vec3(1, 0, 1)), f.x), mix(foHash(i + vec3(0, 1, 1)), foHash(i + vec3(1, 1, 1)), f.x), f.y), f.z); }
uniform float foSeason, foVar, foRed, foDrop, foNoiseK, foSpread, foStart, foLife, foStretch, foLeaf;
varying vec3 vFoL; varying vec3 vFoO; varying float vFoS;
// (1.79.0) the season of this copy: its own (a scatter with a season per model, foSea = 1 + season) or the material's
float foS() { return (vFoS >= 0.0 && foLeaf > 0.5) ? vFoS : foSeason; }
// the phase of this leaf in the season (-1: no season)
float foPhase(out float rL, out float rO) {
  rL = foHash(floor(vFoL / 0.07) + vFoO * 1.37);
  rO = foHash(floor(vFoO * 3.1) + 0.5);
  float S = foS();
  if (S <= 0.0) return -1.0;
  float n = foNoise(vFoL * foNoiseK + rO * 31.0);
  float e = clamp((n * 0.5 + rL * 0.35 + rO * 0.15 - 0.5) * foStretch + 0.5, 0.0, 1.0);
  if (S >= 0.999) return 1.0;
  return clamp((S - foStart - foSpread * e) / foLife, 0.0, 1.0);
}
`;
const FOL_VERT = `
vec4 foO4 = vec4(0.0, 0.0, 0.0, 1.0);
vec4 foP4 = vec4(transformed, 1.0);
#ifdef USE_INSTANCING
foO4 = instanceMatrix * foO4; foP4 = instanceMatrix * foP4;
#endif
foO4 = modelMatrix * foO4; foP4 = modelMatrix * foP4;
vFoO = foO4.xyz; vFoL = foP4.xyz - foO4.xyz;
#ifdef USE_INSTANCING
vFoS = foSea - 1.0;
#else
vFoS = -1.0;
#endif`;
const FOL_VDECL = 'varying vec3 vFoL;\nvarying vec3 vFoO;\nvarying float vFoS;\n#ifdef USE_INSTANCING\nattribute float foSea;\n#endif\n';
function _folRamp(name, pts) {
  // a ramp as a GLSL function: t → (0.5 + hue shift, saturation / 2, value / 2), linear between the points
  let code = `vec3 ${name}(float t) {\n`;
  for (let i = 1; i < pts.length; i++) {
    const a = pts[i - 1], b = pts[i];
    const f = (v) => Number(v).toFixed(5);
    code += `  if (t <= ${f(b[0])}) return mix(vec3(${f(0.5 + a[1])}, ${f(a[2] / 2)}, ${f(a[3] / 2)}), vec3(${f(0.5 + b[1])}, ${f(b[2] / 2)}, ${f(b[3] / 2)}), clamp((t - ${f(a[0])}) / ${f(Math.max(1e-4, b[0] - a[0]))}, 0.0, 1.0));\n`;
  }
  const z = pts[pts.length - 1];
  return code + `  return vec3(${(0.5 + z[1]).toFixed(5)}, ${(z[2] / 2).toFixed(5)}, ${(z[3] / 2).toFixed(5)});\n}\n`;
}
function _folUniforms(f) {
  return { foSeason: { value: f.season || 0 }, foVar: { value: f.variation ?? 0.3 }, foRed: { value: f.red ?? 0.5 },
           foDrop: { value: f.drop ?? 0.86 }, foNoiseK: { value: 1 / Math.max(0.1, f.noiseM || 1.2) }, foSpread: { value: f.spread ?? 0.5 },
           foStart: { value: f.start ?? 0.1 }, foLife: { value: f.life ?? 0.45 }, foStretch: { value: f.stretch ?? 2.2 },
           foBack: { value: f.back || 0 }, foTr: { value: f.translucency || 0 }, foLeaf: { value: f.leaves === false ? 0 : 1 } };
}
function useFoliage(m, f) {
  const prev = m._ownCompile, prevKey = m._ownKey;
  const un = _folUniforms(f);
  const ramps = (f.ramps && f.ramps.gold && f.ramps.red) ? f.ramps : null;
  const rampCode = ramps ? _folRamp('foRampG', ramps.gold) + _folRamp('foRampR', ramps.red) : '';
  m.side = THREE.DoubleSide;
  m.userData.foliage = un;
  if ((f.season || 0) > 0) { FOL.mats.add(m); FOL.dirty = true; }
  m.onBeforeCompile = (sh, r) => {
    if (prev) prev.call(m, sh, r);
    Object.assign(sh.uniforms, un);
    sh.vertexShader = FOL_VDECL + sh.vertexShader.replace('#include <begin_vertex>', '#include <begin_vertex>' + FOL_VERT);
    sh.fragmentShader = sh.fragmentShader.replace('void main() {', FOL_GLSL + rampCode + `uniform float foBack, foTr;
vec3 foRgb2Hsv(vec3 c) { vec4 K = vec4(0.0, -1.0 / 3.0, 2.0 / 3.0, -1.0); vec4 p = mix(vec4(c.bg, K.wz), vec4(c.gb, K.xy), step(c.b, c.g));
  vec4 q = mix(vec4(p.xyw, c.r), vec4(c.r, p.yzx), step(p.x, c.r)); float d = q.x - min(q.w, q.y); float e = 1.0e-10;
  return vec3(abs(q.z + (q.w - q.y) / (6.0 * d + e)), d / (q.x + e), q.x); }
vec3 foHsv2Rgb(vec3 c) { vec4 K = vec4(1.0, 2.0 / 3.0, 1.0 / 3.0, 3.0); vec3 p = abs(fract(c.xxx + K.xyz) * 6.0 - K.www);
  return c.z * mix(K.xxx, clamp(p - K.xxx, 0.0, 1.0), c.y); }
void main() {`).replace('#include <normal_fragment_begin>', `{
  float rL, rO; float t = foPhase(rL, rO);
  float rL2 = fract(rL * 7.31 + 0.13), rL3 = fract(rL * 3.77 + 0.61), rO2 = fract(rO * 5.17 + 0.29);
  float hue = 0.5 + (rO - 0.5) * 0.04 * foVar + (rL3 - 0.5) * 0.012 * foVar;
  float val = 1.0 + (rO2 - 0.5) * 0.25 * foVar + (rL - 0.5) * 0.2 * foVar;
  float sat = 1.0;
  ${ramps ? `if (t >= 0.0) {
    if (t >= foDrop) discard;
    float pick = clamp((foRed - (rO * 0.75 + rL2 * 0.25)) * 10.0 + 0.5, 0.0, 1.0);
    vec3 rg = mix(foRampG(t), foRampR(t), pick);
    float S = foS(), sq = sqrt(S);
    hue = hue - 0.5 + rg.x + (rL3 - 0.5) * 0.03 * sq;
    sat = rg.y * 2.0;
    val *= rg.z * (2.0 + 0.24 * S * rL2 - 0.12 * S);
  }` : ''}
  vec3 hsv = foRgb2Hsv(max(diffuseColor.rgb, vec3(0.0)));
  hsv.x = fract(hsv.x + hue - 0.5); hsv.y = clamp(hsv.y * sat, 0.0, 1.0); hsv.z *= val;
  diffuseColor.rgb = foHsv2Rgb(hsv);
  if (!gl_FrontFacing) diffuseColor.rgb = mix(diffuseColor.rgb, diffuseColor.rgb * vec3(1.35, 1.38, 1.15), foBack);
}
#include <normal_fragment_begin>`).replace('#include <lights_fragment_end>', `#include <lights_fragment_end>
#if NUM_DIR_LIGHTS > 0
if (foTr > 0.0) { float foBl = max(dot(-normal, directionalLights[0].direction), 0.0);
  reflectedLight.directDiffuse += diffuseColor.rgb * directionalLights[0].color * foBl * foTr * 0.5; }
#endif`);
  };
  m.customProgramCacheKey = () => 'fo2' + (ramps ? 'r' : '') + (prevKey ? prevKey.call(m) : '');
}
// the shadows of the leaves gone: meshes with a foliage material in season get a depth material of their own that
// throws away the same leaves (set again for each part of a mesh: leaves and bark in one mesh). Only while some
// foliage material has a season: otherwise nothing is looked at.
function _folDepth() {
  const d = new THREE.MeshDepthMaterial({ depthPacking: THREE.RGBADepthPacking });
  const un = Object.assign(_folUniforms({}), { foOn: { value: 0 } });
  d.userData.un = un;
  d.onBeforeCompile = (sh) => {
    Object.assign(sh.uniforms, un);
    sh.vertexShader = FOL_VDECL + sh.vertexShader.replace('#include <begin_vertex>', '#include <begin_vertex>' + FOL_VERT);
    sh.fragmentShader = sh.fragmentShader.replace('void main() {', FOL_GLSL + 'uniform float foOn;\nvoid main() {')
      .replace('#include <alphatest_fragment>', `#include <alphatest_fragment>
if (foOn > 0.5) { float rL, rO; float t = foPhase(rL, rO); if (t >= foDrop) discard; }`);
  };
  d.customProgramCacheKey = () => 'fod2';
  return d;
}
function _folBeforeShadow(_r, obj, _c, _sc, _g, dm, group) {
  const un = dm.userData && dm.userData.un;
  if (!un) return;
  const mm = Array.isArray(obj.material) ? obj.material[group ? group.materialIndex : 0] : obj.material;
  const f = mm && mm.userData.foliage;
  un.foOn.value = f ? 1 : 0;
  if (f) for (const k of ['foSeason', 'foDrop', 'foNoiseK', 'foSpread', 'foStart', 'foLife', 'foStretch', 'foLeaf']) un[k].value = f[k].value;
  const a = !!dm.alphaMap;
  if (dm.userData.lastA !== a) { dm.userData.lastA = a; dm.needsUpdate = true; }
  dm.uniformsNeedUpdate = true;
}
function foliageShadows() {
  if (!FOL.dirty) return;
  FOL.dirty = false;
  for (const m of [...FOL.mats]) if (!(m.userData.foliage && (m.userData.foliage.foSeason.value > 0 || m.userData.foInst))) FOL.mats.delete(m);
  const noop = THREE.Object3D.prototype.onBeforeShadow;
  scene.traverse((o) => {
    if (!o.isMesh) return;
    const mats = Array.isArray(o.material) ? o.material : [o.material];
    const any = FOL.mats.size > 0 && mats.some((mm) => mm && FOL.mats.has(mm));
    if (any && !o.userData.foDepth) { o.customDepthMaterial = _folDepth(); o.onBeforeShadow = _folBeforeShadow; o.userData.foDepth = true; }
    else if (!any && o.userData.foDepth) { o.customDepthMaterial = undefined; o.onBeforeShadow = noop; o.userData.foDepth = false; }
  });
}
// «Colori dal terreno» (1.76.14) in the view: as matedit tone_color in Cycles - the colour of a terrain zone guided by
// the shape of the land: per point of the mesh (terrain._tone_data: crest 0..1, water, layer of
// the rock; the UV maps texcoord_4 and texcoord_5) crests lighter and gullies darker, darker where water gathers, bands of the rock layers on its walls,
// dark streaks down the steep faces. After the blend of the borders: the same factor on both sides. Its noises are
// not Cycles' noises: the same character, not the same shapes. A mesh without the data (made before): nothing.
// (1.76.58) the colour map of «Rilievo 3D» in the view: as matedit relief_color - on the walls «Dove» picks, from
// three sides in world metres (Grandezza, Rotazione in the plane of each side), × «Colore dalla mappa»; before the
// colours from the land. («Rompi la ripetizione» is the path tracing's only.)
function useReliefColor(m, rc) {
  const prev = m._ownCompile, prevKey = m._ownKey;
  const w = rc.where ?? 0.5;
  const un = { rcTex: { value: _grBlack }, rcHas: { value: 0 }, rcAmt: { value: rc.amount ?? 1 },
               rcK: { value: 1 / Math.max(0.5, rc.sizeM || 10) }, rcRot: { value: rc.rot || 0 },
               rcLo: { value: Math.min(0.75 + 0.3 * w, 0.99) }, rcHi: { value: 0.45 + 0.3 * w } };
  loadImage(rc.image).then((img) => {
    const t = new THREE.Texture(img);
    t.wrapS = t.wrapT = THREE.RepeatWrapping; t.anisotropy = 8; t.colorSpace = THREE.SRGBColorSpace; t.flipY = false;
    t.needsUpdate = true;
    un.rcTex.value = t; un.rcHas.value = 1;
    invalidate();
  }).catch(() => {});
  m.onBeforeCompile = (sh, r) => {
    if (prev) prev.call(m, sh, r);
    Object.assign(sh.uniforms, un);
    sh.vertexShader = 'varying vec3 vRcP;\nvarying vec3 vRcN;\n' + sh.vertexShader.replace('#include <begin_vertex>',
      '#include <begin_vertex>\nvRcP = (modelMatrix * vec4(position, 1.0)).xyz; vRcN = normalize(mat3(modelMatrix) * normal);');
    const helpers = `uniform sampler2D rcTex; uniform float rcHas, rcAmt, rcK, rcRot, rcLo, rcHi;
varying vec3 vRcP; varying vec3 vRcN;
vec3 rcFace(vec2 q) { float c = cos(rcRot), s = sin(rcRot); q *= rcK; return texture2D(rcTex, vec2(c * q.x - s * q.y, s * q.x + c * q.y)).rgb; }
`;
    sh.fragmentShader = sh.fragmentShader.replace('void main() {', helpers + 'void main() {').replace('#include <normal_fragment_begin>', `if (rcHas > 0.5) {
  vec3 rn = normalize(vRcN);
  float rmask = clamp((rn.z - rcLo) / (rcHi - rcLo), 0.0, 1.0) * rcAmt;
  if (rmask > 0.0) {
    vec3 wt = pow(abs(rn), vec3(4.0)); wt /= (wt.x + wt.y + wt.z + 1e-5);
    vec3 col = rcFace(vRcP.yz) * wt.x + rcFace(vRcP.xz) * wt.y + rcFace(vRcP.xy) * wt.z;
    diffuseColor.rgb = mix(diffuseColor.rgb, col, rmask);
  }
}
#include <normal_fragment_begin>`);
  };
  m.customProgramCacheKey = () => 'rc1' + (prevKey ? prevKey.call(m) : '');
}
function useTone(m, t) {
  const prev = m._ownCompile, prevKey = m._ownKey;
  const un = { tnK: { value: new THREE.Vector4(t.streaks || 0, t.bands || 0, t.ridges || 0, t.wet || 0) } };
  m.onBeforeCompile = (sh, r) => {
    if (prev) prev.call(m, sh, r);
    Object.assign(sh.uniforms, un);
    // (the data: the zone mesh's 5th and 6th UV maps; the glTF exporter writes v as 1 - v: the water + 2 comes back
    // as -(water + 1), 0 where the mesh has none)
    sh.vertexShader = 'attribute vec2 texcoord_4;\nattribute vec2 texcoord_5;\nvarying vec3 vTnC;\nvarying vec3 vTnP;\nvarying vec3 vTnN;\n' + sh.vertexShader.replace('#include <begin_vertex>',
      '#include <begin_vertex>\nvTnC = vec3(texcoord_4.x, -texcoord_4.y, texcoord_5.x); vTnP = (modelMatrix * vec4(position, 1.0)).xyz; vTnN = normalize(mat3(modelMatrix) * normal);');
    const helpers = `uniform vec4 tnK;
varying vec3 vTnC; varying vec3 vTnP; varying vec3 vTnN;
float tnH(vec3 p) { p = fract(p * 0.1031); p += dot(p, p.zyx + 31.32); return fract((p.x + p.y) * p.z); }
float tnV(vec3 p) {
  vec3 i = floor(p), f = fract(p); f = f * f * (3.0 - 2.0 * f);
  return mix(mix(mix(tnH(i), tnH(i + vec3(1, 0, 0)), f.x), mix(tnH(i + vec3(0, 1, 0)), tnH(i + vec3(1, 1, 0)), f.x), f.y),
             mix(mix(tnH(i + vec3(0, 0, 1)), tnH(i + vec3(1, 0, 1)), f.x), mix(tnH(i + vec3(0, 1, 1)), tnH(i + vec3(1, 1, 1)), f.x), f.y), f.z);
}
float tnN2(vec3 p) { return 0.65 * tnV(p) + 0.35 * tnV(p * 2.03 + 7.1); }
`;
    sh.fragmentShader = sh.fragmentShader.replace('void main() {', helpers + 'void main() {').replace('#include <normal_fragment_begin>', `if (vTnC.y > 0.5) {
  vec3 tn = normalize(vTnN);
  float steep = clamp((0.85 - tn.z) / 0.30, 0.0, 1.0);
  float wet = max(vTnC.y - 1.0, 0.0);      // (-(1 - (water + 2)) = water + 1)
  float val = (1.0 + 1.2 * tnK.z * (vTnC.x - 0.5)) * (1.0 - 0.45 * tnK.w * wet);
  float warm = 0.0;
  if (tnK.y > 0.0) {
    float b1 = (tnV(vec3(vTnC.z, 0.37, 0.71)) - 0.5) * 2.0;
    float b2 = (tnV(vec3(vTnC.z * 5.0, 0.91, 0.13)) - 0.5) * 2.0;
    warm = 0.6 * tnK.y * b1 * steep;
    val *= 1.0 + 0.2 * tnK.y * b2 * steep;
  }
  if (tnK.x > 0.0) {
    float ax = pow(abs(tn.x), 4.0), ay = pow(abs(tn.y), 4.0), wx = ax / (ax + ay + 1e-4);
    float sn = tnN2(vec3(vTnP.y / 0.8, vTnP.z / 9.0, 3.3)) * wx + tnN2(vec3(vTnP.x / 0.8, vTnP.z / 9.0, 8.9)) * (1.0 - wx);
    // (1.76.43) in groups, more in the gullies (as matedit _wall_groups): not a comb over the whole wall
    float grp = smoothstep(0.44, 0.6, tnV(vec3(vTnP.x / 10.0, vTnP.y / 10.0, vTnP.z / 25.0))) * mix(0.2, 1.0, clamp((0.7 - vTnC.x) / 0.4, 0.0, 1.0));
    val *= 1.0 - 0.45 * tnK.x * steep * grp * clamp((sn - 0.52) / 0.16, 0.0, 1.0);
  }
  diffuseColor.rgb *= val * vec3(1.0 + warm, 1.0 + 0.7 * warm, 1.0 + 0.4 * warm);
}
#include <normal_fragment_begin>`);
  };
  m.customProgramCacheKey = () => 'tn2' + (prevKey ? prevKey.call(m) : '');
}
// «Variazione su grande scala» (1.76.6) in the view: as matedit macro_color in Cycles - the big picture with its own
// box projection (its size in metres), its pattern (picture / its mean) multiplying the colour (strength), its colour
// taking over with «colour» (the detail keeping its grain: detail / its mean), and a slow change of brightness and
// saturation (tone). The macro normal map is the path tracing's only (as every normal map of a box projection here).
function useMacro(m, mc, ownUv) {
  const prev = m._ownCompile, prevKey = m._ownKey;
  const at = !!ownUv.antitile;
  const k = 100 / Math.max(10, mc.sizeCm || 2000);
  const un = {
    mcTex: { value: _grBlack }, mcHas: { value: 0 }, mcK: { value: k }, mcStr: { value: mc.strength || 0 },
    mcCol: { value: mc.colour || 0 }, mcMean: { value: new THREE.Vector3(...(mc.mean || [0.5, 0.5, 0.5]).map((v) => Math.max(1e-3, v))) },
    mcDMean: { value: new THREE.Vector3(...(mc.detailMean || [0.5, 0.5, 0.5]).map((v) => Math.max(1e-3, v))) },
    mcTone: { value: mc.tone || 0 }, mcToneK: { value: 1 / Math.max(1, mc.toneSizeM || 30) },
  };
  if (mc.image) loadImage(mc.image).then((img) => {
    const t = new THREE.Texture(img);
    t.flipY = false; t.wrapS = t.wrapT = THREE.RepeatWrapping; t.anisotropy = 8; t.colorSpace = THREE.SRGBColorSpace;
    t.needsUpdate = true; un.mcTex.value = t; un.mcHas.value = 1; invalidate();
  }).catch(() => {});
  m.onBeforeCompile = (sh, r) => {
    if (prev) prev.call(m, sh, r);
    Object.assign(sh.uniforms, un);
    sh.vertexShader = 'varying vec3 vMcP;\nvarying vec3 vMcN;\n' + sh.vertexShader.replace('#include <begin_vertex>',
      '#include <begin_vertex>\nvMcP = position * vec3(length(modelMatrix[0].xyz), length(modelMatrix[1].xyz), length(modelMatrix[2].xyz)); vMcN = normal;');
    const helpers = `uniform sampler2D mcTex; uniform float mcHas, mcK, mcStr, mcCol, mcTone, mcToneK; uniform vec3 mcMean, mcDMean;
varying vec3 vMcP; varying vec3 vMcN;
float mcH(vec3 p) { p = fract(p * 0.1031); p += dot(p, p.zyx + 31.32); return fract((p.x + p.y) * p.z); }
float mcV(vec3 p) {
  vec3 i = floor(p), f = fract(p); f = f * f * (3.0 - 2.0 * f);
  return mix(mix(mix(mcH(i), mcH(i + vec3(1, 0, 0)), f.x), mix(mcH(i + vec3(0, 1, 0)), mcH(i + vec3(1, 1, 0)), f.x), f.y),
             mix(mix(mcH(i + vec3(0, 0, 1)), mcH(i + vec3(1, 0, 1)), f.x), mix(mcH(i + vec3(0, 1, 1)), mcH(i + vec3(1, 1, 1)), f.x), f.y), f.z);
}
float mcNoise(vec3 p) { float a = 0.5, s = 0.0, t = 0.0; for (int o = 0; o < 3; o++) { s += a * mcV(p); t += a; p *= 2.0; a *= 0.5; } return s / t; }
vec3 mcBox() {
  vec3 n = normalize(vMcN);
  vec3 w = pow(abs(n), vec3(5.0)); w /= (w.x + w.y + w.z + 1e-5);
  vec3 q = vMcP * mcK;
  vec2 ux = vec2(n.x < 0.0 ? -q.y : q.y, -q.z), uy = vec2(n.y > 0.0 ? -q.x : q.x, -q.z), uz = vec2(n.z > 0.0 ? -q.y : q.y, -q.x);
${at ? '  return atTex(mcTex, ux).rgb * w.x + atTex(mcTex, uy).rgb * w.y + atTex(mcTex, uz).rgb * w.z;' : '  return texture2D(mcTex, ux).rgb * w.x + texture2D(mcTex, uy).rgb * w.y + texture2D(mcTex, uz).rgb * w.z;'}
}
`;
    sh.fragmentShader = sh.fragmentShader.replace('void main() {', helpers + 'void main() {').replace('#include <normal_fragment_begin>', `{
  if (mcHas > 0.5 && mcStr > 0.0) {
    vec3 M = mcBox();
    vec3 D = diffuseColor.rgb;
    vec3 P = D * mix(vec3(1.0), M / mcMean, mcStr);
    diffuseColor.rgb = mix(P, M * (D / mcDMean), mcCol);
  }
  if (mcTone > 0.0) {
    float n1 = mcNoise(vMcP * mcToneK), n2 = mcNoise(vMcP * mcToneK + 17.3);
    vec3 c = diffuseColor.rgb * (1.0 - 0.7 * mcTone + 1.4 * mcTone * n1);
    float l = dot(c, vec3(0.2126, 0.7152, 0.0722));
    diffuseColor.rgb = max(vec3(0.0), mix(vec3(l), c, 1.0 - 0.3 * mcTone + 0.6 * mcTone * n2));
  }
}
#include <normal_fragment_begin>`);
  };
  m.customProgramCacheKey = () => 'mc1' + (at ? 'a' : '') + (prevKey ? prevKey.call(m) : '');
}
// «Sfumatura dei bordi» of the terrain (1.76.4) in the view: as matedit edge_blend in Cycles - near the border with
// another zone (its distance: the UV maps uv1..uv3 of the zone's mesh, stored + 1) the colour and the roughness of
// that zone come in where its texture is lighter (stones out of the grass) and a noise breaks the line; the two sides
// use the same numbers with opposite sign, so they meet without a line. The colour of the partner is sampled with its
// own box projection; its relief and normal map are the path tracing's only. The noise is not Cycles' noise: the same
// character, not the same shapes.
// (1.76.56) how much a texture's brightness leads the border blend: 1 up to 10 m, less for a photo of a whole cliff
function ebLumW(uv) {
  if (!uv || (uv.mode || 'uv') === 'uv') return 1;
  return Math.min(1, 10 / Math.max(0.01, (uv.sizeCm || 100) / 100));
}
function useEdgeBlend(m, b, ownUv) {
  const prev = m._ownCompile, prevKey = m._ownKey;
  const parts = b.partners.slice(0, 5);
  const at = !!ownUv.antitile;
  const un = { ebW: { value: Math.max(0.05, b.width) }, ebIrr: { value: Math.max(0, Math.min(1, b.irregular ?? 0.6)) },
              ebLwA: { value: ebLumW(ownUv) } };
  parts.forEach((q, i) => {
    const pj = q.proj || {}, k = 100 / Math.max(0.1, pj.sizeCm || 100), st = pj.stretch || [1, 1], off = pj.offset || [0, 0];
    un['ebTex' + i] = { value: _grBlack };
    un['ebHas' + i] = { value: 0 };
    un['ebCol' + i] = { value: new THREE.Vector3(...(q.color || [0.5, 0.5, 0.5])) };
    un['ebRough' + i] = { value: q.roughness ?? 0.8 };
    un['ebW' + i] = { value: Math.max(0.05, q.width || b.width) };      // (1.76.12: the snow, wider)
    un['ebLw' + i] = { value: ebLumW(pj) };                               // (1.76.56: matedit.blend_lum_weight)
    un['ebK' + i] = { value: new THREE.Vector3(k * st[0], k * st[1], k) };
    un['ebRot' + i] = { value: (pj.rotation || 0) * Math.PI / 180 };
    un['ebOff' + i] = { value: new THREE.Vector3(off[0] || 0, off[1] || 0, off[2] || 0) };
    if (q.map) loadImage(q.map).then((img) => {
      const t = new THREE.Texture(img);
      t.flipY = false; t.wrapS = t.wrapT = THREE.RepeatWrapping; t.anisotropy = 8; t.colorSpace = THREE.SRGBColorSpace;
      t.needsUpdate = true;
      un['ebTex' + i].value = t; un['ebHas' + i].value = 1;
      invalidate();
    }).catch(() => {});
  });
  const slots = [...new Set(parts.map((q) => q.uv))];
  m.onBeforeCompile = (sh, r) => {
    if (prev) prev.call(m, sh, r);
    Object.assign(sh.uniforms, un);
    sh.vertexShader = slots.map((u) => `attribute vec2 ${u};\nvarying vec2 vEb_${u};\n`).join('') + 'varying vec3 vEbP;\nvarying vec3 vEbN;\n' + sh.vertexShader
      .replace('#include <begin_vertex>', `#include <begin_vertex>
vEbP = (modelMatrix * vec4(position, 1.0)).xyz; vEbN = normalize(mat3(modelMatrix) * normal);
${slots.map((u) => `vEb_${u} = ${u};`).join(' ')}`);
    const decl = parts.map((q, i) => `uniform sampler2D ebTex${i}; uniform float ebHas${i}, ebRough${i}, ebRot${i}, ebW${i}, ebLw${i}; uniform vec3 ebCol${i}, ebK${i}, ebOff${i};`).join('\n');
    const body = parts.map((q, i) => {
      const at2 = at && q.proj && q.proj.antitile;
      // (the glTF exporter writes v as 1 - v: the second distance comes back flipped)
      return `{ float d = ${q.comp ? `1.0 - vEb_${q.uv}.y` : `vEb_${q.uv}.x`};
  if (d > 0.5 && d < 1.0 + 2.3 * ebW${i}) {      // (past 2.3 W nothing can come through: no samples there)
    d -= 1.0;
    float ebNi = abs(ebW${i} - ebW) > 1e-4 ? ebNoise(vEbP / max(0.3, ebW${i})) : ebN;
    vec3 cB = ebCol${i};
    if (ebHas${i} > 0.5) cB *= ebBox(ebTex${i}, ebK${i}, ebRot${i}, ebOff${i}, ${at2 ? 'true' : 'false'});
    float hB = dot(cB, vec3(0.2126, 0.7152, 0.0722));
    float arg = 0.5 - 0.5 * d / ebW${i} + ${q.sign >= 0 ? '1.0' : '-1.0'} * ebIrr * (ebNi - 0.5) + 0.5 * (ebLw${i} * (hB - 0.5) - ebLwA * (ebHA - 0.5));
    float f = clamp((arg - 0.5) * 4.0 + 0.5, 0.0, 1.0);
    diffuseColor.rgb = mix(diffuseColor.rgb, cB, f);
    roughnessFactor = mix(roughnessFactor, ebRough${i}, f);
  } }`;
    }).join('\n');
    // (the helpers just before main: after the antitile functions the triplanar projection put at the top)
    const helpers = `uniform float ebW, ebIrr, ebLwA;
${decl}
varying vec3 vEbP; varying vec3 vEbN;
${slots.map((u) => `varying vec2 vEb_${u};`).join('\n')}
float ebH(vec3 p) { p = fract(p * 0.1031); p += dot(p, p.zyx + 31.32); return fract((p.x + p.y) * p.z); }
float ebV(vec3 p) {
  vec3 i = floor(p), f = fract(p); f = f * f * (3.0 - 2.0 * f);
  return mix(mix(mix(ebH(i), ebH(i + vec3(1, 0, 0)), f.x), mix(ebH(i + vec3(0, 1, 0)), ebH(i + vec3(1, 1, 0)), f.x), f.y),
             mix(mix(ebH(i + vec3(0, 0, 1)), ebH(i + vec3(1, 0, 1)), f.x), mix(ebH(i + vec3(0, 1, 1)), ebH(i + vec3(1, 1, 1)), f.x), f.y), f.z);
}
float ebNoise(vec3 p) { float a = 0.5, s = 0.0, t = 0.0; for (int o = 0; o < 4; o++) { s += a * ebV(p); t += a; p *= 2.0; a *= 0.6; } return s / t; }
vec3 ebBox(sampler2D t, vec3 k, float rot, vec3 off, bool anti) {
  vec3 n = normalize(vEbN);
  vec3 w = pow(abs(n), vec3(5.0)); w /= (w.x + w.y + w.z + 1e-5);
  vec3 p = vEbP * k;
  float c = cos(rot), s = sin(rot);
  vec3 q = vec3(c * p.x - s * p.y + off.x, s * p.x + c * p.y + off.y, p.z + off.z);
  vec2 ux = vec2(n.x < 0.0 ? -q.y : q.y, q.z), uy = vec2(n.y > 0.0 ? -q.x : q.x, q.z), uz = vec2(n.z > 0.0 ? -q.y : q.y, q.x);
  ux.y = -ux.y; uy.y = -uy.y; uz.y = -uz.y;
${at ? `  if (anti) return atTex(t, ux).rgb * w.x + atTex(t, uy).rgb * w.y + atTex(t, uz).rgb * w.z;` : ''}
  return texture2D(t, ux).rgb * w.x + texture2D(t, uy).rgb * w.y + texture2D(t, uz).rgb * w.z;
}
`;
    sh.fragmentShader = sh.fragmentShader.replace('void main() {', helpers + 'void main() {').replace('#include <normal_fragment_begin>', `{ float ebHA = dot(diffuseColor.rgb, vec3(0.2126, 0.7152, 0.0722));
  float ebN = ebNoise(vEbP / max(0.3, ebW));
${body}
}
#include <normal_fragment_begin>`);
  };
  m.customProgramCacheKey = () => 'eb1' + parts.map((q) => q.uv + q.comp + (q.sign >= 0 ? 'p' : 'n') + (at && q.proj && q.proj.antitile ? 'a' : '')).join('') + (prevKey ? prevKey.call(m) : '');
}
// ------------------------------------------------------------------ Volumetrico (volumetric.py)
// A model with a volumetric material is drawn as the volume inside its faces: its back faces, a ray from the camera
// marched through it (as Cycles, lighter: performance first). The shape: a grid of the signed distance to its
// surface, made here once per mesh (three-mesh-bvh: closest point + inside by crossings); the density as in
// volumetric.py: d = clamp(-sdf / band, 0, 1), puffs eaten by a noise (another noise function than Cycles: the same
// character, not the same puffs), sigma = 4 / visibility, albedo = colour (1 - 0.85 absorb), emission f^2. The light:
// the sun (phase of Henyey-Greenstein, dimmed by how deep the point is) and a share of the sky. Fewer steps while the
// view moves.
const VOL = { mats: new Set(), grid: 28 };
const VOL_VS = `varying vec3 vLocal; varying vec3 vCamL; varying vec3 vMx; varying vec3 vMy; varying vec3 vMz;
void main() {
  mat4 m = modelMatrix;
#ifdef USE_INSTANCING
  m = m * instanceMatrix;
#endif
  vLocal = position;
  vCamL = ( inverse( m ) * vec4( cameraPosition, 1.0 ) ).xyz;
  vMx = m[0].xyz; vMy = m[1].xyz; vMz = m[2].xyz;
  gl_Position = projectionMatrix * viewMatrix * m * vec4( position, 1.0 );
}`;
const VOL_FS = `precision highp sampler3D;
uniform sampler3D uGrid; uniform vec3 uBMin; uniform vec3 uBMax; uniform float uBand; uniform float uSigma;
uniform vec3 uAlbedo; uniform float uPuffs; uniform float uPuffRel; uniform float uLongest; uniform float uSeed; uniform float uAniso;
uniform float uEmit; uniform vec3 uEmitCol; uniform vec3 uSunDir; uniform vec3 uSunCol; uniform vec3 uAmb; uniform float uSteps; uniform vec3 uGridN;
varying vec3 vLocal; varying vec3 vCamL; varying vec3 vMx; varying vec3 vMy; varying vec3 vMz;
float h31( vec3 p ) { p = fract( p * 0.1031 ); p += dot( p, p.zyx + 31.32 ); return fract( ( p.x + p.y ) * p.z ); }
float vnoise( vec3 p ) {
  vec3 i = floor( p ), f = fract( p ); f = f * f * ( 3.0 - 2.0 * f );
  return mix( mix( mix( h31( i ), h31( i + vec3( 1, 0, 0 ) ), f.x ), mix( h31( i + vec3( 0, 1, 0 ) ), h31( i + vec3( 1, 1, 0 ) ), f.x ), f.y ),
              mix( mix( h31( i + vec3( 0, 0, 1 ) ), h31( i + vec3( 1, 0, 1 ) ), f.x ), mix( h31( i + vec3( 0, 1, 1 ) ), h31( i + vec3( 1, 1, 1 ) ), f.x ), f.y ), f.z );
}
float fbm( vec3 p, float oct ) {
  float a = 0.5, s = 0.0, n = 0.0;
  for ( int i = 0; i < 4; i++ ) { if ( float( i ) >= oct ) break; s += a * vnoise( p ); n += a; p = p * 2.03 + 17.1; a *= 0.55; }
  return s / n;
}
void main() {
  vec3 ro = vCamL, d = vLocal - vCamL;
  float tEnd = length( d ); vec3 rd = d / tEnd;
  vec3 inv = 1.0 / rd, ta = ( uBMin - ro ) * inv, tb = ( uBMax - ro ) * inv;
  vec3 tn = min( ta, tb ), tf = max( ta, tb );
  float t0 = max( max( max( tn.x, tn.y ), tn.z ), 0.0 ), t1 = min( min( min( tf.x, tf.y ), tf.z ), tEnd );
  if ( t1 <= t0 ) discard;
  mat3 M = mat3( vMx, vMy, vMz );
  // (the puffs: a share of the model - its longest side in metres)
  float uPuffScale = 1.0 / max( 1e-3, uPuffRel * uLongest * max( length( vMx ), max( length( vMy ), length( vMz ) ) ) );
  float wscale = length( M * rd );                     // metres per unit of the model along the ray
  vec3 rdW = normalize( M * rd );
  float g = uAniso, cosT = dot( rdW, uSunDir );
  float phase = ( 1.0 - g * g ) / ( 12.566 * pow( max( 1e-3, 1.0 + g * g + 2.0 * g * cosT ), 1.5 ) );
  float steps = uSteps, dt = ( t1 - t0 ) / steps, ds = dt * wscale;
  float j = h31( vec3( gl_FragCoord.xy, 0.0 ) );
  vec3 L = vec3( 0.0 ); float T = 1.0;
  vec3 span = uBMax - uBMin;
  float oct = uSteps > 20.0 ? 3.0 : 2.0;
  for ( int i = 0; i < 64; i++ ) {
    if ( float( i ) >= steps ) break;
    vec3 p = ro + rd * ( t0 + ( float( i ) + j ) * dt );
    float sdf = texture( uGrid, ( p - uBMin ) / span ).r;
    float dd = clamp( -sdf / uBand, 0.0, 1.0 );
    if ( dd <= 0.0 ) continue;
    float f = dd;
    if ( uPuffs > 0.0 ) {
      float n = smoothstep( 0.3, 0.7, fbm( M * p * uPuffScale + uSeed, oct ) );
      f = clamp( ( dd - uPuffs * ( 1.0 - n ) ) / ( 1.0 - 0.5 * uPuffs ), 0.0, 1.0 );
    }
    if ( f <= 0.0 ) continue;
    float sig = uSigma * f, a = 1.0 - exp( -sig * ds );
    // the light: a dense volume is lit almost as a surface - its side towards the sun bright, the other in its own
    // shadow (the normal from the grid of the shape: outwards where the distance grows), with the light passing
    // through the edges (phase) and the sky from above; deeper inside, less of everything (light scattered many
    // times in Cycles)
    vec3 hx = vec3( span.x / uGridN.x, 0.0, 0.0 ), hy = vec3( 0.0, span.y / uGridN.y, 0.0 ), hz = vec3( 0.0, 0.0, span.z / uGridN.z );
    vec3 gl = vec3( texture( uGrid, ( p + hx - uBMin ) / span ).r - texture( uGrid, ( p - hx - uBMin ) / span ).r,
                    texture( uGrid, ( p + hy - uBMin ) / span ).r - texture( uGrid, ( p - hy - uBMin ) / span ).r,
                    texture( uGrid, ( p + hz - uBMin ) / span ).r - texture( uGrid, ( p - hz - uBMin ) / span ).r );
    vec3 nW = normalize( M * gl + vec3( 0.0, 0.0, 1e-5 ) );
    float lam = clamp( ( dot( nW, uSunDir ) + 0.25 ) / 1.25, 0.0, 1.0 );
    float depth = exp( -uSigma * dd * uBand * wscale * 0.12 );      // (deeper inside: less light)
    float skyK = 0.55 + 0.45 * nW.z;
    vec3 lit = uSunCol * ( lam * 0.32 + phase * 1.5 ) * mix( 0.35, 1.0, depth ) + uAmb * skyK * 2.2;
    L += T * ( a * uAlbedo * lit + uEmit * f * f * uEmitCol * ds );
    T *= 1.0 - a;
    if ( T < 0.02 ) break;
  }
  float alpha = 1.0 - T;
  if ( alpha < 0.002 && dot( L, L ) < 1e-6 ) discard;
  gl_FragColor = vec4( L / max( alpha, 1e-3 ), alpha );
  #include <tonemapping_fragment>
  #include <colorspace_fragment>
}`;
function volGrid(geometry) {
  const ud = geometry.userData;
  if (ud.volSrc) return volGrid(ud.volSrc);      // (a copy for instancing: the grid of its source, made once)
  if (ud.volGrid) return ud.volGrid;
  geometry.computeBoundingBox();
  const bb = geometry.boundingBox.clone();
  const size = bb.getSize(new THREE.Vector3());
  const longest = Math.max(size.x, size.y, size.z, 1e-4);
  const pad = longest / VOL.grid;
  bb.min.addScalar(-pad); bb.max.addScalar(pad);
  bb.getSize(size);
  const n = [0, 1, 2].map((k) => Math.max(4, Math.round(VOL.grid * size.getComponent(k) / (longest + 2 * pad))));
  if (!geometry.boundsTree) geometry.computeBoundsTree();
  const bvh = geometry.boundsTree;
  const shape = volShape(geometry);
  // (the grid here is coarser than the voxels of Cycles: spheres smaller than a cell would fall between the cells)
  const wrapR = shape.open ? Math.max(shape.radius, 0.9 * Math.max(size.x / n[0], size.y / n[1], size.z / n[2])) : 0;
  const N3 = n[0] * n[1] * n[2];
  const sdf = new Float32Array(N3);
  const p = new THREE.Vector3(), hit = {}, ray = new THREE.Ray(p, new THREE.Vector3(1, 0.000173, 0.000311).normalize());
  for (let z = 0; z < n[2]; z++) for (let y = 0; y < n[1]; y++) for (let x = 0; x < n[0]; x++) {
    p.set(bb.min.x + (x + 0.5) * size.x / n[0], bb.min.y + (y + 0.5) * size.y / n[1], bb.min.z + (z + 0.5) * size.z / n[2]);
    const c = bvh.closestPointToPoint(p, hit);
    const dist = c ? c.distance : longest;
    const i = (z * n[1] + y) * n[0] + x;
    if (shape.open) sdf[i] = dist - wrapR;                   // (wrapped in spheres: inside when near a piece)
    else sdf[i] = bvh.raycast(ray, THREE.DoubleSide).length % 2 ? -dist : dist;    // (odd crossings: inside)
  }
  if (shape.open) volDepth(sdf, n, [size.x / n[0], size.y / n[1], size.z / n[2]]);
  const data = new Uint16Array(N3);
  for (let i = 0; i < N3; i++) data[i] = THREE.DataUtils.toHalfFloat(sdf[i]);
  const tex = new THREE.Data3DTexture(data, n[0], n[1], n[2]);
  tex.format = THREE.RedFormat; tex.type = THREE.HalfFloatType;
  tex.minFilter = tex.magFilter = THREE.LinearFilter; tex.unpackAlignment = 1;
  tex.wrapS = tex.wrapT = tex.wrapR = THREE.ClampToEdgeWrapping;
  tex.needsUpdate = true;
  const sm = Math.min(...[0, 1, 2].map((k) => geometry.boundingBox.getSize(new THREE.Vector3()).getComponent(k)).filter((v) => v > 1e-5).concat([longest]));
  ud.volGrid = { tex, min: bb.min.clone(), max: bb.max.clone(), longest, smallest: sm, n: new THREE.Vector3(...n) };
  return ud.volGrid;
}
// Is the mesh closed? (as volumetric.shape_info) Vertices welded by position (1e-4 of the longest side: the export
// splits them at the seams); open = more than 1% of the edges with one face; then its pieces (islands) and the radius
// of the spheres that wrap them into a closed shape: 0.8 (box volume / islands)^(1/3), between 2 voxels and 0.35 of
// the smallest side.
function volShape(geometry) {
  const pos = geometry.attributes.position, nv = pos.count;
  const bb = geometry.boundingBox, size = bb.getSize(new THREE.Vector3());
  const longest = Math.max(size.x, size.y, size.z, 1e-6), q = longest * 1e-4;
  const ids = new Int32Array(nv), keys = new Map();
  for (let i = 0; i < nv; i++) {
    const k = Math.round((pos.getX(i) - bb.min.x) / q) + ',' + Math.round((pos.getY(i) - bb.min.y) / q) + ',' + Math.round((pos.getZ(i) - bb.min.z) / q);
    let id = keys.get(k);
    if (id === undefined) { id = keys.size; keys.set(k, id); }
    ids[i] = id;
  }
  const idx = geometry.index ? geometry.index.array : null, nt = (idx ? idx.length : nv) / 3;
  const edges = new Map();
  const vi = (t) => ids[idx ? idx[t] : t];
  for (let t = 0; t < nt; t++) for (let k = 0; k < 3; k++) {
    let a = vi(t * 3 + k), b = vi(t * 3 + (k + 1) % 3);
    if (a === b) continue;
    if (a > b) [a, b] = [b, a];
    const key = a * 4294967296 + b;
    edges.set(key, (edges.get(key) || 0) + 1);
  }
  let boundary = 0;
  for (const c of edges.values()) if (c === 1) boundary++;
  const open = boundary > 0.01 * Math.max(1, edges.size);
  if (!open) return { open: false, radius: 0 };
  const parent = new Int32Array(keys.size).map((_, i) => i);
  const find = (x) => { while (parent[x] !== x) { parent[x] = parent[parent[x]]; x = parent[x]; } return x; };
  for (const key of edges.keys()) {
    const a = find(Math.floor(key / 4294967296)), b = find(key % 4294967296);
    if (a !== b) parent[Math.max(a, b)] = Math.min(a, b);
  }
  let islands = 0;
  for (let i = 0; i < parent.length; i++) if (find(i) === i) islands++;
  const dims = [size.x, size.y, size.z];
  const smallest = Math.min(...dims.filter((d) => d > 1e-5).concat([longest]));
  const vol = dims.reduce((a, d) => a * Math.max(d, 0.05 * smallest), 1);
  const voxel = longest / (48 + 112 * 0.5);
  const radius = Math.max(2 * voxel, Math.min(0.8 * Math.cbrt(vol / Math.max(1, islands)), 0.35 * smallest));
  return { open: true, radius, islands };
}
// signed distance inside the shape of an open mesh (cells within its spheres: sdf < 0): the distance to the outside
// cells (chamfer, two passes), so the density deep inside reaches 1 as in Cycles (where the spheres become a mesh)
function volDepth(sdf, n, cell) {
  const [nx, ny, nz] = n, BIG = 1e9;
  const d = new Float32Array(sdf.length);
  for (let i = 0; i < sdf.length; i++) d[i] = sdf[i] < 0 ? BIG : 0;
  const off = [];
  for (let dz = -1; dz <= 1; dz++) for (let dy = -1; dy <= 1; dy++) for (let dx = -1; dx <= 1; dx++)
    if (dx || dy || dz) off.push([dx, dy, dz, Math.hypot(dx * cell[0], dy * cell[1], dz * cell[2])]);
  const fw = off.filter(([dx, dy, dz]) => dz < 0 || (dz === 0 && (dy < 0 || (dy === 0 && dx < 0))));
  const bw = off.filter(([dx, dy, dz]) => !(dz < 0 || (dz === 0 && (dy < 0 || (dy === 0 && dx < 0)))));
  const pass = (list, z0, z1, st) => {
    for (let z = z0; z !== z1; z += st) for (let y = st > 0 ? 0 : ny - 1; st > 0 ? y < ny : y >= 0; y += st) for (let x = st > 0 ? 0 : nx - 1; st > 0 ? x < nx : x >= 0; x += st) {
      const i = (z * ny + y) * nx + x;
      if (d[i] === 0) continue;
      let best = d[i];
      for (const [dx, dy, dz, w] of list) {
        const X = x + dx, Y = y + dy, Z = z + dz;
        if (X < 0 || Y < 0 || Z < 0 || X >= nx || Y >= ny || Z >= nz) { best = Math.min(best, w); continue; }
        best = Math.min(best, d[(Z * ny + Y) * nx + X] + w);
      }
      d[i] = best;
    }
  };
  pass(fw, 0, nz, 1);
  pass(bw, nz - 1, -1, -1);
  for (let i = 0; i < sdf.length; i++) if (sdf[i] < 0) sdf[i] = -d[i];
}
function volSun() {
  let best = null;
  for (const e of lights.values()) if (e.light && e.light.isDirectionalLight && e.light.visible && (!best || e.light.intensity > best.intensity)) best = e.light;
  return best;
}
function volMaterial(v, name) {
  const s = { visibility: 0.25, color: [1, 1, 1], absorb: 0, soft: 0.3, puffs: 0.6, puffRel: 0.12, detail: 0.5, aniso: 0.4, seed: 0, emission: 0, emitColor: [1, 0.42, 0.08], ...(v || {}) };
  const alb = s.color.map((c) => c * (1 - 0.85 * s.absorb));
  const u = {
    uGrid: { value: null }, uBMin: { value: new THREE.Vector3() }, uBMax: { value: new THREE.Vector3(1, 1, 1) }, uBand: { value: 0.1 },
    uSigma: { value: 4 / Math.max(0.05, s.visibility) }, uAlbedo: { value: new THREE.Vector3(...alb) },
    uPuffs: { value: s.puffs }, uPuffRel: { value: Math.max(0.01, s.puffRel || 0.12) }, uLongest: { value: 1 }, uSeed: { value: s.seed * 7.31 },
    uAniso: { value: s.aniso }, uEmit: { value: s.emission }, uEmitCol: { value: new THREE.Vector3(...s.emitColor) },
    uSunDir: { value: new THREE.Vector3(0, 0, 1) }, uSunCol: { value: new THREE.Vector3(1, 1, 1) }, uAmb: { value: new THREE.Vector3(0.2, 0.22, 0.25) },
    uSteps: { value: 32 }, uGridN: { value: new THREE.Vector3(28, 28, 28) },
  };
  const m = new THREE.ShaderMaterial({ uniforms: u, vertexShader: VOL_VS, fragmentShader: VOL_FS, side: THREE.BackSide, transparent: true, depthWrite: false });
  m.name = name || '';
  m.userData.dry = true;            // (rain and snow leave it alone)
  m.userData.volume = s;
  m.onBeforeRender = (_r, _scene, _cam, geometry) => {
    const g = volGrid(geometry);
    u.uGrid.value = g.tex; u.uBMin.value.copy(g.min); u.uBMax.value.copy(g.max); u.uLongest.value = g.longest; u.uGridN.value.copy(g.n);
    // (as volumetric.sizes: «Morbidezza» on the smallest side, 2 voxels at least - here in the model's own units)
    u.uBand.value = Math.max(2 * g.longest / (48 + 112 * s.detail), s.soft * 0.5 * g.smallest);
    const sun = volSun();
    if (sun) {
      u.uSunDir.value.copy(sun.position).sub(sun.target.position).normalize();
      const k = sun.intensity;
      u.uSunCol.value.set(sun.color.r * k, sun.color.g * k, sun.color.b * k);
    } else u.uSunCol.value.set(0, 0, 0);
    const sk = Math.max(0.05, scene.environmentIntensity || 0) * 0.35;
    const sc = u.uSunCol.value;
    u.uAmb.value.set(0.10 + sc.x * sk * 0.25, 0.11 + sc.y * sk * 0.25, 0.13 + sc.z * sk * 0.28);
    u.uSteps.value = interacting ? 14 : 36;
    m.uniformsNeedUpdate = true;
  };
  VOL.mats.add(m);
  return m;
}
// meshes with a volumetric material: their material replaced, no shadow of their own surface
function volApply(o) {
  if (!o.isMesh) return;
  const swap = (m) => {
    if (!m || m.userData.volume) return m;
    let raw = m.userData.simpler_volumetric;
    if (!raw) return m;
    try { raw = typeof raw === 'string' ? JSON.parse(raw) : raw; } catch { return m; }
    if (!raw.on) return m;
    return volMaterial(raw, m.name);
  };
  if (Array.isArray(o.material)) o.material = o.material.map(swap); else o.material = swap(o.material);
  if (needsProgram(o.material)) shadersDirty();
  const any = (Array.isArray(o.material) ? o.material : [o.material]).some((m) => m && m.userData.volume);
  if (any) { o.castShadow = false; o.receiveShadow = false; o.userData.volNoShadow = true; }
}
function rtMaterial(p, standIn = false) {
  const key = JSON.stringify(p) + (standIn ? '#standin' : '');
  let m = rtMaterials.get(key);
  if (m) return m;
  if (p.volume) {                          // (volumetric.py: drawn as a volume)
    m = volMaterial(p.volume, p.name);
    rtMaterials.set(key, m);
    rtMaterialSet.add(m);
    if (m.name && !standIn) knownMaterials.set(m.name, m);
    return m;
  }
  const c = p.color || [0.8, 0.8, 0.8];
  m = new THREE.MeshPhysicalMaterial({
    color: new THREE.Color().setRGB(c[0], c[1], c[2]),
    metalness: p.metallic ?? 0, roughness: p.roughness ?? 0.5,
    transmission: p.transmission ?? 0, ior: p.ior ?? 1.5, thickness: (p.transmission || 0) > 0 ? 0.01 : 0,
    clearcoat: p.coat ?? 0,
    opacity: p.alpha ?? 1, transparent: (p.alpha ?? 1) < 1, side: THREE.DoubleSide,
  });
  const e = p.emission || [0, 0, 0];
  if ((p.emissionStrength || 0) > 0) { m.emissive = new THREE.Color().setRGB(e[0], e[1], e[2]); m.emissiveIntensity = p.emissionStrength; }
  if (p.simpler) simplerMaterial(p, m);
  m.name = p.name || '';
  rtMaterials.set(key, m);
  rtMaterialSet.add(m);
  if (m.name && !standIn && (p.simpler || !knownMaterials.has(m.name))) knownMaterials.set(m.name, m);
  return m;
}
function ownMeshes(node, out = []) {
  for (const c of node.children) {
    if (c.userData && c.userData.simpler_id) continue;   // another object of the scene
    if (c.isMesh) out.push(c);
    ownMeshes(c, out);
  }
  if (node.isMesh) out.push(node);
  return out;
}
// materials the view already has, by name (from the export, or replaced by applyMaterials)
const knownMaterials = new Map();
// the materials as the export made them (never replaced by an edit): an undo back to the original material, or
// "Ripristina originale", finds it here (before, the edited version had taken its name: it stayed white/edited)
const exportMaterials = new Map();
// Every surface has two faces, as in the path tracing (Cycles draws both sides of every face): models with a
// missing wall or with some faces turned the wrong way no longer show holes or black sides in the real-time view.
// (Cost: the faces turned away from the camera are drawn too - a small share of the frame.)
function twoSided(m) { if (m && m.side !== THREE.DoubleSide) { m.side = THREE.DoubleSide; m.needsUpdate = true; } return m; }
// (1.79, Luca: «modelli importati: in path tracing si vedono bene, in tempo reale sono pieni di buchi») many models
// have the alpha of their colour picture plugged in the material while the picture is opaque everywhere: Cycles sees
// a solid surface, the glTF says «blended» and the view drew it as glass without depth (the surfaces behind showed
// through, whole walls missing). A blended material whose picture has no transparent pixel is drawn solid.
const _solidChecked = new WeakMap();      // image -> true when every pixel is opaque
function pictureOpaque(img) {
  if (!img || !img.width) return false;
  if (_solidChecked.has(img)) return _solidChecked.get(img);
  let solid = false;
  try {
    const w = Math.min(256, img.width), h = Math.min(256, img.height);
    const c = document.createElement('canvas');
    c.width = w; c.height = h;
    const g = c.getContext('2d', { willReadFrequently: true });
    g.drawImage(img, 0, 0, w, h);
    const d = g.getImageData(0, 0, w, h).data;
    solid = true;
    for (let i = 3; i < d.length; i += 4) if (d[i] < 250) { solid = false; break; }
  } catch { solid = false; }
  _solidChecked.set(img, solid);
  return solid;
}
function solidIfOpaque(m) {
  if (!m || !m.isMaterial || m.userData.volume || m.userData.solidChecked) return;
  if (!(m.transparent || m.alphaTest > 0) || (m.opacity ?? 1) < 1 || m.alphaMap || (m.transmission || 0) > 0) return;
  const img = m.map && m.map.image;
  if (!img) return;
  m.userData.solidChecked = true;
  if (!pictureOpaque(img)) return;
  m.transparent = false; m.depthWrite = true; m.alphaTest = 0;
  m.needsUpdate = true;
}
function indexMaterials(obj) {
  obj.traverse((o) => {
    if (!o.isMesh) return;
    volApply(o);
    (Array.isArray(o.material) ? o.material : [o.material]).forEach((m) => {
      twoSided(m);
      solidIfOpaque(m);
      if (m && m.name && !knownMaterials.has(m.name)) knownMaterials.set(m.name, m);
      if (m && m.name && !exportMaterials.has(m.name) && !rtMaterialSet.has(m)) exportMaterials.set(m.name, m);
    });
  });
}
function slotMaterial(s) {
  if (s.simpler) return rtMaterial(s);       // edited in Simpler: always the current version of its channels
  const known = exportMaterials.get(s.name) || knownMaterials.get(s.name);
  if (known) return known;
  // a textured material the view does not have yet: its plain colour for now (no new preparation of the
  // whole scene for one material); the textures appear the next time the view is prepared. Not remembered under
  // its name: a library model arriving a moment later brings the real one (before, this stand-in took the name and
  // the next push of materials put it on the model - a whole building white right after opening a project)
  return rtMaterial(s, true);
}
function applyMaterials(items) {
  try {
    for (const it of items || []) {
      for (const s of it.slots || []) slotMaterial(s);   // all available, or a new export is needed
    }
  } catch { needReason = 'textured material not in the view'; return false; }
  for (const it of items || []) {
    const node = byId.get(it.id);
    if (!node) { scatterMaterials(it.slots || []); continue; }   // a part of a library piece: its prototype
    // (1.78.4, Luca: «season sembra non funzionare») a library piece of one object is a node of the view drawn from
    // its prototype: it has no meshes of its own, the change goes to the prototype (it was lost: the season, any
    // edit of its materials did not show in the view)
    if (node.userData.paintPiece && !ownMeshes(node).length) { scatterMaterials(it.slots || []); continue; }
    const slots = it.slots || [];
    const meshes = ownMeshes(node);
    meshes.forEach((mesh, mi) => {
      const pick = (old, idx) => {
        if (slots.length === 1) return slotMaterial(slots[0]);
        const s = slots.find((x) => x.old && old && x.old === old.name) || (meshes.length === slots.length ? slots[mi] : slots[idx]);
        return s ? slotMaterial(s) : old;
      };
      const remember = (m) => { if (m && m.name && !knownMaterials.has(m.name)) knownMaterials.set(m.name, m); };
      if (Array.isArray(mesh.material)) { mesh.material.forEach(remember); mesh.material = mesh.material.map((m, i) => pick(m, i)); }
      else { remember(mesh.material); mesh.material = pick(mesh.material, mi); }
      if (needsProgram(mesh.material)) shadersDirty();
      const vol = (Array.isArray(mesh.material) ? mesh.material : [mesh.material]).some((m) => m && m.userData.volume);
      if (vol && !mesh.userData.volNoShadow) { mesh.userData.volNoShadow = true; mesh.castShadow = mesh.receiveShadow = false; }
      else if (!vol && mesh.userData.volNoShadow) { mesh.userData.volNoShadow = false; mesh.castShadow = mesh.receiveShadow = true; }
    });
  }
  return true;
}

function matricesClose(a, b) {
  for (let i = 0; i < 16; i++) if (Math.abs(a.elements[i] - b.elements[i]) > 1e-5) return false;
  return true;
}

function setWorldMatrix(o, world) {
  o.parent && o.parent.updateMatrixWorld(true);
  const parentInv = o.parent ? o.parent.matrixWorld.clone().invert() : new THREE.Matrix4();
  o.matrix.copy(parentInv.multiply(world));
  o.matrix.decompose(o.position, o.quaternion, o.scale);
  o.updateMatrixWorld(true);
}

// ------------------------------------------------------------------ selection
let selection = [];   // ids, in click order
let primary = '';
let selectionHelpers = [];

function idOf(o) {
  for (; o; o = o.parent) {
    if (o.userData && o.userData.pickId) return o.userData.pickId;
    if (o.userData && o.userData.simpler_id) return o.userData.simpler_id;
  }
  return '';
}
function parentIdOf(id) {
  const o = byId.get(id);
  return o && o.parent ? idOf(o.parent) : '';
}

/** Selected objects without those already moved by a selected ancestor. */
function topLevel() {
  const set = new Set(selection);
  const out = [];
  for (const id of selection) {
    const o = byId.get(id);
    if (!o) continue;
    let covered = false;
    for (let p = o.parent; p; p = p.parent) if (p.userData && set.has(p.userData.simpler_id)) { covered = true; break; }
    if (!covered) out.push(o);
  }
  return out;
}

let partMats = null;
function matNames(m) { return (Array.isArray(m) ? m : [m]).map((x) => x && x.name).filter(Boolean); }
function applySelection(ids, prim) {
  const _t0 = performance.now();
  try { applySelectionNow(ids, prim); } finally {
    const ms = performance.now() - _t0;
    if (ms > 200) viewLog(`selection in the view: ${Math.round(ms)} ms`);
  }
}
function applySelectionNow(ids, prim) {
  selection = [...new Set((ids || []).filter((id) => id))];
  primary = prim && selection.includes(prim) ? prim : (selection[selection.length - 1] || '');
  for (const h of selectionHelpers) { scene.remove(h); h.geometry.dispose(); }
  selectionHelpers = [];
  const objs = topLevel();
  scatterSelection();
  // the selection is drawn as an outline of the pieces (see renderOutline); a box only for what has no surface
  for (const o of objs.slice(0, 64)) {
    let hasMesh = false;
    o.traverse((c) => { if (c.isMesh && !c.userData.helper) hasMesh = true; });
    if (hasMesh) continue;
    // a distribution whose line is on screen: the line already shows it, the box only hid the view
    if (paint.on && lineTool() && paint.group && o.userData.simpler_id === paint.group) continue;
    const box = boxOf(o);
    if (box.isEmpty()) continue;
    const h = new THREE.Box3Helper(box, o.userData.simpler_id === primary ? WARM : 0x9cc6ff);
    h.material.depthTest = false; h.material.transparent = true; h.material.opacity = 0.7;
    h.userData.target = o;
    noRaycast(h);
    selectionHelpers.push(h);
    scene.add(h);
  }
  if (objs.length && !partMats) { placePivot(); attachGizmos(pivot); } else attachGizmos(null);
  applySnap();
  updateToolbar();
}

function refreshSelectionBoxes() {
  for (const h of selectionHelpers) h.box.copy(boxOf(h.userData.target));
}

// ------------------------------------------------------------------ pivot & gizmo
// The gizmo drives a pivot placed at the centre (or base, or origin) of the selection; on every change the
// pivot delta is applied to every selected object, so composite objects move, rotate and scale as one.
const pivot = new THREE.Object3D();
scene.add(pivot);
let pivotMode = 'base';       // base | center | origin (the app sends the one chosen last time)
let useCustomPivot = true;    // a pivot moved by hand wins until the user picks Centre / Base / Origin (and again after «Manuale»)
let space = 'world';          // world | local
let snapOn = false, shiftDown = false, ctrlDown = false;   // Ctrl inverts the snap while dragging; Shift at the start of a drag = copy
const drag = { p0: new THREE.Matrix4(), items: [], startPos: new THREE.Vector3(), copy: false, ghosts: [] };

// true while the selection has no size yet (a library model still arriving): the gizmo stands on the origin for
// the moment and is placed again as soon as the model is there (tick)
let pivotNoSize = false, _pivotRetry = 0;
function selectionBox(objs) {
  const box = new THREE.Box3();
  for (const o of objs) box.union(boxOf(o));
  pivotNoSize = box.isEmpty() && objs.some((o) => o.userData.paintPiece);     // (a light or an empty group: no size by nature)
  if (box.isEmpty()) for (const o of objs) box.expandByPoint(new THREE.Vector3().setFromMatrixPosition(o.matrixWorld));
  return box;
}

// (1.78.4, Luca: «se lo deseleziono torna dove era prima») the pivot is of the whole model (pivotEdit picks its root),
// but a click selects the piece under the mouse: a piece that is the only one of its model shows the model's pivot
function pivotOwner(prim) {
  if (!prim) return null;
  if (prim.userData.customPivot) return prim;
  let child = prim;
  for (let p = prim.parent; p && p !== root; child = p, p = p.parent) {
    if (!p.userData || !p.userData.simpler_id) continue;
    let n = 0;
    for (const c of p.children) if (c.userData && c.userData.simpler_id && !c.userData.helper) n++;
    if (n !== 1) return null;
    if (p.userData.customPivot) return p;
  }
  return null;
}
function customPivotShown(objs, prim) {
  return objs.length === 1 && !!pivotOwner(prim) && !lights.has(prim.userData.simpler_id) && (useCustomPivot || pivotEdit);
}
function placePivot() {
  const objs = topLevel();
  if (!objs.length) return;
  const prim = byId.get(primary) || objs[0];
  prim.updateMatrixWorld(true);
  const box = selectionBox(objs);
  const pos = new THREE.Vector3();
  if (customPivotShown(objs, prim)) {
    const own = pivotOwner(prim);
    own.updateMatrixWorld(true);
    pos.copy(own.userData.customPivot).applyMatrix4(own.matrixWorld);         // placed by hand (violet gizmo)
  }
  else if (pivotMode === 'origin' || lights.has(prim.userData.simpler_id)) pos.setFromMatrixPosition(prim.matrixWorld);
  else if (pivotMode === 'base') { box.getCenter(pos); pos.z = box.min.z; }
  else box.getCenter(pos);
  const q = new THREE.Quaternion();
  if (objs.length === 1) prim.matrixWorld.decompose(new THREE.Vector3(), q, new THREE.Vector3());
  pivot.position.copy(pos);
  pivot.quaternion.copy(q);
  pivot.scale.set(1, 1, 1);
  pivot.updateMatrixWorld(true);
  for (const g of gizmos) g.space = objs.length > 1 ? 'world' : space;
}

// rotation snap: its own setting (on by default, 5°), apart from the snap of moving and scaling
const ROT_STEPS = [5, 15, 45, 1, 0];          // the button goes through them; 0 = off
let rotSnapDeg = 5;
try { const v = localStorage.getItem('simpler.rotSnap'); if (v !== null && ROT_STEPS.includes(Number(v))) rotSnapDeg = Number(v); } catch { /* storage unavailable */ }
function applySnap() {
  const on = snapOn !== ctrlDown; // Ctrl inverts the toolbar setting while held
  const rotOn = (rotSnapDeg > 0) !== ctrlDown;
  gRot.setRotationSnap(rotOn ? THREE.MathUtils.degToRad(rotSnapDeg > 0 ? rotSnapDeg : 5) : null);
  if (!on) { gMove.setTranslationSnap(null); gScale.setScaleSnap(null); return; }
  const objs = topLevel();
  const r = objs.length ? selectionBox(objs).getSize(new THREE.Vector3()).length() : sceneRadius() * 2;
  const step = Math.pow(10, Math.floor(Math.log10(Math.max(r, 1e-4) / 10)));   // 1 mm for a ring, 1 cm for a chair...
  gMove.setTranslationSnap(step);
  gScale.setScaleSnap(0.1);
}
function cycleRotSnap() {
  rotSnapDeg = ROT_STEPS[(ROT_STEPS.indexOf(rotSnapDeg) + 1) % ROT_STEPS.length];
  try { localStorage.setItem('simpler.rotSnap', String(rotSnapDeg)); } catch { /* storage unavailable */ }
  applySnap(); updateToolbar();
}

// Scale: three.js divides the distance of the mouse from the centre by the distance at the start, so grabbing a
// handle close to the centre (the gizmo is small on a big model) made a tiny movement double or halve the model.
// Here the factor comes from how far the mouse moved on screen along the handle: 200 pixels = ×2 (or ÷2 back).
const SCALE_PX_PER_DOUBLE = 200;
const scaleDrag = { x: 0, y: 0, dir: new THREE.Vector2(1, -1).normalize(), s0: new THREE.Vector3(1, 1, 1) };
let ptrX = 0, ptrY = 0;
window.addEventListener('pointermove', (e) => { ptrX = e.clientX; ptrY = e.clientY; }, true);
let ptrShift = false;
window.addEventListener('pointerdown', (e) => { ptrX = e.clientX; ptrY = e.clientY; ptrShift = e.shiftKey; }, true);
function toScreen(v) {
  const p = v.clone().project(camera);
  const r = renderer.domElement.getBoundingClientRect();
  return new THREE.Vector2(r.left + (p.x + 1) / 2 * r.width, r.top + (1 - p.y) / 2 * r.height);
}
function beginScaleDrag(ctl) {
  scaleDrag.x = ptrX; scaleDrag.y = ptrY;
  scaleDrag.s0.copy(pivot.scale);
  const axis = ctl.axis || 'XYZ';
  scaleDrag.dir.set(1, -1).normalize();                    // all axes: up/right = bigger
  if (axis.length === 1) {
    const w = new THREE.Vector3(axis === 'X' ? 1 : 0, axis === 'Y' ? 1 : 0, axis === 'Z' ? 1 : 0);
    if (ctl.space === 'local') w.applyQuaternion(pivot.getWorldQuaternion(new THREE.Quaternion()));
    const c = pivot.getWorldPosition(new THREE.Vector3());
    const a = toScreen(c), b = toScreen(c.clone().add(w.multiplyScalar(sceneRadius() * 0.1)));
    const d = b.sub(a);
    if (d.lengthSq() > 1) scaleDrag.dir.copy(d.normalize());
  }
}
function calmScale() {
  const axis = gizmo.axis || 'XYZ';
  const moved = (ptrX - scaleDrag.x) * scaleDrag.dir.x + (ptrY - scaleDrag.y) * scaleDrag.dir.y;
  let f = Math.pow(2, moved / SCALE_PX_PER_DOUBLE);
  if (snapOn !== ctrlDown) f = Math.max(0.1, Math.round(f * 10) / 10);
  const s = pivot.scale.copy(scaleDrag.s0);
  if (axis.includes('X')) s.x *= f;
  if (axis.includes('Y')) s.y *= f;
  if (axis.includes('Z')) s.z *= f;
}

// Dragging the centre of the move gizmo (the yellow square): the selection slides over the surfaces under the mouse
// with its base resting on them, like Twinmotion (the "Appoggia" of the toolbar, while moving). Alt held: free move.
let ptrAlt = false;
window.addEventListener('pointermove', (e) => { ptrAlt = e.altKey; }, true);
window.addEventListener('pointerdown', (e) => { ptrAlt = e.altKey; }, true);
const _surfRay = new THREE.Raycaster();
function surfaceMove() {
  if (gizmo.mode !== 'translate' || gizmo.axis !== 'XYZ' || ptrAlt || drag.copy) { drag.onSurface = false; return; }
  const r = renderer.domElement.getBoundingClientRect();
  _surfRay.setFromCamera(new THREE.Vector2(((ptrX - r.left) / r.width) * 2 - 1, -((ptrY - r.top) / r.height) * 2 + 1), camera);
  _surfRay.camera = camera;
  const mine = drag.mine;
  const hit = sceneHits(_surfRay).find((h) => {
    const o = h.object;
    if (!o.isMesh || o.userData.helper || !isVisible(o)) return false;
    for (let p = o; p; p = p.parent) if (mine.has(p)) return false;     // not on itself
    return true;
  });
  drag.onSurface = !!hit;
  if (!hit) return;
  // the selection leans with the surface: its up turns to the normal of the face under the mouse (a book on a
  // slanted lectern); on a level surface it stays as it was
  const n = new THREE.Vector3(0, 0, 1);
  if (hit.face && hit.object.matrixWorld) {
    n.copy(hit.face.normal).transformDirection(hit.object.matrixWorld).normalize();
    if (n.dot(_surfRay.ray.direction) > 0) n.negate();
  }
  // straightened first (its own up back to vertical), then turned to the normal: on a level floor a piece that
  // was leaning on a slope stands up again
  const tilt = new THREE.Quaternion().setFromUnitVectors(_zUp, n);
  const turn = tilt.clone().multiply(drag.straight);
  pivot.quaternion.copy(turn).multiply(drag.q0);
  pivot.position.copy(hit.point).sub(drag.baseStraight.clone().applyQuaternion(tilt));
}
const _zUp = new THREE.Vector3(0, 0, 1);
// box of the selection as it would be straightened by rotation q around point c (corners of every part's box)
function straightBox(objs, q, c) {
  const M = new THREE.Matrix4().makeTranslation(c.x, c.y, c.z).multiply(new THREE.Matrix4().makeRotationFromQuaternion(q)).multiply(new THREE.Matrix4().makeTranslation(-c.x, -c.y, -c.z));
  const box = new THREE.Box3(), b = new THREE.Box3(), W = new THREE.Matrix4();
  const add = (geomBox, world) => { b.copy(geomBox).applyMatrix4(W.multiplyMatrices(M, world)); box.union(b); };
  for (const obj of objs) obj.traverse((o) => {
    if (o.userData.paintPiece && !scatter.shown.has(o) && isVisible(o)) {
      const P = protoOf(o);
      if (P && P.state === 'ready') for (const part of P.parts) {
        if (!part.geom.boundingBox) part.geom.computeBoundingBox();
        add(part.geom.boundingBox, new THREE.Matrix4().multiplyMatrices(o.matrixWorld, part.rel));
      }
      return;
    }
    if (!o.isMesh || o.userData.helper || !isVisible(o) || o.isInstancedMesh) return;
    if (!o.geometry.boundingBox) o.geometry.computeBoundingBox();
    add(o.geometry.boundingBox, o.matrixWorld);
  });
  return box;
}

function onGizmoChange() {
  if (!drag.items.length) return;
  if (gizmo.mode === 'scale') calmScale();
  if (gizmo.mode === 'translate') surfaceMove();
  pivot.updateMatrixWorld(true);
  if (gizmo.mode === 'scale' && drag.items.length > 1) {
    // several objects: uniform scale only, so nothing gets sheared
    const s = pivot.scale;
    const k = [s.x, s.y, s.z].reduce((a, b) => (Math.abs(b - 1) > Math.abs(a - 1) ? b : a), 1);
    s.set(k, k, k);
    pivot.updateMatrixWorld(true);
  }
  const delta = pivot.matrixWorld.clone().multiply(drag.p0.clone().invert());
  for (const it of drag.items) setWorldMatrix(it.obj, delta.clone().multiply(it.m0));
  refreshSelectionBoxes();
  updateHud();
}

function onGizmoDragging(ctl, e) {
  orbit.enabled = !e.value;
  if (pivotEdit) {
    // only the gizmo moves; released, its place becomes the model's pivot (in the model's own space)
    if (e.value) { gizmo = ctl; interactionStart(); drag.items = []; return; }
    const prim = byId.get(primary);
    if (prim) {
      prim.updateMatrixWorld(true);
      pivot.updateMatrixWorld(true);
      const local = pivot.position.clone().applyMatrix4(prim.matrixWorld.clone().invert());
      prim.userData.customPivot = local;
      useCustomPivot = true;
      post({ type: 'setPivot', id: primary, pivot: local.toArray() });
    }
    scheduleEnd();
    setGizmosEnabled(!locked && !selectMode);
    return;
  }
  if (e.value) {
    gizmo = ctl;
    for (const g of gizmos) if (g !== ctl) g.enabled = false;    // one at a time
    interactionStart();
    pivot.updateMatrixWorld(true);
    drag.p0.copy(pivot.matrixWorld);
    drag.startPos.copy(pivot.position);
    drag.items = topLevel().map((obj) => { obj.updateMatrixWorld(true); return { obj, m0: obj.matrixWorld.clone() }; });
    // for the move on the surfaces: where the base of the selection is, from the gizmo
    drag.mine = new Set(drag.items.map((it) => it.obj));
    { const b = selectionBox(drag.items.map((it) => it.obj)); const base = b.getCenter(new THREE.Vector3()); base.z = b.min.z; drag.baseOffset = base.sub(pivot.position); }
    drag.onSurface = false;
    drag.q0 = pivot.quaternion.clone();
    // the up of the selection (of the primary object) and where its base is once it stands straight
    { const prim = byId.get(primary) || drag.items[0].obj;
      const up = _zUp.clone().applyQuaternion(prim.getWorldQuaternion(new THREE.Quaternion())).normalize();
      drag.straight = new THREE.Quaternion().setFromUnitVectors(up, _zUp);
      const b = straightBox(drag.items.map((it) => it.obj), drag.straight, pivot.position);
      if (b.isEmpty()) drag.baseStraight = drag.baseOffset.clone();
      else { const base = b.getCenter(new THREE.Vector3()); base.z = b.min.z; drag.baseStraight = base.sub(pivot.position); }
      // (1.78.4, Luca: «se scelgo il gizmo con le tre frecce gialle … appoggiando il gizmo») a pivot placed by hand is
      // the point that touches the surface, as in the distributions: the model rests on it, not on its lowest point
      if (customPivotShown(drag.items.map((it) => it.obj), prim)) { drag.baseOffset.set(0, 0, 0); drag.baseStraight.set(0, 0, 0); } }
    // Shift held when the drag starts: the original stays (a ghost shows it) and copies are made where it is released
    drag.copy = shiftDown || ptrShift;
    if (drag.copy) for (const it of drag.items) {
      // (14/11: «RangeError: Invalid string length» in the log) clone() copies userData through JSON: the data of a big model
      // (its parts, its points) made a string too long and the copy failed. The data are put aside while the ghost is made
      const kept = [];
      it.obj.traverse((o) => { kept.push([o, o.userData]); o.userData = {}; });
      let g;
      try { g = it.obj.clone(true); } finally { for (const [o, u] of kept) o.userData = u; }
      g.traverse((o) => { o.userData = { helper: true }; if (o.isLight || o.isSprite) o.visible = false; });
      it.obj.parent.add(g);
      drag.ghosts.push(g);
    }
    if (ctl.mode === 'scale') beginScaleDrag(ctl);
    hud.style.left = (mouseX + 18) + 'px'; hud.style.top = (mouseY + 14) + 'px';
    updateHud();
    hud.classList.add('on');
  } else {
    const items = drag.items;
    drag.items = [];
    hud.classList.remove('on');
    sector.visible = false;
    for (const g of drag.ghosts) g.parent && g.parent.remove(g);
    drag.ghosts = [];
    const copy = drag.copy;
    drag.copy = false;
    if (items.length && copy) {
      // the original goes back; the app asks what kind of copies and how many (delta = the movement of the first)
      pivot.updateMatrixWorld(true);
      const delta = pivot.matrixWorld.clone().multiply(drag.p0.clone().invert());
      for (const it of items) setWorldMatrix(it.obj, it.m0);
      const moved = !delta.equals(new THREE.Matrix4());
      if (moved) post({ type: 'shiftCopy', ids: items.map((it) => it.obj.userData.simpler_id), delta: delta.toArray() });
    } else if (items.length) {
      // (Luca: «quando clicco su un oggetto parte il box rosso di aggiornamento dei materiali») a click on the gizmo
      // that does not move anything is not a move: it sent the same matrices, and the engine looked again at the
      // shelter from the rain and the materials of the scene
      const moved = items.some((it) => { it.obj.updateMatrixWorld(true); return !it.obj.matrixWorld.equals(it.m0); });
      if (moved) {
        expectChange();
        post({ type: 'transform', items: items.map((it) => ({ id: it.obj.userData.simpler_id, matrix: it.obj.matrixWorld.toArray() })) });
      }
    }
    placePivot();
    fitShadow();
    scheduleEnd();
    setGizmosEnabled(!locked && !selectMode);
  }
}
for (const g of gizmos) {
  g.addEventListener('objectChange', onGizmoChange);
  g.addEventListener('dragging-changed', (e) => onGizmoDragging(g, e));
}

// ------------------------------------------------------------------ on-screen feedback: value label and rotation sector
const hud = document.getElementById('hud');
let mouseX = 0, mouseY = 0;
renderer.domElement.addEventListener('pointermove', (e) => {
  const r = renderer.domElement.getBoundingClientRect();
  mouseX = e.clientX - r.left; mouseY = e.clientY - r.top;
  if (gizmoDragging()) { hud.style.left = (mouseX + 18) + 'px'; hud.style.top = (mouseY + 14) + 'px'; }
});

function fmtLen(m) {
  const a = Math.abs(m);
  const s = m >= 0 ? '+' : '';
  return a < 0.1 ? s + (m * 1000).toFixed(1) + ' mm' : a < 10 ? s + (m * 100).toFixed(1) + ' cm' : s + m.toFixed(2) + ' m';
}

function updateHud() {
  const axis = gizmo.axis || '';
  let html = '';
  if (gizmo.mode === 'translate') {
    const d = pivot.position.clone().sub(drag.startPos);
    const parts = [];
    for (const a of ['X', 'Y', 'Z']) if (axis.includes(a)) parts.push(`<b class="${a}">${a}</b> ${fmtLen(d[a.toLowerCase()])}`);
    html = parts.join('&nbsp; ') || fmtLen(d.length());
  } else if (gizmo.mode === 'rotate') {
    const deg = THREE.MathUtils.radToDeg(gizmo.rotationAngle || 0);
    const a = axis.length === 1 ? axis : '';
    html = `${a ? `<b class="${a}">${a}</b> ` : ''}${deg >= 0 ? '+' : ''}${deg.toFixed(1)}°`;
    if (gizmo.dragging) drawSector();          // (only while turning: called at rest it drew the last sector again and left it there)
  } else {
    const s = pivot.scale;
    html = Math.abs(s.x - s.y) < 1e-6 && Math.abs(s.y - s.z) < 1e-6
      ? `× ${s.x.toFixed(3)}`
      : ['X', 'Y', 'Z'].filter((a) => axis.includes(a)).map((a) => `<b class="${a}">${a}</b> × ${s[a.toLowerCase()].toFixed(3)}`).join('&nbsp; ');
  }
  if (snapOn !== ctrlDown) html += ' <span class="snap">snap</span>';
  if (drag.onSurface) html += ' <span class="snap">' + tr('appoggiato') + '</span>';
  if (drag.copy) html += ' <span class="snap">' + tr('copia') + '</span>';
  hud.innerHTML = html;
}

const sectorGeo = new THREE.BufferGeometry();
const sector = new THREE.Group();
const sectorFill = new THREE.Mesh(sectorGeo, new THREE.MeshBasicMaterial({ color: 0xffffff, transparent: true, opacity: 0.22, side: THREE.DoubleSide, depthTest: false, depthWrite: false }));
const sectorEdgeGeo = new THREE.BufferGeometry();
const sectorEdge = new THREE.LineSegments(sectorEdgeGeo, new THREE.LineBasicMaterial({ color: 0xffffff, depthTest: false }));
sector.add(sectorFill, sectorEdge);
sectorFill.renderOrder = 1000; sectorEdge.renderOrder = 1001;
sector.visible = false;
noRaycast(sector);
scene.add(sector);

function drawSector() {
  const axis = gizmo.axis;
  if (!axis || axis.length !== 1) { sector.visible = false; return; }
  const center = gizmo.worldPositionStart.clone();
  const worldAxis = gizmo.rotationAxis.clone();
  if (gizmo.space === 'local') worldAxis.applyQuaternion(gizmo.worldQuaternionStart);
  worldAxis.normalize();
  const start = gizmo.pointStart.clone();
  start.sub(worldAxis.clone().multiplyScalar(start.dot(worldAxis)));
  if (start.lengthSq() < 1e-14) { sector.visible = false; return; }
  start.normalize();
  const factor = center.distanceTo(camera.position) * Math.min(1.9 * Math.tan(Math.PI * camera.fov / 360), 7);
  const R = 0.5 * factor * gizmo.size / 4;
  const angle = gizmo.rotationAngle || 0;
  const n = Math.max(2, Math.ceil(Math.abs(angle) / (Math.PI / 64)));
  const pos = [], edge = [];
  const q = new THREE.Quaternion();
  let prev = null;
  for (let i = 0; i <= n; i++) {
    q.setFromAxisAngle(worldAxis, (angle * i) / n);
    const p = start.clone().applyQuaternion(q).multiplyScalar(R).add(center);
    if (prev) pos.push(center.x, center.y, center.z, prev.x, prev.y, prev.z, p.x, p.y, p.z);
    prev = p;
  }
  const first = start.clone().multiplyScalar(R).add(center);
  edge.push(center.x, center.y, center.z, first.x, first.y, first.z, center.x, center.y, center.z, prev.x, prev.y, prev.z);
  sectorGeo.setAttribute('position', new THREE.Float32BufferAttribute(pos, 3));
  sectorEdgeGeo.setAttribute('position', new THREE.Float32BufferAttribute(edge, 3));
  sectorGeo.computeBoundingSphere(); sectorEdgeGeo.computeBoundingSphere();
  const col = AXIS_COLORS[axis] || 0xffffff;
  sectorFill.material.color.setHex(col);
  sectorEdge.material.color.setHex(col);
  sector.visible = true;
}

// ------------------------------------------------------------------ toolbar inside the view (space, pivot, snap, floor)
const toolbar = document.getElementById('toolbar');
function tbButton(label, title, onClick) {
  const b = document.createElement('button');
  b.textContent = label; b.title = title;
  b.addEventListener('click', (e) => { e.stopPropagation(); onClick(); renderer.domElement.focus(); });
  toolbar.appendChild(b);
  return b;
}
function tbSep() { const s = document.createElement('span'); s.className = 'sep'; toolbar.appendChild(s); }
const tb = {};
tb.world = tbButton(tr('Mondo'), tr('Assi del mondo (Q per cambiare)'), () => setSpace('world'));
tb.local = tbButton(tr('Locale'), tr('Assi dell\'oggetto (Q per cambiare)'), () => setSpace('local'));
tbSep();
tb.center = tbButton('◎ ' + tr('Centro 3D'), tr('Gizmo al centro 3D dell\'oggetto: rotazioni e scale attorno al suo cuore'), () => setPivotMode('center'));
tb.base = tbButton('⊥ ' + tr('Base (piedi)'), tr('Gizmo al centro della base, nel punto più basso dell\'oggetto (i piedi di un personaggio): comodo per appoggiarlo su una superficie e ruotarlo sul posto'), () => setPivotMode('base'));
tb.origin = tbButton(tr('Origine'), tr("Gizmo nell'origine dell'oggetto, dove l'aveva messa il programma che l'ha creato"), () => setPivotMode('origin'));
tb.manual = tbButton('✥ ' + tr('Manuale'), tr('Gizmo nel pivot spostato a mano (gizmo viola). Centro 3D, Base e Origine lo ignorano finché non clicchi di nuovo qui'), () => { useCustomPivot = true; placePivot(); updateToolbar(); });
tbSep();
tb.snap = tbButton(tr('Snap'), tr('Scatti di spostamento e del 10% di scala (tieni premuto Ctrl mentre trascini per invertire)'), () => { snapOn = !snapOn; applySnap(); updateToolbar(); });
tb.rot = tbButton('↻ 5°', tr('Scatti di rotazione: clic per cambiare (5° → 15° → 45° → 1° → spenti). Ctrl mentre ruoti li inverte'), () => cycleRotSnap());
tb.floor = tbButton(tr('Appoggia'), tr('Appoggia la selezione sulla superficie sottostante'), () => dropToFloor());
tbSep();
tb.rect = tbButton('▭ ' + tr('Rettangolo'), tr('Selezione a rettangolo: tieni premuto il tasto sinistro e trascina; viene selezionato ciò che sta dentro. Ctrl o Maiusc aggiungono, Alt toglie. Clicca di nuovo (o Esc) per tornare a muovere la vista'),
  () => setSelectMode(selectMode === 'rect' ? '' : 'rect'));
tb.lasso = tbButton('◌ ' + tr('Lazo'), tr('Selezione a lazo: tieni premuto il tasto sinistro e disegna una forma; viene selezionato ciò che sta dentro. Ctrl o Maiusc aggiungono, Alt toglie. Clicca di nuovo (o Esc) per tornare a muovere la vista'),
  () => setSelectMode(selectMode === 'lasso' ? '' : 'lasso'));
tb.rect.classList.add('sel'); tb.lasso.classList.add('sel');
tbSep();
// (1.75.19) the picture of the view as it is now, saved to a file: the path-traced image when it is shown, otherwise
// the real-time view at its full size (no gizmo, no outline)
tb.save = tbButton('⤓ ' + tr('Salva immagine'), tr('Salva in un file l\'immagine della vista come è ora: il path tracing raggiunto finora, o la vista in tempo reale'), () => saveViewImage());
// (1.75.45) it works with nothing selected too: not dimmed with the transform buttons (class «sel», as Rettangolo/Lazo)
tb.save.classList.add('sel');
async function saveViewImage() {
  try {
    if (cyclesImg.classList.contains('on') && engineUrl) {
      const r = await fetch(engineUrl + 'frame', { cache: 'no-store' });
      if (r.ok) {
        const buf = new Uint8Array(await r.arrayBuffer());
        let bin = '';
        for (let i = 0; i < buf.length; i += 0x8000) bin += String.fromCharCode.apply(null, buf.subarray(i, i + 0x8000));
        post({ type: 'saveView', data: btoa(bin), ext: 'jpg', kind: 'pathtracing' });
        return;
      }
    }
    post({ type: 'saveView', data: snapshot(100000, 100000, 0.95), ext: 'jpg', kind: 'realtime' });
  } catch (err) { viewLog('save view: ' + err); }
}

// top-right bar: options of the real-time view
const viewbar = document.getElementById('viewbar');
const vb = {};
{
  const lab = document.createElement('span'); lab.className = 'lab'; lab.textContent = tr('Ombre'); viewbar.appendChild(lab);
  for (const [k, v] of Object.entries(SHADOW_LEVELS)) {
    const b = document.createElement('button');
    b.textContent = v.label;
    b.title = k === 'off' ? tr('Ombre spente nella vista in tempo reale (più veloce)') : tr('Qualità ombre in tempo reale: mappa {0}×{0}', v.map);
    b.addEventListener('click', (e) => { e.stopPropagation(); setShadowLevel(k); post({ type: 'shadows', level: k }); renderer.domElement.focus(); });
    viewbar.appendChild(b);
    vb[k] = b;
  }
}
function updateViewbar() { for (const k of Object.keys(vb)) vb[k].classList.toggle('on', k === shadowLevel); }
// (in the app the shadows are chosen in its bar, in the menu next to «Path tracing»: this bar only for the tests)
if (host) viewbar.style.display = 'none';
setShadowLevel(shadowLevel);

function updateToolbar() {
  const multi = topLevel().length > 1;
  tb.world.classList.toggle('on', multi || space === 'world');
  tb.local.classList.toggle('on', !multi && space === 'local');
  tb.local.disabled = multi;
  const objs = topLevel(), prim = byId.get(primary) || objs[0];
  const hasCustom = objs.length === 1 && !!prim && !!prim.userData.customPivot && !lights.has(prim.userData.simpler_id);
  const manual = hasCustom && (useCustomPivot || pivotEdit);
  for (const m of ['center', 'base', 'origin']) tb[m].classList.toggle('on', !manual && pivotMode === m);
  tb.manual.style.display = hasCustom ? '' : 'none';
  tb.manual.classList.toggle('on', manual);
  tb.snap.classList.toggle('on', snapOn);
  tb.rot.textContent = rotSnapDeg > 0 ? '↻ ' + rotSnapDeg + '°' : '↻ ' + tr('libera');
  tb.rot.classList.toggle('on', rotSnapDeg > 0);
  tb.floor.disabled = !selection.length;
  tb.rect.classList.toggle('on', selectMode === 'rect');
  tb.lasso.classList.toggle('on', selectMode === 'lasso');
  toolbar.classList.toggle('dim', !selection.length);
}
function setSpace(s) { space = s; placePivot(); updateToolbar(); }
function setPivotMode(m, fromHost) { pivotMode = m; if (!fromHost) useCustomPivot = false; placePivot(); updateToolbar(); if (!fromHost) post({ type: 'pivotMode', mode: m }); }
updateToolbar();
applySnap();

function dropToFloor() {
  const objs = topLevel();
  if (!objs.length) return;
  const box = selectionBox(objs);
  if (box.isEmpty()) return;
  const exclude = new Set();
  for (const o of objs) o.traverse((c) => exclude.add(c));
  const targets = [];
  root.traverse((o) => { if (o.isMesh && !o.userData.helper && !exclude.has(o) && isVisible(o)) targets.push(o); });
  const ray = new THREE.Raycaster();
  let best = -Infinity;
  const n = 4;
  for (let i = 0; i <= n; i++) for (let j = 0; j <= n; j++) {
    const x = THREE.MathUtils.lerp(box.min.x, box.max.x, i / n), y = THREE.MathUtils.lerp(box.min.y, box.max.y, j / n);
    // from half its height: a model sunk into the floor (an imported car with the wheels under the ground) finds the
    // floor that cuts it and comes up onto it (from 2% of its height the rays started under the floor and missed it)
    ray.set(new THREE.Vector3(x, y, box.min.z + (box.max.z - box.min.z) * 0.5), new THREE.Vector3(0, 0, -1));
    const hit = ray.intersectObjects(targets, false)[0];
    if (hit) best = Math.max(best, hit.point.z);
    const ph = scatterHits(ray).filter((h) => !exclude.has(h.object.parent)).sort((p, q) => p.distance - q.distance)[0];   // library pieces below
    if (ph) best = Math.max(best, ph.point.z);
    const sh = setHits(ray).filter((h) => !exclude.has(h.object.parent)).sort((p, q) => p.distance - q.distance)[0];   // distributions below
    if (sh) best = Math.max(best, sh.point.z);
  }
  if (best === -Infinity) best = 0;
  const dz = best - box.min.z;
  if (Math.abs(dz) < 1e-7) return;
  const t = new THREE.Matrix4().makeTranslation(0, 0, dz);
  for (const o of objs) { o.updateMatrixWorld(true); setWorldMatrix(o, t.clone().multiply(o.matrixWorld)); }
  expectChange();
  post({ type: 'transform', items: objs.map((o) => ({ id: o.userData.simpler_id, matrix: o.matrixWorld.toArray() })) });
  placePivot(); refreshSelectionBoxes(); fitShadow();
}

// ------------------------------------------------------------------ navigation (Twinmotion-like)
// right drag: orbit around the view target · left drag on empty space: orbit around the point under the mouse
// wheel: walk forward / back along the view, at the chosen speed (walk, bike, car) · middle drag: pan
const SPEEDS = { ant: 0.2, walk: 1, bike: 4, car: 15 };
let speedLevel = 'walk';
// The size the walk is measured on: the scene, but no more than a large building. A forest or a town that reaches the
// horizon (an ecosystem «only where the camera looks» is kilometres deep) made «walk» hundreds of metres a second; in
// a large scene the bike and the car are for the long distances. Kept for a second: the box of the scene walks
// every piece of the distributions, and the keyboard walk asked for it at every frame.
const WALK_REF_MAX = 40;
let _walkRef = 0, _walkRefAt = -1e9;
function walkRef() {
  const now = performance.now();
  if (now - _walkRefAt > 1000) { _walkRef = Math.min(Math.max(sceneRadius(), 0.005), WALK_REF_MAX); _walkRefAt = now; }
  return _walkRef;
}
try { const v = localStorage.getItem('simpler.speed'); if (v && SPEEDS[v]) speedLevel = v; } catch { /* storage unavailable */ }
function setSpeed(level) {
  if (!SPEEDS[level]) return;
  speedLevel = level;
  try { localStorage.setItem('simpler.speed', level); } catch { /* storage unavailable */ }
}

// Touchpad: two fingers up/down/sideways move the view (pan, like the middle button: the scene follows the fingers),
// pinch walks forward/back. A wheel notch of a mouse is a multiple of 120 (wheelDelta) with no sideways part; the
// touchpad sends small, uneven steps (and Chromium sends a pinch as a wheel with Ctrl). Off in the settings: the
// two fingers walk as the wheel does.
let touchpadPan = true;
let _tpUntil = 0, _wheelLogged = 0;
let _panDist = 0;               // metres to what is under the fingers, measured when a gesture starts
function wheelFromTouchpad(e) {
  const now = performance.now();
  if (now >= _tpUntil) _panDist = 0;
  const wd = e.wheelDeltaY || 0, wx = e.wheelDeltaX || 0;
  const mouse = e.deltaMode === 1 || (e.deltaX === 0 && wx === 0 && wd !== 0 && Math.abs(wd) % 120 === 0);
  if (!mouse) _tpUntil = now + 350;          // a gesture goes on: its steps that look like a notch stay touchpad
  return now < _tpUntil;
}
function panDistance(e) {
  // the scene follows the fingers at the depth of what is under the cursor (the orbit centre can be anywhere:
  // right after opening a scene it is often a few metres from the camera, and the pan was invisible)
  const s = surfaceUnder(e.clientX, e.clientY);
  if (s) return Math.max(s.point.distanceTo(camera.position), camera.near * 10);
  const d = camera.position.distanceTo(orbit.target);
  return Math.max(d, sceneRadius() * 0.5, camera.near * 10);
}
function panView(dx, dy, dist) {
  const h = renderer.domElement.clientHeight || 1;
  const wpp = 2 * dist * Math.tan(THREE.MathUtils.degToRad(camera.fov) / 2) / h;     // metres per pixel at the target
  camera.updateMatrixWorld();
  const right = new THREE.Vector3().setFromMatrixColumn(camera.matrixWorld, 0);
  const up = new THREE.Vector3().setFromMatrixColumn(camera.matrixWorld, 1);
  const move = right.multiplyScalar(dx * wpp).addScaledVector(up, -dy * wpp);
  camera.position.add(move);
  orbit.target.add(move);
  orbit.update();
}

// any click or wheel in the view tells the app that the user is working (it closes the news)
let _userInputAt = 0;
function userInput() { const n = performance.now(); if (n - _userInputAt > 1500) { _userInputAt = n; post({ type: 'userInput' }); } }
renderer.domElement.addEventListener('pointerdown', userInput, true);
renderer.domElement.addEventListener('wheel', userInput, { capture: true, passive: true });

renderer.domElement.addEventListener('wheel', (e) => {
  e.preventDefault();
  if (gizmoDragging()) return;
  const pad = wheelFromTouchpad(e);
  if (_wheelLogged < 40) {      // what the mouse and the touchpad send on this computer (app.log), to tune the rule
    _wheelLogged++;
    post({ type: 'wheelLog', text: `dx=${e.deltaX} dy=${e.deltaY} wdx=${e.wheelDeltaX} wdy=${e.wheelDeltaY} mode=${e.deltaMode} ctrl=${e.ctrlKey} pad=${pad} panOn=${touchpadPan}` });
  }
  if (pad && touchpadPan && !e.ctrlKey) {
    const k = e.deltaMode === 1 ? 16 : 1;
    if (!_panDist) {
      _panDist = panDistance(e);
      if (_wheelLogged < 120) { _wheelLogged++; post({ type: 'wheelLog', text: `pan start dist=${_panDist.toFixed(2)} orbit=${camera.position.distanceTo(orbit.target).toFixed(2)} r=${sceneRadius().toFixed(2)}` }); }
    }
    panView(e.deltaX * k, e.deltaY * k, _panDist);
    interactionStart();
    cameraChanged();
    return;
  }
  // a pinch (or a touchpad with pan off) walks smoothly: its steps are small and many
  const notch = pad ? Math.max(-3, Math.min(3, e.deltaY / (e.ctrlKey ? 12 : 100)))
                    : Math.sign(e.deltaY) * Math.min(3, Math.max(1, Math.abs(e.deltaY) / 100));
  let step = walkRef() * 0.05 * SPEEDS[speedLevel] * notch;
  if (e.shiftKey) step *= 0.25;   // Shift: fine steps
  const dir = new THREE.Vector3();
  camera.getWorldDirection(dir);
  const move = dir.multiplyScalar(-step);   // wheel up (deltaY < 0) walks forward
  camera.position.add(move);
  orbit.target.add(move);
  orbit.update();
  interactionStart();
  cameraChanged();
}, { passive: false });

// Right drag orbits around what is in the middle of the view: the orbit centre moves, along the line of sight,
// onto the first surface the camera looks at. Moving it along that line changes nothing on screen (no jump);
// without it, after walking with the wheel the centre stayed at its old distance, often in empty space or behind
// the objects, and the view swung around a point nobody could see.
const _sightRay = new THREE.Raycaster();
function centerOrbitOnView() {
  const dir = new THREE.Vector3();
  camera.getWorldDirection(dir);
  _sightRay.set(camera.position, dir);
  _sightRay.camera = camera;
  const hit = sceneHits(_sightRay).find((h) => h.object.isMesh && !h.object.userData.helper && isVisible(h.object));
  if (!hit || hit.distance < camera.near * 2) return;
  orbit.target.copy(camera.position).addScaledVector(dir, hit.distance);
  orbit.update();
}

// Where new objects and lights go: the surface in the middle of the view (or the orbit centre if there is none).
function viewPoint(sx, sy) {
  // the surface at the centre of the view, or under a point of the view (sx, sy: CSS pixels, e.g. a drop)
  const dir = new THREE.Vector3();
  camera.updateMatrixWorld();
  if (typeof sx === 'number' && typeof sy === 'number') {
    const r = renderer.domElement.getBoundingClientRect();
    _sightRay.setFromCamera(new THREE.Vector2((sx / r.width) * 2 - 1, -(sy / r.height) * 2 + 1), camera);
    dir.copy(_sightRay.ray.direction);
  } else {
    camera.getWorldDirection(dir);
    _sightRay.set(camera.position, dir);
  }
  _sightRay.camera = camera;
  const hit = sceneHits(_sightRay).find((h) => h.object.isMesh && !h.object.userData.helper && isVisible(h.object));
  let point, normal = new THREE.Vector3(0, 0, 1);
  if (hit) {
    point = hit.point.clone();
    if (hit.face) {
      normal = hit.face.normal.clone().transformDirection(hit.object.matrixWorld);
      if (normal.dot(dir) > 0) normal.negate();
    }
  } else point = camera.position.clone().addScaledVector(dir, camera.position.distanceTo(orbit.target));
  const toCm = (v) => v.toArray().map((x) => x / CM);
  let objectId = '', material = '', meshId = '';
  if (hit) {
    objectId = idOf(hit.object);
    // (the piece itself under the mouse, not the model it belongs to: an ecosystem grows on that surface)
    for (let o = hit.object; o && !meshId; o = o.parent) if (o.userData && o.userData.simpler_id) meshId = o.userData.simpler_id;
    let m = hit.object.material;
    if (Array.isArray(m)) m = m[hit.face?.materialIndex ?? 0];
    material = (m && m.name) || '';
  }
  return { point: toCm(point), normal: normal.toArray(), camera: toCm(camera.position), distance: camera.position.distanceTo(point) / CM, hit: !!hit,
           objectId, meshId, material };
}

const orbitPoint = { active: false, pivot: new THREE.Vector3(), lastX: 0, lastY: 0, started: false };
function pointUnderMouse(clientX, clientY) {
  const rect = renderer.domElement.getBoundingClientRect();
  const ndc = new THREE.Vector2(((clientX - rect.left) / rect.width) * 2 - 1, -((clientY - rect.top) / rect.height) * 2 + 1);
  raycaster.setFromCamera(ndc, camera);
  const hit = sceneHits(raycaster).find((h) => h.object.isMesh && !h.object.userData.helper && isVisible(h.object));
  return hit ? hit.point.clone() : null;
}
renderer.domElement.addEventListener('pointermove', (e) => {
  if (!orbitPoint.active) return;
  const dx = e.clientX - orbitPoint.lastX, dy = e.clientY - orbitPoint.lastY;
  if (!orbitPoint.started) {
    if (Math.abs(e.clientX - down.x) + Math.abs(e.clientY - down.y) < 5) return;
    orbitPoint.started = true;
    renderer.domElement.setPointerCapture(e.pointerId);
    interactionStart();
  }
  orbitPoint.lastX = e.clientX; orbitPoint.lastY = e.clientY;
  const P = orbitPoint.pivot;
  const yaw = -dx * 0.006, pitchIn = -dy * 0.006;
  // keep away from the poles: never flip over the top or under the bottom
  const fwd = orbit.target.clone().sub(camera.position).normalize();
  const elev = Math.asin(THREE.MathUtils.clamp(fwd.z, -1, 1));
  const pitch = THREE.MathUtils.clamp(pitchIn, -1.45 - elev, 1.45 - elev);
  const right = new THREE.Vector3().crossVectors(fwd, camera.up).normalize();
  const q = new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(0, 0, 1), yaw)
    .multiply(new THREE.Quaternion().setFromAxisAngle(right, pitch));
  for (const v of [camera.position, orbit.target]) v.sub(P).applyQuaternion(q).add(P);
  orbit.update();
  cameraChanged();
});
function endOrbitPoint(e) {
  if (!orbitPoint.active) return false;
  const was = orbitPoint.started;
  orbitPoint.active = false; orbitPoint.started = false;
  if (was && e && renderer.domElement.hasPointerCapture(e.pointerId)) renderer.domElement.releasePointerCapture(e.pointerId);
  return was;
}

// keyboard walk: arrows = forward/back and sideways, PageUp/PageDown = up/down (Shift = slow)
const keysDown = new Set();
let walkSlow = false;
let lastWalk = performance.now();
function walkStep() {
  const now = performance.now();
  const dt = Math.min(0.1, (now - lastWalk) / 1000);
  lastWalk = now;
  if (!keysDown.size || gizmoDragging()) return;
  let speed = walkRef() * 0.6 * SPEEDS[speedLevel] * dt;
  if (walkSlow) speed *= 0.25;
  const fwd = new THREE.Vector3(); camera.getWorldDirection(fwd);
  const side = new THREE.Vector3().crossVectors(fwd, camera.up).normalize();
  const move = new THREE.Vector3();
  if (keysDown.has('ArrowUp')) move.add(fwd);
  if (keysDown.has('ArrowDown')) move.sub(fwd);
  if (keysDown.has('ArrowRight')) move.add(side);
  if (keysDown.has('ArrowLeft')) move.sub(side);
  if (keysDown.has('PageUp')) move.z += 1;
  if (keysDown.has('PageDown')) move.z -= 1;
  if (move.lengthSq() === 0) return;
  move.normalize().multiplyScalar(speed);
  camera.position.add(move);
  orbit.target.add(move);
  orbit.update();
  interactionStart();
  cameraChanged();
}
const WALK_KEYS = ['ArrowUp', 'ArrowDown', 'ArrowLeft', 'ArrowRight', 'PageUp', 'PageDown'];
window.addEventListener('keydown', (e) => {
  if (WALK_KEYS.includes(e.key)) { e.preventDefault(); if (!keysDown.size) lastWalk = performance.now(); keysDown.add(e.key); }
  walkSlow = e.shiftKey;
});
window.addEventListener('keyup', (e) => { keysDown.delete(e.key); walkSlow = e.shiftKey; });
window.addEventListener('blur', () => keysDown.clear());

// ------------------------------------------------------------------ picking
const raycaster = new THREE.Raycaster();
let down = null;
renderer.domElement.addEventListener('pointerdown', (e) => {
  renderer.domElement.focus();
  if (selectMode && e.button === 0 && !locked && !eyedropping && !pickingFocus) {
    // box / lasso selection: the left button draws instead of turning the view
    down = { x: e.clientX, y: e.clientY, button: 0, sel: true };
    beginAreaSelect(e);
    return;
  }
  down = { x: e.clientX, y: e.clientY, button: e.button };
  if (e.button === 1) {
    // middle drag: the scene follows the mouse at the depth of what is under it when the drag starts. (The pan of
    // OrbitControls went at the distance of the orbit centre: after turning around a surface a few millimetres
    // away - a ring, a glass in front of the camera - the whole view moved by a millimetre at a time.)
    e.preventDefault();
    middlePan = { x: e.clientX, y: e.clientY, dist: panDistance(e) };
    try { renderer.domElement.setPointerCapture(e.pointerId); } catch { /* not capturable */ }
  }
  if (e.button === 2) centerOrbitOnView();
  if (e.button !== 0) interactionStart();
  if (e.button === 0 && !gizmoAxis()) {
    orbitPoint.active = true; orbitPoint.started = false;
    orbitPoint.lastX = e.clientX; orbitPoint.lastY = e.clientY;
    orbitPoint.pivot.copy(pointUnderMouse(e.clientX, e.clientY) || orbit.target);
  }
});
let middlePan = null;
renderer.domElement.addEventListener('pointermove', (e) => {
  if (!middlePan) return;
  if (!(e.buttons & 4)) { middlePan = null; return; }
  const dx = e.clientX - middlePan.x, dy = e.clientY - middlePan.y;
  middlePan.x = e.clientX; middlePan.y = e.clientY;
  if (!dx && !dy) return;
  panView(-dx, -dy, middlePan.dist);
  interactionStart();
  cameraChanged();
});
renderer.domElement.addEventListener('pointerup', (e) => {
  if (e.button === 1) middlePan = null;
  if (!down) return;
  if (down.sel) {
    const moved = Math.abs(e.clientX - down.x) + Math.abs(e.clientY - down.y);
    endAreaSelect(e, moved >= 5);
    if (moved < 5) pick(e);            // a plain click still picks one piece
    down = null;
    return;
  }
  const moved = Math.abs(e.clientX - down.x) + Math.abs(e.clientY - down.y);
  const orbited = endOrbitPoint(e);
  if (down.button === 0 && moved < 5 && !orbited && pickingFocus) { focusAt(e); down = null; return; }
  // (with the line of Area / Spaziatura on screen a plain click does not change the selection: it only lets the view turn)
  if (down.button === 0 && moved < 5 && !orbited && !gizmoDragging() && !gizmoAxis() && !(paint.on && lineTool())) pick(e);
  if (down.button === 2 && moved < 5) contextPick(e);
  down = null;
  scheduleEnd();
});
// a click in the view while the app is locked by an open window (import, material fix): the app says why
renderer.domElement.addEventListener('pointerdown', () => { if (locked) post({ type: 'lockedClick' }); }, true);
renderer.domElement.addEventListener('dblclick', () => {
  // double click: climb to the parent group of the current piece
  if (locked || !primary || gizmoAxis()) return;
  if (pendingInside && performance.now() - pendingInside.t < 800) return;   // (the second click went into the model)
  const p = parentIdOf(primary);
  if (p) { applySelection([p], p); post({ type: 'pick', ids: [p], primary: p }); }
});

let eyedropping = false;
let pendingInside = null;
// the parts of the model are in the view: pick the one where the second click was
function pickAt(rootId) {
  const p = pendingInside;
  pendingInside = null;
  if (!p || p.root !== rootId || performance.now() - p.t > 120000) return;
  const rootNode = byId.get(rootId);
  if (!rootNode) return;
  raycaster.setFromCamera(p.ndc, camera);
  raycaster.camera = camera;
  const hit = sceneHits(raycaster).find((h) => {
    if (!isVisible(h.object) || !h.object.isMesh) return false;
    for (let o = h.object; o; o = o.parent) if (o === rootNode) return true;
    return false;
  });
  const id = hit ? idOf(hit.object) : '';
  if (!id || id === rootId) return;
  applySelection([id], id);
  let mat = hit.object.userData.realMat || hit.object.material;
  if (Array.isArray(mat)) mat = mat[hit.face?.materialIndex ?? 0];
  post({ type: 'pick', ids: selection, primary, material: (mat && mat.name) || '' });
}
function pick(e) {
  if (eyedropping) {
    // material eyedropper: the material of the surface under the mouse (names come from Blender through the glTF)
    eyedropping = false;
    renderer.domElement.style.cursor = selectMode ? 'crosshair' : '';
    const r0 = renderer.domElement.getBoundingClientRect();
    raycaster.setFromCamera(new THREE.Vector2(((e.clientX - r0.left) / r0.width) * 2 - 1, -((e.clientY - r0.top) / r0.height) * 2 + 1), camera);
    // (Luca: «con eyedropper clicco sul pavimento … No material on that surface») a decal lying on the floor
    // (road lines, tyre tracks) took the click: it has no material of the scene. The surface under it is picked.
    const hit = sceneHits(raycaster).find((h) => isVisible(h.object) && h.object.isMesh && !h.object.userData.decalMesh && !h.object.userData.helper);
    if (!hit) { post({ type: 'eyedropper', id: '', material: '' }); return; }
    let mat = hit.object.userData.realMat || hit.object.material;
    if (Array.isArray(mat)) mat = mat[hit.face?.materialIndex ?? 0];
    post({ type: 'eyedropper', id: idOf(hit.object), material: (mat && mat.name) || '' });
    return;
  }
  if (locked) return;
  const r = renderer.domElement.getBoundingClientRect();
  const ndc = new THREE.Vector2(((e.clientX - r.left) / r.width) * 2 - 1, -((e.clientY - r.top) / r.height) * 2 + 1);
  raycaster.setFromCamera(ndc, camera);
  raycaster.camera = camera;
  const hits = sceneHits(raycaster).filter((h) => isVisible(h.object) && (h.object.isMesh || h.object.isSprite));
  // light icons win over geometry behind them
  const hit = hits.find((h) => h.object.isSprite) || hits[0];
  const id = hit ? idOf(hit.object) : '';
  let ids, prim;
  // second click on a library model already selected (alone): the part under the mouse (the app opens the model)
  const hn = id ? byId.get(id) : null;
  if (!e.ctrlKey && !pivotEdit && hn && hn.userData.paintPiece && !hn.userData.paintGen && selection.length === 1 && selection[0] === id) {
    pendingInside = { root: id, ndc: ndc.clone(), t: performance.now() };
    post({ type: 'pickInside', id });
    return;
  }
  if (e.ctrlKey) {
    if (!id) return;
    ids = selection.includes(id) ? selection.filter((x) => x !== id) : [...selection, id];
    prim = ids.includes(id) ? id : primary;
  } else { ids = id ? [id] : []; prim = id; }
  if (pivotEdit && prim) { const r = modelRootOf(prim); if (r) { ids = [r]; prim = r; } }   // (the pivot is of the whole model)
  applySelection(ids, prim);
  // the material of the clicked surface: the material editor follows it
  let mat = hit && hit.object.isMesh ? (hit.object.userData.realMat || hit.object.material) : null;
  if (Array.isArray(mat)) mat = mat[hit.face?.materialIndex ?? 0];
  post({ type: 'pick', ids: selection, primary, material: (!e.ctrlKey && mat && mat.name) || '' });
}

// right click on a piece: it is selected (Ctrl: its group; a piece inside the selection keeps the selection),
// then the app shows its menu
function contextPick(e) {
  if (locked || eyedropping) return;
  const r = renderer.domElement.getBoundingClientRect();
  raycaster.setFromCamera(new THREE.Vector2(((e.clientX - r.left) / r.width) * 2 - 1, -((e.clientY - r.top) / r.height) * 2 + 1), camera);
  const hits = sceneHits(raycaster).filter((h) => isVisible(h.object) && (h.object.isMesh || h.object.isSprite));
  const hit = hits.find((h) => h.object.isSprite) || hits[0];
  const id = hit ? idOf(hit.object) : '';
  if (!id) return;
  // the right button never changes a selection the piece is part of: a piece inside a selected group keeps the
  // group selected (so "Salva nella libreria" saves the whole model, not the piece under the mouse)
  let inSel = '';
  for (let o = byId.get(id); o; o = o.parent) {
    const sid = o.userData && o.userData.simpler_id;
    if (sid && selection.includes(sid)) { inSel = sid; break; }
  }
  let target = id;
  if (inSel) target = inSel;
  else if (e.ctrlKey) { const p = parentIdOf(id); if (p) target = p; }
  if (!inSel) applySelection([target], target);
  else if (primary !== target) applySelection(selection, target);
  let mat = !e.ctrlKey && hit.object.isMesh ? hit.object.material : null;
  if (Array.isArray(mat)) mat = mat[hit.face?.materialIndex ?? 0];
  post({ type: 'context', ids: selection, primary: target, material: (mat && mat.name) || '' });
}

// ------------------------------------------------------------------ box and lasso selection
// What counts is the centre of each piece (as seen on screen): inside the shape = selected. Pieces are the same
// units a click selects (lights included); hidden ones are skipped.
const selSvg = document.getElementById('selshape');
const selPath = selSvg.querySelector('path');
let area = null;                     // { points: [[x, y]], pointerId }
function setSelectMode(m) {
  selectMode = m;
  setGizmosEnabled(!m && !locked);   // while selecting, the left button only draws
  renderer.domElement.style.cursor = m ? 'crosshair' : '';
  updateToolbar();
}
function beginAreaSelect(e) {
  area = { points: [[e.clientX, e.clientY]], pointerId: e.pointerId };
  renderer.domElement.setPointerCapture(e.pointerId);
  drawArea();
}
function drawArea() {
  if (!area) { selSvg.style.display = 'none'; return; }
  const p = area.points;
  let d;
  if (selectMode === 'rect') {
    const [x0, y0] = p[0], [x1, y1] = p[p.length - 1];
    d = `M${x0},${y0}H${x1}V${y1}H${x0}Z`;
  } else d = 'M' + p.map(([x, y]) => `${x},${y}`).join('L') + 'Z';
  selPath.setAttribute('d', d);
  selSvg.style.display = 'block';
}
renderer.domElement.addEventListener('pointermove', (e) => {
  if (!area) return;
  const p = area.points, last = p[p.length - 1];
  if (selectMode === 'rect') { if (p.length > 1) p.pop(); p.push([e.clientX, e.clientY]); }
  else if (Math.abs(e.clientX - last[0]) + Math.abs(e.clientY - last[1]) > 3) p.push([e.clientX, e.clientY]);
  drawArea();
});
function insidePolygon(x, y, poly) {
  let inside = false;
  for (let i = 0, j = poly.length - 1; i < poly.length; j = i++) {
    const [xi, yi] = poly[i], [xj, yj] = poly[j];
    if ((yi > y) !== (yj > y) && x < (xj - xi) * (y - yi) / (yj - yi) + xi) inside = !inside;
  }
  return inside;
}
function endAreaSelect(e, apply) {
  if (!area) return;
  if (renderer.domElement.hasPointerCapture(area.pointerId)) renderer.domElement.releasePointerCapture(area.pointerId);
  const pts = area.points;
  area = null;
  drawArea();
  if (!apply || locked) return;
  let poly = pts;
  if (selectMode === 'rect') {
    const [x0, y0] = pts[0], [x1, y1] = pts[pts.length - 1];
    poly = [[x0, y0], [x1, y0], [x1, y1], [x0, y1]];
  }
  if (poly.length < 3) return;
  // the centre of every piece on screen
  const boxes = new Map();
  root.updateWorldMatrix(true, true);
  root.traverse((o) => {
    if (!(o.isMesh || o.isSprite) || o.userData.helper || !isVisible(o)) return;
    const id = idOf(o);
    if (!id) return;
    let b = boxes.get(id);
    if (!b) { b = new THREE.Box3(); boxes.set(id, b); }
    if (o.isSprite || o.isInstancedMesh) b.expandByPoint(new THREE.Vector3().setFromMatrixPosition(o.matrixWorld));
    else {
      if (!o.geometry.boundingBox) o.geometry.computeBoundingBox();
      b.union(_tmpBox.copy(o.geometry.boundingBox).applyMatrix4(o.matrixWorld));
    }
  });
  // (1.75.63) the pieces drawn from a library model (a car of the library, a painted piece): their node carries no
  // mesh - the model is drawn from its prototype - so the box and the lasso never found them (Luca)
  for (const [id, node] of byId) {
    if (boxes.has(id) || !node.userData.paintPiece || !isVisible(node) || node.userData.paintGen) continue;
    if (node.parent && node.parent.userData.paintPiece) continue;        // (a part inside the model: the model is chosen)
    const b = boxOf(node);
    if (b.isEmpty()) b.expandByPoint(new THREE.Vector3().setFromMatrixPosition(node.matrixWorld));
    boxes.set(id, b);
  }
  const r = renderer.domElement.getBoundingClientRect();
  const found = [];
  const c = new THREE.Vector3();
  for (const [id, b] of boxes) {
    if (b.isEmpty()) continue;
    b.getCenter(c).project(camera);
    if (c.z < -1 || c.z > 1) continue;                 // behind the camera
    const x = r.left + (c.x + 1) / 2 * r.width, y = r.top + (1 - c.y) / 2 * r.height;
    if (insidePolygon(x, y, poly)) found.push(id);
  }
  let ids;
  if (e.altKey) ids = selection.filter((id) => !found.includes(id));
  else if (e.ctrlKey || e.shiftKey) ids = [...selection, ...found];
  else ids = found;
  const prim = ids.includes(primary) ? primary : (found[found.length - 1] || ids[ids.length - 1] || '');
  applySelection(ids, prim);
  post({ type: 'pick', ids: selection, primary, material: '' });
}

// (1.76.31, Luca) the bench of an ecosystem (a flat square): seen three quarters from above, along its diagonal on
// the side the camera is, filling about two thirds of the view - framed as any selection it was seen edge on, a line
function frameBench(id) {
  const o = byId.get(id);
  if (!o) return;
  const box = selectionBox([o]);
  if (box.isEmpty()) return;
  const center = box.getCenter(new THREE.Vector3());
  const up = camera.up.clone().normalize();
  // the two world axes across «up» (the sides of the square)
  const axes = [new THREE.Vector3(1, 0, 0), new THREE.Vector3(0, 1, 0), new THREE.Vector3(0, 0, 1)]
    .filter((a) => Math.abs(a.dot(up)) < 0.5);
  const now = camera.position.clone().sub(orbit.target);
  const s0 = Math.sign(now.dot(axes[0])) || -1, s1 = Math.sign(now.dot(axes[1])) || -1;
  const horiz = axes[0].clone().multiplyScalar(s0).add(axes[1].clone().multiplyScalar(s1)).normalize();
  const el = THREE.MathUtils.degToRad(38);
  const dir = horiz.multiplyScalar(Math.cos(el)).add(up.clone().multiplyScalar(Math.sin(el))).normalize();
  const sz = box.getSize(new THREE.Vector3());
  const side = Math.max(Math.abs(sz.dot(axes[0])), Math.abs(sz.dot(axes[1])));
  const diag = side * Math.SQRT2;
  const half = THREE.MathUtils.degToRad(camera.fov) / 2;
  const hx = Math.atan(Math.tan(half) * camera.aspect);
  // the diagonal across the view at 2/3 of its width (and the square, flattened by the angle, within its height)
  const dist = Math.max(diag / 2 / Math.tan(hx) / 0.7, diag * Math.sin(el) / 2 / Math.tan(half) / 0.7);
  orbit.target.copy(center);
  camera.position.copy(center).add(dir.multiplyScalar(dist));
  orbit.update();
  cameraChanged();
}
function benchNote(m) {
  const el = document.getElementById('benchNote');
  if (!m || !m.show) { el.classList.remove('on'); return; }
  document.getElementById('benchTitle').textContent = m.title || '';
  document.getElementById('benchWhat').textContent = m.text || '';
  // (1.79.0, Luca: «come esco da qui!!») the way out of the bench, where the note is
  const ex = document.getElementById('benchExit');
  ex.textContent = m.exit || '';
  ex.style.display = m.exit ? '' : 'none';
  ex.onclick = (e) => { e.stopPropagation(); post({ type: 'benchExit' }); };
  el.classList.add('on');
}
function frameSelection(ids) {
  const objs = (ids || []).map((id) => byId.get(id)).filter(Boolean);
  const box = objs.length ? selectionBox(objs) : boxOf(root, true);
  if (box.isEmpty()) return;
  const center = box.getCenter(new THREE.Vector3());
  const radius = Math.max(box.getSize(new THREE.Vector3()).length() / 2, 0.005);
  const dir = camera.position.clone().sub(orbit.target).normalize();
  const fov = THREE.MathUtils.degToRad(camera.fov) / 2;
  const dist = radius / Math.sin(Math.min(fov, Math.atan(Math.tan(fov) * camera.aspect))) * 1.15;
  orbit.target.copy(center);
  camera.position.copy(center).add(dir.multiplyScalar(dist));
  orbit.update();
  cameraChanged();
}

// ------------------------------------------------------------------ camera sync
let cameraTimer = 0;
function cameraChanged() {
  clearTimeout(cameraTimer);
  refitShadowsSoon();
  cameraTimer = setTimeout(() => {
    expectChange();
    post({
      type: 'camera',
      position: camera.position.toArray().map((v) => v / CM),
      target: orbit.target.toArray().map((v) => v / CM),
      vfov: camera.fov,
      aspect: camera.aspect,
    });
  }, 180);
  scheduleEnd();
}
orbit.addEventListener('change', () => { interactionStart(); cameraChanged(); });

function setCamera(view) {
  camera.position.fromArray(view.position.map((v) => v * CM));
  orbit.target.fromArray(view.target.map((v) => v * CM));
  if (view.vfov) { camera.fov = view.vfov; camera.updateProjectionMatrix(); }
  orbit.update();
  applyCameraOpts();
  // (15/11, Luca: a project opened with the camera on the bare ground, once) where the camera is put, in the log
  try { const p = camera.position, t = orbit.target; viewLog(`camera set: position ${p.x.toFixed(2)}, ${p.y.toFixed(2)}, ${p.z.toFixed(2)} m, target ${t.x.toFixed(2)}, ${t.y.toFixed(2)}, ${t.z.toFixed(2)} m`); } catch { }
}

// ------------------------------------------------------------------ realistic (Cycles) overlay
const cyclesImg = document.getElementById('cycles');
// Shadows / highlights of the render settings (engine/simpler/tone.py): the same curve on the brightness of each pixel,
// keeping its colour, after the AgX tone mapping - here inside the tone mapping shader of the real-time view. The
// path tracing frame comes already toned from the engine. A change rebuilds the shaders once (on release).
const tone = { s: 0, h: 0, vivid: false };
function toneGlsl(s, h, vivid) {
  const f = (v) => v.toFixed(4);
  return `vec3 CustomToneMapping( vec3 color ) {
	vec3 d = pow( max( ${vivid ? 'NeutralToneMapping' : 'AgXToneMapping'}( color ), vec3( 0.0 ) ), vec3( 1.0 / 2.2 ) );
	float y = dot( d, vec3( 0.2126, 0.7152, 0.0722 ) );
	float y2 = clamp( y + 2.2 * ${f(s)} * y * pow( 1.0 - y, 6.0 ) - 0.8 * ${f(h)} * pow( y, 4.0 ) * ( 1.0 - y ), 0.0, 1.0 );
	d *= y > 1e-5 ? y2 / y : 1.0;
	float m = max( d.r, max( d.g, d.b ) );
	float t = clamp( ( m - 1.0 ) / max( m, 1e-5 ), 0.0, 1.0 );
	d = min( d, vec3( 1.0 ) ) * ( 1.0 - t ) + t;
	return pow( d, vec3( 2.2 ) );
}`;
}
// Luce di riempimento (render.fill_light): a directional light from the camera, a little above it, diffuse only in
// the engine; here without shadows. Strength as the engine: at 100% a 50% grey facing the camera gets 18% at the
// automatic exposure (ev). Light and target ride on the camera.
const fill = { light: null, fraction: 0, ev: 0 };
// (14/11) the fill light is made at the start and never hidden (power 0 when it is off): made or hidden later, it changed the
// number of lights of every shader - a wait of seconds at each change of the render settings
function ensureFill() {
  if (fill.light) return;
  fill.light = new THREE.DirectionalLight(0xffffff, 0);
  fill.light.userData.helper = true;
  fill.light.castShadow = false;
  const a = THREE.MathUtils.degToRad(20);
  fill.light.position.set(0, 0, 0);
  fill.light.target.position.set(0, -Math.sin(a), -Math.cos(a));
  camera.add(fill.light, fill.light.target);
  if (!camera.parent) scene.add(camera);
}
function setFill(fraction, ev) {
  fill.fraction = Math.max(0, Math.min(1, +fraction || 0)); fill.ev = +ev || 0;
  ensureFill();
  if (fill.fraction <= 0.0005) { fill.light.intensity = 0; invalidate(); return; }
  fill.light.intensity = fill.fraction * 0.18 * Math.PI / (0.5 * Math.pow(2, fill.ev));
  invalidate();
}
try { ensureFill(); setFallback(); } catch (err) { console.warn('fill light', err); }
const TONE_BASE = THREE.ShaderChunk.tonemapping_pars_fragment;
function setTone(s, h, vivid) {
  s = Math.max(0, Math.min(1, +s || 0)); h = Math.max(0, Math.min(1, +h || 0)); vivid = !!vivid;
  if (Math.abs(s - tone.s) < 1e-4 && Math.abs(h - tone.h) < 1e-4 && vivid === tone.vivid) return;
  tone.s = s; tone.h = h; tone.vivid = vivid;
  const on = s > 0.001 || h > 0.001;
  THREE.ShaderChunk.tonemapping_pars_fragment = on
    ? TONE_BASE.replace(/vec3 CustomToneMapping\( vec3 color \) \{ return color; \}/, toneGlsl(s, h, vivid)) : TONE_BASE;
  // "Vivida": Khronos PBR Neutral, as the engine (render._apply_common)
  renderer.toneMapping = on ? THREE.CustomToneMapping : (vivid ? THREE.NeutralToneMapping : THREE.AgXToneMapping);
  // every material compiles again with the new curve (its old program is released)
  const seen = new Set();
  scene.traverse((o) => {
    const ms = Array.isArray(o.material) ? o.material : (o.material ? [o.material] : []);
    for (const m of ms) if (!seen.has(m)) { seen.add(m); m.needsUpdate = true; m.dispose(); }
  });
  prepareShaders(tr('Aggiornamento dei materiali nella vista'));
  invalidate();
}
// ------------------------------------------------------------------ camera effects (engine: simpler/post.py)
// On the finished picture, as the engine does on the path tracing frame and the final render: the frame drawn by
// three.js is copied into a texture and drawn again through one shader (and a small blurred copy for the bloom).
// Same order and formulas as post.py; sizes from the frame of the format, not from the pixels. All neutral: no
// copy, no extra pass - nothing costs anything.
const FX = {
  p: { temp: 6500, tint: 0, contrast: 0, saturation: 1, lut: '', lutAmount: 1, bloom: 0, vignette: 0, ca: 0, grain: 0, grainSize: 0.3, sharpen: 0 },
  lutTex: null, lutN: 0, lutId: '', frameTex: null, rtA: null, rtB: null, quad: null, cam: null, mats: null,
};
function fxKelvin(t) {
  t = Math.max(1000, Math.min(40000, t)) / 100;
  const r = t <= 66 ? 255 : 329.698727446 * Math.pow(t - 60, -0.1332047592);
  const g = t <= 66 ? 99.4708025861 * Math.log(t) - 161.1195681661 : 288.1221695283 * Math.pow(t - 60, -0.0755148492);
  const b = t >= 66 ? 255 : (t <= 19 ? 0 : 138.5177312231 * Math.log(t - 10) - 305.0447927307);
  return [r, g, b].map((x) => Math.max(1, Math.min(255, x)) / 255);
}
function fxGain(temp, tint) {
  const a = fxKelvin(6500), b = fxKelvin(temp);
  let g = [0, 1, 2].map((i) => Math.pow(a[i] / b[i], 2.2));
  const t = Math.max(-1, Math.min(1, tint));
  g = [g[0] * (1 + 0.2 * t), g[1] * (1 - 0.2 * t), g[2] * (1 + 0.2 * t)];
  const y = 0.2126 * g[0] + 0.7152 * g[1] + 0.0722 * g[2];
  return g.map((x) => Math.pow(x / y, 1 / 2.2));
}
function fxActive() {
  const p = FX.p;
  return Math.abs(p.temp - 6500) > 1 || Math.abs(p.tint) > 1e-3 || Math.abs(p.contrast) > 1e-3 || Math.abs(p.saturation - 1) > 1e-3
    || (p.lut && FX.lutTex && p.lutAmount > 1e-3) || p.bloom > 1e-3 || p.vignette > 1e-3 || p.ca > 1e-3 || p.grain > 1e-3 || p.sharpen > 1e-3;
}
async function setFx(m) {
  const p = FX.p;
  for (const k of Object.keys(p)) if (m[k] !== undefined && m[k] !== null) p[k] = k === 'lut' ? String(m[k] || '') : +m[k];
  if (p.lut !== FX.lutId) {
    FX.lutId = p.lut;
    if (FX.lutTex) { FX.lutTex.dispose(); FX.lutTex = null; }
    if (p.lut && engineUrl) {
      const want = p.lut;
      try {
        const r = await fetch(`${engineUrl}lut/table?id=${encodeURIComponent(want)}`, { cache: 'no-store' });
        const buf = r.ok ? new Uint8Array(await r.arrayBuffer()) : null;
        if (buf && buf.length > 4 && FX.lutId === want) {
          const n = buf[0] | (buf[1] << 8) | (buf[2] << 16) | (buf[3] << 24);
          const rgba = new Uint8Array(n * n * n * 4);
          for (let i = 0, j = 4; i < n * n * n; i++, j += 3) { rgba[i * 4] = buf[j]; rgba[i * 4 + 1] = buf[j + 1]; rgba[i * 4 + 2] = buf[j + 2]; rgba[i * 4 + 3] = 255; }
          const t = new THREE.Data3DTexture(rgba, n, n, n);
          t.format = THREE.RGBAFormat; t.type = THREE.UnsignedByteType;
          t.minFilter = t.magFilter = THREE.LinearFilter;
          t.wrapS = t.wrapT = t.wrapR = THREE.ClampToEdgeWrapping;
          t.unpackAlignment = 1; t.needsUpdate = true;
          FX.lutTex = t; FX.lutN = n;
        }
      } catch (err) { viewLog('look not loaded: ' + err); }
    }
  }
  invalidate(600);
}
const FX_VERT = 'void main() { gl_Position = vec4(position.xy, 0.0, 1.0); }';
function fxMaterials() {
  if (FX.mats) return FX.mats;
  const common = { vertexShader: FX_VERT, depthTest: false, depthWrite: false, glslVersion: THREE.GLSL3 };
  const bright = new THREE.ShaderMaterial({ ...common,
    uniforms: { tSrc: { value: null }, uRes: { value: new THREE.Vector2() }, uStep: { value: new THREE.Vector2() } },
    fragmentShader: `out highp vec4 fxOut; uniform sampler2D tSrc; uniform vec2 uRes; uniform vec2 uStep;
      void main() {
        // (the bright pass on 16 points of the 8 x 8 block, then their average: as post.py, per pixel then small)
        vec2 uv = gl_FragCoord.xy / uRes;
        vec3 acc = vec3(0.0);
        for (int j = 0; j < 4; j++) for (int i = 0; i < 4; i++) {
          vec3 c = texture(tSrc, uv + uStep * vec2(float(i) - 1.5, float(j) - 1.5)).rgb;
          float k = clamp((dot(c, vec3(0.2126, 0.7152, 0.0722)) - 0.7) / 0.3, 0.0, 1.0);
          acc += c * k * k;
        }
        fxOut = vec4(acc / 16.0, 1.0);
      }` });
  const blur = new THREE.ShaderMaterial({ ...common,
    uniforms: { tSrc: { value: null }, uRes: { value: new THREE.Vector2() }, uDir: { value: new THREE.Vector2() }, uSigma: { value: 1 } },
    fragmentShader: `out highp vec4 fxOut; uniform sampler2D tSrc; uniform vec2 uRes; uniform vec2 uDir; uniform float uSigma;
      void main() {
        vec2 uv = gl_FragCoord.xy / uRes;
        int r = int(min(48.0, ceil(uSigma * 3.0)));
        vec3 acc = vec3(0.0); float wsum = 0.0;
        for (int i = -48; i <= 48; i++) {
          if (i < -r || i > r) continue;
          float w = exp(-0.5 * float(i * i) / (uSigma * uSigma));
          acc += w * texture(tSrc, uv + uDir * float(i) / uRes).rgb; wsum += w;
        }
        fxOut = vec4(acc / wsum, 1.0);
      }` });
  const final = new THREE.ShaderMaterial({ ...common, transparent: false,
    uniforms: {
      tFrame: { value: null }, tBloom: { value: null }, tLut: { value: null }, uRes: { value: new THREE.Vector2() },
      uRect: { value: new THREE.Vector4() }, uGain: { value: new THREE.Vector3(1, 1, 1) }, uContrast: { value: 0 }, uSat: { value: 1 },
      uLutAmt: { value: 0 }, uLutN: { value: 2 }, uBloom: { value: 0 }, uVig: { value: 0 }, uCA: { value: 0 }, uGrain: { value: 0 },
      uCell: { value: 1 }, uSharpen: { value: 0 },
    },
    fragmentShader: `precision highp sampler3D; out highp vec4 fxOut;
      uniform sampler2D tFrame; uniform sampler2D tBloom; uniform sampler3D tLut;
      uniform vec2 uRes; uniform vec4 uRect; uniform vec3 uGain;
      uniform float uContrast, uSat, uLutAmt, uLutN, uBloom, uVig, uCA, uGrain, uCell, uSharpen;
      vec4 px(vec2 p) { return texture(tFrame, p / uRes); }
      float h1(vec2 q) { return fract(sin(dot(q, vec2(127.1, 311.7))) * 43758.5453); }
      float gauss(vec2 q) { return (h1(q) + h1(q + 17.31) + h1(q + 41.97) - 1.5) * 2.0; }
      void main() {
        vec2 p = gl_FragCoord.xy;
        vec2 c = uRect.xy + 0.5 * uRect.zw;
        float halfd = 0.5 * length(uRect.zw);
        vec4 src = px(p);
        vec3 col = src.rgb;
        if (uCA > 0.0) {
          float k = uCA * 0.006;
          col = vec3(px(c + (p - c) * (1.0 - k)).r, col.g, px(c + (p - c) * (1.0 + k)).b);
        }
        if (uSharpen > 0.0) {
          vec3 b = (4.0 * src.rgb + 2.0 * (px(p + vec2(1, 0)).rgb + px(p - vec2(1, 0)).rgb + px(p + vec2(0, 1)).rgb + px(p - vec2(0, 1)).rgb)
                   + px(p + vec2(1, 1)).rgb + px(p - vec2(1, 1)).rgb + px(p + vec2(1, -1)).rgb + px(p - vec2(1, -1)).rgb) / 16.0;
          col = clamp(col + uSharpen * 1.5 * (src.rgb - b), 0.0, 1.0);
        }
        if (uBloom > 0.0) {
          vec3 g = texture(tBloom, p / uRes).rgb;
          col = 1.0 - (1.0 - col) * (1.0 - clamp(g * uBloom * 2.0, 0.0, 1.0));
        }
        col = clamp(col * uGain, 0.0, 1.0);
        if (abs(uContrast) > 0.0) col += uContrast * (col * col * (3.0 - 2.0 * col) - col);
        if (abs(uSat - 1.0) > 0.0) { float y = dot(col, vec3(0.2126, 0.7152, 0.0722)); col = clamp(y + (col - y) * uSat, 0.0, 1.0); }
        if (uLutAmt > 0.0) {
          vec3 l = texture(tLut, clamp(col, 0.0, 1.0) * ((uLutN - 1.0) / uLutN) + 0.5 / uLutN).rgb;
          col = mix(col, l, uLutAmt);
        }
        if (uVig > 0.0) {
          float s = clamp((length(p - c) / halfd - 0.35) / 0.7, 0.0, 1.0);
          col *= pow(1.0 - uVig * 0.75 * s * s * (3.0 - 2.0 * s), 1.0 / 2.2);
        }
        if (uGrain > 0.0) {
          vec2 q = (p - 0.5) / uCell, i = floor(q), f = fract(q);
          float n = mix(mix(gauss(i), gauss(i + vec2(1, 0)), f.x), mix(gauss(i + vec2(0, 1)), gauss(i + vec2(1, 1)), f.x), f.y);
          if (uCell > 1.0) n *= 1.4;
          float y = dot(col, vec3(0.2126, 0.7152, 0.0722));
          col += n * uGrain * 0.10 * (0.25 + 3.0 * y * (1.0 - y));
        }
        fxOut = vec4(clamp(col, 0.0, 1.0), src.a);
      }` });
  FX.mats = { bright, blur, final };
  FX.cam = new THREE.OrthographicCamera(-1, 1, 1, -1, 0, 1);
  FX.quad = new THREE.Mesh(new THREE.PlaneGeometry(2, 2), final);
  FX.quad.frustumCulled = false;
  return FX.mats;
}
function fxPass(mat, target) {
  FX.quad.material = mat;
  renderer.setRenderTarget(target);
  renderer.render(FX.quad, FX.cam);
}
// After the scene is drawn on the screen (before the outlines and the gizmos): the effects on it.
function fxApply() {
  // (audit 1.78.5) SmartView: speed first - no finishing effects (a copy of the frame and their passes at every frame)
  if (!fxActive() || _smartOn) return;
  const m = fxMaterials(), p = FX.p;
  const size = renderer.getDrawingBufferSize(new THREE.Vector2());
  const W = size.x, H = size.y;
  if (!FX.frameTex || FX.frameTex.image.width !== W || FX.frameTex.image.height !== H) {
    if (FX.frameTex) FX.frameTex.dispose();
    FX.frameTex = new THREE.FramebufferTexture(W, H);
    FX.frameTex.minFilter = FX.frameTex.magFilter = THREE.LinearFilter;
  }
  renderer.copyFramebufferToTexture(FX.frameTex);
  // the frame of the format inside the view (as the engine: post.frame_rect)
  let fw = W, fh = H;
  if (frameAspect) { fh = W / frameAspect; if (fh > H) { fh = H; fw = H * frameAspect; } }
  const rect = new THREE.Vector4((W - fw) / 2, (H - fh) / 2, fw, fh);
  const halfd = 0.5 * Math.hypot(fw, fh);
  const am = renderer.autoClear, tm = renderer.toneMapping;
  renderer.autoClear = false;
  renderer.toneMapping = THREE.NoToneMapping;
  try {
    if (p.bloom > 1e-3) {
      const f = 8, bw = Math.max(1, Math.floor(W / f)), bh = Math.max(1, Math.floor(H / f));
      for (const k of ['rtA', 'rtB']) {
        if (!FX[k] || FX[k].width !== bw || FX[k].height !== bh) {
          if (FX[k]) FX[k].dispose();
          FX[k] = new THREE.WebGLRenderTarget(bw, bh, { minFilter: THREE.LinearFilter, magFilter: THREE.LinearFilter, depthBuffer: false });
        }
      }
      m.bright.uniforms.tSrc.value = FX.frameTex; m.bright.uniforms.uRes.value.set(bw, bh); m.bright.uniforms.uStep.value.set(2 / W, 2 / H);       // (16 points 2 pixels apart cover the block)
      fxPass(m.bright, FX.rtA);
      const sigma = 0.02 * 2 * halfd / f;
      m.blur.uniforms.uSigma.value = sigma;
      m.blur.uniforms.tSrc.value = FX.rtA.texture; m.blur.uniforms.uRes.value.set(bw, bh); m.blur.uniforms.uDir.value.set(1, 0);
      fxPass(m.blur, FX.rtB);
      m.blur.uniforms.tSrc.value = FX.rtB.texture; m.blur.uniforms.uDir.value.set(0, 1);
      fxPass(m.blur, FX.rtA);
    }
    const u = m.final.uniforms;
    u.tFrame.value = FX.frameTex; u.tBloom.value = FX.rtA ? FX.rtA.texture : FX.frameTex;
    u.tLut.value = FX.lutTex; u.uLutN.value = FX.lutN || 2; u.uLutAmt.value = (p.lut && FX.lutTex) ? p.lutAmount : 0;
    u.uRes.value.set(W, H); u.uRect.value.copy(rect);
    u.uGain.value.fromArray(fxGain(p.temp, p.tint));
    u.uContrast.value = p.contrast; u.uSat.value = p.saturation; u.uBloom.value = p.bloom; u.uVig.value = p.vignette;
    u.uCA.value = p.ca; u.uGrain.value = p.grain; u.uSharpen.value = p.sharpen;
    u.uCell.value = Math.max(1, (1 + 3 * p.grainSize) * fh / 1080);
    fxPass(m.final, null);
  } finally {
    renderer.autoClear = am;
    renderer.toneMapping = tm;
    renderer.setRenderTarget(null);
  }
}
const badge = document.getElementById('badge');
// the badge text lives in a span: a thin bar under it shows the progress of long preparations
const badgeText = document.createElement('span');
const badgeBar = document.createElement('i');
badgeBar.className = 'bar';
badge.textContent = '';
badge.append(badgeText, badgeBar);
function setBadge(text, fraction = null, kind = null) {
  badgeText.textContent = text;
  if (kind !== null) badge.className = kind;
  const on = fraction !== null && fraction !== undefined;
  badge.classList.toggle('progress', on);
  badgeBar.style.width = on ? Math.round(Math.max(0, Math.min(1, fraction)) * 100) + '%' : '0';
}
let engineUrl = params.get('engine') || '';
if (engineUrl) { busyWarn.polling = true; setTimeout(busyPoll, 0); }
let realistic = false;
let lastVersion = -1, polling = false;
// (1.75.57) the finished path tracing, cut like the scene thumbnails: the app makes it the thumbnail of the scene just
// opened, if nothing changed since (views.pt_thumb). Once per picture.
let ptThumbVersion = -1;
function ptSnapshot(maxW = 320, maxH = 200) {
  const c = renderer.domElement, iw = cyclesImg.naturalWidth, ih = cyclesImg.naturalHeight;
  if (!iw || !ih || !c.width || !c.height) return '';
  let sw = c.width, sh = c.height;
  if (frameAspect) { sh = sw / frameAspect; if (sh > c.height) { sh = c.height; sw = sh * frameAspect; } }
  const kx = iw / c.width, ky = ih / c.height;            // (the picture is stretched over the whole view)
  const sx = (c.width - sw) / 2 * kx, sy = (c.height - sh) / 2 * ky, w = sw * kx, h = sh * ky;
  const k = Math.min(maxW / w, maxH / h, 1);
  const out = document.createElement('canvas');
  out.width = Math.max(1, Math.round(w * k)); out.height = Math.max(1, Math.round(h * k));
  const g = out.getContext('2d');
  g.imageSmoothingQuality = 'high';
  g.drawImage(cyclesImg, sx, sy, w, h, 0, 0, out.width, out.height);
  return out.toDataURL('image/jpeg', 0.88).split(',')[1];
}
// A Cycles frame is shown only when it was rendered for the current scene/camera state (epoch) and the user
// is not interacting; while moving, the real-time view is shown and the overlay comes back by itself.
let interacting = false, endTimer = 0;
let lastCurrent = -1, needEpochAbove = -1; // after sending a change, wait until the engine has seen it
function expectChange() { needEpochAbove = lastCurrent; }
function scheduleEnd() { clearTimeout(endTimer); endTimer = setTimeout(interactionEnd, 260); }

function interactionStart() {
  if (!realistic || interacting) return;
  interacting = true;
  cyclesImg.classList.remove('on');
  setBadge(tr('Tempo reale (in movimento)'), null, '');
}
function interactionEnd() { interacting = false; }

function fmtElapsed(sec) {
  const s = Math.floor(sec), m = Math.floor(s / 60);
  return m + ':' + String(s % 60).padStart(2, '0');
}
const _ptCam = { ver: -1, m: new THREE.Matrix4(), p: new THREE.Matrix4() };   // the view of the picture shown (pollCycles)
let realisticGen = 0;      // a new number at every switch: an answer that arrives after a switch is dropped
async function pollCycles() {
  if (!realistic || !engineUrl || polling) return;
  polling = true;
  const gen = realisticGen;
  const stale = () => gen !== realisticGen || !realistic;
  try {
    const info = await (await fetch(engineUrl + 'frame/info', { cache: 'no-store' })).json();
    if (stale()) { polling = false; return; }
    lastCurrent = info.current;
    const current = info.epoch !== undefined && info.epoch === info.current && info.current > needEpochAbove;
    if (current && info.version !== lastVersion) {
      const resp = await fetch(engineUrl + 'frame', { cache: 'no-store' });
      if (resp.status === 200) {
        const blob = await resp.blob();
        if (stale()) { polling = false; return; }
        const old = cyclesImg.src;
        cyclesImg.src = URL.createObjectURL(blob);
        await cyclesImg.decode().catch(() => {});
        if (old.startsWith('blob:')) URL.revokeObjectURL(old);
        lastVersion = info.version;
        // (the real-time view chosen while the picture was arriving: it stays the real-time view)
        if (stale()) { cyclesImg.classList.remove('on'); polling = false; return; }
      }
    }
    if (info.error) {
      cyclesImg.classList.remove('on');
      setBadge(tr('Path tracing non riuscito: {0}', info.error), null, 'cycles error');
      badge.title = info.error;
    } else if (current && lastVersion === info.version && !interacting && !down && !gizmoDragging()) {
      // (1.78.5, Luca) a frame at once when the picture appears: the canvas must turn transparent over it - the still
      // view is no longer redrawn every 2 s, and the real-time frame stayed on top of the path tracing passes
      if (!cyclesImg.classList.contains('on')) { cyclesImg.classList.add('on'); invalidate(300); }
      if (_ptCam.ver !== info.version) { _ptCam.ver = info.version; _ptCam.m.copy(camera.matrixWorld); _ptCam.p.copy(camera.projectionMatrix); }
      const done = info.pass + 1 >= info.passes;
      // (14/11, Luca: «non si capisce se va o è bloccato») while the next pass is computed: its samples done so far, or what the
      // engine is doing and for how long (info.prep, the same news as the first picture)
      let more = '';
      if (!done && info.prep) {
        const what = (info.prep.detail || '').split(' · ')[0] || info.prep.phase || '';
        if (what) more = ' · ' + what;
        if (info.prep.elapsed >= 1) more += ' · ' + fmtElapsed(info.prep.elapsed);
      }
      setBadge(done ? tr('Path tracing · ✓ finito · {0} campioni', info.samples) : (more ? tr('Path tracing · passaggio {0}/{1}', info.pass + 1, info.passes) + more : tr('Path tracing · passaggio {0}/{1} · sto affinando…', info.pass + 1, info.passes)), null, done ? 'cycles' : 'cycles running');
      if (done && ptThumbVersion !== info.version) {
        ptThumbVersion = info.version;
        try { const t = ptSnapshot(); if (t) post({ type: 'ptDone', thumb: t }); } catch (e) { /* (a picture that cannot be read) */ }
      }
    } else if (!current) {
      // (14/11, Luca: «non vedo più l'avanzamento 1/5 … 5/5», «Switching to real time ma nessuno ha premuto realtime») a change that
      // comes from the app (ambience, a material, a light) with the view where it was: the picture of before STAYS until
      // the new one arrives. Before, it went away, the real-time view was drawn under it and made its shaders again
      // (20-80 s with the page still, log of Luca): the passes computed meanwhile were never shown. The real-time view
      // is prepared when it is really looked at (a move, or the real-time mode)
      const keep = cyclesImg.classList.contains('on') && !interacting && !down && !gizmoDragging() && info.current > needEpochAbove
        && _ptCam.ver !== -1 && _ptCam.m.equals(camera.matrixWorld) && _ptCam.p.equals(camera.projectionMatrix);
      if (!keep) cyclesImg.classList.remove('on');
      if (!interacting) {
        const p = info.prep;
        if (p && p.elapsed >= 1) {
          // a big scene: say what Cycles is doing and for how long, so it is clear it is not stuck
          // most useful first (count, time left), the file name last: it is cut when the view is narrow
          const [count, ...rest] = (p.detail || '').split(' · ');
          const parts = [p.phase];
          if (count) parts.push(count);
          parts.push(p.eta ? tr('≈ {0} rimanenti', fmtElapsed(p.eta)) : fmtElapsed(p.elapsed));
          if (p.memory) parts.push(tr('memoria {0}', p.memory));
          if (rest.length) parts.push(rest.join(' · '));
          setBadge(tr('Path tracing · {0}', parts.join(' · ')), p.fraction ?? null, 'cycles');
        } else setBadge(tr('Path tracing · calcolo…'), null, 'cycles');
        badge.title = '';
      }
    }
  } catch { /* engine busy: retry */ }
  polling = false;
}
setInterval(pollCycles, 120);

function setRealistic(on) {
  realistic = on;
  realisticGen++;
  interacting = false;
  invalidate(600);
  toolbar.classList.toggle('hidden', false);
  if (!on) { cyclesImg.classList.remove('on'); setBadge(boxMode ? tr('Sagome') : tr('Tempo reale'), null, ''); }
  else setBadge(tr('Path tracing · in preparazione…'), null, 'cycles');
}

// ------------------------------------------------------------------ photographic camera: focal length, lens shift, frame guide, click-to-focus
let shiftX = 0, shiftY = 0, frameAspect = 0, pickingFocus = false;
const frameEl = document.getElementById('frame');
function setLens(mm) {
  const a = camera.aspect;
  const half = Math.atan(18 / Math.max(1, mm));
  const vfov = a >= 1 ? 2 * Math.atan(Math.tan(half) / a) : 2 * half;
  camera.fov = THREE.MathUtils.radToDeg(vfov);
  camera.updateProjectionMatrix();
  cameraChanged();
}
function applyCameraOpts() {
  const w = container.clientWidth, h = container.clientHeight;
  if (!w || !h) return;
  const big = Math.max(w, h);
  if (Math.abs(shiftX) > 1e-6 || Math.abs(shiftY) > 1e-6) camera.setViewOffset(w, h, shiftX * big, -shiftY * big, w, h);
  else camera.clearViewOffset();
  camera.updateProjectionMatrix();
  // frame guide: largest rectangle with the render's proportions (same rule as the engine's final render)
  if (!frameAspect) { frameEl.style.display = 'none'; return; }
  let fw = w, fh = w / frameAspect;
  if (fh > h) { fh = h; fw = h * frameAspect; }
  frameEl.style.display = 'block';
  frameEl.style.left = ((w - fw) / 2) + 'px'; frameEl.style.top = ((h - fh) / 2) + 'px';
  frameEl.style.width = fw + 'px'; frameEl.style.height = fh + 'px';
}
new ResizeObserver(applyCameraOpts).observe(container);
function startFocusPick() { pickingFocus = true; renderer.domElement.style.cursor = 'crosshair'; }
function focusAt(e) {
  pickingFocus = false;
  renderer.domElement.style.cursor = '';
  const r = renderer.domElement.getBoundingClientRect();
  const ndc = new THREE.Vector2(((e.clientX - r.left) / r.width) * 2 - 1, -((e.clientY - r.top) / r.height) * 2 + 1);
  raycaster.setFromCamera(ndc, camera);
  const hit = sceneHits(raycaster).find((x) => x.object.isMesh && !x.object.userData.helper && isVisible(x.object));
  if (!hit) return;
  const fwd = new THREE.Vector3(); camera.getWorldDirection(fwd);
  const depth = hit.point.clone().sub(camera.position).dot(fwd);   // distance of the focus plane along the view axis
  post({ type: 'focus', distance: depth / CM });
}


// New objects only (a primitive, a model dropped in): a small file added to the view, not the whole scene again.
// Messages that arrive meanwhile (the structure, materials and positions of the same change) wait for it.
let partLoading = null;
const partQueue = [];
// Objects already in the view with a new geometry (new UV of «Adatta all'oggetto»): their meshes take the geometry
// of the small file, everything else stays (materials, shaders, place, selection). 1.70.3: before, the whole scene
// was prepared again (20 s on a big model). Anything unexpected: the whole view again, as before.
function replaceGeometry(gltf, ids) {
  // (1.76.50) -> the ids that could not be swapped here (null: nothing at all could be done). Before, any of them
  // failing - a zone of a terrain empty before and after (no mesh at all: «Sabbia» of a mountain), a zone that
  // appeared or went - sent the whole view to be prepared again: 37 times in Luca's logs, at every terrain change
  const fresh = new Map();
  gltf.scene.traverse((o) => { const id = o.userData && o.userData.simpler_id; if (id) fresh.set(id, o); });
  const pairs = [], retry = [];
  for (const id of ids) {
    const old = byId.get(id), neu = fresh.get(id);
    if (old && old.userData.paintPiece) return null;
    const om = old ? [...new Set(ownMeshes(old))] : [], nm = neu ? [...new Set(ownMeshes(neu))] : [];
    if (!om.length && !nm.length) continue;                  // (empty before and after: nothing to draw)
    if (!old || om.length !== nm.length || om.some((m) => m.isInstancedMesh) || nm.some((m) => m.isInstancedMesh)) {
      retry.push(id);                                          // (its pieces changed: brought again whole, below)
      continue;
    }
    for (let i = 0; i < om.length; i++) pairs.push([om[i], nm[i]]);
  }
  const usedBy = new Map();      // (a geometry shared by several meshes of the view: replaced for all of them)
  root.traverse((o) => { if (o.isMesh && o.geometry) { const l = usedBy.get(o.geometry) || []; l.push(o); usedBy.set(o.geometry, l); } });
  for (const [om, nm] of pairs) {
    const g = om.geometry;
    if (g === nm.geometry) continue;
    for (const m of usedBy.get(g) || [om]) m.geometry = nm.geometry;
    if (g.boundsTree) g.disposeBoundsTree();
    g.dispose();
    nm.geometry = new THREE.BufferGeometry();     // (the file's own copy no longer owns it)
  }
  disposeTree(gltf.scene);                        // (its materials and textures: the view keeps its own)
  // the objects whose pieces changed: out of the view, to come back with their materials (the app asks: partRetry)
  for (const id of retry) {
    const node = byId.get(id);
    if (!node) continue;
    if (node.parent) node.parent.remove(node);
    byId.delete(id);
    node.traverse((c) => { if (c.isMesh && c.geometry) { if (c.geometry.boundsTree) c.geometry.disposeBoundsTree(); c.geometry.dispose(); } });
  }
  return retry;
}

async function addPart(url, ids, replace) {
  const t0 = performance.now();
  let gltf;
  try {
    gltf = await loader.loadAsync(url);
  } catch (err) {
    post({ type: 'needReload', reason: 'part not loaded: ' + err });
    return;
  }
  if (replace) {
    const retry = replaceGeometry(gltf, ids || []);
    if (!retry) { disposeTree(gltf.scene); post({ type: 'needReload', reason: 'geometry not replaced' }); return; }
    invalidate(600);
    post({ type: 'partLoaded', objects: (ids || []).length - retry.length, ms: Math.round(performance.now() - t0) });
    if (retry.length) post({ type: 'partRetry', ids: retry });
    return;
  }
  const want = new Set(ids || []);
  // a library model opened for its parts: its placeholder (drawn from the prototype) gives way to the real pieces
  for (const id of want) {
    const node = byId.get(id);
    if (node && node.userData.paintPiece) { scatterRelease(node); if (node.parent) node.parent.remove(node); byId.delete(id); }
  }
  const tops = [];
  gltf.scene.traverse((o) => {
    const id = o.userData && o.userData.simpler_id;
    if (id && want.has(id) && !byId.has(id)) {
      let p = o.parent, inside = false;
      for (; p; p = p.parent) if (p.userData && want.has(p.userData.simpler_id)) { inside = true; break; }
      if (!inside) tops.push(o);
    }
    if (o.isMesh) { o.castShadow = o.receiveShadow = !o.userData.volNoShadow; }
    if (o.isInstancedMesh) o.userData.gltfInstances = true;
  });
  for (const o of tops) root.attach(o);       // under their parents with the structure that follows
  let n = 0;
  for (const o of tops) o.traverse((c) => { const id = c.userData && c.userData.simpler_id; if (id) { byId.set(id, c); graveyard.delete(id); n++; } });
  indexMaterials(root);
  prepareShaders(tr('Preparazione della vista 3D'));
  post({ type: 'partLoaded', objects: n, ms: Math.round(performance.now() - t0) });
}

// ------------------------------------------------------------------ messages from the host
// (Luca: «ogni cambio di slider o valore DEVE mostrare la modifica») the view draws only while it is «invalidated» (a few
// hundred ms after a message): a change that finished later than that (a distribution made again, a model arriving, shaders
// made) stayed on the screen only when the mouse moved. Now every message from the app is followed by a last redraw
// (scatter included) when the messages stop, and a message shown late is written in the log with the time it took.
let _settleTimer = 0, _msgPending = null, _settleScatter = false;
// messages that change nothing of the picture (the busy box and its progress, tasks, toasts, the mouse, the camera and
// the tools): no extra redraw for them - some come every few hundred ms during a long job
const SETTLE_SKIP = new Set(['busy', 'busyNow', 'working', 'task', 'toast', 'touchpad', 'speed', 'tool', 'lock', 'pickAt', 'pickFocus',
  'viewPoint', 'eyedropper', 'benchNote', 'cameraOpts', 'frameBench', 'setCamera', 'lens', 'frame', 'releaseAll', 'log', 'redraw']);
// the ones that change the pieces of distributions and models: the scatter is computed again too (the others only draw)
const SETTLE_SCATTER = new Set(['paint', 'paintSeed', 'paintGroup', 'areaUpdate', 'addPart', 'structure', 'materials', 'load', 'sync', 'clone']);
function settleRedraw(type) {
  if (SETTLE_SKIP.has(type)) return;
  if (SETTLE_SCATTER.has(type)) _settleScatter = true;
  clearTimeout(_settleTimer);
  _settleTimer = setTimeout(() => { if (_settleScatter) { _settleScatter = false; scatter.dirty = true; } invalidate(500); }, 700);
}
let partSince = 0;
function onMessage(msg) {
  invalidate(600);
  if (msg && !SETTLE_SKIP.has(msg.type)) {
    if (!_msgPending) _msgPending = { type: String(msg.type), t: performance.now() };
    settleRedraw(msg.type);
  }
  if (msg && msg.type === 'addPart') {
    const run = () => addPart(msg.url, msg.ids, !!msg.replace);
    if (!partLoading) partSince = performance.now();
    partLoading = (partLoading || Promise.resolve()).then(run).finally(() => {
      partLoading = null;
      const q = partQueue.splice(0);
      for (const m of q) onMessage(m);
    });
    return;
  }
  // the messages wait while a model is being loaded: if it takes too long they go on anyway (a load that never ends froze
  // every slider of the app)
  if (partLoading && performance.now() - partSince > 25000) viewLog('a model is loading for more than 25 s: the messages of the app go on');
  // (15/11, Luca: the previews of the looks on a chart of colours, then an error: the picture of the view asked by the app waited
  // 28 s behind a model - it only reads the view, it never has to wait)
  else if (partLoading && msg.type !== 'snapshot') { partQueue.push(msg); return; }
  if (msg && msg.type === 'boxes') { setBoxMode(msg.on); return; }
  switch (msg.type) {
    case 'init': engineUrl = msg.engine; if (!busyWarn.polling) { busyWarn.polling = true; busyPoll(); } break;
    case 'ambience': setAmbience(msg.info); break;
    case 'ocean': oceanSet(msg.info); break;
    case 'rainPreview': wetSet({ state: { mode: msg.mode, rain: msg.rain, snow: msg.snow } }); break;
    case 'puddleBrush': setPuddleBrush(msg); break;
    case 'terrainSculptUndo': terrainUndo(); break;
    case 'terrainSculptFlush': terrainSculptCommit(); break;
    case 'dirtPaint': if (msg.info) DIRT.pending.shift(); else DIRT.pending = []; dirtFetch(msg.info || null); break;
    case 'dirtRefresh': DIRT.asked = false; dirtAsk(); break;
    case 'load': loadScene(msg.url, !!msg.big).then(() => { if (typeof msg.frame === 'string') frameSelection(msg.frame ? [msg.frame] : []); }); break;
    case 'sync':
      lastSync = msg.objects || [];
      applySync(lastSync);
      if (selection.length) { placePivot(); refreshSelectionBoxes(); }
      updateToolbar();             // «Manuale» shows only while the selected model has a pivot moved by hand
      fitShadow();
      break;
    case 'lightPreview': {
      const L = lights.get(msg.id);
      if (L && msg.sun) previewSun(msg.id, msg.sun);
      else if (L) updateLight(msg.id, msg.kind || L.kind, { ...L.data, ...msg.light });
      break;
    }
    case 'select':
      // a part of a library model (drawn from its prototype, merged by material): the app sends its materials, the
      // outline shows only that part and the gizmo stays away (it would move the whole model)
      partMats = Array.isArray(msg.parts) && msg.parts.length ? new Set(msg.parts) : null;
      applySelection(msg.ids || (msg.id ? [msg.id] : []), msg.primary || msg.id);
      break;
    case 'tool': setGizmoTool(msg.mode); updateToolbar(); break;
    case 'pickAt': pickAt(msg.root); break;
    case 'pivotEdit': setPivotEdit(!!msg.on); break;
    case 'visible': { const o = byId.get(msg.id); if (o) o.visible = msg.visible; break; }
    case 'frame': frameSelection(msg.ids || (msg.id ? [msg.id] : [])); break;
    case 'frameBench': frameBench(msg.id); break;
    case 'benchNote': benchNote(msg); break;
    case 'setCamera': setCamera(msg.view); break;
    case 'mode': setRealistic(!!msg.realistic); break;
    case 'releaseAll': releaseAll(); break;
    case 'redraw': viewDiag('before «Ridisegna la vista»'); releaseAll(); break;
    case 'touchpad': touchpadPan = !!msg.on; break;
    case 'busy': case 'task': working.owner = false; setBusy(msg.text, msg.fraction ?? null, msg.detail || ''); break;
    case 'toast': showToast(msg.text || '', msg.seconds || 3); break;
    case 'working':
      // the app waits for the engine (a drag, a material on many pieces): busy cursor and, if no other task has the
      // pill, a small pill saying what is going on
      document.body.classList.toggle('working', !!msg.on);
      busyWarn.appWorking = !!msg.on; busyWarn.appText = msg.text || '';
      if (msg.on) {
        if (working.owner || !taskEl.classList.contains('on')) { working.owner = true; setBusy(msg.text, null, msg.detail || ''); }
      } else if (working.owner) { working.owner = false; setBusy(''); }
      break;
    case 'shadows': setShadowLevel(msg.level); break;
    case 'speed': setSpeed(msg.level); break;
    case 'viewLight': setViewLight(msg); break;
    case 'smartView': setSmartView(msg.on); break;
    case 'snowHidden': if (msg.hidden) { mantleSync(null); flakesSync(null); } snowState(_snowState.present, !!msg.hidden); if (WET.pollWake) WET.pollWake(); break;
    case 'paint': setPaint(msg); break;
    case 'paintDone': paintDone(msg); break;
    case 'paintGroup': setPaintGroup(msg); break;
    case 'paintSeed': setPaintSeed(msg.seed); break;
    case 'areaUpdate': areaRebuild(true); break;
    case 'pivotMode': if (['base', 'center', 'origin'].includes(msg.mode)) setPivotMode(msg.mode, true); break;
    case 'lens': setLens(msg.mm); break;
    case 'tone': setTone(msg.s, msg.h, msg.vivid); break;
    case 'fill': setFill(msg.fraction, msg.ev); break;
    case 'fx': setFx(msg); break;
    case 'cameraOpts': shiftX = msg.shiftX || 0; shiftY = msg.shiftY || 0; frameAspect = msg.aspect || 0; applyCameraOpts(); break;
    case 'pickFocus': startFocusPick(); break;
    case 'dropToFloor': dropToFloor(); break;
    case 'eyedropper': eyedropping = true; renderer.domElement.style.cursor = 'crosshair'; break;
    case 'structure': if (!applyStructure(msg.objects, msg.removed, msg.closed)) post({ type: 'needReload', reason: needReason }); break;
    case 'clone': if (!applyClones(msg.copies)) post({ type: 'needReload', reason: needReason }); break;
    case 'materials': if (!applyMaterials(msg.items)) post({ type: 'needReload', reason: needReason }); break;
    case 'busyNow':
      // the app starts something that will keep the view busy (a new ambience, a light): the box at once
      busyWarn.hold = true; busyWarn.holdFresh = true; busyWarn.holdFrames = 3; busyWarn.holdAt = performance.now();
      busyWarn.holdWhat = msg.what || '';
      busyTick();
      invalidate(300);
      break;
    case 'lock':
      locked = !!msg.on;
      lockedByWindow = locked && !!msg.window;
      setGizmosEnabled(!locked && !selectMode);
      document.body.classList.toggle('locked', locked);
      document.body.classList.toggle('lockwork', locked && !lockedByWindow);   // (full hourglass only then)
      break;
    case 'viewPoint': post({ type: 'viewPoint', id: msg.id, ...viewPoint(msg.x, msg.y) }); break;
    case 'snapshot': {
      let data = '';
      try { data = snapshot(msg.w || 320, msg.h || 200, msg.q || 0.85); } catch (e) { console.error(e); }
      post({ type: 'snapshot', id: msg.id, data });
      break;
    }
  }
}
if (host) host.addEventListener('message', (e) => onMessage(e.data));
window.simplerMessage = onMessage; // for tests

// keyboard: Q and Shift are handled here; the other shortcuts go to the host
// (WebView2 keeps the focus while the mouse is over the 3D view)
window.addEventListener('keydown', (e) => {
  if (e.key === 'Shift') { shiftDown = true; return; }
  if (e.key === 'Control') { ctrlDown = true; applySnap(); if (gizmoDragging()) updateHud(); }
  if (e.repeat) return;
  const k = e.key.length === 1 ? e.key.toLowerCase() : e.key;
  if (k === 'q' && !e.ctrlKey) { setSpace(space === 'world' ? 'local' : 'world'); e.preventDefault(); return; }
  // (1.76.44) Ctrl+Z while sculpting the terrain: the last stroke of the session, here (the engine has none yet)
  if (k === 'z' && e.ctrlKey && !e.shiftKey && puddle.on && puddle.layer === 'terrain' && TS.strokes.length) { terrainUndo(); e.preventDefault(); return; }
  if (paint.on && paint.mode === 'brush' && (k === '[' || k === ']')) {
    paint.radius = Math.max(0.05, Math.min(500, paint.radius * (k === ']' ? 1.15 : 1 / 1.15)));
    brush.scale.setScalar(paint.radius);
    post({ type: 'paintRadius', radius: paint.radius });
    e.preventDefault(); return;
  }
  if (areaKey(k)) { e.preventDefault(); return; }
  if (paint.on && k === 'Escape') { post({ type: 'paintExit' }); e.preventDefault(); return; }
  if (k === 'Escape' && eyedropping) { eyedropping = false; renderer.domElement.style.cursor = selectMode ? 'crosshair' : ''; return; }
  if (k === 'Escape' && selectMode) { if (area) { area = null; drawArea(); } setSelectMode(''); return; }
  if (['w', 'e', 'r', 'f', 'd', 's', 'o', 'n', 'i', 'z', 'y', 'a', 'c', 'v', 'Delete', 'Escape', ' ', 'End'].includes(k)) {
    e.preventDefault();
    post({ type: 'key', key: k, ctrl: e.ctrlKey, shift: e.shiftKey });
  }
});
window.addEventListener('keyup', (e) => {
  if (e.key === 'Shift') shiftDown = false;
  if (e.key === 'Control') { ctrlDown = false; applySnap(); if (gizmoDragging()) updateHud(); }
});
window.addEventListener('blur', () => { shiftDown = false; ctrlDown = false; applySnap(); });
window.addEventListener('dragover', (e) => e.preventDefault());
window.addEventListener('drop', (e) => e.preventDefault());
renderer.domElement.addEventListener('contextmenu', (e) => e.preventDefault());

// ------------------------------------------------------------------ snapshot of the real-time view (scene thumbnails)
// Instant, whatever the size of the scene: a thumbnail only has to show the framing, it is not path traced.
function snapshot(maxW = 320, maxH = 200, q = 0.85) {
  const hidden = [];
  const hide = (o) => { if (o && o.visible) { o.visible = false; hidden.push(o); } };
  gizmos.forEach((g) => hide(g.getHelper())); hide(sector);
  selectionHelpers.forEach(hide);
  // (14/11, found with Luca's log: «slow frame: 101390 ms, 63 new shaders» when a scene was chosen) NEVER a light: the spare lights
  // (reserveLights) are helpers too, and hiding them for the thumbnail changed the number of lights of the view - three.js made
  // the shader of every material again, inside this frame, for the picture of one thumbnail, and again at every thumbnail
  scene.traverse((o) => { if (o.userData && o.userData.helper && !o.userData.glow && !o.isLight) hide(o); });
  try {
    renderer.render(scene, camera);
    const c = renderer.domElement, W = c.width, H = c.height;
    let sw = W, sh = H;
    if (frameAspect) { sh = W / frameAspect; if (sh > H) { sh = H; sw = H * frameAspect; } }
    const sx = (W - sw) / 2, sy = (H - sh) / 2;
    const k = Math.min(maxW / sw, maxH / sh, 1);
    const out = document.createElement('canvas');
    out.width = Math.max(1, Math.round(sw * k)); out.height = Math.max(1, Math.round(sh * k));
    const g = out.getContext('2d');
    g.imageSmoothingQuality = 'high';
    g.drawImage(c, sx, sy, sw, sh, 0, 0, out.width, out.height);
    return out.toDataURL('image/jpeg', q).split(',')[1];     // (q 0.95: the view for the AI)
  } finally {
    hidden.forEach((o) => { o.visible = true; });
  }
}

// ------------------------------------------------------------------ render loop
// light icons: always the same small size on screen, whatever the scale of the light or of its groups
// (a sprite without size attenuation is still multiplied by the scale of its parents)
const _iconScale = new THREE.Vector3();
const ICON_SIZE = 0.045;           // fraction of the view height
// (and of the lens: without size attenuation a sprite still grows when the field of view narrows - a long lens
// made the icons huge)
const ICON_FOV_REF = Math.tan(THREE.MathUtils.degToRad(35) / 2);
function keepIconsSmall() {
  const k = ICON_SIZE * Math.tan(THREE.MathUtils.degToRad(camera.fov) / 2) / ICON_FOV_REF;
  for (const L of lights.values()) {
    if (!L.sprite) continue;
    L.node.getWorldScale(_iconScale);
    L.sprite.scale.set(k / (Math.abs(_iconScale.x) || 1), k / (Math.abs(_iconScale.y) || 1), 1);
  }
}

// ------------------------------------------------------------------ selection outline
// The selected pieces are drawn white into a mask (only them, layer 10, no shadows), then a full-screen pass draws an
// orange line where the mask ends. While the path-traced picture is shown the 3D canvas is transparent and carries
// nothing (the canvas sits above the picture, transparent: the picture stays clean, without outline).
const OUTLINE_LAYER = 10;
const OUTLINE_PX = 2.5;
const maskRT = new THREE.WebGLRenderTarget(1, 1);
// (position only, no fog, no uv: the program does not depend on the textures and attributes of the piece - one per kind
// of mesh - and is made at start: see warmOutline)
const maskMat = new THREE.ShaderMaterial({
  side: THREE.DoubleSide, fog: false,
  vertexShader: `#include <common>
#include <batching_pars_vertex>
#include <morphtarget_pars_vertex>
#include <skinning_pars_vertex>
void main() {
#include <batching_vertex>
#include <skinbase_vertex>
#include <begin_vertex>
#include <morphinstance_vertex>
#include <morphtarget_vertex>
#include <skinning_vertex>
#include <project_vertex>
}`,
  fragmentShader: 'void main() { gl_FragColor = vec4(1.0); }',
});
const outlineMat = new THREE.ShaderMaterial({
  uniforms: { mask: { value: maskRT.texture }, texel: { value: new THREE.Vector2(1, 1) }, width: { value: OUTLINE_PX }, color: { value: new THREE.Color(0xf2a43a) } },
  vertexShader: 'varying vec2 vUv; void main() { vUv = uv; gl_Position = vec4(position.xy, 0.0, 1.0); }',
  fragmentShader: `uniform sampler2D mask; uniform vec2 texel; uniform float width; uniform vec3 color; varying vec2 vUv;
void main() {
  if (texture2D(mask, vUv).r > 0.5) discard;           // inside the piece: nothing (only the contour)
  float hit = 0.0;
  for (int i = 0; i < 16; i++) {
    float a = 6.2831853 * float(i) / 16.0;
    vec2 d = vec2(cos(a), sin(a)) * texel;
    hit = max(hit, texture2D(mask, vUv + d * width).r);
    hit = max(hit, texture2D(mask, vUv + d * width * 0.5).r * 1.0);
  }
  if (hit < 0.02) discard;
  gl_FragColor = vec4(color, hit);
}`,
  transparent: true, depthTest: false, depthWrite: false,
});
const outlineScene = new THREE.Scene();
const outlineQuad = new THREE.Mesh(new THREE.PlaneGeometry(2, 2), outlineMat);
outlineQuad.frustumCulled = false;
outlineScene.add(outlineQuad);
const outlineCam = new THREE.OrthographicCamera(-1, 1, 1, -1, 0, 1);
const _dbs = new THREE.Vector2();
const OUTLINE_WARM = new THREE.Color(0xf2a43a), OUTLINE_PART = new THREE.Color(0x4fc3f7);
// a selected piece inside an opened library model (not the model itself)
function insideOpenModel(o) {
  for (let p = o.parent; p; p = p.parent) if (p.userData && p.userData.openModel) return true;
  return false;
}
// The two programs of the outline (mask and contour) are made with the other shaders (prepareShaders), not at the first
// selection (a click that froze the view while three.js linked them). The mask program knows the lights of the view
// (same set as the frame, see renderOutline), so it is made in the same state: layer of the mask, the lights on it
let _outlineDummy = null;
function warmOutline() {
  try {
    if (!_outlineDummy) { _outlineDummy = new THREE.Mesh(new THREE.PlaneGeometry(1, 1), maskMat); _outlineDummy.layers.set(OUTLINE_LAYER); _outlineDummy.frustumCulled = false; _outlineDummy.userData = { helper: true }; }
    scene.add(_outlineDummy);
    const bg = scene.background, mask = camera.layers.mask, ov = scene.overrideMaterial;
    const lit = lightList()
      .filter((L) => L && L.isLight && !L.layers.isEnabled(OUTLINE_LAYER));
    for (const L of lit) L.layers.enable(OUTLINE_LAYER);
    scene.background = null; scene.overrideMaterial = maskMat; camera.layers.set(OUTLINE_LAYER);
    try { renderer.setRenderTarget(maskRT); renderer.compile(scene, camera); } finally {
      renderer.setRenderTarget(null);
      for (const L of lit) L.layers.disable(OUTLINE_LAYER);
      camera.layers.mask = mask; scene.background = bg; scene.overrideMaterial = ov; scene.remove(_outlineDummy);
    }
    renderer.compile(outlineScene, outlineCam);
  } catch (err) { console.warn('outline warm', err); }
}
function renderOutline() {
  const marked = [];
  const tops = topLevel();
  outlineMat.uniforms.color.value.copy(tops.length && tops.every(insideOpenModel) ? OUTLINE_PART : OUTLINE_WARM);
  for (const o of tops) o.traverse((c) => {
    if (!c.isMesh || c.userData.helper || !isVisible(c)) return;
    if (partMats && !matNames(c.material).some((n) => partMats.has(n))) return;    // only the chosen part
    c.layers.enable(OUTLINE_LAYER); marked.push(c);
  });
  if (!marked.length) return;
  renderer.getDrawingBufferSize(_dbs);
  if (maskRT.width !== _dbs.x || maskRT.height !== _dbs.y) maskRT.setSize(_dbs.x, _dbs.y);
  outlineMat.uniforms.texel.value.set(1 / _dbs.x, 1 / _dbs.y);
  outlineMat.uniforms.width.value = OUTLINE_PX * renderer.getPixelRatio();
  const bg = scene.background, auto = renderer.shadowMap.autoUpdate, mask = camera.layers.mask, tm = renderer.toneMapping;
  scene.background = null;
  scene.overrideMaterial = maskMat;
  renderer.shadowMap.autoUpdate = false;
  camera.layers.set(OUTLINE_LAYER);
  // (the lights seen by the mask too: the same set of lights as the frame, so three.js does not see a new state of the
  // lights twice a frame and look again at the shader of every material - a cost at every frame with a selection)
  const lit = lightList()     // (ALL the lights of the frame, the spare ones too: the same state of lights, see lightList)
    .filter((L) => L && L.isLight && !L.layers.isEnabled(OUTLINE_LAYER));
  for (const L of lit) L.layers.enable(OUTLINE_LAYER);
  const cc = renderer.getClearColor(new THREE.Color()), ca = renderer.getClearAlpha();
  renderer.setRenderTarget(maskRT);
  renderer.setClearColor(0x000000, 1);
  renderer.clear();
  renderer.render(scene, camera);
  renderer.setRenderTarget(null);
  renderer.setClearColor(cc, ca);
  for (const L of lit) L.layers.disable(OUTLINE_LAYER);
  camera.layers.mask = mask;
  renderer.shadowMap.autoUpdate = auto;
  scene.overrideMaterial = null;
  scene.background = bg;
  renderer.toneMapping = tm;
  for (const c of marked) c.layers.disable(OUTLINE_LAYER);
  const autoClear = renderer.autoClear;
  renderer.autoClear = false;
  renderer.render(outlineScene, outlineCam);
  renderer.autoClear = autoClear;
}

// ------------------------------------------------------------------ Distribuisci > Pennello (paint models on surfaces)
// The app sends the palette (library models with a weight) and the brush settings. Dragging with the left button
// places pieces under the brush: random points in the circle, each one dropped on the surface below, kept apart by
// the spacing (with a random part), model chosen by weight, random rotation and scale. Shift + drag erases the
// pieces of the painting under the brush. Small markers show what was painted until the engine has made the real
// objects (they arrive as instances). [ and ] change the size of the brush, Esc leaves the brush.
const paint = {
  on: false, radius: 1.5, spacing: 0.8, spacingRand: 0.3, scale: 1, scaleRand: 0.2, rot: 0, rotRand: 1, align: false,
  palette: [], group: '', painting: false, erasing: false, last: null, grid: new Map(), erased: new Set(),
  eraseIds: [], batch: 0, strokes: [], items: [], seed: 0, editing: false, local: { by: new Map(), done: 0, inv: null },
  // the fixed pieces of the distribution (an ecosystem put back on the bench to be changed): always first in the
  // items, the strokes add to them and erase them (paint.py BASE_KEY)
  baseItems: [], basePalette: '',
  // Area (see below)
  mode: 'brush', tension: 50, prob: 1, falloff: false, falloffDist: 2, snap: true,
  // Spaziatura (see below)
  byCount: false, count: 10, step: 2, stepRand: 0, lateral: 0, randomOrder: false, follow: true,
};
const lineTool = () => paint.mode === 'area' || paint.mode === 'spacing';      // modes drawn with points
// the brush: a light green disc with a solid rim, well visible on light and dark ground (red while erasing)
const BRUSH_GREEN = 0x6ee07f, BRUSH_RED = 0xff7a6e;
const brushMat = new THREE.MeshBasicMaterial({ color: BRUSH_GREEN, transparent: true, opacity: 1, depthTest: false, depthWrite: false, side: THREE.DoubleSide });
const brushFill = new THREE.MeshBasicMaterial({ color: BRUSH_GREEN, transparent: true, opacity: 0.28, depthTest: false, depthWrite: false, side: THREE.DoubleSide });
const brush = new THREE.Group();
{
  const ring = new THREE.Mesh(new THREE.RingGeometry(0.95, 1, 96), brushMat);
  const fill = new THREE.Mesh(new THREE.CircleGeometry(0.95, 64), brushFill);
  for (const m of [ring, fill]) { m.renderOrder = 998; m.userData.helper = true; brush.add(m); }
  brush.userData.helper = true; brush.visible = false;
  scene.add(brush);
}
const _pr = new THREE.Raycaster();
function paintGroupNode() { return paint.group ? byId.get(paint.group) : null; }
function paintingNew() { return !!(paint.on && !paint.group); }
function inPainting(o) { const g = paintGroupNode(); for (let p = o; p; p = p.parent) if (p === g) return true; return false; }
// (15/11, Luca: «ho due montagne… volevo continuare lo scatter lì sopra ma non funziona») a model put in the scene from the
// library is drawn from its prototype (scatter.nodes: an empty node, its parts drawn as copies): for the brush, the area
// and everything that asks «what surface is here» it was not there at all - only the clicks saw it (scatterHits). The
// first mountain was an imported file (real meshes), the second came from the library: nothing could be put on it.
// Here its parts as meshes at full detail (never drawn, only to be hit), for surfaceHits, paintSurfaces and areaSurfaces.
function pieceSurfaces(near) {
  const out = [];
  for (const node of scatter.nodes) {
    if (scatter.shown.has(node) || node.userData.ghost || !node.parent || !isVisible(node) || inPainting(node)) continue;
    const P = protoOf(node);
    if (!P || P.state !== 'ready') continue;
    _ssph.center.copy(P.center).applyMatrix4(node.matrixWorld);
    _ssph.radius = P.radius * node.matrixWorld.getMaxScaleOnAxis();
    if (near && !near(_ssph)) continue;
    for (const part of P.parts) {
      const g = part.geom;
      if (!g || (part.mat && part.mat.userData && part.mat.userData.volume)) continue;      // (a cloud is not a surface)
      if (!g.boundsTree && g.index !== undefined) { try { g.computeBoundsTree(); } catch (e) { /* no tree: plain test */ } }
      const m = new THREE.Mesh(g, part.mat);
      m.matrixAutoUpdate = false;
      m.matrix.copy(part.rel);
      m.matrixWorld.multiplyMatrices(node.matrixWorld, part.rel);
      m.parent = node;               // (not added to it: only so that «whose surface is this» finds the model)
      out.push(m);
    }
  }
  return out;
}
function surfaceHits(ray) {
  const hits = ray.intersectObject(root, true).filter((h) => h.object.isMesh && !h.object.userData.helper && isVisible(h.object) && !inPainting(h.object));
  {
    const ph = ray.intersectObjects(pieceSurfaces((sp) => ray.ray.intersectsSphere(sp)), false);
    if (ph.length) { hits.push(...ph); hits.sort((a, b) => a.distance - b.distance); }
  }
  // (1.76.26) the library models of the scene drawn from their prototype (after «Ridisegna la vista», a Poly Haven
  // cliff): they are surfaces too - before, a click on them went through, to the ground under them
  // (1.79.0, Luca) not the new distribution being painted: it is drawn under '' until the engine gives it its id, and
  // its own trees were taken as ground - the next touches put trees on the tops of the first ones
  const sh = scatter.sets.has('') && !paintingNew() ? setHits(ray, true) : [];
  if (sh.length) { hits.push(...sh); hits.sort((a, b) => a.distance - b.distance); }
  return hits;
}
function hitNormal(h) {
  const n = h.face ? h.face.normal.clone().transformDirection(h.object.matrixWorld) : new THREE.Vector3(0, 0, 1);
  if (n.dot(_pr.ray.direction) > 0) n.negate();
  return n.normalize();
}
function surfaceUnder(clientX, clientY) {
  const r = renderer.domElement.getBoundingClientRect();
  camera.updateMatrixWorld();      // (the view may not have drawn since the camera moved: path tracing shown, idle)
  _pr.setFromCamera(new THREE.Vector2(((clientX - r.left) / r.width) * 2 - 1, -((clientY - r.top) / r.height) * 2 + 1), camera);
  const h = surfaceHits(_pr)[0];
  if (!h) return null;
  let mat = h.object.material;
  if (Array.isArray(mat)) mat = mat[h.face?.materialIndex ?? 0];
  return { point: h.point.clone(), normal: hitNormal(h), mat: (mat && mat.name) || '' };
}
function gridKey(p, c) { return Math.floor(p.x / c) + ',' + Math.floor(p.y / c) + ',' + Math.floor(p.z / c); }
function gridAdd(p) { const c = Math.max(0.01, paint.spacing); const k = gridKey(p, c); (paint.grid.get(k) || paint.grid.set(k, []).get(k)).push(p.clone()); }
function gridNear(p, d) {
  const c = Math.max(0.01, paint.spacing);
  const ix = Math.floor(p.x / c), iy = Math.floor(p.y / c), iz = Math.floor(p.z / c);
  const span = Math.ceil(d / c);
  for (let x = -span; x <= span; x++) for (let y = -span; y <= span; y++) for (let z = -span; z <= span; z++) {
    const list = paint.grid.get((ix + x) + ',' + (iy + y) + ',' + (iz + z));
    if (list) for (const q of list) if (q.distanceTo(p) < d) return true;
  }
  return false;
}
// The distribution is made from its strokes: every brush position (with its size) and every erased spot is kept,
// and the pieces come from them with the present settings, always in the same way (random numbers drawn from the
// seed of the distribution and the number of the stroke). So changing spacing, scale, rotation, presence or the
// models afterwards re-makes the whole distribution in the view at once, and the engine follows (paint/set).
function mulberry(seed) {
  let a = seed >>> 0;
  return () => { a = (a + 0x6D2B79F5) >>> 0; let t = a; t = Math.imul(t ^ (t >>> 15), t | 1); t ^= t + Math.imul(t ^ (t >>> 7), t | 61); return ((t ^ (t >>> 14)) >>> 0) / 4294967296; };
}
function paintResetItems() {
  paint.items = [];
  paint.grid = new Map();
  paintAlive = 0; paintLocalReset();
}
function pickModel(u) {
  const list = paint.palette.filter((p) => p.weight > 0);
  const tot = list.reduce((a, p) => a + p.weight, 0);
  let r = u * tot;
  for (const p of list) { r -= p.weight; if (r <= 0) return p.model; }
  return list.length ? list[list.length - 1].model : null;
}
// each model of the brush can have its own settings (Avanzate under its row): its scale (× the general one), its
// random scale and random turn (instead of the general ones, when set) and a turn of its own (+ the general one)
function itemAngle(it, base, uRot) {
  const rr = it && it.rotRand != null ? it.rotRand : paint.rotRand;
  return base + THREE.MathUtils.degToRad((it && it.rot) || 0) + (uRot * 2 - 1) * Math.PI * rr;
}
function itemScale(it, uScale) {
  const sr = it && it.scaleRand != null ? it.scaleRand : paint.scaleRand;
  return paint.scale * (it && it.scale != null ? it.scale : 1) * (1 + (uScale * 2 - 1) * sr);
}
const _up = new THREE.Vector3(0, 0, 1);
// surfaces under a stroke: the meshes near it, with a search tree (three-mesh-bvh) so the thousands of tries of a
// stroke are fast also on big models
function paintSurfaces(center, radius) {
  const out = [];
  const sph = new THREE.Sphere(center, radius);
  root.traverse((o) => {
    if (!o.isMesh || o.isInstancedMesh || o.userData.helper || !isVisible(o) || inPainting(o) || !o.layers.test(camera.layers)) return;
    if (!o.geometry.boundingBox) o.geometry.computeBoundingBox();
    if (!_tmpBox.copy(o.geometry.boundingBox).applyMatrix4(o.matrixWorld).intersectsSphere(sph)) return;
    if (!o.geometry.boundsTree && o.geometry.index !== undefined) { try { o.geometry.computeBoundsTree(); } catch (e) { /* no tree: plain test */ } }
    out.push(o);
  });
  out.push(...pieceSurfaces((sp) => sp.intersectsSphere(sph)));        // (the library models of the scene: see pieceSurfaces)
  // (1.76.26, Luca) the library models of the scene drawn from their prototype are surfaces too: after «Ridisegna la
  // vista» a cliff of Poly Haven was one of them, and a change of the scale made the brush again without it - the
  // whole distribution fell to the ground under the cliff. Their pieces near the stroke, as meshes of their own
  const set = paintingNew() ? null : scatter.sets.get('');     // (1.79.0: not the pieces just painted - see surfaceHits)
  const f = set && setFrame(set);
  if (set && f && f.visible) {
    for (const b of set.blocks) {
      const P = blockProto(b);
      if (!P || P.state !== 'ready') continue;
      const c = blockCentres(b, P);
      for (let i = 0; i < b.count; i++) {
        _ssph.center.set(c[i * 4], c[i * 4 + 1], c[i * 4 + 2]);
        _ssph.radius = c[i * 4 + 3];
        if (!_ssph.intersectsSphere(sph)) continue;
        const M = new THREE.Matrix4().fromArray(b.xf, i * 16);
        if (P.place) M.multiply(P.place);
        for (const part of P.parts) {
          const g = part.geom;
          if (!g.boundsTree && g.index !== undefined) { try { g.computeBoundsTree(); } catch (e) { /* plain test */ } }
          const m = new THREE.Mesh(g, part.mat);
          m.matrixAutoUpdate = false;
          m.matrixWorld.multiplyMatrices(M, part.rel);
          out.push(m);
        }
      }
    }
  }
  return out;
}
// one stroke position: new pieces (or, erasing, the pieces under it go)
// (1.78.4) limits of the brush: a big radius with a small distance asked thousands of pieces at every touch (10.5 m
// and 0.17 m: 3,600 each, 120,000 in a few seconds of a heavy grass - the view froze). At most PAINT_DAB_MAX new
// pieces per touch, and a distribution holds at most PAINT_TRI_BUDGET triangles at full detail (counted on its
// heaviest model, once its shape is known), between PAINT_MIN_ITEMS and PAINT_MAX_ITEMS pieces. The user's values
// are left as they are: the bar says what was held back and the distance that fits.
const PAINT_DAB_MAX = 2000, PAINT_TRI_BUDGET = 250e6, PAINT_MIN_ITEMS = 2000, PAINT_MAX_ITEMS = 300000;
// (15/11, Luca: «devo riempire una montagna di alberi … perché devo fermarmi a 2000 quando me ne serviranno 50.000») the limit
// counted the triangles of the model at FULL detail (250 M / a tree of 125,000 triangles = 2,000 trees), but the pieces are
// copies of one model: far ones are drawn with the lightest level or not at all (the view's own budget, scatterUpdate), and the
// path tracing draws them as instances. What a distribution costs is the NUMBER of its pieces, whatever the model: one limit,
// PAINT_MAX_ITEMS. (The freeze of 1.78.4 came from thousands of pieces per touch: PAINT_DAB_MAX stays.)
function paintMaxItems() { return PAINT_MAX_ITEMS; }
let paintAlive = 0;
function paintLimitInfo(state, extra) {
  const now = performance.now();
  if (paint.infoAt && now - paint.infoAt < 1500 && paint.infoState === state) return;
  paint.infoAt = now; paint.infoState = state;
  post(Object.assign({ type: 'paintInfo', state }, extra));
}
function paintApplyStroke(st, index) {
  const R = st.r, P = new THREE.Vector3().fromArray(st.p);
  if (st.e) {
    const R2 = R * R;
    let gone = false;
    for (const it of paint.items) if (it.alive && it.pos.distanceToSquared(P) <= R2) { it.alive = false; gone = true; paintAlive--; }
    if (gone) gridRebuild();
    return;
  }
  if (!paint.palette.some((p) => p.weight > 0)) return;
  const rnd = mulberry((paint.seed * 7919 + index * 104729) | 0);
  const n = new THREE.Vector3().fromArray(st.n).normalize(), sp = Math.max(0.02, paint.spacing);
  const t1 = new THREE.Vector3().crossVectors(Math.abs(n.z) < 0.9 ? _up : new THREE.Vector3(1, 0, 0), n).normalize();
  const t2 = new THREE.Vector3().crossVectors(n, t1);
  const asked = Math.max(1, Math.round(Math.PI * R * R / (sp * sp) * 0.3));
  const want = Math.min(asked, PAINT_DAB_MAX);
  const maxItems = paintMaxItems();
  if (paintAlive >= maxItems) { paintLimitInfo('total', { count: maxItems }); return; }
  if (asked > PAINT_DAB_MAX) paintLimitInfo('dab', { spacing: Math.sqrt(Math.PI * R * R * 0.3 / PAINT_DAB_MAX) });
  const meshes = paintSurfaces(P, R + sp * 2);
  if (!meshes.length) return;
  _pr.firstHitOnly = true;
  const p = new THREE.Vector3(), down = n.clone().negate();
  let made = 0;
  for (let i = 0; i < want * 4 && made < want; i++) {
    if (paintAlive >= maxItems) { paintLimitInfo('total', { count: maxItems }); break; }
    // always six numbers per try: the same try gives the same piece whatever the settings
    const a = rnd() * Math.PI * 2, d = R * Math.sqrt(rnd()), uMin = rnd(), uModel = rnd(), uRot = rnd(), uScale = rnd();
    p.copy(P).addScaledVector(t1, Math.cos(a) * d).addScaledVector(t2, Math.sin(a) * d).addScaledVector(n, R + sp);
    _pr.set(p, down);
    const hits = _pr.intersectObjects(meshes, false);
    const h = hits[0];
    if (!h) continue;
    const q = h.point;
    if (gridNear(q, sp * (1 - paint.spacingRand * uMin))) continue;
    const model = pickModel(uModel);
    if (!model) continue;
    const up = paint.align ? hitNormal(h) : _up.clone();
    const it = paint.palette.find((e) => e.model === model);
    const ang = itemAngle(it, THREE.MathUtils.degToRad(paint.rot), uRot);
    const quat = new THREE.Quaternion().setFromUnitVectors(_up, up).multiply(new THREE.Quaternion().setFromAxisAngle(_up, ang));
    const s = Math.max(0.05, itemScale(it, uScale));
    paint.items.push({ pos: q.clone(), q: quat, s, model, alive: true });
    gridAdd(q); made++; paintAlive++;
  }
  _pr.firstHitOnly = false;
}
function gridRebuild() {
  paint.items = paint.items.filter((it) => it.alive);
  paintAlive = paint.items.length; paintLocalReset();
  paint.grid = new Map();
  for (const it of paint.items) gridAdd(it.pos);
}
// the whole distribution again from its strokes (settings or models changed)
function paintRegenerate() {
  paintFollowGroup();
  paintResetItems();
  paintAddBase();
  paint.strokes.forEach((st, i) => paintApplyStroke(st, i));
  paintShowLocal();
}
// while a distribution is being changed the view draws it from the pieces made here (before the engine has them)
// (1.78.4) while the brush is dragged only the new pieces are added to the arrays of the view (before, every touch
// made the matrices of the whole distribution again), and the view takes them at most every PAINT_SHOW_MS
const PAINT_SHOW_MS = 120;
let paintShowTimer = 0, paintShowAt = 0;
function paintShowLocal(now) {
  paint.editing = true;
  if (!now && paint.painting) {
    const wait = PAINT_SHOW_MS - (performance.now() - paintShowAt);
    if (wait > 0) { if (!paintShowTimer) paintShowTimer = setTimeout(() => { paintShowTimer = 0; paintShowLocal(true); }, wait); return; }
  }
  clearTimeout(paintShowTimer); paintShowTimer = 0; paintShowAt = performance.now();
  scatterLocalSet(paint.group, paint.items, paint.local);
}
function paintLocalReset() { paint.local = { by: new Map(), done: 0, inv: null }; }
function paintPacked() {
  // pieces as binary (base64): model index, position, rotation (quaternion), scale - 32 bytes each
  const models = [], index = new Map();
  const alive = paint.items.filter((it) => it.alive);
  const idx = new Int32Array(alive.length), trs = new Float32Array(alive.length * 8);
  alive.forEach((it, k) => {
    let m = index.get(it.model);
    if (m === undefined) { m = models.length; models.push(it.model); index.set(it.model, m); }
    idx[k] = m;
    trs.set([it.pos.x, it.pos.y, it.pos.z, it.q.x, it.q.y, it.q.z, it.q.w, it.s], k * 8);
  });
  const b64 = (buf) => { let s = ''; const u = new Uint8Array(buf); for (let i = 0; i < u.length; i += 0x8000) s += String.fromCharCode.apply(null, u.subarray(i, i + 0x8000)); return btoa(s); };
  // (the fixed pieces still there: the first ones - paint.py BASE_KEY)
  return { models, idx: b64(idx.buffer), trs: b64(trs.buffer), count: alive.length, base: alive.filter((it) => it.base).length };
}
function paintSend() {
  paint.batch++;
  post({
    type: 'paintSet', group: paint.group, batch: paint.batch, seed: paint.seed, strokes: paint.strokes, packed: paintPacked(),
    settings: paintSettingsNow(),
  });
}
function paintSettingsNow() {
  const o = { mode: paint.mode };
  for (const k of PAINT_KEYS) o[k] = paint[k];
  return o;
}
let paintTimer = 0;
function paintSendSoon() { clearTimeout(paintTimer); paintTimer = setTimeout(paintSend, 250); }
function paintStroke(hit, erase) {
  {   // (the distribution was moved with its gizmo since the last stroke: strokes and pieces come along first, then the new stroke)
    const g0 = paint.group ? byId.get(paint.group) : null;
    if (g0 && paintGroupAt) { g0.updateMatrixWorld(true); if (!g0.matrixWorld.equals(paintGroupAt)) paintRegenerate(); }
  }
  const st = { p: hit.point.toArray().map((v) => +v.toFixed(4)), n: hit.normal.toArray().map((v) => +v.toFixed(4)), r: +paint.radius.toFixed(4), e: erase ? 1 : 0 };
  paint.strokes.push(st);
  paintApplyStroke(st, paint.strokes.length - 1);
  paintShowLocal();
}
function placeBrush(hit) {
  brushCursor(hit, paint.radius);
  if (!hit) { brush.visible = false; return; }
  brush.visible = true;
  brush.position.copy(hit.point).addScaledVector(hit.normal, paint.radius * 0.01);
  brush.quaternion.setFromUnitVectors(_up, hit.normal);
  brush.scale.setScalar(paint.radius);
  const col = paint.erasing || shiftDown ? BRUSH_RED : BRUSH_GREEN;
  brushMat.color.set(col); brushFill.color.set(col);
}
const PAINT_KEYS = ['spacing', 'spacingRand', 'scale', 'scaleRand', 'rot', 'rotRand', 'align', 'tension', 'prob', 'falloff', 'falloffDist', 'snap',
  'byCount', 'count', 'step', 'stepRand', 'lateral', 'randomOrder', 'follow'];
function setPaint(msg) {
  let changed = false;
  if (msg.settings) {
    if (msg.settings.radius !== undefined) paint.radius = msg.settings.radius;
    for (const k of PAINT_KEYS) if (msg.settings[k] !== undefined && msg.settings[k] !== paint[k]) { paint[k] = msg.settings[k]; changed = true; }
  }
  if (msg.palette) {
    if (JSON.stringify(msg.palette) !== JSON.stringify(paint.palette)) changed = true;
    paint.palette = msg.palette;
    if (msg.on) for (const p of paint.palette) ensureProto(p.model);
  }
  if (msg.group !== undefined && msg.group !== paint.group) {
    // another distribution: its strokes come with a 'paintGroup' message
    paint.group = msg.group || ''; paint.strokes = []; paint.seed = 0; paint.baseItems = []; paintResetItems(); areaReset(); changed = false;
  }
  if (msg.settings && msg.settings.mode && msg.settings.mode !== paint.mode) {
    paint.mode = msg.settings.mode;
    areaReset();
  }
  if (msg.regen && msg.group === undefined || msg.regen && (msg.group || '') === paint.group) changed = true;   // (a setting moved in the panel: always made again, never «nothing changed»)
  paint.on = !!msg.on;
  if (!paint.on || paint.mode !== 'brush') { brush.visible = false; paint.painting = false; }
  if (!paint.on) areaTool.drag = null;
  // (Luca: the gizmo of the distribution shown while painting must work: moving the group is followed by its strokes and points,
  // paintFollowGroup; only a distribution not chosen yet - a new one - has no gizmo to use)
  setGizmosEnabled(!locked && !selectMode && !paintingNew());
  renderer.domElement.style.cursor = !paint.on ? '' : paint.mode === 'brush' ? 'crosshair' : areaTool.done ? '' : 'crosshair';
  areaDraw();
  // settings changed after painting: the distribution follows them
  if (msg.regen) viewLog(`distribution: a setting came from the panel (mode ${paint.mode}, step ${paint.step}, count ${paint.count}, changed ${changed}, line ${areaTool.done ? 'done' : 'not done'}, ${paint.strokes.length} strokes, painting ${paint.painting})`);
  if (changed && lineTool() && areaTool.done) areaRebuild(true).catch((err) => viewLog('distribution: ' + (err && err.stack ? err.stack : err)));
  else if (changed && (paint.strokes.length || paint.baseItems.length) && !paint.painting) { paintRegenerate(); paintSendSoon(); }
  else if (changed && msg.regen) viewLog(`distribution: a setting changed in the panel but there is nothing to make again (mode ${paint.mode}, line ${areaTool.done ? 'done' : 'not done'}, ${paint.strokes.length} strokes)`);
}
// a new seed from the panel: the same distribution, other random choices
function setPaintSeed(seed) {
  paint.seed = seed | 0;
  if (lineTool() && areaTool.done) areaRebuild(true);
  else if (paint.strokes.length || paint.baseItems.length) { paintRegenerate(); paintSendSoon(); }
}
// the strokes of a distribution (chosen in the tree, opened with the project, after undo/redo)
function setPaintGroup(msg) {
  // the distribution was deleted: nothing of it stays (its line, the pieces being drawn)
  if (msg.reset) { paint.editing = false; if (scatter.sets.get('')) scatter.sets.delete(''); scatter.dirty = true; }
  paint.group = msg.group || '';
  paint.strokes = msg.strokes || [];
  paint.seed = msg.seed || (Math.random() * 1e9) | 0;
  if (msg.settings) for (const k of PAINT_KEYS) if (msg.settings[k] !== undefined) paint[k] = msg.settings[k];
  if (msg.palette) paint.palette = msg.palette.map((p) => ({ model: p.model, weight: p.weight, scale: p.scale, scaleRand: p.scaleRand, rot: p.rot, rotRand: p.rotRand }));
  if (msg.settings && msg.settings.mode) paint.mode = msg.settings.mode;
  if (msg.area) paint.mode = (msg.settings && msg.settings.mode === 'spacing') ? 'spacing' : 'area';
  if (!paint.editing) {
    paint.baseItems = paintBaseOf(msg.base);
    paint.basePalette = paintPaletteKey();
    paintResetItems(); paintAddBase(); paint.strokes.forEach((st, i) => paintApplyStroke(st, i));
    areaLoad(msg.area);
  }
}
// the fixed pieces sent by the app (GET paint/base: model index; position, quaternion x y z w, scale per piece)
function paintBaseOf(b) {
  if (!b || !b.count || !b.trs) return [];
  const bytes = (s) => { const t = atob(s), u = new Uint8Array(t.length); for (let i = 0; i < t.length; i++) u[i] = t.charCodeAt(i); return u.buffer; };
  const idx = new Int32Array(bytes(b.idx)), trs = new Float32Array(bytes(b.trs));
  const out = [];
  for (let k = 0; k < Math.min(b.count, idx.length); k++) {
    const model = (b.models || [])[idx[k]];
    if (!model) continue;
    const o = k * 8;
    out.push({ pos: new THREE.Vector3(trs[o], trs[o + 1], trs[o + 2]), q: new THREE.Quaternion(trs[o + 3], trs[o + 4], trs[o + 5], trs[o + 6]), s: trs[o + 7], model });
  }
  return out;
}
// (Luca: «ho aggiunto i fiori ma l'area non si è aggiornata») the models of the brush changed (one added, removed or
// weighed differently): every fixed piece picks its model again from them, as the strokes do - its place, turn and
// size stay; the same models as when it was loaded: the pieces as they were saved
function paintPaletteKey() { return JSON.stringify(paint.palette.map((p) => [p.model, p.weight])); }
function paintAddBase() {
  const same = paintPaletteKey() === paint.basePalette;
  paint.baseItems.forEach((b, k) => {
    const model = same ? b.model : pickModel(mulberry((paint.seed * 31 + k * 2654435761) | 0)());
    if (!model) return;
    paint.items.push({ pos: b.pos.clone(), q: b.q.clone(), s: b.s, model, alive: true, base: true });
    gridAdd(b.pos); paintAlive++;
  });
}
renderer.domElement.addEventListener('pointerdown', (e) => {
  if (!paint.on || e.button !== 0 || locked) return;
  if (gizmoAxis()) return;       // (the mouse is on a handle of the gizmo: the click moves the distribution, it does not paint)
  // a line already drawn (Area, Spaziatura): a click that is not on one of its points or "+" belongs to the view -
  // held down it turns the view around the point under the mouse, as always (before, every click was kept by the
  // tool and the view could not be turned any more)
  if (lineTool() && areaTool.done && !areaHandleAt(e.clientX, e.clientY)) {
    if (areaTool.sel >= 0) { areaTool.sel = -1; areaDraw(); }
    return;
  }
  e.stopImmediatePropagation();
  renderer.domElement.setPointerCapture(e.pointerId);
  if (lineTool()) { areaPointerDown(e); return; }
  paint.painting = true; paint.erasing = e.shiftKey; paint.last = null;
  if (!paint.seed) paint.seed = (Math.random() * 1e9) | 0;
  const hit = surfaceUnder(e.clientX, e.clientY);
  placeBrush(hit);
  if (hit) { paintStroke(hit, paint.erasing); paint.last = hit.point; }
}, true);
renderer.domElement.addEventListener('pointermove', (e) => {
  if (!paint.on) return;
  if (gizmoAxis() || gizmoDragging()) { brush.visible = false; return; }     // (over the gizmo: no brush)
  if (lineTool()) { areaPointerMove(e); return; }
  const hit = surfaceUnder(e.clientX, e.clientY);
  placeBrush(hit);
  if (!paint.painting || !hit) return;
  if (paint.last && paint.last.distanceTo(hit.point) < (paint.erasing ? paint.radius * 0.35 : Math.max(paint.spacing, paint.radius * 0.35))) return;
  paint.last = hit.point;
  paintStroke(hit, paint.erasing);
});
window.addEventListener('pointerup', () => {
  if (paint.on && lineTool()) { areaPointerUp(); return; }
  if (!paint.painting) return;
  paint.painting = false; paint.erasing = false;
  paintShowLocal(true);
  paintSend();
});
renderer.domElement.addEventListener('pointerleave', () => {
  if (paint.on && !paint.painting) brush.visible = false;
  if (paint.on && lineTool() && areaTool.cursor && !areaTool.done) { areaTool.cursor = null; areaDraw(); }
});
// ---- (1.76.44, Luca: «il pennello per alzare e abbassare la geometria del terreno») «Scultura» of the terrain.
// The brush of the puddles with layer 'terrain': while the mouse moves the meshes of the zones are deformed here,
// at once (no engine: the view stays fluid); the strokes go to the engine only when the tool is left (switched
// off, another panel, path tracing, saving: terrainSculptCommit), and it makes the terrain again with them, once.
// The same formulas as terrain.py _apply_sculpt (SCULPT_RATE, SCULPT_SMOOTH, _sculpt_falloff). Ctrl+Z takes back
// the last stroke of the session here; after the commit the whole session is one step of the app's undo.
const TS = { ids: [], tool: 'raise', k: 0.3, soft: 0.7, strokes: [], undo: [], cur: null, snap: null,
  frame: null, index: null, dirty: new Set(), bvhT: 0 };
const TS_RATE = 0.03, TS_SMOOTH = 0.5;
function puddleMaxRadius() { return puddle.layer === 'terrain' ? 1000 : 50; }
function terrainSculptSet(t) {
  TS.tool = ['raise', 'lower', 'smooth'].includes(t.tool) ? t.tool : 'raise';
  TS.k = Math.max(0, Math.min(1, +t.strength || 0));
  TS.soft = Math.max(0, Math.min(1, t.soft == null ? 0.7 : +t.soft));
  const ids = Array.isArray(t.ids) ? t.ids.map(String) : [];
  if (ids.join(',') !== TS.ids.join(',')) { TS.ids = ids; TS.index = null; }
}
// the meshes of the zones as they are now in the view (new geometry after the commit: found again)
function terrainMeshes() {
  const out = [];
  for (const id of TS.ids) {
    const node = byId.get(id);
    if (!node) continue;
    node.traverse((o) => { if (o.isMesh && !o.isInstancedMesh && o.geometry && o.geometry.attributes.position) out.push(o); });
  }
  if (out.length) TS.frame = byId.get(TS.ids.find((id) => byId.get(id))) || out[0];
  return out;
}
function terrainUnder(clientX, clientY) {
  const ms = terrainMeshes();
  if (!ms.length) return null;
  const r = renderer.domElement.getBoundingClientRect();
  camera.updateMatrixWorld();
  _pr.setFromCamera(new THREE.Vector2(((clientX - r.left) / r.width) * 2 - 1, -((clientY - r.top) / r.height) * 2 + 1), camera);
  for (const m of ms) if (!m.geometry.boundsTree) { try { m.geometry.computeBoundsTree(); } catch (e) { /* plain test */ } }
  const h = _pr.intersectObjects(ms, false)[0];
  return h ? { point: h.point.clone(), normal: hitNormal(h), mat: '' } : null;
}
// the points of all the zone meshes in buckets on the ground (world x, y): found again when the meshes change or
// the brush is much bigger or smaller than the buckets
function terrainIndex(r) {
  const ms = terrainMeshes();
  const key = ms.map((m) => m.geometry.uuid).join(',');
  const cell = Math.max(1, r * 0.5);
  if (TS.index && TS.index.key === key && cell / TS.index.cell < 2 && TS.index.cell / cell < 2) return TS.index;
  const buckets = new Map(), info = [];
  ms.forEach((m, mi) => {
    m.updateMatrixWorld();
    const e = m.matrixWorld.elements, pos = m.geometry.attributes.position, a = pos.array, n = pos.count;
    const inv = new THREE.Matrix3().setFromMatrix4(m.matrixWorld).invert();
    const up = new THREE.Vector3(0, 0, 1).applyMatrix3(inv);
    info.push({ m, e, up, wx: new Float32Array(n), wy: new Float32Array(n) });
    const I = info[mi];
    for (let i = 0; i < n; i++) {
      const x = a[i * 3], y = a[i * 3 + 1], z = a[i * 3 + 2];
      const wx = e[0] * x + e[4] * y + e[8] * z + e[12], wy = e[1] * x + e[5] * y + e[9] * z + e[13];
      I.wx[i] = wx; I.wy[i] = wy;
      const k = Math.floor(wx / cell) * 73856093 ^ Math.floor(wy / cell) * 19349663;
      let b = buckets.get(k);
      if (!b) buckets.set(k, b = []);
      b.push(mi, i);
    }
  });
  TS.index = { key, cell, buckets, info };
  return TS.index;
}
function terrainFall(d, soft) {
  const inner = 1 - Math.max(0.05, Math.min(1, soft));
  const t = Math.max(0, Math.min(1, (d - inner) / Math.max(1e-3, 1 - inner)));
  return 1 - t * t * (3 - 2 * t);
}
function terrainStrokeStart() {
  // (Shift with «Alza» or «Abbassa»: the other one, for the whole stroke)
  const tool = TS.tool === 'smooth' ? 'smooth' : (TS.tool === 'lower') !== !!puddle.removing ? 'lower' : 'raise';
  TS.cur = { tool, r: puddle.radius, k: TS.k, soft: TS.soft, pts: [] };
  TS.snap = new Map();
}
// which triangles each point of a mesh belongs to (for its normal: only the points moved get a new one - the
// normals of the whole mesh made again would show its border with the next zone as a line)
function terrainAdjacency(I) {
  if (I.adj) return I.adj;
  const g = I.m.geometry, n = g.attributes.position.count;
  const idx = g.index ? g.index.array : null, nt = idx ? idx.length / 3 : n / 3;
  const cnt = new Uint32Array(n + 1);
  for (let t = 0; t < nt * 3; t++) cnt[(idx ? idx[t] : t) + 1]++;
  for (let i = 0; i < n; i++) cnt[i + 1] += cnt[i];
  const fill = cnt.slice(0, n), list = new Uint32Array(nt * 3);
  for (let t = 0; t < nt; t++) for (let c = 0; c < 3; c++) { const v = idx ? idx[t * 3 + c] : t * 3 + c; list[fill[v]++] = t; }
  I.adj = { start: cnt, list, idx };
  return I.adj;
}
function terrainNormals(I, verts) {
  const g = I.m.geometry, nrm = g.attributes.normal;
  if (!nrm) return;
  const A = terrainAdjacency(I), a = g.attributes.position.array, na = nrm.array, ix = A.idx;
  const vi = (t, c) => (ix ? ix[t * 3 + c] : t * 3 + c);
  for (const v of verts) {
    let nx = 0, ny = 0, nz = 0;
    for (let k = A.start[v]; k < A.start[v + 1]; k++) {
      const t = A.list[k], p0 = vi(t, 0) * 3, p1 = vi(t, 1) * 3, p2 = vi(t, 2) * 3;
      const ux = a[p1] - a[p0], uy = a[p1 + 1] - a[p0 + 1], uz = a[p1 + 2] - a[p0 + 2];
      const wx = a[p2] - a[p0], wy = a[p2 + 1] - a[p0 + 1], wz = a[p2 + 2] - a[p0 + 2];
      nx += uy * wz - uz * wy; ny += uz * wx - ux * wz; nz += ux * wy - uy * wx;
    }
    const l = Math.hypot(nx, ny, nz);
    if (l > 0) { na[v * 3] = nx / l; na[v * 3 + 1] = ny / l; na[v * 3 + 2] = nz / l; }
  }
  nrm.needsUpdate = true;
}
function terrainDab(p) {
  const S = TS.cur;
  if (!S || S.k <= 0) return;
  const tool = S.tool, r = S.r, X = terrainIndex(r);
  if (!X.info.length) return;
  const loc = TS.frame.worldToLocal(p.clone());
  S.pts.push([+loc.x.toFixed(2), +loc.y.toFixed(2)]);
  const cell = X.cell, i0 = Math.floor((p.x - r) / cell), i1 = Math.floor((p.x + r) / cell);
  const j0 = Math.floor((p.y - r) / cell), j1 = Math.floor((p.y + r) / cell);
  const pick = [];      // mesh index, vertex, weight, world z
  for (let i = i0; i <= i1; i++) for (let j = j0; j <= j1; j++) {
    const b = X.buckets.get(i * 73856093 ^ j * 19349663);
    if (!b) continue;
    for (let q = 0; q < b.length; q += 2) {
      const I = X.info[b[q]], v = b[q + 1];
      const f = terrainFall(Math.hypot(I.wx[v] - p.x, I.wy[v] - p.y) / r, S.soft);
      if (f <= 0) continue;
      const a = I.m.geometry.attributes.position.array, e = I.e;
      pick.push(b[q], v, f, e[2] * a[v * 3] + e[6] * a[v * 3 + 1] + e[10] * a[v * 3 + 2] + e[14]);
    }
  }
  if (!pick.length) return;
  let plane = null;
  if (tool === 'smooth') {
    // the plane that fits the ground under the brush (weighted, in units of the radius)
    let s00 = 0, s01 = 0, s02 = 0, s11 = 0, s12 = 0, s22 = 0, b0 = 0, b1 = 0, b2 = 0;
    for (let q = 0; q < pick.length; q += 4) {
      const I = X.info[pick[q]], v = pick[q + 1], w = pick[q + 2], z = pick[q + 3];
      const u = (I.wx[v] - p.x) / r, t = (I.wy[v] - p.y) / r;
      s00 += w; s01 += w * u; s02 += w * t; s11 += w * u * u; s12 += w * u * t; s22 += w * t * t;
      b0 += w * z; b1 += w * u * z; b2 += w * t * z;
    }
    const M = new THREE.Matrix3().set(s00 + 1e-9, s01, s02, s01, s11 + 1e-9, s12, s02, s12, s22 + 1e-9);
    if (Math.abs(M.determinant()) < 1e-12) return;
    plane = new THREE.Vector3(b0, b1, b2).applyMatrix3(M.invert());
  }
  const moved = new Map();
  for (let q = 0; q < pick.length; q += 4) {
    const mi = pick[q], v = pick[q + 1], f = pick[q + 2], z = pick[q + 3], I = X.info[mi];
    let dz;
    if (tool === 'smooth') dz = (plane.x + plane.y * (I.wx[v] - p.x) / r + plane.z * (I.wy[v] - p.y) / r - z) * f * TS_SMOOTH * S.k;
    else dz = (tool === 'lower' ? -1 : 1) * f * TS_RATE * r * S.k;
    const a = I.m.geometry.attributes.position.array;
    let sm = TS.snap.get(I.m);
    if (!sm) TS.snap.set(I.m, sm = new Map());
    if (!sm.has(v)) sm.set(v, [a[v * 3], a[v * 3 + 1], a[v * 3 + 2]]);
    a[v * 3] += I.up.x * dz; a[v * 3 + 1] += I.up.y * dz; a[v * 3 + 2] += I.up.z * dz;
    TS.dirty.add(I.m);
    let mv = moved.get(I);
    if (!mv) moved.set(I, mv = []);
    mv.push(v);
  }
  for (const [I, vs] of moved) terrainNormals(I, vs);
  terrainRefresh(false);
}
// after points moved: positions to the GPU at once; normals and the search tree now and then (and at the end)
function terrainRefresh(final) {
  const now = performance.now();
  const bvh = final || now - TS.bvhT > 400;
  for (const m of TS.dirty) {
    m.geometry.attributes.position.needsUpdate = true;
    if (bvh && m.geometry.boundsTree) { try { m.geometry.boundsTree.refit(); } catch (e) { m.geometry.disposeBoundsTree(); } }
    if (bvh) m.geometry.computeBoundingSphere();
  }
  if (bvh) { TS.bvhT = now; TS.dirty.clear(); }
  if (final) refitShadowsSoon();
  invalidate(300);
}
function terrainStrokeEnd() {
  const S = TS.cur;
  TS.cur = null;
  terrainRefresh(true);
  if (!S || !S.pts.length) return;
  TS.strokes.push(S);
  TS.undo.push(TS.snap);
  TS.snap = null;
  post({ type: 'terrainSculptCount', n: TS.strokes.length });
}
function terrainUndo() {
  if (!TS.strokes.length) return;
  TS.strokes.pop();
  const snap = TS.undo.pop();
  for (const [m, sm] of snap) {
    const a = m.geometry.attributes.position.array;
    for (const [v, xyz] of sm) { a[v * 3] = xyz[0]; a[v * 3 + 1] = xyz[1]; a[v * 3 + 2] = xyz[2]; }
    TS.dirty.add(m);
    const I = TS.index && TS.index.info.find((x) => x.m === m);
    if (I) terrainNormals(I, [...sm.keys()]);
  }
  terrainRefresh(true);
  post({ type: 'terrainSculptCount', n: TS.strokes.length });
}
function terrainSculptCommit() {
  if (TS.cur) terrainStrokeEnd();
  if (!TS.strokes.length) return;
  post({ type: 'terrainSculptCommit', strokes: TS.strokes });
  TS.strokes = []; TS.undo = [];
  post({ type: 'terrainSculptCount', n: 0 });
}
// the brush of the puddles (puddle, setPuddleBrush): same gestures as the brush of the distributions
renderer.domElement.addEventListener('pointerdown', (e) => {
  if (!puddle.on || paint.on || e.button !== 0 || locked) return;
  e.stopImmediatePropagation();
  renderer.domElement.setPointerCapture(e.pointerId);
  puddle.painting = true; WET.stroke = true;
  puddle.removing = puddle.layer === 'terrain' ? e.shiftKey && TS.tool !== 'smooth'
    : puddle.layer !== 'sculpt' && (puddle.mode === 'remove' || e.shiftKey);
  puddle.pts = []; puddle.last = null;
  if (puddle.layer === 'terrain') terrainStrokeStart();
  const hit = puddle.layer === 'terrain' ? terrainUnder(e.clientX, e.clientY) : surfaceUnder(e.clientX, e.clientY);
  placePuddleBrush(hit, puddle.removing);
  if (hit) puddleDab(hit);
}, true);
renderer.domElement.addEventListener('pointermove', (e) => {
  if (!puddle.on || paint.on) return;
  const hit = puddle.layer === 'terrain' ? terrainUnder(e.clientX, e.clientY) : surfaceUnder(e.clientX, e.clientY);
  placePuddleBrush(hit, puddle.painting ? puddle.removing : puddle.layer === 'terrain' ? e.shiftKey && TS.tool !== 'smooth'
    : puddle.layer !== 'sculpt' && (puddle.mode === 'remove' || e.shiftKey));
  if (!puddle.painting || !hit) return;
  if (puddle.last && puddle.last.distanceTo(hit.point) < (puddle.layer === 'sculpt' ? sculptStep() : puddle.radius * 0.25)) return;
  puddleDab(hit);
});
window.addEventListener('pointerup', () => {
  if (!puddle.painting) return;
  puddle.painting = false;
  if (puddle.layer === 'terrain') { terrainStrokeEnd(); WET.stroke = false; return; }
  if (puddle.pts.length && puddle.layer === 'sculpt') {
    post({ type: 'sculptStroke', points: puddle.pts, radius: puddle.radius, ...(puddle.sculpt || {}) });
    clearTimeout(SCULPT.timer);
    SCULPT.timer = setTimeout(sculptPreviewClear, 15000);     // (the mantle did not come: the line goes anyway)
  } else if (puddle.pts.length && puddle.layer === 'dirt') {
    DIRT.pending.push({ pts: puddle.pts, radius: puddle.radius, add: !puddle.removing, preset: puddle.preset, strength: puddle.strength, t: performance.now() });
    post({ type: 'puddleStroke', points: puddle.pts, radius: puddle.radius, mode: puddle.removing ? 'remove' : 'add', layer: 'dirt',
      preset: puddle.preset, strength: puddle.strength, materials: [...puddle.mats] });
  } else if (puddle.pts.length) post({ type: 'puddleStroke', points: puddle.pts, radius: puddle.radius, mode: puddle.removing ? 'remove' : 'add', layer: puddle.layer });
  puddle.pts = []; puddle.mats.clear();
  // the engine's map comes back in a moment (asked again at once, then the regular 1.5 s)
  setTimeout(() => { WET.stroke = false; if (WET.pollWake) WET.pollWake(); }, 350);
});
renderer.domElement.addEventListener('pointerleave', () => { if (puddle.on && !puddle.painting) brush.visible = false; });
window.addEventListener('keydown', (e) => {
  if (!puddle.on) return;
  if (e.key === 'Escape') { post({ type: 'puddleExit' }); e.preventDefault(); return; }
  if (e.key === '[' || e.key === ']') {
    puddle.radius = Math.max(0.05, Math.min(puddleMaxRadius(), puddle.radius * (e.key === ']' ? 1.15 : 1 / 1.15)));
    brush.scale.setScalar(puddle.layer === 'sculpt' ? sculptReach() : puddle.radius);
    post({ type: 'puddleRadius', radius: puddle.radius });
    invalidate(); e.preventDefault();
  }
});
// the engine has made the pieces of a change (batch): when it is the last one, the view keeps what it drew
function paintDone(msg) {
  if (msg.group) paint.group = msg.group;
  if (msg.batch && msg.batch < paint.batch) return;
  paint.editing = false;
  scatterLocalDone(msg.group || '', msg.rev || '');
}

// ------------------------------------------------------------------ Distribuisci > Area (fill a drawn area)
// Like the Area tool of Twinmotion. Clicks on the surfaces draw the outline (a closed curve through the points; the
// tension makes it rounder or straighter); clicking the first point again, a double click, Enter or Esc closes it.
// Then the points can be dragged (they slide on the surfaces), a "+" in the middle of every stretch adds a point,
// Delete removes the selected one. The area is filled on a grid as wide as the spacing: every cell can move by a
// random part of the spacing, appears with the probability, gets thinner and smaller near the edge (edge falloff),
// and its piece is dropped on the first surface under the area (objects marked "Escludi da Area" are passed
// through; walls and other steep faces get nothing). Random numbers come from the seed and the cell, so moving a
// point only changes the pieces near it. The pieces go to the engine as one distribution (paint/set), like the
// brush: GPU instancing in the view, Geometry Nodes points in Cycles.
const areaTool = {
  pts: [],          // control points (THREE.Vector3, world)
  closed: false,    // the curve comes back to the first point (an area always; a Spaziatura line when closed on it)
  done: false,      // drawing finished: the points can be edited and the pieces are made
  hover: null,      // {kind: 'pt'|'plus', i} under the mouse
  sel: -1,          // selected point (Delete removes it)
  drag: null,       // {i, moved}
  cursor: null,     // surface point under the mouse while drawing
  gen: 0,           // number of the generation (a newer one cancels the older)
  out: null,        // last pieces made: {models, idx, trs, count}
  ms: 0,            // how long the last generation took (live update while dragging when it is quick)
  lastClick: null,  // {x, y, t} to recognise a double click
};
const AREA_MAX_CELLS = 4000000;
const areaRoot = new THREE.Group();
areaRoot.userData.helper = true;
areaRoot.visible = false;
scene.add(areaRoot);
const areaLine = new THREE.Line(new THREE.BufferGeometry(), new THREE.LineBasicMaterial({ color: BRUSH_GREEN, transparent: true, opacity: 1, depthTest: false }));
const areaRubber = new THREE.Line(new THREE.BufferGeometry(), new THREE.LineBasicMaterial({ color: BRUSH_GREEN, transparent: true, opacity: 0.55, depthTest: false }));
for (const l of [areaLine, areaRubber]) { l.renderOrder = 998; l.frustumCulled = false; l.userData.helper = true; l.raycast = () => {}; areaRoot.add(l); }
const areaSprites = new THREE.Group();
areaSprites.userData.helper = true;
areaRoot.add(areaSprites);
const _areaTex = {};
function areaTexture(kind) {
  if (_areaTex[kind]) return _areaTex[kind];
  const s = 64, cv = document.createElement('canvas');
  cv.width = cv.height = s;
  const g = cv.getContext('2d');
  g.translate(s / 2, s / 2);
  const green = '#6ee07f';
  if (kind === 'plus') {
    g.fillStyle = 'rgba(10,18,34,0.8)'; g.strokeStyle = green; g.lineWidth = 4;
    g.beginPath(); g.arc(0, 0, 20, 0, Math.PI * 2); g.fill(); g.stroke();
    g.lineWidth = 5; g.lineCap = 'round';
    g.beginPath(); g.moveTo(-10, 0); g.lineTo(10, 0); g.moveTo(0, -10); g.lineTo(0, 10); g.stroke();
  } else {
    g.fillStyle = kind === 'sel' ? green : kind === 'hover' ? '#d9ffe0' : '#ffffff';
    g.strokeStyle = kind === 'sel' ? '#ffffff' : green; g.lineWidth = 7;
    g.beginPath(); g.arc(0, 0, 22, 0, Math.PI * 2); g.fill(); g.stroke();
  }
  const t = new THREE.CanvasTexture(cv);
  t.colorSpace = THREE.SRGBColorSpace;
  return (_areaTex[kind] = t);
}
function areaCurve() {
  const pts = areaTool.pts;
  if (pts.length < 2) return null;
  const closed = areaTool.closed;
  const t = 1 - Math.min(1, Math.max(0.01, (paint.tension ?? 50) / 100));      // 100% = straight stretches
  return new THREE.CatmullRomCurve3(pts, closed, 'catmullrom', t);
}
// the outline as a list of points (closed: without repeating the first one)
function areaOutline(per = 16) {
  const c = areaCurve();
  if (!c) return areaTool.pts.map((p) => p.clone());
  const segs = areaTool.closed ? areaTool.pts.length : areaTool.pts.length - 1;
  const out = c.getPoints(Math.max(1, segs * per));
  if (areaTool.closed) out.pop();
  return out;
}
// where the "+" of every stretch is (middle of the curve between two points)
function areaPluses() {
  const c = areaCurve();
  if (!c || !areaTool.done) return [];
  const segs = areaSegs();
  return Array.from({ length: segs }, (_, i) => c.getPoint((i + 0.5) / segs));
}
function areaSegs() { return areaTool.closed ? areaTool.pts.length : areaTool.pts.length - 1; }
const _areaLift = new THREE.Vector3(0, 0, 0.02);
function areaDraw() {
  const show = paint.on && lineTool();
  areaRoot.visible = show;
  if (!show) { invalidate(); return; }
  const line = areaOutline();
  if (areaTool.closed && line.length) line.push(line[0].clone());
  areaLine.geometry.dispose();
  areaLine.geometry = new THREE.BufferGeometry().setFromPoints(line.map((p) => p.clone().add(_areaLift)));
  // while drawing: from the last point to the mouse (and back to the first one)
  const rub = [];
  if (!areaTool.done && areaTool.pts.length && areaTool.cursor) {
    rub.push(areaTool.pts[areaTool.pts.length - 1], areaTool.cursor);
    if (areaTool.pts.length >= 2 && paint.mode === 'area') rub.push(areaTool.pts[0]);
  }
  areaRubber.geometry.dispose();
  areaRubber.geometry = new THREE.BufferGeometry().setFromPoints(rub.map((p) => p.clone().add(_areaLift)));
  for (const s of [...areaSprites.children]) { areaSprites.remove(s); s.material.dispose(); }
  const add = (p, kind, size, tag) => {
    const sp = new THREE.Sprite(new THREE.SpriteMaterial({ map: areaTexture(kind), depthTest: false, sizeAttenuation: false }));
    sp.scale.set(size, size, 1);
    sp.position.copy(p).add(_areaLift);
    sp.renderOrder = 999;
    sp.userData.helper = true;
    sp.userData.area = tag;
    sp.raycast = () => {};
    areaSprites.add(sp);
  };
  areaPluses().forEach((p, i) => add(p, 'plus', 0.024, { kind: 'plus', i }));
  areaTool.pts.forEach((p, i) => {
    const h = areaTool.hover && areaTool.hover.kind === 'pt' && areaTool.hover.i === i;
    add(p, areaTool.sel === i ? 'sel' : h ? 'hover' : 'pt', 0.026, { kind: 'pt', i });
  });
  invalidate();
}
// handle under the mouse (points before pluses), in pixels
function areaHandleAt(clientX, clientY) {
  const r = renderer.domElement.getBoundingClientRect();
  const v = new THREE.Vector3();
  let best = null, bestD = 11;
  for (const s of areaSprites.children) {
    v.copy(s.position).project(camera);
    if (v.z > 1) continue;
    const x = (v.x + 1) / 2 * r.width + r.left, y = (1 - v.y) / 2 * r.height + r.top;
    const d = Math.hypot(x - clientX, y - clientY) - (s.userData.area.kind === 'pt' ? 2 : 0);
    if (d < bestD) { bestD = d; best = s.userData.area; }
  }
  return best;
}
function areaReset() {
  areaTool.pts = []; areaTool.closed = false; areaTool.done = false; areaTool.sel = -1; areaTool.hover = null; areaTool.drag = null;
  areaTool.cursor = null; areaTool.out = null; areaTool.gen++;
  areaDraw();
}
const areaMinPts = () => (paint.mode === 'spacing' ? 2 : 3);
// end of the drawing: an area always closes; a Spaziatura line closes only when ended on its first point
function areaClose(onFirst) {
  if (areaTool.pts.length < areaMinPts()) return false;
  areaTool.closed = paint.mode === 'area' || (!!onFirst && areaTool.pts.length >= 3);
  areaTool.done = true; areaTool.cursor = null;
  areaDraw();
  areaRebuild(true);
  return true;
}
// meshes the pieces can land on: visible, not helpers, not inside an excluded object, near the area
function areaSurfaces(minX, minY, maxX, maxY) {
  const out = [];
  root.traverse((o) => {
    if (!o.isMesh || o.isInstancedMesh || o.userData.helper || !isVisible(o) || inPainting(o) || !o.layers.test(camera.layers)) return;
    for (let p = o; p; p = p.parent) if (p.userData && p.userData.noScatter) return;
    if (!o.geometry.boundingBox) o.geometry.computeBoundingBox();
    const b = _tmpBox.copy(o.geometry.boundingBox).applyMatrix4(o.matrixWorld);
    if (b.max.x < minX || b.min.x > maxX || b.max.y < minY || b.min.y > maxY) return;
    if (!o.geometry.boundsTree) { try { o.geometry.computeBoundsTree(); } catch (e) { /* no tree: plain test */ } }
    out.push({ o, b: b.clone() });
  });
  // (the library models of the scene drawn from their prototype: see pieceSurfaces)
  for (const o of pieceSurfaces(null)) {
    let no = false;
    for (let p = o.parent; p; p = p.parent) if (p.userData && p.userData.noScatter) { no = true; break; }
    if (no) continue;
    if (!o.geometry.boundingBox) o.geometry.computeBoundingBox();
    const b = _tmpBox.copy(o.geometry.boundingBox).applyMatrix4(o.matrixWorld);
    if (b.max.x < minX || b.min.x > maxX || b.max.y < minY || b.min.y > maxY) continue;
    out.push({ o, b: b.clone() });
  }
  return out;
}
function hash3(a, b, c) {
  let h = Math.imul(a ^ 0x9e3779b9, 0x85ebca6b) ^ Math.imul(b + 0x632be5ab, 0xc2b2ae35) ^ Math.imul(c - 0x27d4eb2f, 0x165667b1);
  h ^= h >>> 15; h = Math.imul(h, 0x2c1b3c6d); h ^= h >>> 12; h = Math.imul(h, 0x297a2d39); h ^= h >>> 15;
  return h >>> 0;
}
const yieldUi = () => new Promise((r) => setTimeout(r, 0));
// the pieces of the area (null when a newer generation started or the area is too big)
async function areaGenerate() {
  const my = ++areaTool.gen;
  const t0 = performance.now();
  const models = paint.palette.filter((p) => p.weight > 0).map((p) => p.model);
  const empty = { models, idx: new Int32Array(0), trs: new Float32Array(0), count: 0 };
  if (!areaTool.done || areaTool.pts.length < 3 || !models.length) return empty;
  const poly = areaOutline();
  const n = poly.length;
  let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity, maxZ = -Infinity, sumZ = 0;
  for (const p of poly) { minX = Math.min(minX, p.x); maxX = Math.max(maxX, p.x); minY = Math.min(minY, p.y); maxY = Math.max(maxY, p.y); }
  for (const p of areaTool.pts) { maxZ = Math.max(maxZ, p.z); sumZ += p.z; }
  const flatZ = sumZ / areaTool.pts.length;
  const sp = Math.max(0.02, paint.spacing);
  const ix0 = Math.floor(minX / sp) - 1, ix1 = Math.ceil(maxX / sp) + 1, iy0 = Math.floor(minY / sp) - 1, iy1 = Math.ceil(maxY / sp) + 1;
  const cells = (ix1 - ix0 + 1) * (iy1 - iy0 + 1);
  if (cells > AREA_MAX_CELLS) { post({ type: 'areaInfo', state: 'tooMany', cells, spacing: Math.sqrt((maxX - minX) * (maxY - minY) / AREA_MAX_CELLS) }); return null; }
  if (cells > 150000) post({ type: 'areaInfo', state: 'computing' });
  // edges in horizontal bands as tall as the spacing (inside test) ...
  const ex0 = new Float64Array(n), ey0 = new Float64Array(n), ex1 = new Float64Array(n), ey1 = new Float64Array(n);
  for (let i = 0; i < n; i++) { const a = poly[i], b = poly[(i + 1) % n]; ex0[i] = a.x; ey0[i] = a.y; ex1[i] = b.x; ey1[i] = b.y; }
  const by0 = minY - sp * 2, nb = Math.ceil((maxY - by0) / sp) + 3;
  const bands = Array.from({ length: nb }, () => []);
  for (let i = 0; i < n; i++) {
    const b0 = Math.max(0, Math.floor((Math.min(ey0[i], ey1[i]) - by0) / sp)), b1 = Math.min(nb - 1, Math.floor((Math.max(ey0[i], ey1[i]) - by0) / sp));
    for (let b = b0; b <= b1; b++) bands[b].push(i);
  }
  const inside = (x, y) => {
    const b = Math.floor((y - by0) / sp);
    if (b < 0 || b >= nb) return false;
    let c = false;
    for (const i of bands[b]) {
      if ((ey0[i] > y) !== (ey1[i] > y) && x < ex0[i] + (y - ey0[i]) * (ex1[i] - ex0[i]) / (ey1[i] - ey0[i])) c = !c;
    }
    return c;
  };
  // ... and in squares for the distance to the edge (falloff)
  const fd = paint.falloff ? Math.max(0.01, paint.falloffDist) : 0;
  let edgeDist = null;
  if (fd > 0) {
    const cs = Math.max(sp, fd), gx0 = minX - fd - cs, gy0 = minY - fd - cs;
    const gw = Math.ceil((maxX - gx0 + fd) / cs) + 2, gh = Math.ceil((maxY - gy0 + fd) / cs) + 2;
    const grid = new Map();
    for (let i = 0; i < n; i++) {
      const cx0 = Math.floor((Math.min(ex0[i], ex1[i]) - fd - gx0) / cs), cx1 = Math.floor((Math.max(ex0[i], ex1[i]) + fd - gx0) / cs);
      const cy0 = Math.floor((Math.min(ey0[i], ey1[i]) - fd - gy0) / cs), cy1 = Math.floor((Math.max(ey0[i], ey1[i]) + fd - gy0) / cs);
      for (let cx = cx0; cx <= cx1; cx++) for (let cy = cy0; cy <= cy1; cy++) { const k = cy * gw + cx; (grid.get(k) || grid.set(k, []).get(k)).push(i); }
    }
    edgeDist = (x, y) => {
      const list = grid.get(Math.floor((y - gy0) / cs) * gw + Math.floor((x - gx0) / cs));
      if (!list) return Infinity;
      let best = Infinity;
      for (const i of list) {
        const dx = ex1[i] - ex0[i], dy = ey1[i] - ey0[i], L = dx * dx + dy * dy;
        let t = L > 0 ? ((x - ex0[i]) * dx + (y - ey0[i]) * dy) / L : 0;
        t = t < 0 ? 0 : t > 1 ? 1 : t;
        const qx = ex0[i] + t * dx - x, qy = ey0[i] + t * dy - y, d = qx * qx + qy * qy;
        if (d < best) best = d;
      }
      return Math.sqrt(best);
    };
  }
  // surfaces in coarse squares, so a ray only tests the meshes near it
  let surf = null, sx0 = 0, sy0 = 0, scs = 1, sw = 1;
  if (paint.snap !== false) {
    const list = areaSurfaces(minX - sp, minY - sp, maxX + sp, maxY + sp);
    scs = Math.max(sp * 4, Math.max(maxX - minX, maxY - minY) / 48, 0.5);
    sx0 = minX - sp * 2; sy0 = minY - sp * 2;
    sw = Math.ceil((maxX - sx0 + sp * 2) / scs) + 1;
    surf = new Map();
    for (const { o, b } of list) {
      const cx0 = Math.max(0, Math.floor((b.min.x - sx0) / scs)), cx1 = Math.floor((b.max.x - sx0) / scs);
      const cy0 = Math.max(0, Math.floor((b.min.y - sy0) / scs)), cy1 = Math.floor((b.max.y - sy0) / scs);
      for (let cx = cx0; cx <= Math.min(cx1, sw - 1); cx++) for (let cy = cy0; cy <= cy1; cy++) { const k = cy * sw + cx; (surf.get(k) || surf.set(k, []).get(k)).push(o); }
    }
  }
  const startZ = maxZ + 2;
  const pr = new THREE.Raycaster();
  pr.firstHitOnly = true;
  const down = new THREE.Vector3(0, 0, -1), org = new THREE.Vector3(), nrm = new THREE.Vector3();
  const quatUp = new THREE.Quaternion(), quatRot = new THREE.Quaternion(), q = new THREE.Quaternion();
  const total = paint.palette.filter((p) => p.weight > 0).reduce((a, p) => a + p.weight, 0);
  const weights = paint.palette.filter((p) => p.weight > 0).map((p) => p.weight / total);
  const items = paint.palette.filter((p) => p.weight > 0);
  let cap = 65536, count = 0;
  let idx = new Int32Array(cap), trs = new Float32Array(cap * 8);
  const seed = paint.seed | 0, jit = sp * Math.max(0, Math.min(1, paint.spacingRand));
  const prob = Math.max(0, Math.min(1, paint.prob ?? 1));
  const rot0 = THREE.MathUtils.degToRad(paint.rot);
  let since = performance.now();
  for (let iy = iy0; iy <= iy1; iy++) {
    for (let ix = ix0; ix <= ix1; ix++) {
      const rnd = mulberry(hash3(seed, ix, iy));
      // always the same seven numbers per cell: the same cell gives the same piece whatever the settings
      const a = rnd() * Math.PI * 2, r = Math.sqrt(rnd()) * jit, uProb = rnd(), uModel = rnd(), uRot = rnd(), uScale = rnd();
      rnd();
      const x = (ix + 0.5) * sp + Math.cos(a) * r, y = (iy + 0.5) * sp + Math.sin(a) * r;
      if (uProb >= prob || !inside(x, y)) continue;
      let f = 1;
      if (edgeDist) { f = Math.min(1, edgeDist(x, y) / fd); if (uProb >= prob * f) continue; }
      let z = flatZ;
      nrm.set(0, 0, 1);
      if (surf) {
        const cand = surf.get(Math.floor((y - sy0) / scs) * sw + Math.floor((x - sx0) / scs));
        if (!cand) continue;
        pr.set(org.set(x, y, startZ), down);
        const h = pr.intersectObjects(cand, false)[0];
        if (!h) continue;
        if (h.face) nrm.copy(h.face.normal).transformDirection(h.object.matrixWorld);
        if (nrm.z < 0) nrm.negate();
        if (nrm.z < 0.34) continue;                // walls and very steep faces: nothing
        z = h.point.z;
      }
      // model by weight
      let m = 0, acc = weights[0];
      while (uModel > acc && m < weights.length - 1) acc += weights[++m];
      const it = items[m];
      const ang = itemAngle(it, rot0, uRot);
      quatRot.setFromAxisAngle(_up, ang);
      if (paint.align) quatUp.setFromUnitVectors(_up, nrm); else quatUp.identity();
      q.copy(quatUp).multiply(quatRot);
      const s = Math.max(0.02, itemScale(it, uScale) * (fd > 0 ? 0.35 + 0.65 * f : 1));
      if (count === cap) {
        cap *= 2;
        const i2 = new Int32Array(cap); i2.set(idx); idx = i2;
        const t2 = new Float32Array(cap * 8); t2.set(trs); trs = t2;
      }
      idx[count] = m;
      trs.set([x, y, z, q.x, q.y, q.z, q.w, s], count * 8);
      count++;
    }
    if (performance.now() - since > 14) {
      await yieldUi();
      if (my !== areaTool.gen) return null;
      since = performance.now();
    }
  }
  areaTool.ms = performance.now() - t0;
  return { models, idx: idx.subarray(0, count), trs: trs.subarray(0, count * 8), count };
}
// Spaziatura (like the Spacing tool of Twinmotion): pieces at regular steps along the line, as many as "Numero" or
// one every "Distanza"; each one moved sideways by a random part of the lateral offset, models in the order of the
// list (repeated) or at random by presence, dropped on the first surface under the line. Optionally turned along
// the line (their X axis follows it), so fences, benches or lamp posts line up.
async function spacingGenerate() {
  ++areaTool.gen;
  const models = paint.palette.filter((p) => p.weight > 0).map((p) => p.model);
  const empty = { models, idx: new Int32Array(0), trs: new Float32Array(0), count: 0 };
  const c = areaCurve();
  if (!areaTool.done || !c || !models.length) return empty;
  const len = c.getLength();
  const closed = areaTool.closed;
  let n, du;
  let at = null;           // with a random distance: where each piece goes along the line (0..1)
  if (paint.byCount) {
    n = Math.max(1, Math.min(100000, Math.round(paint.count)));
    du = closed ? 1 / n : n > 1 ? 1 / (n - 1) : 0;
  } else {
    const step = Math.max(0.01, paint.step);
    const extra = Math.max(0, paint.stepRand || 0);
    if (extra > 0 && len > 0) {
      // each gap = Distanza + a random part of «Distanza casuale»: never shorter than Distanza (no overlaps);
      // a closed line also keeps Distanza between the last piece and the first
      at = [0];
      const rg = mulberry(hash3(paint.seed | 0, 0x51ACE, 7));
      for (let s = step + rg() * extra; at.length < 100000; s += step + rg() * extra) {
        if (s > len + 1e-6 || (closed && s > len - step + 1e-6)) break;
        at.push(s / len);
      }
      n = at.length;
    } else {
      n = Math.min(100000, Math.floor(len / step + 1e-6) + (closed ? 0 : 1));
      n = Math.max(1, n);
    }
    du = len > 0 ? step / len : 0;
  }
  const lat = Math.max(0, paint.lateral);
  // surfaces near the line
  let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity, maxZ = -Infinity;
  const probe = c.getSpacedPoints(Math.max(8, areaSegs() * 16));
  for (const p of probe) { minX = Math.min(minX, p.x); maxX = Math.max(maxX, p.x); minY = Math.min(minY, p.y); maxY = Math.max(maxY, p.y); maxZ = Math.max(maxZ, p.z); }
  const meshes = paint.snap !== false ? areaSurfaces(minX - lat - 1, minY - lat - 1, maxX + lat + 1, maxY + lat + 1).map((m) => m.o) : null;
  const pr = new THREE.Raycaster();
  pr.firstHitOnly = true;
  const down = new THREE.Vector3(0, 0, -1), org = new THREE.Vector3(), nrm = new THREE.Vector3(), tan = new THREE.Vector3(), side = new THREE.Vector3();
  const quatUp = new THREE.Quaternion(), quatRot = new THREE.Quaternion(), q = new THREE.Quaternion();
  const ws = paint.palette.filter((p) => p.weight > 0).map((p) => p.weight);
  const lineItems = paint.palette.filter((p) => p.weight > 0);
  const tot = ws.reduce((a, b) => a + b, 0);
  const idx = new Int32Array(n), trs = new Float32Array(n * 8);
  const seed = paint.seed | 0, rot0 = THREE.MathUtils.degToRad(paint.rot);
  let count = 0;
  for (let i = 0; i < n; i++) {
    const rnd = mulberry(hash3(seed, i, 0x5a17));
    const uLat = rnd(), uModel = rnd(), uRot = rnd(), uScale = rnd();
    const u = at ? at[i] : paint.byCount && !closed && n === 1 ? 0.5 : Math.min(1, i * du);
    const p = c.getPointAt(u);
    c.getTangentAt(u, tan);
    tan.z = 0;
    if (tan.lengthSq() < 1e-12) tan.set(1, 0, 0);
    tan.normalize();
    side.set(-tan.y, tan.x, 0);
    p.addScaledVector(side, (uLat * 2 - 1) * lat);
    let z = p.z;
    nrm.set(0, 0, 1);
    if (meshes) {
      pr.set(org.set(p.x, p.y, Math.max(p.z, maxZ) + 2), down);
      const h = pr.intersectObjects(meshes, false)[0];
      if (h) {
        z = h.point.z;
        if (h.face) { nrm.copy(h.face.normal).transformDirection(h.object.matrixWorld); if (nrm.z < 0) nrm.negate(); }
      }
    }
    let m;
    if (paint.randomOrder) { let r = uModel * tot; m = 0; while (m < ws.length - 1 && (r -= ws[m]) > 0) m++; }
    else m = i % ws.length;
    const it = lineItems[m];
    const ang = itemAngle(it, rot0, uRot) + (paint.follow ? Math.atan2(tan.y, tan.x) : 0);
    quatRot.setFromAxisAngle(_up, ang);
    if (paint.align) quatUp.setFromUnitVectors(_up, nrm); else quatUp.identity();
    q.copy(quatUp).multiply(quatRot);
    const s = Math.max(0.02, itemScale(it, uScale));
    idx[count] = m;
    trs.set([p.x, p.y, z, q.x, q.y, q.z, q.w, s], count * 8);
    count++;
  }
  areaTool.ms = 1;
  return { models, idx: idx.subarray(0, count), trs: trs.subarray(0, count * 8), count };
}
// the pieces drawn in the view at once (before the engine has them)
function areaShowLocal(out) {
  const g = paint.group ? byId.get(paint.group) : null;
  const inv = g ? g.matrixWorld.clone().invert() : null;
  const per = out.models.map(() => 0);
  for (let i = 0; i < out.count; i++) per[out.idx[i]]++;
  const xfs = per.map((c) => new Float32Array(c * 16)), fill = per.map(() => 0);
  const over = paintSeasons(), seas = per.map((c) => new Float32Array(c));
  const p = new THREE.Vector3(), q = new THREE.Quaternion(), s = new THREE.Vector3(), m4 = new THREE.Matrix4();
  for (let i = 0; i < out.count; i++) {
    const t = out.trs, o = i * 8, k = out.idx[i];
    m4.compose(p.set(t[o], t[o + 1], t[o + 2]), q.set(t[o + 3], t[o + 4], t[o + 5], t[o + 6]), s.set(t[o + 7], t[o + 7], t[o + 7]));
    if (inv) m4.premultiply(inv);
    seas[k][fill[k]] = seasonOf(over, out.models[k], t[o], t[o + 1]);
    m4.toArray(xfs[k], fill[k]++ * 16);
  }
  const blocks = [];
  out.models.forEach((model, k) => {
    if (!per[k]) return;
    const P = protoForModel(model);
    blocks.push({ model, key: P && P.key ? P.key : '', id: '', count: per[k], xf: xfs[k], c: null, sea: over.has(model) ? seas[k] : null });
    ensureProto(model);
  });
  const old = scatter.sets.get(paint.group);
  scatter.sets.set(paint.group, { group: paint.group, rev: old ? old.rev : '', local: true, blocks, box: null });
  paint.editing = true;
  scatter.dirty = true; invalidate(300);
}
function areaData() {
  return { pts: areaTool.pts.map((p) => p.toArray().map((v) => +v.toFixed(4))), closed: areaTool.closed };
}
function areaSend(out) {
  paint.batch++;
  const b64 = (buf) => { let s = ''; const u = new Uint8Array(buf.buffer, buf.byteOffset, buf.byteLength); for (let i = 0; i < u.length; i += 0x8000) s += String.fromCharCode.apply(null, u.subarray(i, i + 0x8000)); return btoa(s); };
  post({
    type: 'paintSet', group: paint.group, batch: paint.batch, seed: paint.seed, strokes: [], mode: paint.mode, area: areaData(),
    packed: { models: out.models, idx: b64(out.idx), trs: b64(out.trs), count: out.count },
    settings: paintSettingsNow(),
  });
}
// the area again (points, settings, models or seed changed); send = also to the engine
let areaBusy = false, areaAgain = false;
async function areaRebuild(send) {
  if (!areaTool.done) return;
  paintFollowGroup();
  if (areaBusy) { areaAgain = areaAgain || send || 'show'; areaTool.gen++; return; }
  areaBusy = true;
  try {
    if (!paint.seed) paint.seed = (Math.random() * 1e9) | 0;
    const out = paint.mode === 'spacing' ? await spacingGenerate() : await areaGenerate();
    if (out) {
      areaTool.out = out;
      areaShowLocal(out);
      if (send) areaSend(out);
    }
  } finally {
    areaBusy = false;
    if (areaAgain) { const s = areaAgain === true; areaAgain = false; areaRebuild(s); }
  }
}
function areaPointerDown(e) {
  const hit = surfaceUnder(e.clientX, e.clientY);
  if (!areaTool.done) {
    if (!paint.seed) paint.seed = (Math.random() * 1e9) | 0;
    const h = areaHandleAt(e.clientX, e.clientY);
    const now = performance.now(), lc = areaTool.lastClick;
    const dbl = lc && now - lc.t < 400 && Math.hypot(lc.x - e.clientX, lc.y - e.clientY) < 6;
    areaTool.lastClick = { x: e.clientX, y: e.clientY, t: now };
    const last = areaTool.pts.length - 1;
    if (h && h.kind === 'pt' && h.i === 0 && areaTool.pts.length >= 3) { areaClose(true); return; }
    if ((dbl || (h && h.kind === 'pt' && h.i === last && last > 0)) && areaClose(false)) return;
    if (dbl) return;
    if (!hit) return;
    areaTool.pts.push(hit.point.clone());
    areaDraw();
    return;
  }
  const h = areaHandleAt(e.clientX, e.clientY);
  if (!h) { if (areaTool.sel >= 0) { areaTool.sel = -1; areaDraw(); } return; }
  if (h.kind === 'plus') {
    const c = areaCurve();
    const p = c.getPoint((h.i + 0.5) / areaSegs());
    areaTool.pts.splice(h.i + 1, 0, p);
    areaTool.sel = h.i + 1;
    areaTool.drag = { i: h.i + 1, moved: true };
  } else {
    areaTool.sel = h.i;
    areaTool.drag = { i: h.i, moved: false };
  }
  renderer.domElement.style.cursor = 'grabbing';
  areaDraw();
}
let areaLiveTimer = 0;
function areaPointerMove(e) {
  if (areaTool.drag) {
    const hit = surfaceUnder(e.clientX, e.clientY);
    if (!hit) return;
    areaTool.pts[areaTool.drag.i].copy(hit.point);
    areaTool.drag.moved = true;
    areaDraw();
    // small areas follow the point while it moves
    if (areaTool.ms < 60 && !areaLiveTimer) areaLiveTimer = setTimeout(() => { areaLiveTimer = 0; areaRebuild(false); }, 40);
    return;
  }
  if (!areaTool.done) {
    const hit = surfaceUnder(e.clientX, e.clientY);
    areaTool.cursor = hit ? hit.point.clone() : null;
  }
  const h = areaHandleAt(e.clientX, e.clientY);
  const was = areaTool.hover;
  areaTool.hover = h;
  renderer.domElement.style.cursor = h ? 'pointer' : areaTool.done ? '' : 'crosshair';
  if (!areaTool.done || (was ? JSON.stringify(was) : '') !== (h ? JSON.stringify(h) : '')) areaDraw();
}
function areaPointerUp() {
  const d = areaTool.drag;
  if (!d) return;
  areaTool.drag = null;
  renderer.domElement.style.cursor = '';
  if (d.moved) areaRebuild(true);
}
// keys of the area tool; true when used
function areaKey(k) {
  if (!paint.on || !lineTool()) return false;
  if (!areaTool.done) {
    if (k === 'Enter' || k === 'Escape') {
      if (areaClose()) return true;
      if (k === 'Escape' && areaTool.pts.length) { areaReset(); return true; }
      return k === 'Enter';
    }
    if (k === 'Backspace' || k === 'Delete') { if (areaTool.pts.length) { areaTool.pts.pop(); areaDraw(); } return true; }
    return false;
  }
  if ((k === 'Delete' || k === 'Backspace') && areaTool.sel >= 0) {
    if (areaTool.pts.length > areaMinPts() && (!areaTool.closed || areaTool.pts.length > 3)) {
      areaTool.pts.splice(areaTool.sel, 1);
      areaTool.sel = -1;
      areaDraw();
      areaRebuild(true);
    }
    return true;
  }
  return false;
}
// the area of a distribution (chosen in the tree, opened with the project, after undo/redo)
function areaLoad(a) {
  areaTool.gen++;
  areaTool.pts = (a && a.pts || []).map((p) => new THREE.Vector3().fromArray(p));
  areaTool.done = areaTool.pts.length >= areaMinPts();
  areaTool.closed = areaTool.done && (paint.mode === 'area' || !!(a && a.closed));
  areaTool.sel = -1; areaTool.hover = null; areaTool.drag = null; areaTool.out = null;
  paintGroupMark();
  areaDraw();
}
// where the distribution was when its line and strokes came (the engine already moved them with it, paint.py): moved
// again while it is being edited, they follow it before the pieces are made again
let paintGroupAt = null;
function paintGroupMark() {
  const g = paint.group ? byId.get(paint.group) : null;
  paintGroupAt = g ? (g.updateMatrixWorld(true), g.matrixWorld.clone()) : null;
}
function paintFollowGroup() {
  const g = paint.group ? byId.get(paint.group) : null;
  if (!g || !paintGroupAt) { paintGroupMark(); return; }
  g.updateMatrixWorld(true);
  if (g.matrixWorld.equals(paintGroupAt)) return;
  const d = g.matrixWorld.clone().multiply(paintGroupAt.clone().invert());
  const r = new THREE.Matrix3().setFromMatrix4(d);
  for (const p of areaTool.pts) p.applyMatrix4(d);
  for (const st of paint.strokes) {
    if (st.p) st.p = new THREE.Vector3().fromArray(st.p).applyMatrix4(d).toArray();
    if (st.n) st.n = new THREE.Vector3().fromArray(st.n).applyMatrix3(r).normalize().toArray();
  }
  paintGroupAt = g.matrixWorld.clone();
  areaDraw();
}

// ------------------------------------------------------------------ painted pieces: GPU instancing + levels of detail
// Every painted piece (Distribuisci) is only a placeholder here: an empty node with its id and its position. They
// are all drawn from one copy of their library model (its "prototype", a small GLB made once by the engine, see
// paint.py) with one InstancedMesh per part of the model and per level of detail: thousands of pieces cost a few
// draw calls. The levels (30%, 8%, 2% of the triangles, lodworker.js) are chosen per piece from its size on the
// screen, and pushed further when the scene has more triangles than the video card can draw smoothly: the budget
// follows the measured frame time. Pieces outside the view are not drawn. A selected piece is drawn as a normal
// mesh (outline, gizmo); clicks hit the pieces through the lightest level.
const LOD_SIZES = [0.5, 0.16, 0.05];        // part of the screen height for the levels 0, 1, 2 (smaller: 3)
const scatterRoot = new THREE.Group();
scatterRoot.name = 'scatter';
scene.add(scatterRoot);
const scatter = {
  nodes: new Set(), protos: new Map(), shown: new Map(), dirty: true, k: 1, budget: 40e6, tris: 0, drawn: 0,
  rs: new Float32Array(0), ri: new Int32Array(0), rb: new Int32Array(0), rl: new Uint8Array(0),
  cam: new THREE.Matrix4(), proj: new THREE.Matrix4(),
};
const waitDots = new THREE.InstancedMesh(new THREE.ConeGeometry(0.5, 1, 6).translate(0, 0.5, 0).rotateX(Math.PI / 2),
  new THREE.MeshBasicMaterial({ color: 0x6fd66f }), 4096);
waitDots.count = 0; waitDots.userData.helper = true; waitDots.frustumCulled = false; waitDots.raycast = () => {};
scatterRoot.add(waitDots);
// the cone where a model is still arriving: always the same size in the world (25 × 40 cm), whatever the scale of the
// object - a model imported in inches has scale 37.8 and its cone filled the whole view
const _wdP = new THREE.Vector3(), _wdQ = new THREE.Quaternion(), _wdS = new THREE.Vector3(), _wdM = new THREE.Matrix4();
const _wdSize = new THREE.Vector3(0.25, 0.25, 0.4);
function waitDotMatrix(m) {
  m.decompose(_wdP, _wdQ, _wdS);
  return _wdM.compose(_wdP, _wdQ, _wdSize);
}
let lodWorker = null;
const lodJobs = new Map();
function lodRequest(key, geom) {
  if (!lodWorker) {
    try {
      lodWorker = new Worker(new URL('./lodworker.js', import.meta.url), { type: 'module' });
      lodWorker.onmessage = (ev) => { const cb = lodJobs.get(ev.data.key); lodJobs.delete(ev.data.key); if (cb) cb(ev.data); };
    } catch (e) { console.warn('LOD worker', e); return Promise.resolve(null); }
  }
  const plain = (a) => {
    if (!a.isInterleavedBufferAttribute) return { array: a.array.slice(), itemSize: a.itemSize, normalized: a.normalized };
    const out = new Float32Array(a.count * a.itemSize);
    for (let i = 0; i < a.count; i++) for (let k = 0; k < a.itemSize; k++) out[i * a.itemSize + k] = a.getComponent(i, k);
    return { array: out, itemSize: a.itemSize, normalized: false };
  };
  const attrs = {};
  for (const [name, a] of Object.entries(geom.attributes)) attrs[name] = plain(a);
  const position = attrs.position.array instanceof Float32Array ? attrs.position.array : Float32Array.from(attrs.position.array);
  const index = geom.index ? Uint32Array.from(geom.index.array) : null;
  return new Promise((resolve) => { lodJobs.set(key, resolve); lodWorker.postMessage({ key, position, index, attrs }); });
}
function lodGeometry(base, lv) {
  const g = new THREE.BufferGeometry();
  if (lv.attrs) for (const [name, a] of Object.entries(lv.attrs)) g.setAttribute(name, new THREE.BufferAttribute(a.array, a.itemSize, a.normalized));
  else for (const [name, a] of Object.entries(base.attributes)) g.setAttribute(name, a);
  g.setIndex(new THREE.BufferAttribute(lv.index, 1));
  g.groups = [];
  g.computeBoundingSphere();
  return g;
}
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
// prototypes are kept by their key (what the piece looks like: parts, materials, see proto_key in core.py); a brush
// that has no piece yet asks by model ('m:' + model)
function protoOf(node) {
  const u = node.userData;
  if (u.protoKey) {
    const P = scatter.protos.get(u.protoKey);
    if (P && P.state === 'ready') return P;
    // its new look is still being prepared: the previous one meanwhile (no gap, no cones)
    const Q = u.prevKey ? scatter.protos.get(u.prevKey) : null;
    return Q && Q.state === 'ready' ? Q : P;
  }
  return protoForModel(u.paintModel);
}
function protoForModel(model) {
  const P = scatter.protos.get('m:' + model);
  if (P && P.state === 'ready') return P;
  for (const Q of scatter.protos.values()) if (Q.model === model && Q.state === 'ready') return Q;
  return P;
}
function nodeProto(node) {
  const u = node.userData;
  if (u.protoKey && !scatter.protos.has(u.protoKey)) ensureProto(u.paintModel, u.protoKey, u.simpler_id || '');
  const P = protoOf(node);
  if (!P) ensureProto(u.paintModel, u.protoKey || '', u.simpler_id || '');
  return P;
}
const protoFails = new Map();          // mapKey -> {n, t}: prototypes that could not be made (see the catch below)
// (15/11, log of Luca: opening a street = 20 s of «models for the view» after the shaders were no longer the problem) where the time
// goes, per opening: waiting for the engine, download, reading the file, preparing - one line in the log when all have arrived
const protoStat = { n: 0, wait: 0, down: 0, read: 0, prep: 0, t0: 0, slow: '', slowMs: 0 };
function protoStatDone() {
  if (!protoStat.n) return;
  const s = (ms) => (ms / 1000).toFixed(1);
  viewLog(`models for the view: ${protoStat.n} models in ${s(performance.now() - protoStat.t0)} s (one after the other they add up to: engine ${s(protoStat.wait)} s, download ${s(protoStat.down)} s, ` +
    `reading ${s(protoStat.read)} s, preparing ${s(protoStat.prep)} s); slowest: ${protoStat.slow} ${s(protoStat.slowMs)} s`);
  protoStat.n = 0; protoStat.wait = protoStat.down = protoStat.read = protoStat.prep = 0; protoStat.slow = ''; protoStat.slowMs = 0;
}
async function ensureProto(model, key = '', id = '') {
  const mapKey = key || ('m:' + model);
  if (!model || scatter.protos.has(mapKey) || !engineUrl) return;
  const P = { state: 'loading', parts: [], tris: [0, 0, 0, 0], center: new THREE.Vector3(), radius: 1, place: null, model };
  scatter.protos.set(mapKey, P);
  const label = String(model).split(/[\\/]/).pop().replace(/\.[^.]+$/, '');
  protoBusy.total++; protoProgress(label);
  let counted = false;
  const finished = () => { if (!counted) { counted = true; protoBusy.done++; protoProgress(''); if (protoBusy.done >= protoBusy.total) { try { protoStatDone(); } catch { } } } };
  const _t0 = performance.now();
  if (!protoStat.n && protoBusy.done + 1 >= protoBusy.total) protoStat.t0 = _t0;
  try {
    let st = null;
    for (let i = 0; i < 600; i++) {
      st = await (await fetch(engineUrl + 'paint/proto?model=' + encodeURIComponent(model) + '&key=' + encodeURIComponent(key) + '&id=' + encodeURIComponent(id), { cache: 'no-store' })).json();
      if (st.state !== 'running') break;
      await sleep(400);
    }
    if (!st || st.state !== 'done') throw new Error((st && st.error) || 'prototype');
    if (st.key && st.key !== key) {
      const Q = scatter.protos.get(st.key);
      if (Q && Q !== P) { scatter.protos.set(mapKey, Q); finished(); return; }   // the same prototype, already loaded or loading
      scatter.protos.set(st.key, P);
    }
    P.key = st.key || key;
    const _t1 = performance.now(), _url = engineUrl + 'paint/proto.glb?f=' + encodeURIComponent(st.file);
    const gltf = await loader.loadAsync(_url);
    const _t2 = performance.now();
    let _down = 0;
    try { const e = performance.getEntriesByName(_url).pop(); if (e) _down = Math.min(_t2 - _t1, e.responseEnd - e.startTime); performance.clearResourceTimings(); } catch { }
    const src = gltf.scene;
    src.updateMatrixWorld(true);
    // volumetric materials (a cloud saved in the library): drawn as volumes here too - they were left with the
    // material of the export, and the cloud came out as its pieces (a heap of grey discs)
    src.traverse((o) => { if (o.isMesh) volApply(o); });
    // (1.78.4) the materials of Simpler as the view draws them (an inverted opacity map, the leaves, the cloth): the
    // glTF has only what its export understands
    const own = st.mats || {};
    if (Object.keys(own).length) src.traverse((o) => {
      if (!o.isMesh) return;
      const sw = (m) => (m && own[m.name] && !m.userData.volume ? rtMaterial(own[m.name]) : m);
      o.material = Array.isArray(o.material) ? o.material.map(sw) : sw(o.material);
    });
    const box = new THREE.Box3();
    const mats = [];
    src.traverse((o) => {
      if (!o.isMesh) return;
      const count = o.isInstancedMesh ? o.count : 1;
      for (let j = 0; j < count; j++) {
        const rel = o.matrixWorld.clone();
        if (o.isInstancedMesh) { const im = new THREE.Matrix4(); o.getMatrixAt(j, im); rel.multiply(im); }
        if (!o.geometry.boundingBox) o.geometry.computeBoundingBox();
        box.union(o.geometry.boundingBox.clone().applyMatrix4(rel));
        P.parts.push({ geom: o.geometry, mat: o.material, rel, levels: [o.geometry], tris: [triCount(o.geometry)], meshes: [] });
        mats.push(o.material);
      }
    });
    indexMaterials(src);
    P.parts = mergePartsByMaterial(P.parts);
    const sph = box.getBoundingSphere(new THREE.Sphere());
    P.center.copy(sph.center); P.radius = Math.max(sph.radius, 1e-3);
    // where the base of the model is (painted pieces stand on it): for the preview of a stroke
    protoSetPlace(P, st);
    P.tris = [0, 1, 2, 3].map(() => P.parts.reduce((a, p) => a + p.tris[0], 0));
    P.state = 'ready';
    {
      const _t3 = performance.now();
      if (!protoStat.n && !protoStat.t0) protoStat.t0 = _t0;
      protoStat.n++; protoStat.wait += _t1 - _t0; protoStat.down += _down; protoStat.read += Math.max(0, _t2 - _t1 - _down); protoStat.prep += _t3 - _t2;
      if (_t3 - _t0 > protoStat.slowMs) { protoStat.slowMs = _t3 - _t0; protoStat.slow = label; }
    }
    finished();
    scatter.dirty = true; invalidate(400);
    protoWarm(P);
    // selected pieces drawn with a previous look: with this one now
    for (const [node, g] of [...scatter.shown]) if (node.userData.protoKey === P.key && g.userData.proto !== P) { node.remove(g); scatter.shown.delete(node); }
    scatterSelection();
    // a piece selected while its model was still arriving (a library car dropped near the camera: selected at once,
    // drawn a moment later) had no size yet: its gizmo went to the model's origin (half a metre under the floor
    // for a car) and stayed there. Now the gizmo and the boxes are placed again on the real model
    if (selection.some((id) => { const n = byId.get(id); return n && n.userData.paintPiece && protoOf(n) === P; })) {
      placePivot(); refreshSelectionBoxes(); updateHud(); invalidate(300);
    }
    // the lighter levels, one part after the other (until they arrive the full model is used)
    for (let i = 0; i < P.parts.length; i++) {
      const part = P.parts[i];
      const r = await lodRequest(model + '#' + i, part.geom);
      if (!r || r.error || !r.levels) { part.levels = [part.geom, part.geom, part.geom, part.geom]; part.tris = [part.tris[0], part.tris[0], part.tris[0], part.tris[0]]; continue; }
      part.levels = [part.geom, ...r.levels.map((lv) => lodGeometry(part.geom, lv))];
      part.tris = r.tris;
      for (const m of part.meshes) if (m) partMeshDrop(m);
      part.meshes = [];
    }
    for (const part of P.parts) while (part.levels.length < 4) { part.levels.push(part.levels[part.levels.length - 1]); part.tris.push(part.tris[part.tris.length - 1]); }
    P.tris = [0, 1, 2, 3].map((l) => P.parts.reduce((a, p) => a + p.tris[l], 0));
    scatter.dirty = true; invalidate(400);
  } catch (err) {
    P.state = 'error';
    finished();
    console.warn('prototype', model, err);
    // (1.75.62) tried again a few times, further and further apart, then left alone: before, it was forgotten after
    // 1.5 s and asked again at once, for ever - «Preparing the model for the view» flashing endlessly, the view stuck
    // (Luca: a material dropped on a piece of a library car)
    const f = protoFails.get(mapKey) || { n: 0 };
    f.n++; f.t = performance.now();
    protoFails.set(mapKey, f);
    viewLog('model not prepared for the view: ' + label + ' · ' + (err && err.message ? err.message : err) + ' (attempt ' + f.n + ')');
    if (f.n <= 3) setTimeout(() => { for (const [k, Q] of [...scatter.protos]) if (Q === P) scatter.protos.delete(k); scatter.dirty = true; invalidate(300); }, 1500 * Math.pow(4, f.n - 1));
  }
}
// The parts of a model with the same material become one geometry: a building of a kit can have hundreds of
// pieces, and every piece was one draw call per level for all its copies (112 buildings: 12 000 draw calls, 16 fps,
// and the budget then hid the far ones). Merged: one draw call per material and level.
function plainGeometry(g, rel) {
  const out = new THREE.BufferGeometry();
  for (const [name, a] of Object.entries(g.attributes)) {
    const n = a.count, k = a.itemSize, arr = new Float32Array(n * k);
    for (let i = 0; i < n; i++) for (let c = 0; c < k; c++) arr[i * k + c] = a.getComponent(i, c);
    out.setAttribute(name, new THREE.BufferAttribute(arr, k));
  }
  if (g.index) out.setIndex(new THREE.BufferAttribute(Uint32Array.from(g.index.array), 1));
  else { const idx = new Uint32Array(out.attributes.position.count); for (let i = 0; i < idx.length; i++) idx[i] = i; out.setIndex(new THREE.BufferAttribute(idx, 1)); }
  out.applyMatrix4(rel);
  if (rel.determinant() < 0) {                 // a mirrored piece: keep its faces turned outwards
    const ix = out.index.array;
    for (let i = 0; i < ix.length; i += 3) { const s = ix[i + 1]; ix[i + 1] = ix[i + 2]; ix[i + 2] = s; }
  }
  return out;
}
function mergePartsByMaterial(parts) {
  const groups = new Map();
  for (const p of parts) {
    const key = Array.isArray(p.mat) ? p : p.mat;
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(p);
  }
  if (groups.size === parts.length) return parts;
  const out = [];
  for (const list of groups.values()) {
    if (list.length === 1 || Array.isArray(list[0].mat)) { out.push(...list); continue; }
    try {
      // every attribute any part has (a part without normals gets them computed, without uv or colours: zeros)
      const sizes = new Map();
      for (const p of list) for (const [n, a] of Object.entries(p.geom.attributes)) if (!sizes.has(n)) sizes.set(n, a.itemSize);
      if (list.some((p) => [...sizes].some(([n, k]) => p.geom.attributes[n] && p.geom.attributes[n].itemSize !== k))) { out.push(...list); continue; }
      const geoms = list.map((p) => {
        const g = plainGeometry(p.geom, p.rel);
        for (const [n, k] of sizes) {
          if (g.attributes[n]) continue;
          if (n === 'normal') g.computeVertexNormals();
          else g.setAttribute(n, new THREE.BufferAttribute(new Float32Array(g.attributes.position.count * k), k));
        }
        return g;
      });
      const merged = mergeGeometries(geoms, false);
      if (!merged) { out.push(...list); continue; }
      merged.computeBoundingBox(); merged.computeBoundingSphere();
      out.push({ geom: merged, mat: list[0].mat, rel: new THREE.Matrix4(), levels: [merged], tris: [triCount(merged)], meshes: [] });
    } catch (err) {
      console.warn('merge parts', err);
      out.push(...list);
    }
  }
  return out;
}
// a material changed on a part of library pieces: every prototype using it (pieces share their materials)
// the material a prototype already has with this name (library models: their materials come with the prototype,
// not with the export of the scene - after a new export the view did not know them any more)
function protoMaterial(name) {
  for (const P of scatter.protos.values()) for (const part of P.parts || []) if (part.mat && part.mat.name === name) return part.mat;
  return null;
}
function scatterMaterials(slots) {
  for (const s of slots) {
    const old = s.old || s.name;
    if (!old) continue;
    // a textured material not edited in Simpler that the view knows only from the prototypes: kept as it is (before
    // it became its plain colour - a whole building white - when another material of the same pieces changed)
    // the same material as before, not edited in Simpler (it comes along because another material of the piece
    // changed or is switched at dusk): the prototype keeps what it has, with its textures
    if (!s.simpler && s.name === old) continue;
    if (!s.simpler && !exportMaterials.has(s.name) && !knownMaterials.has(s.name)) {
      const own = protoMaterial(s.name);
      if (!own) continue;
      for (const P of new Set(scatter.protos.values())) for (const part of P.parts) if (part.mat && part.mat.name === old) part.mat = own;
      for (const g of scatter.shown.values()) g.traverse((m) => { if (m.isMesh && m.material && m.material.name === old) m.material = own; });
      shadersDirty();
      continue;
    }
    const mat = slotMaterial(s);
    for (const P of new Set(scatter.protos.values())) for (const part of P.parts) if (part.mat && part.mat.name === old) part.mat = mat;
    for (const g of scatter.shown.values()) g.traverse((m) => { if (m.isMesh && m.material && m.material.name === old) m.material = mat; });
    shadersDirty();
  }
  scatter.dirty = true;
}
function triCount(g) { return (g.index ? g.index.count : g.attributes.position.count) / 3; }

// a node of the view becomes a painted piece (placeholder); a new one is made when the view has none
function scatterAdopt(node, model, gen, key) {
  node.userData.paintModel = model;
  if (gen !== undefined) node.userData.paintGen = !!gen;
  if (key !== undefined) node.userData.protoKey = key || '';
  node.userData.paintPiece = true;
  scatter.nodes.add(node);
  scatter.dirty = true;
  nodeProto(node);
}
// a piece no longer drawn from its library model (the model opened for its parts, MainWindow.OpenModel)
function scatterRelease(node) {
  const g = scatter.shown.get(node);
  if (g) { node.remove(g); scatter.shown.delete(node); }
  scatter.nodes.delete(node);
  const u = node.userData;
  delete u.paintPiece; delete u.paintModel; delete u.protoKey; delete u.prevKey; delete u.paintGen;
  scatter.dirty = true;
}
function scatterPlaceholder(id, model, parent, gen, key) {
  const node = new THREE.Object3D();
  node.name = id;
  node.userData.simpler_id = id;
  (parent || root).add(node);
  byId.set(id, node);
  scatterAdopt(node, model, gen, key);
  return node;
}
// A new or another project: everything the view kept for the old one goes (models of the distributions with their
// levels of detail, textures, materials). Without this the view kept gigabytes of a heavy scene after "Nuovo".
function releaseAll() {
  const geoms = new Set(), mats = new Set();
  for (const P of new Set(scatter.protos.values())) {
    for (const part of P.parts || []) {
      for (const g of part.levels || []) if (g) geoms.add(g);
      if (part.geom) geoms.add(part.geom);
      for (const m of part.meshes || []) if (m) partMeshDrop(m);
      part.meshes = [];
      for (const mt of Array.isArray(part.mat) ? part.mat : [part.mat]) if (mt) mats.add(mt);
    }
  }
  scatter.protos.clear();
  scatter.sets.clear();
  scatter.syncRev.clear();
  for (const m of rtMaterials.values()) mats.add(m);
  for (const m of knownMaterials.values()) mats.add(m);
  for (const m of exportMaterials.values()) mats.add(m);
  rtMaterials.clear(); knownMaterials.clear(); exportMaterials.clear();
  const texs = new Set();
  for (const m of mats) {
    for (const v of Object.values(m)) if (v && v.isTexture) texs.add(v);
    m.dispose();
  }
  for (const t of texs) t.dispose();
  for (const g of geoms) g.dispose();
  texCache.clear();
  if (typeof THREE.Cache !== 'undefined') THREE.Cache.clear();
  renderer.renderLists.dispose();
  scatter.dirty = true;
}
function scatterReset() {
  for (const [node, g] of scatter.shown) node.remove(g);
  scatter.shown.clear();
  scatter.nodes.clear();
  scatter.dirty = true;
}
// selected pieces: drawn as real meshes (outline, gizmo, click on the exact surface)
// (1.75.13) the shaders of a model drawn as plain meshes (how a selected piece is drawn: outline, gizmo) made in the
// background as soon as its prototype is ready - selecting a car is then immediate, not seconds of «Aggiornamento
// dei materiali» (Luca). Never inside a frame.
// (1.75.23) The shaders depend on the lights of the view (how many, which ones with shadows): when they change -
// the lamps of the distributions lit at dusk, a light more, SmartView holding them - the plain-mesh shaders made
// before are of no use any more, and the view's own preparation does not make them again (nothing in the scene is
// drawn as a plain mesh). Selecting a car then made 3 shaders inside one frame: 9 s with SmartView on (Luca). Now
// every prototype already warmed is warmed again with the new lights, in the background after the view's own.
const _warmQ = [];
const _warmed = new Map();      // prototype -> the lights of the view its plain-mesh shaders were made with
function protoWarm(P) {
  return;                           // (nothing is drawn as plain meshes any more, see scatterSelection)
  if (_warmQ.includes(P)) return;
  _warmQ.push(P);
  if (_warmQ.length === 1) setTimeout(protoWarmNext, 1500);
}
function protoRewarm() {
  return;                           // (see protoWarm)
  const live = new Set(scatter.protos.values());
  for (const P of [..._warmed.keys()]) {
    if (!live.has(P) || P.state !== 'ready') { _warmed.delete(P); continue; }   // (a model gone from the scene)
    protoWarm(P);
  }
}
function protoWarmNext() {
  const P = _warmQ[0];
  if (!P) return;
  if (shaderPrep.busy || !renderer || _lightSig === null || _smartOn) { setTimeout(protoWarmNext, 700); return; }
  const g = new THREE.Group();
  for (const part of P.parts) if (part.mat && part.geom) {
    const m = new THREE.Mesh(part.geom, part.mat);
    m.castShadow = m.receiveShadow = true;
    m.parent = g; g.children.push(m);       // (not add(): that would ask for the preparation of the whole view)
  }
  let p;
  _inCompile = true;
  try { p = renderer.compileAsync(g, camera, scene); } catch (err) { p = Promise.resolve(); }
  _inCompile = false;
  _warmed.set(P, _lightSig);
  p.catch(() => {}).then(() => { _warmQ.shift(); if (_warmQ.length) setTimeout(protoWarmNext, 50); });
}
const SMART_TWIN = new THREE.MeshBasicMaterial({ colorWrite: false, depthWrite: false });
SMART_TWIN.userData.smartCheap = true; SMART_TWIN.userData.dry = true;
const _sdiag = { skip: 0, cull: 0, hid: [], last: '' };
function scatterSelection() {
  const want = new Set();
  for (const id of selection) { const n = byId.get(id); if (n && n.userData.paintPiece) want.add(n); }
  for (const [node, g] of [...scatter.shown]) if (!want.has(node) || !node.parent) { node.remove(g); scatter.shown.delete(node); }
  for (const node of want) {
    if (scatter.shown.has(node)) continue;
    const P = protoOf(node);
    if (!P || P.state !== 'ready') continue;
    const g = new THREE.Group();
    g.userData.displayClone = true;
    g.userData.proto = P;
    // (SmartView: the copy stays drawn; this twin draws nothing - outline, gizmo and clicks only - no shader to make)
    // (Luca: selecting a car = the red box «Aggiornamento dei materiali», 5-20 s) ALWAYS so, not only in
    // SmartView: the selected piece used to be drawn as normal meshes, and a normal mesh needs shaders of its own
    // (three.js makes different ones from an instanced mesh) for every material of the car, 14 for a car, seconds each
    // on a slow driver. Now the piece stays drawn by its instance (same shaders as before the click); the twin only
    // gives the outline, the gizmo and the clicks something to work on
    g.userData.smart = true;
    for (const part of P.parts) {
      const m = new THREE.Mesh(part.geom, SMART_TWIN);
      m.matrixAutoUpdate = false; m.matrix.copy(part.rel);
      m.castShadow = m.receiveShadow = false;
      m.userData.realMat = part.mat;      // (what the eyedropper and the material editor name: the twin itself has no material of the scene)
      g.add(m);
    }
    node.add(g);
    scatter.shown.set(node, g);
  }
  scatter.dirty = true;
}
// Every instanced mesh has its own small geometry: the buffers of its level (shared, nothing copied) plus its own
// «Sempre asciutto» per instance (1 = the rain leaves it alone; the instances of a model are shared by all the
// distributions that use it, so it is said per instance). Before (1.44.3 - 1.45.2) that buffer was put on the shared
// geometry of the level: a level not arrived yet (the lighter levels are made one part after the other, minutes for
// a city) stopped the whole update of the pieces with an error - buildings and cars stayed invisible - and meshes of
// different sizes sharing one geometry overwrote each other's buffer.
function instGeometry(src, n) {
  const g = new THREE.BufferGeometry();
  for (const [name, a] of Object.entries(src.attributes)) if (name !== 'wetDry' && name !== 'foSea') g.setAttribute(name, a);
  g.setIndex(src.index);
  for (const gr of src.groups) g.addGroup(gr.start, gr.count, gr.materialIndex);
  g.setDrawRange(src.drawRange.start, src.drawRange.count);
  if (!src.boundingSphere) src.computeBoundingSphere();
  g.boundingSphere = src.boundingSphere; g.boundingBox = src.boundingBox;
  g.setAttribute('wetDry', new THREE.InstancedBufferAttribute(new Float32Array(n), 1));
  g.setAttribute('foSea', new THREE.InstancedBufferAttribute(new Float32Array(n), 1));     // (1.79.0: season per piece)
  g.userData.volSrc = src;
  return g;
}
// (only its own buffer goes with it: the buffers of the level stay, other meshes use them)
// (1.75.26) the material the copies of a part are drawn with: in SmartView its plain stand-in while its own shader is
// not made (a model put in the scene with SmartView on), see _smartOn
function partMat(part) {
  if (!_smartOn || !needsProgram(part.mat)) return part.mat;
  return Array.isArray(part.mat) ? part.mat.map(standInOf) : standInOf(part.mat);
}
function partMeshDrop(m) {
  scatterRoot.remove(m);
  const g = m.geometry, own = g.attributes.wetDry, sea = g.attributes.foSea;
  g.attributes = {}; if (own) g.attributes.wetDry = own; if (sea) g.attributes.foSea = sea; g.index = null;
  g.dispose();
  m.dispose();
}
function partMesh(part, level, need) {
  let m = part.meshes[level];
  if (m && m.instanceMatrix.count >= need) return m;
  if (m) partMeshDrop(m);
  const cap = Math.max(16, Math.ceil(need * 1.5));
  // a lighter level not made yet: the nearest one there is meanwhile (it is replaced when it arrives)
  const vol = (Array.isArray(part.mat) ? part.mat : [part.mat]).some((x) => x && x.userData.volume);
  // (a volume: always its full shape - the lighter levels would change the cloud - and no shadow of its surface)
  const src = vol ? part.geom : (part.levels[Math.min(level, part.levels.length - 1)] || part.geom);
  m = new THREE.InstancedMesh(instGeometry(src, cap), part.mat, cap);
  m.frustumCulled = false; m.castShadow = !vol; m.receiveShadow = !vol;
  m.userData.scatter = true;
  m.raycast = () => {};
  m.count = 0;
  part.meshes[level] = m;
  scatterRoot.add(m);
  return m;
}
// ---- distributions: one set of points each (paint.py), drawn per model with the same instancing and levels
// Every point has a 4x4 matrix in the space of its group (where the base of the model goes, its rotation and
// scale). The engine sends them as a block of float32 (GET paint/points); while a distribution is being changed
// the view draws the points it has just made itself (local set) and keeps them when the engine confirms.
const LOD_HIDE = 0.004;            // smaller on the screen than this: not drawn (a far blade of grass)
const LOD_HIDE_MAX = 0.02;         // the budget never hides a piece taller than 2% of the view (far buildings stay)
scatter.sets = new Map();          // group id ('' = a new one not made yet) -> {group, rev, local, blocks}
scatter.syncRev = new Map();       // group id -> the last version of its points told by the app
const _sx = new THREE.Matrix4(), _sy = new THREE.Matrix4(), _sv = new THREE.Vector3();
// (1.79.0, Luca: «se è una vegetazione puoi aggiungere season») the season of a piece from the settings of its model
// in the brush (season, seasonRand): 1 + season, 0 = the material's own. The random number comes from its place, as
// paint._season_hash in the engine (the same piece gets the same season in the view and in the render).
function seasonHash(x, y) {
  const ix = Math.floor(Math.fround(x) * 1000 + 0.5) | 0, iy = Math.floor(Math.fround(y) * 1000 + 0.5) | 0;
  let h = (Math.imul(ix, 73856093) ^ Math.imul(iy, 19349663)) >>> 0;
  for (let k = 0; k < 2; k++) { h = (h ^ (h >>> 16)) >>> 0; h = Math.imul(h, 0x45D9F3B) >>> 0; }
  h = (h ^ (h >>> 16)) >>> 0;
  return h / 4294967296;
}
function paintSeasons() {
  const m = new Map();
  for (const e of paint.palette) {
    const sv = +e.season || 0, rv = +e.seasonRand || 0;
    if (sv > 0 || rv > 0) m.set(e.model, [sv, rv]);
  }
  return m;
}
function seasonOf(over, model, x, y) {
  const o = over.get(model);
  if (!o) return 0;
  return 1 + Math.min(1, Math.max(0, o[0] + (seasonHash(x, y) * 2 - 1) * o[1]));
}
function scatterLocalSet(group, items, cache) {
  const g = group ? byId.get(group) : null;
  const inv = g ? g.matrixWorld.clone().invert() : null;
  // cache (the brush): the matrices already made stay, only the pieces added since are composed (arrays grown by
  // half when full); a piece erased, a new frame of the group or a regeneration start it again (paintLocalReset)
  if (cache && cache.inv && (!inv || !cache.inv.equals(inv))) { cache.by = new Map(); cache.done = 0; }
  if (cache && !cache.inv && inv && cache.done) { cache.by = new Map(); cache.done = 0; }
  const by = cache ? cache.by : new Map();
  const from = cache ? Math.min(cache.done, items.length) : 0;
  const over = paintSeasons();
  for (let k = from; k < items.length; k++) {
    const it = items[k];
    if (!it.alive) continue;
    let e = by.get(it.model);
    if (!e) by.set(it.model, e = { xf: new Float32Array(16 * 64), sea: new Float32Array(64), n: 0 });
    if ((e.n + 1) * 16 > e.xf.length) {
      const bigger = new Float32Array(Math.max(e.xf.length * 1.5, (e.n + 1) * 16) | 0); bigger.set(e.xf); e.xf = bigger;
      const sb = new Float32Array(bigger.length / 16 | 0); sb.set(e.sea); e.sea = sb;
    }
    e.sea[e.n] = seasonOf(over, it.model, it.pos.x, it.pos.y);
    _sx.compose(it.pos, it.q, _sv.set(it.s, it.s, it.s));
    if (inv) _sx.premultiply(inv);
    _sx.toArray(e.xf, e.n * 16);
    e.n++;
  }
  if (cache) { cache.done = items.length; cache.inv = inv; }
  const blocks = [];
  for (const [model, e] of by) {
    if (!e.n) continue;
    const P = protoForModel(model);
    blocks.push({ model, key: P && P.key ? P.key : '', id: '', count: e.n, xf: e.xf, c: null, sea: over.has(model) ? e.sea : null });
    ensureProto(model);
  }
  const old = scatter.sets.get(group);
  scatter.sets.set(group, { group, rev: old ? old.rev : '', local: true, blocks, box: null });
  scatter.dirty = true; invalidate(300);
}
function scatterLocalDone(group, rev) {
  // a new distribution was drawn under '' until the engine gave it its id
  const blank = group ? scatter.sets.get('') : null;
  if (blank) { scatter.sets.delete(''); blank.group = group; scatter.sets.set(group, blank); }
  const set = scatter.sets.get(group);
  if (set) set.local = false;
  // the engine's points replace the ones drawn here (same pieces, with the exact look of every model)
  const r = scatter.syncRev.get(group);
  if (set && r && set.rev !== r) scatterFetchSet(group, r);
  scatter.dirty = true;
}
async function scatterFetchSet(group, rev) {
  const cur = scatter.sets.get(group);
  if ((cur && (cur.local || cur.rev === rev)) || !engineUrl) return;
  scatter.sets.set(group, { group, rev, local: false, blocks: cur ? cur.blocks : [], box: null, loading: true });
  try {
    const info = await (await fetch(engineUrl + 'paint/points?group=' + encodeURIComponent(group), { cache: 'no-store' })).json();
    const buf = info.file ? await (await fetch(engineUrl + 'paint/points.bin?f=' + encodeURIComponent(info.file), { cache: 'no-store' })).arrayBuffer() : new ArrayBuffer(0);
    const all = new Float32Array(buf);
    // (1.79.0) the season of each piece, same order, when the distribution has some
    const seaAll = info.sea ? new Float32Array(await (await fetch(engineUrl + 'paint/points.bin?f=' + encodeURIComponent(info.sea), { cache: 'no-store' })).arrayBuffer()) : null;
    let off = 0;
    const blocks = (info.models || []).map((m) => {
      const xf = all.subarray(off * 16, (off + m.count) * 16);
      const sea = seaAll && seaAll.length >= off + m.count ? seaAll.subarray(off, off + m.count) : null;
      off += m.count;
      ensureProto(m.model, m.key, m.id);
      return { model: m.model, key: m.key, id: m.id, count: m.count, xf, c: null, lamps: m.lamps || [], sea: sea && sea.some((v) => v > 0.5) ? sea : null };
    });
    const now = scatter.sets.get(group);
    if (now && now.local) return;                     // changed here meanwhile: what is drawn here wins
    scatter.sets.set(group, { group, rev, local: false, blocks, box: null });
    distLamps.dirty = true;
  } catch (err) {
    console.warn('points', group, err);
    scatter.sets.delete(group);
  }
  scatter.dirty = true; invalidate(400);
}
function protoSetPlace(P, st) {
  if (!(st && st.rest && st.rest.length === 16)) return false;
  const rest = new THREE.Matrix4().fromArray(st.rest).transpose();     // row-major from the engine
  const lin = rest.clone().setPosition(0, 0, 0);
  const b = st.base || [0, 0, 0];
  P.place = lin.multiply(new THREE.Matrix4().makeTranslation(-b[0], -b[1], -b[2]));
  return true;
}
// a prototype loaded first for a copy of the model placed in the scene has no rest (the copy carries its own
// matrix); drawn in a distribution it needs the model's own turn and scale (an FBX in inches: 38 times smaller).
// Asked again once the distribution is there (the engine takes it from the model's original, paint._rest_now)
function protoReplace(model) {
  for (const P of new Set(scatter.protos.values())) {
    if (P.model !== model || P.state !== 'ready' || !engineUrl) continue;
    fetch(engineUrl + 'paint/proto?model=' + encodeURIComponent(P.model) + '&key=' + encodeURIComponent(P.key || ''), { cache: 'no-store' })
      .then((r) => r.json()).then((st) => {
        if (st && st.state === 'done' && protoSetPlace(P, st)) {
          for (const set of scatter.sets.values()) for (const b of set.blocks || []) if (b.cP === P) b.c = null;
          scatter.dirty = true; invalidate(400);
        }
      }).catch(() => {});
  }
}
function protoPlaceAgain(P) {
  if (!P || P.place || P.state !== 'ready' || !engineUrl) return;
  const now = performance.now();
  if (P.placeAsk && now - P.placeAsk < 3000) return;
  P.placeAsk = now;
  fetch(engineUrl + 'paint/proto?model=' + encodeURIComponent(P.model) + '&key=' + encodeURIComponent(P.key || ''), { cache: 'no-store' })
    .then((r) => r.json()).then((st) => {
      if (st && st.state === 'done' && protoSetPlace(P, st)) {
        for (const set of scatter.sets.values()) for (const b of set.blocks || []) if (b.cP === P) b.c = null;
        for (const node of scatter.nodes) if (node.userData.ghost && !node.userData.placed) scatterPlaceGhost(node);
        scatter.dirty = true; invalidate(400);
      }
    }).catch(() => {});
}
// the pieces of a distribution stand in their model through its own turn and scale (P.place, from the engine): until
// it is known they wait as small cones - drawn without it a car came backwards for a moment when a project opened.
// Without an answer for 8 s they are drawn anyway (a model with no turn of its own)
function placeKnown(P) {
  if (P.place) return true;
  const now = performance.now();
  if (!P.placeWait) {
    P.placeWait = now;
    setTimeout(() => { scatter.dirty = true; invalidate(300); }, 8100);
  }
  return now - P.placeWait > 8000;
}
function blockProto(b) {
  const P = b.key ? scatter.protos.get(b.key) : null;
  if (P && P.state === 'ready') { protoPlaceAgain(P); return P; }
  const Q = protoForModel(b.model);
  if (Q && Q.state === 'ready') protoPlaceAgain(Q);
  return Q && Q.state === 'ready' ? Q : P || Q;
}
// centres and radii of the pieces of a block (in the group space), once its prototype is known
function blockCentres(b, P) {
  if (b.c && b.cP === P) return b.c;
  const place = P.place || new THREE.Matrix4();
  const pc = P.center.clone().applyMatrix4(place);
  const ps = P.radius * place.getMaxScaleOnAxis();
  const c = new Float32Array(b.count * 4), e = b.xf;
  for (let i = 0; i < b.count; i++) {
    const o = i * 16;
    c[i * 4] = e[o] * pc.x + e[o + 4] * pc.y + e[o + 8] * pc.z + e[o + 12];
    c[i * 4 + 1] = e[o + 1] * pc.x + e[o + 5] * pc.y + e[o + 9] * pc.z + e[o + 13];
    c[i * 4 + 2] = e[o + 2] * pc.x + e[o + 6] * pc.y + e[o + 10] * pc.z + e[o + 14];
    c[i * 4 + 3] = ps * Math.sqrt(e[o] * e[o] + e[o + 1] * e[o + 1] + e[o + 2] * e[o + 2]);
  }
  b.c = c; b.cP = P;
  return c;
}
// the pieces of a block in spatial chunks of about CHUNK pieces (a grid on the two longest sides of the block), each
// with a sphere that holds all its pieces: a chunk outside the view, or so far that even its biggest piece would be
// hidden, is dropped at once, without looking at its pieces (a million pieces: most of the work of every frame)
const CHUNK = 2048;
function blockChunks(b, c) {
  if (b.ch && b.chC === c) return b.ch;
  const n = b.count;
  const lo = [Infinity, Infinity, Infinity], hi = [-Infinity, -Infinity, -Infinity];
  for (let i = 0; i < n; i++) for (let a = 0; a < 3; a++) { const v = c[i * 4 + a]; if (v < lo[a]) lo[a] = v; if (v > hi[a]) hi[a] = v; }
  const ext = [0, 1, 2].map((a) => Math.max(hi[a] - lo[a], 1e-6));
  const ax = [0, 1, 2].sort((x, y) => ext[y] - ext[x]);          // the two longest sides of the block
  const A = ax[0], B = ax[1];
  const cells = Math.max(1, Math.round(n / CHUNK));
  const size = Math.sqrt(ext[A] * ext[B] / cells);
  const da = Math.max(1, Math.min(1024, Math.ceil(ext[A] / size))), db = Math.max(1, Math.min(1024, Math.ceil(ext[B] / size)));
  // counting sort by cell; the centres copied in that order (read one after the other, every frame)
  const cellOf = new Int32Array(n), count = new Int32Array(da * db + 1);
  for (let i = 0; i < n; i++) {
    const ia = Math.min(da - 1, ((c[i * 4 + A] - lo[A]) / ext[A] * da) | 0), ib = Math.min(db - 1, ((c[i * 4 + B] - lo[B]) / ext[B] * db) | 0);
    const k = ia * db + ib; cellOf[i] = k; count[k + 1]++;
  }
  for (let k = 0; k < da * db; k++) count[k + 1] += count[k];
  const fill = count.slice(0, da * db), order = new Int32Array(n), cc = new Float32Array(n * 4);
  for (let i = 0; i < n; i++) { const q = fill[cellOf[i]]++; order[q] = i; cc.set(c.subarray(i * 4, i * 4 + 4), q * 4); }
  const startL = [], sphL = [];
  for (let k = 0; k < da * db; k++) {
    const s0 = count[k], s1 = count[k + 1];
    if (s1 === s0) continue;
    const l = [Infinity, Infinity, Infinity], h = [-Infinity, -Infinity, -Infinity];
    for (let q = s0; q < s1; q++) for (let a = 0; a < 3; a++) { const v = cc[q * 4 + a]; if (v < l[a]) l[a] = v; if (v > h[a]) h[a] = v; }
    const mx = (l[0] + h[0]) / 2, my = (l[1] + h[1]) / 2, mz = (l[2] + h[2]) / 2;
    let r = 0, rmax = 0;
    for (let q = s0; q < s1; q++) {
      const dx = cc[q * 4] - mx, dy = cc[q * 4 + 1] - my, dz = cc[q * 4 + 2] - mz, ri = cc[q * 4 + 3];
      r = Math.max(r, Math.sqrt(dx * dx + dy * dy + dz * dz) + ri); rmax = Math.max(rmax, ri);
    }
    startL.push(s0); sphL.push(mx, my, mz, r, rmax);
  }
  startL.push(n);
  b.ch = { n: startL.length - 1, start: Int32Array.from(startL), order, cc, sph: Float32Array.from(sphL) }; b.chC = c;
  return b.ch;
}
function sphereInside(f, sp) {          // the whole sphere inside the frustum (its pieces need no test of their own)
  for (const pl of f.planes) if (pl.distanceToPoint(sp.center) < sp.radius) return false;
  return true;
}
// «Alleggerisci» (the box at the bottom of the tree, in the app): what the real-time view leaves out to be lighter -
// the distributions (and the lamps in them), the falling flakes, half the pixels. The path tracing is not touched.
const viewLight = { sets: false, flakes: false, half: false };
function setViewLight(msg) {
  if (typeof msg.sets === 'boolean') { viewLight.sets = msg.sets; scatter.dirty = true; distLamps.dirty = true; }
  if (typeof msg.flakes === 'boolean') viewLight.flakes = msg.flakes;
  if (typeof msg.half === 'boolean' && msg.half !== viewLight.half) {
    viewLight.half = msg.half;
    renderer.setPixelRatio(window.devicePixelRatio * (msg.half ? 0.5 : 1));
    const w = container.clientWidth, h = container.clientHeight;
    if (w && h) renderer.setSize(w, h, false);
  }
  if (FLAKES.mesh) FLAKES.mesh.visible = !viewLight.flakes && !_smartOn;
  if (DROPS.mesh) DROPS.mesh.visible = !viewLight.flakes && !_smartOn;
  invalidate(300);
}
function setFrame(set) {
  // (the distribution being painted stays, also with the distributions left out of the view)
  const hidden = viewLight.sets && !(paint.on && set.group === (paint.group || ''));
  if (!set.group) return { G: null, scale: 1, visible: !hidden };
  const g = byId.get(set.group);
  if (!g) return null;
  return { G: g.matrixWorld, scale: g.matrixWorld.getMaxScaleOnAxis(), visible: isVisible(g) && !hidden };
}
function setBox(set) {
  const f = setFrame(set);
  const box = new THREE.Box3();
  if (!f) return box;
  for (const b of set.blocks) {
    const P = blockProto(b);
    if (!P || P.state !== 'ready') { for (let i = 0; i < b.count; i++) box.expandByPoint(_sv.set(b.xf[i * 16 + 12], b.xf[i * 16 + 13], b.xf[i * 16 + 14])); continue; }
    const c = blockCentres(b, P);
    for (let i = 0; i < b.count; i++) {
      const r = c[i * 4 + 3];
      box.expandByPoint(_sv.set(c[i * 4] - r, c[i * 4 + 1] - r, c[i * 4 + 2] - r));
      box.expandByPoint(_sv.set(c[i * 4] + r, c[i * 4 + 1] + r, c[i * 4 + 2] + r));
    }
  }
  if (f.G && !box.isEmpty()) box.applyMatrix4(f.G);
  return box;
}
const _sf = new THREE.Frustum(), _spm = new THREE.Matrix4(), _ssph = new THREE.Sphere(), _sm4 = new THREE.Matrix4();
let _srecs = [];
const _sT = new Float64Array(16);
function mul4(a, ao, b, bo, out, oo) {       // out = a x b (column-major 4x4, as THREE)
  const a0 = a[ao], a1 = a[ao + 1], a2 = a[ao + 2], a3 = a[ao + 3], a4 = a[ao + 4], a5 = a[ao + 5], a6 = a[ao + 6], a7 = a[ao + 7];
  const a8 = a[ao + 8], a9 = a[ao + 9], a10 = a[ao + 10], a11 = a[ao + 11], a12 = a[ao + 12], a13 = a[ao + 13], a14 = a[ao + 14], a15 = a[ao + 15];
  for (let c = 0; c < 4; c++) {
    const b0 = b[bo + c * 4], b1 = b[bo + c * 4 + 1], b2 = b[bo + c * 4 + 2], b3 = b[bo + c * 4 + 3];
    out[oo + c * 4] = a0 * b0 + a4 * b1 + a8 * b2 + a12 * b3;
    out[oo + c * 4 + 1] = a1 * b0 + a5 * b1 + a9 * b2 + a13 * b3;
    out[oo + c * 4 + 2] = a2 * b0 + a6 * b1 + a10 * b2 + a14 * b3;
    out[oo + c * 4 + 3] = a3 * b0 + a7 * b1 + a11 * b2 + a15 * b3;
  }
}
function scatterUpdate() {
  const camMoved = !scatter.cam.equals(camera.matrixWorld) || !scatter.proj.equals(camera.projectionMatrix);
  if (!scatter.dirty && !camMoved && !gizmoDragging()) return false;
  scatter.dirty = false;
  scatter.cam.copy(camera.matrixWorld); scatter.proj.copy(camera.projectionMatrix);
  _sf.setFromProjectionMatrix(_spm.multiplyMatrices(camera.projectionMatrix, camera.matrixWorldInverse));
  const tanHalf = Math.tan(THREE.MathUtils.degToRad(camera.fov) / 2);
  const recs = _srecs; recs.length = 0;
  let waiting = 0;
  for (const node of scatter.nodes) {
    const id = node.userData.simpler_id;
    if (!node.userData.ghost && byId.get(id) !== node) { scatter.nodes.delete(node); continue; }
    if ((scatter.shown.has(node) && !scatter.shown.get(node).userData.smart) || !node.parent || !isVisible(node)) {
      _sdiag.skip++; if (node.parent && !isVisible(node)) _sdiag.hid.push(node.name || node.userData.simpler_id);
      continue;
    }
    if (scatter.editGroup && node.userData.paintGen && node.parent === scatter.editGroup) continue;   // shown by its ghost
    const P = nodeProto(node);
    if (node.userData.ghost && !node.userData.placed && P && P.state === 'ready') scatterPlaceGhost(node);
    if (!P || P.state !== 'ready') {
      if (waiting < waitDots.instanceMatrix.count) {
        waitDots.setMatrixAt(waiting++, waitDotMatrix(node.matrixWorld));
      }
      continue;
    }
    const w = node.matrixWorld;
    _ssph.center.copy(P.center).applyMatrix4(w);
    _ssph.radius = P.radius * w.getMaxScaleOnAxis();
    if (!_sf.intersectsSphere(_ssph)) { _sdiag.cull++; continue; }
    const d = Math.max(_ssph.center.distanceTo(camera.position), 1e-4);
    recs.push({ node, P, s: _ssph.radius / (d * tanHalf), level: 0 });
  }
  // the points of the distributions: in typed arrays (there can be hundreds of thousands)
  const sb = [];                 // blocks drawn this time: {b, P, G}
  let ns = 0;
  for (const set of scatter.sets.values()) {
    const f = setFrame(set);
    if (!f || !f.visible) continue;
    for (const b of set.blocks) {
      const P = blockProto(b);
      if (!P || P.state !== 'ready' || !placeKnown(P)) {
        if (!P) ensureProto(b.model, b.key, b.id);
        for (let i = 0; i < b.count && waiting < waitDots.instanceMatrix.count; i++) {
          _sm4.fromArray(b.xf, i * 16);
          if (f.G) _sm4.premultiply(f.G);
          waitDots.setMatrixAt(waiting++, waitDotMatrix(_sm4));
        }
        continue;
      }
      sb.push({ b, P, G: f.G, gs: f.scale, c: blockCentres(b, P), from: ns, dry: wetIdCode(set.group) });
      ns += b.count;
    }
  }
  if (scatter.rs.length < ns) { scatter.rs = new Float32Array(ns * 1.5 | 0); scatter.ri = new Int32Array(ns * 1.5 | 0); scatter.rb = new Int32Array(ns * 1.5 | 0); scatter.rl = new Uint8Array(ns * 1.5 | 0); }
  const rs = scatter.rs, ri = scatter.ri, rb = scatter.rb, rl = scatter.rl;
  let nr = 0;
  const cam = camera.position;
  for (let bi = 0; bi < sb.length; bi++) {
    const { b, G, gs, c } = sb[bi];
    const ch = blockChunks(b, c), sph = ch.sph;
    for (let j = 0; j < ch.n; j++) {
      _ssph.center.set(sph[j * 5], sph[j * 5 + 1], sph[j * 5 + 2]);
      if (G) _ssph.center.applyMatrix4(G);
      _ssph.radius = sph[j * 5 + 3] * gs;
      if (!_sf.intersectsSphere(_ssph)) continue;
      // (even the biggest piece, at the nearest point of the chunk, smaller than LOD_HIDE: all hidden at any k >= 1)
      const near = Math.max(_ssph.center.distanceTo(cam) - _ssph.radius, 1e-4);
      if (sph[j * 5 + 4] * gs / (near * tanHalf) <= LOD_HIDE) continue;
      const all = sphereInside(_sf, _ssph);
      const cc = ch.cc, order = ch.order;
      for (let q = ch.start[j], qe = ch.start[j + 1]; q < qe; q++) {
        _ssph.center.set(cc[q * 4], cc[q * 4 + 1], cc[q * 4 + 2]);
        if (G) _ssph.center.applyMatrix4(G);
        _ssph.radius = cc[q * 4 + 3] * gs;
        if (!all && !_sf.intersectsSphere(_ssph)) continue;
        const d = Math.max(_ssph.center.distanceTo(cam), 1e-4);
        rs[nr] = _ssph.radius / (d * tanHalf); ri[nr] = order[q]; rb[nr] = bi; nr++;
      }
    }
  }
  waitDots.count = waiting; waitDots.instanceMatrix.needsUpdate = true;
  {   // (what the pieces are doing, said in the log only when it changes: a piece that is not drawn leaves a reason here)
    const sig = scatter.nodes.size + '/' + recs.length + '/' + _sdiag.skip + '/' + _sdiag.cull + '/' + waiting + '/' + scatter.sets.size + '/' + _sdiag.hid.join(',');
    if (sig !== _sdiag.last) {
      _sdiag.last = sig;
      viewLog(`pieces: ${scatter.nodes.size} placed, ${recs.length} in view, ${_sdiag.skip} left out` + (_sdiag.hid.length ? ` (hidden: ${_sdiag.hid.slice(0, 6).join(', ')})` : '') + `, ${_sdiag.cull} outside the view, ${waiting} waiting for their model, ${scatter.sets.size} distributions`);
    }
    _sdiag.skip = 0; _sdiag.cull = 0; _sdiag.hid.length = 0;
  }
  // levels: by size on the screen, pushed further until the scene fits in the triangle budget (4 = not drawn)
  const lev = (s, k) => (s > LOD_SIZES[0] * k ? 0 : s > LOD_SIZES[1] * k ? 1 : s > LOD_SIZES[2] * k ? 2 : s > Math.min(LOD_HIDE * k, LOD_HIDE_MAX) ? 3 : 4);
  // while the camera moves the pieces use lighter levels (more frames, a smooth movement); when it stops they come
  // back to their detail. The shadows draw the pieces a second time: they count in the budget.
  const now = performance.now();
  if (camMoved) scatter.movedAt = now;
  const moving = now - (scatter.movedAt || 0) < 220;
  if (moving) { clearTimeout(scatter.settle); scatter.settle = setTimeout(() => { scatter.dirty = true; invalidate(300); }, 260); }
  const budget = (moving ? scatter.budget : Math.max(scatter.budget, SCATTER_STILL)) / (renderer.shadowMap.enabled ? 2 : 1) / (moving ? 2.5 : 1);
  let k = moving ? 2 : 1, total = 0, shown = 0;
  for (let it = 0; it < 14; it++) {
    total = 0; shown = 0;
    for (const r of recs) {
      r.level = Math.min(3, lev(r.s, k));
      total += r.P.tris[r.level];
    }
    for (let j = 0; j < nr; j++) {
      const l = lev(rs[j], k);
      rl[j] = l;
      if (l < 4) { total += sb[rb[j]].P.tris[l]; shown++; }
    }
    if (total <= budget) break;
    k *= 1.6;
  }
  scatter.k = k; scatter.tris = total; scatter.drawn = recs.length + shown;
  // two passes: how many instances per part and level, then the matrices
  const used = new Set();
  const protoSet = new Set(scatter.protos.values());
  for (const P of protoSet) for (const part of P.parts) part.need = [0, 0, 0, 0];
  for (const r of recs) for (const part of r.P.parts) part.need[r.level]++;
  for (let j = 0; j < nr; j++) if (rl[j] < 4) for (const part of sb[rb[j]].P.parts) part.need[rl[j]]++;
  for (const P of protoSet) for (const part of P.parts) {
    for (let l = 0; l < 4; l++) {
      if (part.need[l]) { const m = partMesh(part, l, part.need[l]); m.count = 0; m.material = partMat(part); used.add(m); }
      else if (part.meshes[l]) part.meshes[l].count = 0;
    }
  }
  const dryOf = (m) => m.geometry.attributes.wetDry ? m.geometry.attributes.wetDry.array : null;
  const seaOf = (m) => m.geometry.attributes.foSea ? m.geometry.attributes.foSea.array : null;
  for (const r of recs) {
    const w = r.node.matrixWorld;
    const dry = wetNodeDry(r.node);
    for (const part of r.P.parts) {
      const m = part.meshes[r.level];
      _sm4.multiplyMatrices(w, part.rel);
      const d = dryOf(m); if (d) d[m.count] = dry;
      const sa = seaOf(m); if (sa) sa[m.count] = 0;
      m.setMatrixAt(m.count++, _sm4);
    }
  }
  for (const e of sb) {           // (place x rel of every part, once per block)
    const place = e.P.place || new THREE.Matrix4();
    e.pr = e.P.parts.map((part) => new THREE.Matrix4().multiplyMatrices(place, part.rel).elements);
    e.ge = e.G ? e.G.elements : null;
  }
  // group x piece x (place x rel), written straight into the instance buffers (hundreds of thousands of pieces:
  // plain arithmetic on the arrays, no Matrix4 per piece)
  const T = _sT;
  for (let j = 0; j < nr; j++) {
    const l = rl[j];
    if (l === 4) continue;
    const e = sb[rb[j]], X = e.b.xf, xo = ri[j] * 16;
    if (e.ge) mul4(e.ge, 0, X, xo, T, 0);
    else for (let k = 0; k < 16; k++) T[k] = X[xo + k];
    const parts = e.P.parts;
    const sv = e.b.sea ? e.b.sea[ri[j]] : 0;
    for (let pi = 0; pi < parts.length; pi++) {
      const m = parts[pi].meshes[l];
      mul4(T, 0, e.pr[pi], 0, m.instanceMatrix.array, m.count * 16);
      const d = dryOf(m); if (d) d[m.count] = e.dry;
      const sa = seaOf(m); if (sa) sa[m.count] = sv;
      m.count++;
    }
    if (sv > 0.5 && !e.P.foSea) {
      // (the leaf materials of a model with seasons per piece: their fallen leaves throw no shadow either)
      e.P.foSea = true;
      for (const part of parts) for (const mm of (Array.isArray(part.mat) ? part.mat : [part.mat])) {
        if (mm && mm.userData.foliage) { mm.userData.foInst = true; FOL.mats.add(mm); FOL.dirty = true; }
      }
    }
  }
  for (const m of used) {
    m.instanceMatrix.needsUpdate = true;
    if (m.geometry.attributes.wetDry) m.geometry.attributes.wetDry.needsUpdate = true;
    if (m.geometry.attributes.foSea) m.geometry.attributes.foSea.needsUpdate = true;
  }
  return true;
}
// an error while placing the pieces never leaves the view half drawn without a word: it goes in app.log and the
// pieces are placed again a moment later
// ---- the lamps inside the models of distributions (paint.sub_lamps): street lamps of a scatter lit the street only in
// the path tracing. Every copy of a lamp is at group × piece × m; the nearest DIST_LIGHTS of them that are on are
// real lights here (no shadows: each light with shadows draws the scene again, six times for a point light). The
// lights are a fixed set made once (three.js prepares its shaders again when the number of lights changes): the
// ones not needed stay at 0.
const DIST_LIGHTS = 2;      // (14/11: 12 + the reserve = 57 lights in every shader of Luca's street, 417 ms a program against 67 with 6 lights in the test)
const distLamps = { dirty: true, all: [], pool: { point: [], spot: [] }, at: 0, cam: new THREE.Vector3(1e9, 0, 0), used: 0 };
const _dlM = new THREE.Matrix4(), _dlX = new THREE.Matrix4(), _dlL = new THREE.Matrix4();
function distLampsCollect() {
  const out = [];
  for (const set of scatter.sets.values()) {
    if (set.local) continue;
    const f = setFrame(set);
    if (!f || !f.visible) continue;
    for (const b of set.blocks) {
      if (!b.lamps || !b.lamps.length) continue;
      for (let i = 0; i < b.count; i++) {
        _dlX.fromArray(b.xf, i * 16);
        if (f.G) _dlX.premultiply(f.G);
        for (const lp of b.lamps) {
          if (lp.data.lit === false || !(lp.data.power > 0)) continue;
          _dlM.multiplyMatrices(_dlX, _dlL.fromArray(lp.m));
          const pos = new THREE.Vector3().setFromMatrixPosition(_dlM);
          const dir = new THREE.Vector3(0, 0, -1).transformDirection(_dlM);
          out.push({ kind: lp.kind === 'point' ? 'point' : 'spot', data: lp.data, src: lp.kind, pos, dir });
          if (out.length > 20000) return out;          // (a city of lamps: the nearest are taken from these)
        }
      }
    }
  }
  return out;
}
function distLampsUpdate() {
  const now = performance.now();
  if (distLamps.dirty || now - distLamps.at > 2000) {
    // (the groups may have moved: the list again now and then, and at once when a distribution changes)
    const all = distLampsCollect();
    const sig = all.length + ':' + all.reduce((t, l) => t + l.pos.x * 1.3 + l.pos.y * 0.7 + l.pos.z + (l.data.power || 0), 0).toFixed(3);
    distLamps.all = all;
    distLamps.dirty = false; distLamps.at = now;
    if (sig !== distLamps.sig) {
      distLamps.sig = sig; distLamps.cam.set(1e9, 0, 0);
      // (1.75.9) the pools as big as they can ever need for this list: walking from point lamps to spot lamps no
      // longer adds a light - every light more made every shader again («Aggiornamento delle luci», 9 s, Luca)
      for (const kind of ['point', 'spot']) {
        const need = Math.min(DIST_LIGHTS, all.filter((l) => l.kind === kind).length);
        const pool = distLamps.pool[kind];
        while (pool.length < need) {
          const light = makeLight(kind);
          light.castShadow = false;
          light.userData.helper = true;
          light.intensity = 0;
          scene.add(light);
          pool.push(light);
        }
      }
    }
  }
  const all = distLamps.all;
  if (!all.length && !distLamps.used) return;
  if (SMART.on && distLamps.cam.x < 1e8) return;     // (SmartView: the lamps chosen stay as they are)
  if (camera.position.distanceToSquared(distLamps.cam) < 0.25) return;     // (moved less than half a metre)
  distLamps.cam.copy(camera.position);
  const cp = camera.position;
  const pick = all.length > DIST_LIGHTS ? all.slice().sort((a, b) => a.pos.distanceToSquared(cp) - b.pos.distanceToSquared(cp)).slice(0, DIST_LIGHTS) : all;
  const want = { point: pick.filter((l) => l.kind === 'point'), spot: pick.filter((l) => l.kind === 'spot') };
  for (const kind of ['point', 'spot']) {
    const pool = distLamps.pool[kind];
    while (pool.length < want[kind].length) {
      const light = makeLight(kind);
      light.castShadow = false;
      light.userData.helper = true;
      scene.add(light);
      pool.push(light);
    }
    pool.forEach((light, k) => {
      const l = want[kind][k];
      if (!l) { light.intensity = 0; return; }
      lightParams(light, l.src, l.data);
      light.position.copy(l.pos);
      if (light.target) {
        if (light.target.parent !== scene) scene.add(light.target);
        light.target.position.copy(l.pos).add(l.dir);
        light.target.updateMatrixWorld();
      }
      light.updateMatrixWorld();
    });
  }
  distLamps.used = pick.length;
}

function scatterUpdateSafe() {
  try { scatterUpdate(); } catch (err) {
    scatter.dirty = true;
    viewLog('error while placing the pieces: ' + (err && err.stack ? err.stack : err));
    setTimeout(() => invalidate(300), 1000);
  }
}
// the frame time decides how many triangles the painted pieces may use
// (1.78.4, Luca: «non dovrebbe vedersi così poco dettagliato» - cars of a distribution at their lightest level in a
// still view at 31 fps: above 25 ms a quarter of their triangles went at every measure, back only under 11 ms, which a
// scene of 74 M triangles in its buildings never reaches; and the frames that prepared shaders - seconds - counted as
// slow too. Now: lighter only under about 20 fps (SCATTER_SLOW), back over about 30 (SCATTER_FAST), the frames with
// new shaders not counted; and a still view never goes under SCATTER_STILL - the pieces cost little there)
const SCATTER_SLOW = 50, SCATTER_FAST = 33, SCATTER_STILL = 8e6;
let _frameNewShaders = false;
function scatterAdapt(frameMs) {
  if ((!scatter.nodes.size && !scatter.sets.size) || (window.__dbg && window.__dbg.scatterAdaptOff)) return;
  if (_frameNewShaders || shaderPrep.busy) return;        // (a frame preparing shaders says nothing of the triangles)
  const was = scatter.budget;
  if (frameMs > SCATTER_SLOW) scatter.budget = Math.max(2e6, scatter.budget * 0.75);
  else if (frameMs < SCATTER_FAST && scatter.k > 1) scatter.budget = Math.min(600e6, scatter.budget * 1.15);
  // (1.76.50, audit) already at the floor (or at the top): nothing to place again - a slow frame because of the
  // terrain kept asking for every piece to be placed again, a whole pass over the distributions for nothing
  if (scatter.budget === was) return;
  scatter.dirty = true;
}
// clicks: the painted pieces under the ray, through their lightest level
const _srm = new THREE.Mesh();
function scatterHits(rc) {
  const out = [];
  for (const node of scatter.nodes) {
    if (scatter.shown.has(node) || node.userData.ghost || !node.parent || !isVisible(node)) continue;
    const P = protoOf(node);
    if (!P || P.state !== 'ready') continue;
    _ssph.center.copy(P.center).applyMatrix4(node.matrixWorld);
    _ssph.radius = P.radius * node.matrixWorld.getMaxScaleOnAxis();
    if (!rc.ray.intersectsSphere(_ssph)) continue;
    for (const part of P.parts) {
      _srm.geometry = part.levels[2] || part.geom;
      _srm.material = part.mat;
      _srm.matrixWorld.multiplyMatrices(node.matrixWorld, part.rel);
      const hits = [];
      _srm.raycast(rc, hits);
      for (const h of hits) out.push(Object.assign(h, { object: { isMesh: true, visible: true, parent: node, material: part.mat, matrixWorld: _srm.matrixWorld.clone(), userData: { pickId: node.userData.simpler_id } } }));
    }
  }
  return out;
}
// clicks on distributions: the pieces whose sphere the ray crosses (nearest first), tested on their lightest level;
// a piece stands for its distribution (selected as a whole)
function setHits(rc, onlyModels) {
  const out = [], cand = [];
  for (const set of scatter.sets.values()) {
    if (onlyModels && set.group) continue;          // (the library models of the scene only, not the distributions)
    const f = setFrame(set);
    if (!f || !f.visible || !set.group) continue;
    for (const b of set.blocks) {
      const P = blockProto(b);
      if (!P || P.state !== 'ready') continue;
      const c = blockCentres(b, P), ch = blockChunks(b, c), sph = ch.sph;
      for (let j = 0; j < ch.n; j++) {
        _ssph.center.set(sph[j * 5], sph[j * 5 + 1], sph[j * 5 + 2]);
        if (f.G) _ssph.center.applyMatrix4(f.G);
        _ssph.radius = sph[j * 5 + 3] * f.scale;
        if (!rc.ray.intersectsSphere(_ssph)) continue;      // (the chunk first: a click looks at a few chunks only)
        for (let q = ch.start[j]; q < ch.start[j + 1]; q++) {
          const i = ch.order[q];
          _ssph.center.set(c[i * 4], c[i * 4 + 1], c[i * 4 + 2]);
          if (f.G) _ssph.center.applyMatrix4(f.G);
          _ssph.radius = c[i * 4 + 3] * f.scale;
          if (rc.ray.intersectsSphere(_ssph)) cand.push({ d: _ssph.center.distanceToSquared(rc.ray.origin), set, b, P, i, G: f.G });
        }
      }
    }
  }
  cand.sort((a, b) => a.d - b.d);
  for (const e of cand.slice(0, 24)) {
    _sy.fromArray(e.b.xf, e.i * 16);
    if (e.G) _sy.premultiply(e.G);
    if (e.P.place) _sy.multiply(e.P.place);
    for (const part of e.P.parts) {
      _srm.geometry = part.levels[2] || part.geom;
      _srm.material = part.mat;
      _srm.matrixWorld.multiplyMatrices(_sy, part.rel);
      const hits = [];
      _srm.raycast(rc, hits);
      for (const h of hits) out.push(Object.assign(h, { object: { isMesh: true, visible: true, parent: byId.get(e.set.group), material: part.mat, matrixWorld: _srm.matrixWorld.clone(), userData: { pickId: e.set.group } } }));
    }
  }
  return out;
}
function sceneHits(rc) {
  const hits = rc.intersectObject(root, true);
  if (scatter.sets.size) {
    const sh = setHits(rc);
    if (sh.length) { hits.push(...sh); hits.sort((a, b) => a.distance - b.distance); }
  }
  if (!scatter.nodes.size) return hits;
  return hits.concat(scatterHits(rc)).sort((a, b) => a.distance - b.distance);
}
// a distribution being changed: its new pieces shown at once, before the engine has made them ("ghosts"). Until
// the model of a piece is in the view, a small cone stands on its point.
function scatterGhost(model, m) {
  const node = new THREE.Object3D();
  node.matrixAutoUpdate = false;
  node.userData = { ghost: true, paintModel: model, paintPiece: true, raw: m, placed: false };
  scatterPlaceGhost(node);
  scatterRoot.add(node);
  scatter.nodes.add(node);
  scatter.dirty = true;
  ensureProto(model);
  return node;
}
function scatterPlaceGhost(node) {
  const P = protoForModel(node.userData.paintModel);
  node.matrix.fromArray(node.userData.raw);
  if (P && P.state === 'ready' && P.place) { node.matrix.multiply(P.place); node.userData.placed = true; }
  else if (P && P.state === 'ready') protoPlaceAgain(P);
  node.matrixWorld.copy(node.matrix);
}
function scatterDropGhost(node) { scatter.nodes.delete(node); scatterRoot.remove(node); scatter.dirty = true; }
function scatterDropGhosts() {
  for (const node of [...scatter.nodes]) if (node.userData.ghost) { scatter.nodes.delete(node); scatterRoot.remove(node); }
  scatter.dirty = true;
}

// ------------------------------------------------------------------ frames per second (bottom right)
const fpsEl = document.getElementById('fps');
const fpsStat = { frames: 0, t0: performance.now(), cpu: 0, n: 0, frameMs: 0 };
// The view draws once per screen refresh (vsync, like every browser page): on a 60 Hz screen at most 60 fps, which
// also leaves the video card free for the path tracing. How many frames the card COULD draw is measured apart: every
// 20th frame the time to draw it is taken up to the end of the GPU work (gl.finish), and "max ≈" is 1000 / that time.
function scatterLabel() {
  if (!scatter.nodes.size) return '';
  return ` · ${tr('{0} pezzi').replace('{0}', scatter.drawn)}` + (scatter.k > 1.01 ? ` · ${tr('LOD automatico')}` : '');
}
// nothing to draw: the counter says so (the card is free)
function fpsIdle(hidden) {
  const now = performance.now();
  if (now - fpsStat.t0 < 700) return;
  fpsStat.frames = 0; fpsStat.cpu = 0; fpsStat.t0 = now;
  if (hidden) return;
  const l = fpsStat.last || { tri: 0, calls: 0 };
  const tri = l.tri >= 1e6 ? (l.tri / 1e6).toFixed(1) + ' M' : l.tri >= 1e3 ? Math.round(l.tri / 1e3) + ' k' : String(l.tri);
  fpsEl.innerHTML = `<b>${tr('ferma')}</b> · ${tri} ${tr('triangoli')} · ${l.calls} draw` + scatterLabel();
  fpsEl.className = '';
  fpsEl.title = tr('Vista ferma: niente da ridisegnare, la scheda video è libera. Si ridisegna da sola appena muovi la vista o cambi qualcosa.');
}
function fpsShouldMeasure() { return (++fpsStat.n % 20) === 0; }
function fpsFrame(cpuMs, measuredMs) {
  fpsStat.frames++;
  fpsStat.cpu += cpuMs;
  if (measuredMs > 0) fpsStat.frameMs = fpsStat.frameMs ? fpsStat.frameMs * 0.7 + measuredMs * 0.3 : measuredMs;
  const now = performance.now(), dt = now - fpsStat.t0;
  if (dt < 500) return;
  const fps = fpsStat.frames * 1000 / dt;
  const info = renderer.info.render;
  fpsStat.last = { tri: info.triangles, calls: info.calls };
  const tri = info.triangles >= 1e6 ? (info.triangles / 1e6).toFixed(1) + ' M' : info.triangles >= 1e3 ? Math.round(info.triangles / 1e3) + ' k' : String(info.triangles);
  const max = fpsStat.frameMs > 0 ? Math.round(Math.min(2000, 1000 / fpsStat.frameMs)) : 0;
  fpsEl.innerHTML = `<b>${Math.round(fps)}</b> fps` + (max ? ` · max ≈ ${max}` : '') + ` · ${tri} ${tr('triangoli')} · ${info.calls} draw` + scatterLabel();
  // colour from what the card can do, not from the screen limit
  const cap = max || fps;
  fpsEl.className = cap < 15 ? 'veryslow' : cap < 30 ? 'slow' : '';
  fpsEl.title = tr('fps: fotogrammi mostrati, al massimo quanti ne fa lo schermo al secondo (60 Hz = 60): la vista si ferma lì apposta, come ogni pagina web, per non togliere la scheda video al path tracing e non scaldarla per niente. max ≈: quanti fotogrammi al secondo la scheda riuscirebbe a disegnare con questa scena (un fotogramma ogni {0} ms). Se il max scende sotto 30, prova la vista Sagome.')
    .replace('{0}', (fpsStat.frameMs || 0).toFixed(2));
  // (1.75.2) in the log, every 10 s of drawing: where a slow view loses its time - the page (js), the card (gpu) or
  // the wait between frames (screen, Windows, WebView2)
  const pl = fpsStat.perf || (fpsStat.perf = { t0: now, frames: 0, cpu: 0, dt: [] });
  pl.frames += fpsStat.frames; pl.cpu += fpsStat.cpu;
  if (now - pl.t0 > 10000) {
    const d = pl.dt.slice().sort((a, b) => a - b);
    const q = (x) => d.length ? d[Math.min(d.length - 1, Math.floor(x * d.length))].toFixed(1) : '?';
    viewLog(`perf: ${(pl.frames * 1000 / (now - pl.t0)).toFixed(1)} fps, js ${(pl.cpu / Math.max(1, pl.frames)).toFixed(1)} ms/frame, ` +
      `gpu ${(fpsStat.frameMs || 0).toFixed(1)} ms, between frames p50 ${q(0.5)} p95 ${q(0.95)} ms, ` +
      `${(info.triangles / 1e6).toFixed(1)} M tri, ${info.calls} draw, ${renderer.info.programs ? renderer.info.programs.length : '?'} shaders, ` +
      `pixels ${renderer.domElement.width}x${renderer.domElement.height}, shader requests ${_revStat.n}` +
      (_revStat.who.size ? ' (' + [..._revStat.who].map(([k, v]) => `${v}x ${k}`).join(' | ') + ')' : ''));
    _revStat.n = 0; _revStat.who.clear();
    fpsStat.perf = { t0: now, frames: 0, cpu: 0, dt: [] };
  }
  fpsStat.frames = 0; fpsStat.cpu = 0; fpsStat.t0 = now;
}
function fpsInterval(ms) {
  const pl = fpsStat.perf;
  if (pl && pl.dt.length < 2000 && ms < 1000) pl.dt.push(ms);
}

// ------------------------------------------------------------------ "Sagome": clay view
// For heavy scenes and to judge shapes and light without textures: every piece in one matte clay grey (a matcap:
// no lamps, no shadows, no textures - the cheapest material three.js has, the same for instanced pieces), its
// outlines drawn from the depth (one full-screen pass, no extra geometry pass). The real meshes are the ones drawn
// (clicks, gizmo, selection as usual); the selection keeps its orange outline.
let boxMode = false;
const clayScene = new THREE.Scene();
clayScene.background = new THREE.Color(0xc9ccd2);
const clayMat = (() => {
  const c = document.createElement('canvas'); c.width = c.height = 128;
  const g = c.getContext('2d');
  const grd = g.createRadialGradient(46, 40, 6, 64, 64, 66);
  grd.addColorStop(0, '#f6f3ec'); grd.addColorStop(0.55, '#d6d1c7'); grd.addColorStop(0.9, '#aaa69e'); grd.addColorStop(1, '#8e8a84');
  g.fillStyle = grd; g.fillRect(0, 0, 128, 128);
  const t = new THREE.CanvasTexture(c); t.colorSpace = THREE.SRGBColorSpace;
  return new THREE.MeshMatcapMaterial({ matcap: t, side: THREE.DoubleSide });
})();
const clayRT = new THREE.WebGLRenderTarget(1, 1, { depthTexture: new THREE.DepthTexture(1, 1), samples: 0 });
const clayEdge = new THREE.ShaderMaterial({
  uniforms: { tColor: { value: null }, tDepth: { value: null }, texel: { value: new THREE.Vector2() }, near: { value: 0.1 }, far: { value: 1000 } },
  vertexShader: 'varying vec2 vUv; void main(){ vUv = uv; gl_Position = vec4(position.xy, 0.0, 1.0); }',
  fragmentShader: `uniform sampler2D tColor; uniform sampler2D tDepth; uniform vec2 texel; uniform float near; uniform float far; varying vec2 vUv;
    float lin(vec2 uv){ float z = texture2D(tDepth, uv).x * 2.0 - 1.0; return 2.0 * near * far / (far + near - z * (far - near)); }
    void main(){
      vec4 c = texture2D(tColor, vUv);
      float d = lin(vUv);
      float dl = lin(vUv - vec2(texel.x, 0.0)), dr = lin(vUv + vec2(texel.x, 0.0));
      float dd = lin(vUv - vec2(0.0, texel.y)), du = lin(vUv + vec2(0.0, texel.y));
      // outline where the depth jumps (relative: the same at every distance); creases where it bends sharply
      float jump = max(max(abs(dl - d), abs(dr - d)), max(abs(dd - d), abs(du - d))) / max(d, 1e-4);
      float bend = abs(dl + dr - 2.0 * d) + abs(dd + du - 2.0 * d);
      float e = clamp(smoothstep(0.006, 0.025, jump) + smoothstep(0.003, 0.012, bend / max(d, 1e-4)), 0.0, 1.0);
      gl_FragColor = vec4(mix(c.rgb, vec3(0.16, 0.17, 0.19), e * 0.85), 1.0);
    }`,
  depthTest: false, depthWrite: false,
});
const clayQuad = new THREE.Mesh(new THREE.PlaneGeometry(2, 2), clayEdge);
const clayQuadScene = new THREE.Scene(); clayQuadScene.add(clayQuad);
clayQuad.frustumCulled = false;
function setBoxMode(on) {
  boxMode = !!on;
  if (!realistic) setBadge(boxMode ? tr('Sagome') : tr('Tempo reale'), null, '');
  invalidate();
}
function renderClay() {
  renderer.getDrawingBufferSize(_dbs);
  if (clayRT.width !== _dbs.x || clayRT.height !== _dbs.y) clayRT.setSize(_dbs.x, _dbs.y);
  // the pieces go into the clay scene for a moment (with the override material): lamps' icons, glows and other helpers
  // under them are hidden meanwhile
  const hidden = [];
  for (const L of lights.values()) for (const h of [L.sprite, L.helper, L.glow]) if (h && h.visible) { h.visible = false; hidden.push(h); }
  if (waitDots.visible) { waitDots.visible = false; hidden.push(waitDots); }
  const tm = renderer.toneMapping, auto = renderer.shadowMap.autoUpdate;
  scene.remove(root); scene.remove(scatterRoot);
  clayScene.add(root); clayScene.add(scatterRoot);
  clayScene.overrideMaterial = clayMat;
  renderer.toneMapping = THREE.NoToneMapping;
  renderer.shadowMap.autoUpdate = false;
  renderer.setRenderTarget(clayRT);
  renderer.render(clayScene, camera);
  renderer.setRenderTarget(null);
  clayScene.remove(root); clayScene.remove(scatterRoot);
  scene.add(root); scene.add(scatterRoot);
  for (const h of hidden) h.visible = true;
  clayEdge.uniforms.tColor.value = clayRT.texture;
  clayEdge.uniforms.tDepth.value = clayRT.depthTexture;
  clayEdge.uniforms.texel.value.set(1 / _dbs.x, 1 / _dbs.y);
  clayEdge.uniforms.near.value = camera.near; clayEdge.uniforms.far.value = camera.far;
  renderer.render(clayQuadScene, outlineCam);
  renderer.toneMapping = tm;
  // then the rest (gizmo, pivot, selection boxes, measures) over it, without the pieces
  const was = root.visible, sw = scatterRoot.visible, bg = scene.background, fog = scene.fog;
  root.visible = false; scatterRoot.visible = false; scene.background = null; scene.fog = null;
  const autoClear = renderer.autoClear;
  renderer.autoClear = false;
  renderer.render(scene, camera);
  renderer.autoClear = autoClear;
  root.visible = was; scatterRoot.visible = sw; scene.background = bg; scene.fog = fog;
  renderer.shadowMap.autoUpdate = auto;
  renderOutline();
}

// The view is drawn only when something changes (camera, mouse, keyboard, a message from the app, a texture
// arriving), and for a moment after: a still view leaves the video card free (no load, no heat, the path tracing
// and the other programs get all of it). Once every 2 s it is drawn anyway, for anything that slipped through.
let drawUntil = 0, lastDraw = 0;
const ALWAYS_DRAW = !!params.get('alwaysDraw');     // tests (a headless browser gives no frames to a still page)
const _lastCam = new THREE.Matrix4(), _lastProj = new THREE.Matrix4();
function invalidate(ms = 300) { drawUntil = Math.max(drawUntil, performance.now() + ms); }
for (const ev of ['pointerdown', 'pointermove', 'pointerup', 'wheel', 'keydown', 'keyup', 'resize'])
  window.addEventListener(ev, () => invalidate(400), { passive: true, capture: true });
THREE.DefaultLoadingManager.onLoad = () => invalidate(600);
THREE.DefaultLoadingManager.onProgress = () => invalidate(600);
renderer.info.autoReset = false;

// Scale bar (bottom right): a round length (1, 2 or 5 × a power of ten: mm, cm, m, km) drawn as a line of about
// 80-180 px, measured at the depth of what is under it (else of the middle of the view, else of the orbit centre),
// so it is a reference for the sizes there. Updated a few times a second while the camera moves.
const scaleEl = document.getElementById('scale');
const scaleLabel = scaleEl.querySelector('.label'), scaleLine = scaleEl.querySelector('.line');
let _scaleAt = 0, _scaleCam = new THREE.Matrix4(), _scaleFov = 0, _scaleH = 0;
const _scaleSeen = new THREE.Matrix4();
let _scaleMoveAt = 0;
function fmtLength(m) {
  if (m >= 1000) return (m / 1000) + ' km';
  if (m >= 1) return m + ' m';
  if (m >= 0.01) return Math.round(m * 100) + ' cm';
  return Math.round(m * 1000) + ' mm';
}
function updateScaleBar(now) {
  const h = renderer.domElement.clientHeight;
  // (audit 1.78.5) not while the camera moves: its rays go through every object, and through a model of 2 million
  // triangles one costs 65-95 ms - the view jerked every 200 ms orbiting around heavy models. Measured when it stops.
  if (!_scaleSeen.equals(camera.matrixWorld)) { _scaleSeen.copy(camera.matrixWorld); _scaleMoveAt = now; return; }
  if (now - _scaleMoveAt < 250) return;
  if (now - _scaleAt < 200 || (_scaleCam.equals(camera.matrixWorld) && _scaleFov === camera.fov && _scaleH === h)) return;
  _scaleAt = now; _scaleCam.copy(camera.matrixWorld); _scaleFov = camera.fov; _scaleH = h;
  if (!h) return;
  const dir = new THREE.Vector3();
  camera.getWorldDirection(dir);
  _sightRay.camera = camera;
  let dist = camera.position.distanceTo(orbit.target);
  const surface = (rc) => sceneHits(rc).find((x) => x.object.isMesh && !x.object.userData.helper && isVisible(x.object));
  // measured where the bar is (what is under it, bottom right): a street going into the distance in the middle of
  // the view made it 10 m over the pavement next to the camera. Nothing there: the middle of the view
  const cr = renderer.domElement.getBoundingClientRect(), br = scaleEl.getBoundingClientRect();
  let hit = null;
  if (cr.width && br.width) {
    const x = ((br.left + br.width / 2 - cr.left) / cr.width) * 2 - 1, y = -(((br.top + br.height / 2 - cr.top) / cr.height) * 2 - 1);
    _sightRay.setFromCamera(new THREE.Vector2(x, y), camera);
    hit = surface(_sightRay);
  }
  if (!hit) { _sightRay.set(camera.position, dir); hit = surface(_sightRay); }
  if (hit) dist = Math.max(1e-4, hit.point.clone().sub(camera.position).dot(dir));     // (its depth along the view)
  const mpp = 2 * Math.max(dist, 1e-4) * Math.tan(THREE.MathUtils.degToRad(camera.fov) / 2) / h;   // metres per pixel there
  const target = mpp * 120;
  const p10 = Math.pow(10, Math.floor(Math.log10(target)));
  const nice = [1, 2, 5, 10].map((f) => f * p10).reduce((a, b) => (Math.abs(b - target) < Math.abs(a - target) ? b : a));
  const len = +nice.toPrecision(3);
  scaleLine.style.width = Math.round(len / mpp) + 'px';
  scaleLabel.textContent = fmtLength(len);
  scaleEl.classList.remove('hidden');
}

// (Luca: «ogni cosa che tocco è lenta, sempre gli stessi materiali») the log showed the SAME materials of a car compiled
// again and again (aluminium.002, Acciaio, Cromo.002... 14 s, then 36 s, then 23 s): three.js destroys a shader program as
// soon as no material uses it (an object replaced, a material disposed, a light changed and changed back) and makes it again
// the next time - 0.5-1.5 s each on a slow driver. Every program made is kept for the whole session: the next material with
// the same code finds it ready. (A few hundred programs at most: GPU memory is no problem.)
const PROG_KEEP_MAX = 900;
let _progKept = 0;
function keepPrograms() {
  const list = renderer && renderer.info && renderer.info.programs;
  if (!list || list.length === _progKept) return;
  let n = 0;
  for (const pr of list) {
    if (!pr._kept && (list.length <= PROG_KEEP_MAX)) { pr._kept = true; pr.usedTimes++; }
    if (pr._kept) n++;
  }
  _progKept = list.length;
  if (list.length > PROG_KEEP_MAX && !keepPrograms.warned) { keepPrograms.warned = true; viewLog(`shaders: more than ${PROG_KEEP_MAX} programs, no longer kept`); }
}
// Shaders made in the background (renderer.compileAsync: the browser compiles them on its own threads, several at
// once): the page stays alive and shows «Occupato»; tick draws nothing until they are ready
function sceneGlass() {
  const out = { any: false, twoSided: new Set() };
  const see = (m) => { if (m && m.transmission > 0) { out.any = true; if (m.side === THREE.DoubleSide) out.twoSided.add(m); } };
  scene.traverseVisible((o) => { if (!o.isMesh) return; if (Array.isArray(o.material)) o.material.forEach(see); else see(o.material); });
  return out;
}
// the shadow shaders of the scene, see prepareShaders. As WebGLShadowMap.getDepthMaterial of three.js r186 sets its material
// for each object; kinds already prepared with the same lights are not looked at again (_shadowWarmed).
const _SHADOW_SIDE = { [THREE.FrontSide]: THREE.BackSide, [THREE.BackSide]: THREE.FrontSide, [THREE.DoubleSide]: THREE.DoubleSide };
const _shadowWarmed = { lights: null, kinds: new Set() };
function shadowWarmScene() {
  if (!renderer.shadowMap.enabled) return null;
  const state = _lightSig + '|' + renderer.shadowMap.type;
  if (_shadowWarmed.lights !== state) { _shadowWarmed.lights = state; _shadowWarmed.kinds.clear(); }
  const sc = new THREE.Scene();
  scene.traverse((o) => {
    if (!o.isMesh || !o.castShadow || !o.geometry || !o.material || o.userData.helper) return;
    for (const m of (Array.isArray(o.material) ? o.material : [o.material])) {
      if (!m || !m.isMaterial) continue;
      const side = m.shadowSide != null ? m.shadowSide : _SHADOW_SIDE[m.side];
      const test = m.alphaToCoverage === true ? 0.5 : (m.alphaTest || 0);
      const a = o.geometry.attributes || {};
      const kind = [o.isInstancedMesh ? 'i' : 'm', o.instanceColor ? 'c' : '', o.isSkinnedMesh ? 's' : '', side, test > 0 ? 't' : '',
        m.map ? 'M' + (m.map.channel || 0) : '', m.alphaMap ? 'A' + (m.alphaMap.channel || 0) : '', m.wireframe ? 'w' : '',
        o.customDepthMaterial ? 'C' + o.customDepthMaterial.uuid : '', Object.keys(a).sort().join('.'), o.morphTargetInfluences ? 'h' : ''].join('|');
      if (_shadowWarmed.kinds.has(kind)) continue;
      _shadowWarmed.kinds.add(kind);
      // (an object with its own shadow material - the leaves with a season - keeps it; three.js sets the same things on it)
      const dm = o.customDepthMaterial || new THREE.MeshDepthMaterial();
      dm.side = side; dm.alphaMap = m.alphaMap; dm.alphaTest = test; dm.map = m.map; dm.wireframe = m.wireframe;
      const h = o.isInstancedMesh ? new THREE.InstancedMesh(o.geometry, dm, 1) : o.isSkinnedMesh ? null : new THREE.Mesh(o.geometry, dm);
      if (!h) continue;
      if (o.instanceColor) h.instanceColor = o.instanceColor;
      h.parent = sc; sc.children.push(h);        // (not add(): that would ask for the preparation of the whole view)
    }
  });
  return sc.children.length ? sc : null;
}
function prepareShaders(why) {
  if (shaderPrep.busy) { shaderPrep.again = why || 'x'; return; }
  shaderPrep.busy = true;
  shaderPrep.why = why || tr('Preparazione della vista 3D');
  _shaderRevSeen = _shaderRev;
  _shaderNew = false;
  const markedNow = [..._marked]; _marked.clear();
  // (the box comes by the usual rule of busyTick: after 0.4 s - most of the time nothing new is to be made and the
  // check takes a few milliseconds; before 1.67.5 the box flashed at every check)
  const t0 = performance.now();
  const n0 = renderer.info.programs ? renderer.info.programs.length : 0;
  scene.updateMatrixWorld();
  let p;
  _inCompile = true;
  try { p = renderer.compileAsync(scene, camera); } catch (err) { p = Promise.reject(err); }
  // (15/11, two classes of cause found with the log line «shader made inside a frame», for any project with glass:
  //  «… outputColorSpace srgb→srgb-linear, toneMapping 6→0»: with something of glass in the scene three.js first draws all the rest
  //  in a picture of its own (what is seen through the glass), and there every material needs ANOTHER shader (no tone, linear colours);
  //  «… −doubleSided, +flipSided»: in that picture a glass with two sides is drawn from behind, one more shader of its own (89 kB,
  //  2,5-4,7 s each on Luca's card).
  // The preparation in the background made neither: they were all made inside the first frame with a glass in view. Prepared here
  // too, in the same state (a picture as target, the glasses with two sides seen from behind), only when the scene has glass)
  try {
    const glass = sceneGlass();
    if (glass.any) {
      const rt = renderer.getRenderTarget();
      let p2;
      for (const m of glass.twoSided) m.side = THREE.BackSide;
      renderer.setRenderTarget(maskRT);
      try { p2 = renderer.compileAsync(scene, camera); } finally {
        renderer.setRenderTarget(rt);
        for (const m of glass.twoSided) m.side = THREE.DoubleSide;
      }
      const p1 = p;
      p = p1.then(() => p2);
    }
  } catch (err) { viewLog('shaders for the glass: ' + err); }
  // (16/11, the last class of Luca's log at the opening: «slow frame: 3085 ms … (depth, 13 kB) differs from the prepared one
  // in: +instancing», «… +instancing, +alphaTest») the SHADOWS are drawn with shaders of their own, one for every kind of thing
  // that casts one (copies or single objects, leaves with holes, one or two sides): three.js makes them the first time a
  // shadow is drawn, inside the frame - never in the preparation, which only looks at the materials of the scene. Prepared
  // here: one small stand-in per kind found in the scene, with the shadow material three.js would use, in the state of the
  // shadow pass (a picture as target, no fog).
  try {
    const sh = shadowWarmScene();
    if (sh) {
      const rt = renderer.getRenderTarget(), fog = scene.fog;
      let p3;
      scene.fog = null;
      renderer.setRenderTarget(maskRT);
      try { p3 = renderer.compileAsync(sh, camera, scene); } finally { renderer.setRenderTarget(rt); scene.fog = fog; }
      const p0 = p;
      p = p0.then(() => p3);
    }
  } catch (err) { viewLog('shaders for the shadows: ' + err); }
  _inCompile = false;
  p.catch((err) => viewLog('shaders: ' + err)).then(() => {
    shaderPrep.busy = false;
    warmOutline();
    try { keepPrograms(); } catch (err) { viewLog('programs kept: ' + err); }
    const n1 = renderer.info.programs ? renderer.info.programs.length : 0;
    if (n1 > n0 || performance.now() - t0 > 300) viewLog(`shaders ready in ${Math.round(performance.now() - t0)} ms (${n1 - n0} new): ${why}`);
    // (14/11) why a shader was made AGAIN for a state seen before: the start of the key of the first new program (lights, shadows,
    // tone, fog…) in app.log - the next log says which part changes, instead of guessing
    if (n1 - n0 >= 8) { try { const pr = renderer.info.programs[n0]; viewLog('new shaders key: ' + String(pr && pr.cacheKey).replace(/\s+/g, ' ').slice(0, 420)); } catch { } }
    // (1.75.3) nothing new to make, again and again: something marks the materials at every frame (the Qashqai: a
    // frame skipped every other one - 30 fps with a card good for 690, and drawing even when still). After 3 such
    // checks in a row the marks are let pass (tick) until a frame really makes a new shader
    shaderPrep.empty = n1 > n0 ? 0 : (shaderPrep.empty || 0) + 1;
    if (n1 > n0 || _idleMarkers.size > 4000) _idleMarkers.clear(); else for (const m of markedNow) _idleMarkers.add(m);
    if (shaderPrep.empty === 3) viewLog(`shaders: checked 3 times in a row with nothing new (${why}) - the next marks are let pass`);
    if (shaderPrep.again) { const w = shaderPrep.again; shaderPrep.again = ''; prepareShaders(w === 'x' ? '' : w); }
    invalidate(shaderPrep.empty >= 3 ? 50 : 600);
  });
}
// what decides the shaders of three.js: how many lights of each kind are drawn, with or without shadows / pictures
let _lightSig = null;
const _lightPend = { sig: '', t: 0 };
function lightKey(o) { return o.type + (o.castShadow ? 's' : '') + (o.map ? 'm' : ''); }
function lightList() {
  // (each light once: the stand-in sun is also a child of «fallback» and was counted twice - the spare lights were one short)
  return [...new Set([key, fill.light, fallbackHemi, ...fallback.children, ...[...lights.values()].map((L) => L.light), ...distLamps.pool.point,
    ...distLamps.pool.spot, ...(SMART.fillers || []), ...LRES.all])];
}
// (Luca: «copia light per avere una seconda light blocca tutto con box rosso sui materiali») three.js makes the
// shader of EVERY material again when the number of lights of a kind changes: 5-20 s on a slow driver, for each copy
// or delete of a light. A reserve of dark lights (intensity 0, never drawn as a light, no icon) keeps the number the
// shaders know constant: a light more takes the place of a reserve, a light less leaves one. The number of lights of
// a kind only goes up (with 2 spare each time it does), so only the FIRST light of a kind costs a preparation.
// (14/11, Luca: «nella vista realtime non me ne frega delle luci, sono disposto a rinunciare a qualche qualità») the real-time shaders know ONE
// FIXED set of lights from the start: 3 + 2 suns (with shadow), 8 points (1 with shadow), 8 spots (2 with shadow) - the lamps of the
// distributions and the lights of the scene take places in it (the strongest and nearest, see lightBudget), the rest of the lights of the
// scene stay as icons and light only the path tracing. A light more, a light off, the day-night, a copy: no shader is made again.
const LRES = { all: [], cap: { DirectionalLight: 2, DirectionalLights: 2, PointLight: 4, SpotLight: 3, SpotLights: 1 }, by: {} };
const LRES_TYPES = new Set(['DirectionalLight', 'PointLight', 'SpotLight']);
// (14/11, Luca: «secondi e secondi di attesa per una luce aggiunta»; test in a real browser: a NEW light WITH shadow - the default
// of a new light - made every shader again, the 9th plain light too) the reserve now covers the lights with shadows as well
// (one spare of each kind, three.js reads one shadow map each: the total of real + spare shadows stays at SHADOW_SLOTS_MAX, the
// 16 texture units of a shader are not enough for more) and a kind grows by steps (4, 6, 8, 12, 16, 24…): a light more costs a
// preparation only when it goes over the step, not every second light
const SHADOW_SLOTS_MAX = 6;
const LRES_STEPS = [3, 6, 8, 12, 16, 20, 24, 32];
function lresStep(n) { for (const s of LRES_STEPS) if (s >= n) return s; return n + 8; }
function reserveLights() {
  if (SMART.on) return;                  // (SmartView has its own hold of the lights)
  const real = {};
  for (const o of lightList()) {
    if (!o || !o.isLight || o.userData.reserve || !isVisible(o)) continue;
    const k = lightKey(o);
    if (!LRES_TYPES.has(o.type) || o.map) continue;
    real[k] = (real[k] || 0) + 1;
  }
  // the numbers the shaders know: only ever up (and never taken away again: that was a preparation too). The spare lights WITH shadows
  // share SHADOW_SLOTS_MAX: a kind that would go over it gets what is left, never less than its real lights
  for (const k of Object.keys(real)) {
    if (LRES.cap[k] !== undefined && LRES.cap[k] >= real[k]) continue;           // (inside the fixed set: nothing changes)
    if (k.endsWith('s')) {
      let others = 0;
      for (const j of Object.keys(LRES.cap)) if (j !== k && j.endsWith('s')) others += LRES.cap[j];
      LRES.cap[k] = Math.max(LRES.cap[k] || 0, real[k]);
    } else LRES.cap[k] = real[k] + 1;                  // (more lights of a kind than the set: one round of shaders, then one spare)
  }
  for (const k of Object.keys(LRES.cap)) {
    const need = Math.max(0, LRES.cap[k] - (real[k] || 0));
    const pool = LRES.by[k] || (LRES.by[k] = []);
    while (pool.length < need) {
      const shadow = k.endsWith('s'), type = shadow ? k.slice(0, -1) : k;
      const f = new THREE[type](0x000000, 0);
      f.userData.helper = true; f.userData.reserve = true;
      f.castShadow = shadow;
      if (shadow) { f.shadow.autoUpdate = false; f.shadow.needsUpdate = true; }   // (its map is made once, never again)
      f.visible = false;
      scene.add(f);
      pool.push(f); LRES.all.push(f);
    }
    for (let i = 0; i < pool.length; i++) { const v = i < need; if (pool[i].visible !== v) pool[i].visible = v; pool[i].intensity = 0; }
  }
}
function lightSig() {
  const n = {};
  for (const o of lightList()) {
    if (!o || !o.isLight || !isVisible(o)) continue;
    const k = lightKey(o);
    n[k] = (n[k] || 0) + 1;
  }
  // (14/11: 17 of the 117 «changes of the lights» of one day had the same numbers and only the keys in another order -
  // the order of the list changes when a light is made again - and each made the view wait for the shaders: sorted)
  const sorted = {};
  for (const k of Object.keys(n).sort()) sorted[k] = n[k];
  return JSON.stringify(sorted);
}
// (1.75.12) SmartView: the set of lights of the shaders stays as it was when SmartView went on - a light added (or a
// lamp of a distribution, a light turned off or deleted) changed it and three.js made every shader again, seconds of
// «Aggiornamento delle luci» each time (Luca). A light more waits switched off in the view (its icon stays), a light
// less leaves a dark stand-in of its kind. When SmartView goes off, the real set comes back once.
function smartHoldLights() {
  const want = JSON.parse(SMART.sig || '{}');
  const now = {}, byKey = {};
  for (const o of lightList()) {
    if (!o || !o.isLight || !isVisible(o)) continue;
    const k = lightKey(o);
    now[k] = (now[k] || 0) + 1;
    (byKey[k] = byKey[k] || []).push(o);
  }
  for (const k of new Set([...Object.keys(want), ...Object.keys(now)])) {
    let extra = (now[k] || 0) - (want[k] || 0);
    if (extra > 0) {
      // the stand-ins first, then the lights that were not there when SmartView went on
      const list = (byKey[k] || []).slice().sort((a, b) => (SMART.fillers.includes(b) ? 1 : 0) - (SMART.fillers.includes(a) ? 1 : 0)
        || (SMART.base.has(a) ? 1 : 0) - (SMART.base.has(b) ? 1 : 0));
      for (const o of list) {
        if (extra <= 0) break;
        o.visible = false;
        if (!SMART.fillers.includes(o)) SMART.hidden.add(o);
        extra--;
      }
    } else if (extra < 0 && !k.endsWith('m')) {
      const type = k.replace(/s$/, '');
      for (; extra < 0; extra++) {
        let f = SMART.fillers.find((x) => !x.visible && lightKey(x) === k);
        if (!f) {
          const C = THREE[type];
          if (!C) break;
          f = new C(0x000000, 0);
          f.castShadow = k.endsWith('s');
          f.userData.helper = true;
          scene.add(f);
          SMART.fillers.push(f);
        }
        f.visible = true; f.intensity = 0;
      }
    }
  }
}
let _tickLast = 0;
// (1.78.4, Luca: «switcho su realtime e per molti secondi resta fermo… la sensazione è che sia bloccato») leaving the
// path tracing: the view had not drawn for a while (materials, lights, snow changed meanwhile) and its first frame
// made dozens of shaders inside itself - 48 s still, with no word. Now «Occupato · Passaggio al tempo reale» at once,
// the shaders prepared in the background first, the box kept until the first frame is drawn (the shadows' own
// shaders are made there: three.js has no background preparation for them)
let _wasPtOn = false, _ptWarm = false, _lastRtDraw = 0;
function tick() {
  requestAnimationFrame(tick);
  { const n = performance.now(); if (_tickLast) fpsInterval(n - _tickLast); _tickLast = n; }
  // «Occupato» asked by the app at the click (busyNow): this frame only shows it (the browser paints the box before
  // the next frames, which may freeze the page a few seconds while three.js prepares its shaders for a new light or
  // a new sky); then a few frames drawn after the app is done, before it may go
  if (busyWarn.hold) {
    if (busyWarn.holdFresh) { busyWarn.holdFresh = false; busyTick(); invalidate(300); return; }
    if (!locked && busyWarn.holdFrames > 0) { busyWarn.holdFrames--; invalidate(300); }
    if ((!locked && busyWarn.holdFrames <= 0) || performance.now() - busyWarn.holdAt > 60000) busyWarn.hold = false;
  }
  // a selected model that had no size when it was selected (dropped from the library near the camera: the gizmo went
  // to its origin, half a metre under the floor for a car): tried again a few times a second until it has one
  if (pivotNoSize && selection.length && !gizmoDragging() && performance.now() - _pivotRetry > 250) {
    _pivotRetry = performance.now();
    placePivot();
    if (!pivotNoSize) { refreshSelectionBoxes(); updateHud(); invalidate(300); }
  }
  updateScaleBar(performance.now());
  walkStep();
  keepIconsSmall();
  orbit.update();
  const dist = camera.position.distanceTo(orbit.target);
  camera.near = Math.max(0.0002, dist * 0.002);
  // (1.76.26, Luca) far enough for the whole scene too: a terrain of a real elevation file is tens of km (96 km), and
  // past 3 km it was cut - a ragged edge against the sky
  let far = Math.max(amb.active ? 3000 : 50, dist * 400, OCEAN.mesh ? 24000 : 0);   // (the sea: 20 km to the horizon)
  if (_shadowBox) {
    _shadowBox.getCenter(_farC);
    far = Math.max(far, Math.min(400000, camera.position.distanceTo(_farC) + _shadowBox.getSize(_farS).length() / 2));
  }
  camera.far = far;
  camera.updateProjectionMatrix();
  camera.updateMatrixWorld();
  ambPlaceDisc();
  const now = performance.now();
  if (!_lastCam.equals(camera.matrixWorld) || !_lastProj.equals(camera.projectionMatrix) || gizmoDragging()) {
    _lastCam.copy(camera.matrixWorld); _lastProj.copy(camera.projectionMatrix); invalidate(250);
  }
  const ptOn = cyclesImg.classList.contains('on');
  const ptOverlay = ptOn && !gizmoDragging();
  if (_wasPtOn && !ptOn && realistic) {
    // (14/11, Luca: «Switching to real time» with nobody pressing it) the picture went away while the view stays on the path
    // tracing: the engine restarted it (something changed), or a move began. This is not a switch: no «Occupato» box;
    // the shaders are looked at again by the normal path below, which warns only if something is really to be made
    _wasPtOn = false; _shaderRev++; _shaderNew = true; invalidate(300);
  }
  if (_wasPtOn && !ptOn) {
    _wasPtOn = false; _ptWarm = true;
    busyWarn.hold = true; busyWarn.holdFresh = false; busyWarn.holdFrames = 1e9; busyWarn.holdAt = now;
    busyWarn.holdWhat = tr('Passaggio al tempo reale');
    _shaderRev++; _shaderNew = true;
    busyTick();
    invalidate(300);
    return;                           // (this frame only shows the box: painted before the slow work)
  }
  _wasPtOn = ptOn;
  const idle = now > drawUntil && !ALWAYS_DRAW;
  // (audit 1.78.5) the safety redraw of a still view every 10 s (was 2 s: a whole frame of a heavy scene for nothing),
  // never in SmartView
  if (idle && (_smartOn || now - lastDraw < 10000)) { fpsIdle(ptOverlay); return; }
  // the shaders being prepared in the background (prepareShaders): the last picture stays, nothing is drawn - a
  // frame now would make them at once, freezing the page
  if (shaderPrep.busy) { invalidate(300); return; }
  lastDraw = now;
  if (_msgPending) {
    const lat = now - _msgPending.t;
    if (lat > 1500) viewLog(`update late: «${_msgPending.type}» was drawn ${Math.round(lat / 500) * 500} ms after it arrived`);
    _msgPending = null;
  }
  renderer.info.reset();
  if (ptOverlay) {
    // the path-traced picture is visible under the canvas: only the selection outline on a transparent canvas
    // (no outline there: the picture stays clean)
    renderer.setClearColor(0x000000, 0);
    renderer.clear();
    scene.updateMatrixWorld();     // (clicks and drops hit the objects where they are now, also under the picture)
  } else {
    _lastRtDraw = now;
    const measure = fpsShouldMeasure();
    const t0 = performance.now();
    renderer.setClearColor(0x000000, 1);
    scene.updateMatrixWorld();
    try { distLampsUpdate(); } catch (err) { viewLog('lamps of the distributions: ' + err); }
    if (SMART.on && now - (SMART.at || 0) > 500) { SMART.at = now; try { smartShadows(); } catch (err) { viewLog('smartview shadows: ' + err); } }
    try { flakesUniforms(); } catch (err) { viewLog('flakes: ' + err); }
    try { mantleLod(); } catch (err) { viewLog('mantle copies: ' + err); }
    // a light more or less (a copy, a delete, an undo, shadows on or off, a lamp of a distribution): three.js would
    // make the shaders of every material again in this frame, freezing the page from a fraction of a second to half
    // a minute in a big scene (1.65-1.66, logs of Luca): made in the background instead, «Occupato» meanwhile
    try { lightBudget(); } catch (err) { viewLog('light budget: ' + err); }
    try { reserveLights(); } catch (err) { viewLog('light reserve: ' + err); }
    let ls = lightSig();
    if (SMART.on && !SMART.sig && _lightSig !== null && !shaderPrep.busy) {     // (SmartView on from the start)
      SMART.sig = _lightSig;
      SMART.base = new Set(lightList().filter((x) => x && x.isLight && isVisible(x)));
    }
    if (SMART.on && SMART.sig && ls !== SMART.sig) {
      try { smartHoldLights(); } catch (err) { viewLog('smartview lights: ' + err); }
      ls = lightSig();
      // (a light changed in SmartView: what the hold did, and what the view shows now - if the scene is not seen, this says why)
      try {
        let vis = 0, all = 0; root.traverse((o) => { if (o.isMesh) { all++; if (isVisible(o)) vis++; } });
        const c = camera.position;
        viewLog(`smartview hold: lights hidden ${SMART.hidden.size}, stand-in lights ${SMART.fillers.length}; meshes visible ${vis} of ${all}; ` +
                `scatter shown ${scatter.shown.size}; camera ${c.x.toFixed(1)},${c.y.toFixed(1)},${c.z.toFixed(1)}; sig ${ls}`);
      } catch (err) { viewLog('smartview hold log: ' + err); }
    }
    if (_lightSig !== null && ls !== _lightSig) {
      // (14/11, log of Luca: opening a street = three rounds of shaders in a row, 10 + 14 + 19 s - the lamps of the distributions,
      // the lights of the scene and the spare lights arrive one after the other, each made the shaders of the one before useless.
      // The set of lights must stay the same for 0.7 s before the shaders are made: one round for all of them)
      if (_lightPend.sig !== ls) { _lightPend.sig = ls; _lightPend.t = now; }
      if (now - _lightPend.t < 700) { invalidate(250); return; }
      viewLog(`lights of the view: ${_lightSig} -> ${ls}`);
      _lightSig = ls;
      prepareShaders(tr('Aggiornamento delle luci nella vista'));
      protoRewarm();                 // (the shaders of the selected pieces too, after the view's own: see protoWarm)
      return;
    }
    _lightSig = ls;
    if (_smartOn && _shaderRev !== _shaderRevSeen) {          // (SmartView: no preparation - stand-ins, see _smartOn)
      _shaderRevSeen = _shaderRev; _shaderNew = false;
      try { smartStandIns(); } catch (err) { viewLog('smartview stand-ins: ' + err); }
    }
    if (_shaderRev !== _shaderRevSeen) {
      // (see prepareShaders: marks with nothing new are let pass - but never a mesh with a material never drawn:
      // 1.75.13, selecting a car drawn from its prototype added its 14 parts as meshes, their shaders were made inside
      // one frame and the view stood still 15 s, Luca)
      if ((shaderPrep.empty || 0) >= 3 && !_shaderNew && marksPassable()) { _shaderRevSeen = _shaderRev; _marked.clear(); }
      else {
        prepareShaders(tr('Aggiornamento dei materiali nella vista'));
        return;
      }
    }
    if (boxMode) {
      scatterUpdateSafe();
      renderClay();
      if (_ptWarm) { _ptWarm = false; busyWarn.holdFrames = 2; }
    } else {
      scatterUpdateSafe();
      // (1.75.26) the pieces of a model just put in the scene are made here, after the check above: their shaders
      // were made inside this frame - 10 s with the lamps of a street at night, with SmartView on too (Luca). Looked
      // at again now: SmartView draws them with the stand-ins, otherwise the preparation in the background first.
      if (_shaderRev !== _shaderRevSeen) {
        if (_smartOn) {
          _shaderRevSeen = _shaderRev; _shaderNew = false;
          try { smartStandIns(); } catch (err) { viewLog('smartview stand-ins: ' + err); }
        } else if (_shaderNew || !((shaderPrep.empty || 0) >= 3 && marksPassable())) {
          prepareShaders(tr('Aggiornamento dei materiali nella vista'));
          return;
        }
      }
      foliageShadows();
      const _p0 = renderer.info.programs ? renderer.info.programs.length : 0, _r0 = performance.now();
      const _before = renderer.info.programs ? renderer.info.programs.slice() : [];
      renderer.render(scene, camera);
      _frameNewShaders = !!(renderer.info.programs && renderer.info.programs.length > _p0);
      if (_frameNewShaders) { try { keepPrograms(); } catch (err) { viewLog('programs kept: ' + err); } }
      fxApply();
      renderOutline();
      // (a frame that blocks the page: how long, and whether three.js had to prepare new shaders - a new light, a
      // new kind of material: in app.log, for the slow clicks)
      const _rms = performance.now() - _r0;
      if (renderer.info.programs && renderer.info.programs.length > _p0) shaderPrep.empty = 0;   // (a real new shader: checked again first)
      if (_rms > 1500) {
        // (1.78.4) which shaders were made inside the frame: their kinds, for the next slow click in app.log
        const made = renderer.info.programs ? renderer.info.programs.slice(_p0) : [];
        const kinds = {};
        for (const pr of made) { const k = String(pr.name || '?').split(' ')[0]; kinds[k] = (kinds[k] || 0) + 1; }
        viewLog(`slow frame: ${Math.round(_rms)} ms, ${made.length} new shaders, ${renderer.info.render.calls} draws` +
                (made.length ? ` (${Object.entries(kinds).map(([k, n]) => k + ' ' + n).join(', ')})` : '') + (_ptWarm ? ' · first frame after the path tracing' : ''));
      }
      if (_frameNewShaders && _rms > 300) {
        try { for (const l of shaderWhy(renderer.info.programs.filter((p) => !_before.includes(p)), _before)) viewLog('shader made inside a frame: ' + l); } catch (err) { viewLog('shader why: ' + err); }
      }
      if (_ptWarm) { _ptWarm = false; busyWarn.holdFrames = 2; }
    }
    let measured = 0;
    if (measure && !idle) { renderer.getContext().finish(); measured = performance.now() - t0; scatterAdapt(measured); }
    if (!idle) fpsFrame(performance.now() - t0, measured);       // (the safety redraw of a still view is not counted)
  }
  fpsEl.classList.toggle('hidden', ptOverlay);
}
setBadge(tr('Tempo reale'));
resize();
tick();
post({ type: 'ready' });

// standalone test mode: viewer.html?glb=...&engine=...
if (params.get('test')) window.__dbg = {
  THREE, pivot, gizmo, byId, camera, orbit, lights, sector, hud, scene, renderer, fallback, lightList, LRES, lightSig,
  get selection() { return selection; },
  scatter, scatterAdapt, setFrameShaders: (v) => { _frameNewShaders = !!v; },
  busyWarn, get ptWarm() { return [_wasPtOn, _ptWarm, locked, boxMode]; },
  state: () => ({ lastCurrent, needEpochAbove, interacting, lastVersion, realistic, polling, down, selection, primary }),
  setSmartView, get smart() { return { on: _smartOn, pending: _smartPending.size, swapped: _smartSwapped.size }; },
  onMessage, applySync, updateLight,
  refitShadows, amb, ambApply, setAmbience, root, scatter, scatterAdopt, surfaceHits, paintSurfaces, areaSurfaces, paint, OCEAN, oceanSet, fxApply, setFx, FX, lightSig, shaderPrep, WET, wetDryApply, get shaderRev() { return [_shaderRev, _shaderRevSeen]; }, dropToFloor, mantleSync, distLamps, FLAKES, setPivotMode, updateHud, drawSector, applySelection, scatter, scatterUpdate, sceneHits, paint, paintStroke: (h, e) => paintStroke(h, e), surfaceUnder: (x, y) => surfaceUnder(x, y), areaTool, areaGenerate: () => areaGenerate(),
};
if (params.get('glb')) loadScene(params.get('glb')).then(() => { frameSelection([]); window.simplerLoaded = true; });
