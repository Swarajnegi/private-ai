/**
 * The field: dust, the sand wordmark, and the gold core — every one of them
 * made of individual grains.
 *
 * The visual language is the one on austensor.com (studied, not copied): a
 * particle is a CRISP dot a pixel or two wide with a faint private halo, drawn
 * translucent, so density comes from thousands of grains overlapping rather
 * than from a bloom pass smearing them into tubes of light. Each grain has its
 * own existence — its own drift around its home, its own twinkle, its own
 * shade — and now and then one wanders off and comes back.
 *
 * The core keeps the structure of the Age of Ultron lab matrix (0:15): nested
 * spherical shells of BROKEN arcs at varied tilts, a few whole gyroscope
 * rings, circuit ticks where arcs end, a spiral nucleus, radial streaks — but
 * every line is a line of sand, not a line of light.
 *
 * Motion follows JARVIS's real state, never a timer pretending to be one:
 * grains drift when idle, shiver with the microphone when listening, stream
 * along their arcs while thinking, and pulse outward with the actual output
 * audio while speaking.
 */
import * as THREE from "three";
import { EffectComposer } from "three/examples/jsm/postprocessing/EffectComposer.js";
import { RenderPass } from "three/examples/jsm/postprocessing/RenderPass.js";
import { UnrealBloomPass } from "three/examples/jsm/postprocessing/UnrealBloomPass.js";
import { OutputPass } from "three/examples/jsm/postprocessing/OutputPass.js";
import type { CoreState } from "./live";

const TAU = Math.PI * 2;
const rand = (a: number, b: number) => a + Math.random() * (b - a);
const ease = (t: number) => (t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2);

function randomUnit(): THREE.Vector3 {
  const u = rand(-1, 1);
  const th = rand(0, TAU);
  const r = Math.sqrt(1 - u * u);
  return new THREE.Vector3(r * Math.cos(th), u, r * Math.sin(th));
}

function gauss(): number {
  return Math.sqrt(-2 * Math.log(Math.max(1e-6, Math.random()))) * Math.cos(TAU * Math.random());
}

/** Weighted palette pick: [r, g, b, weight]. */
function pick(palette: number[][]): number[] {
  let r = Math.random();
  for (const c of palette) if ((r -= c[3]) < 0) return c;
  return palette[0];
}

// A grain: a crisp dot with a faint halo. The halo is what reads as the
// "translucent glow" — it is private to the grain, not a screen-space bloom.
const GRAIN_FRAG = /* glsl */ `
  varying vec3 vColor;
  varying float vA;
  void main() {
    float d = length(gl_PointCoord - 0.5) * 2.0;
    if (d > 1.0 || vA <= 0.002) discard;
    float core = smoothstep(0.42, 0.0, d);
    float halo = exp(-d * d * 5.0) * 0.22;
    float a = (core + halo) * vA;
    gl_FragColor = vec4(vColor * a, a);
  }
`;

/** Per-state targets the uniforms ease toward each frame. */
const STATE: Record<CoreState, { spin: number; energy: number; scale: number; stream: number; jitter: number }> = {
  waking: { spin: 0.35, energy: 0.25, scale: 0.92, stream: 0, jitter: 1 },
  idle: { spin: 0.5, energy: 0.45, scale: 1.0, stream: 0, jitter: 1 },
  listening: { spin: 0.65, energy: 0.6, scale: 1.03, stream: 0, jitter: 1.8 },
  transcribing: { spin: 1.1, energy: 0.62, scale: 0.95, stream: 0.4, jitter: 1.2 },
  thinking: { spin: 2.4, energy: 0.78, scale: 0.97, stream: 1, jitter: 0.8 },
  speaking: { spin: 0.8, energy: 0.72, scale: 1.02, stream: 0, jitter: 1 },
};

// ---------------------------------------------------------------------------
// The gold core — a swarm of grains holding the shape of the matrix
// ---------------------------------------------------------------------------

const CORE_VERT = /* glsl */ `
  attribute vec3 aAxis;
  attribute vec3 aColor;
  attribute float aSpeed;
  attribute float aKind;     // 0 arc, 1 ring, 2 tick, 3 nucleus, 4 streak, 5 loose
  attribute float aSeed;
  attribute float aAlong;
  attribute float aSize;
  uniform float uTime, uSpin, uEnergy, uScale, uStreamPhase, uJitter, uReveal, uLevel, uPixel;
  varying vec3 vColor;
  varying float vA;

  vec3 rotateAxis(vec3 p, vec3 k, float a) {
    float c = cos(a), s = sin(a);
    return p * c + cross(k, p) * s + k * dot(k, p) * (1.0 - c);
  }

  void main() {
    float t = uTime;
    float s = aSeed;
    // Thinking: grains stream along their arc, each at its own pace. The phase
    // is accumulated on the CPU and rewinds afterwards, so the grains flow back
    // and the matrix reassembles instead of snapping.
    float angle = t * aSpeed * uSpin + uStreamPhase * (0.35 + s * 0.9) * sign(aSpeed + 0.0001);
    vec3 p = rotateAxis(position, aAxis, angle);

    // Its own existence: every grain drifts on its own small orbit.
    vec3 drift = vec3(sin(t * (0.6 + s * 1.7) + s * 91.0),
                      sin(t * (0.5 + s * 1.3) + s * 47.0),
                      cos(t * (0.7 + s * 1.1) + s * 13.0));
    // Arc grains hold their line (the matrix must stay legible); loose grains roam.
    float roam = aKind > 4.5 ? 3.5 : (aKind > 2.5 && aKind < 3.5 ? 1.4 : 1.0);
    float amp = (0.003 + 0.004 * uJitter + uLevel * 0.012 * uJitter) * roam;
    p += drift * amp;

    // A few grains wander off now and then, and come back.
    float wander = pow(max(0.0, sin(t * (0.08 + s * 0.12) + s * 300.0)), 24.0);
    float r = length(p);
    p *= 1.0 + wander * (0.25 + s * 0.4) * step(0.9, fract(s * 7.31));

    // Speaking: the shells breathe outward with the real output amplitude.
    p *= uScale * (1.0 + uLevel * 0.09 * smoothstep(0.2, 1.1, r));

    vec4 mv = modelViewMatrix * vec4(p, 1.0);
    gl_Position = projectionMatrix * mv;
    float twinkle = 0.55 + 0.45 * sin(s * 113.0 + t * (1.2 + s * 3.1));
    gl_PointSize = min(aSize * uPixel / -mv.z, uPixel * 1.9);

    float gain = aKind > 2.5 && aKind < 3.5 ? 1.15 : (aKind > 4.5 ? 0.6 : 1.0);
    vColor = aColor;
    vA = uReveal * gain * twinkle * (0.32 + uEnergy * 0.48 + uLevel * 0.35);
  }
`;

const GOLD = [
  [1.0, 0.95, 0.84, 0.16],   // cream
  [1.0, 0.82, 0.48, 0.24],   // pale gold
  [1.0, 0.71, 0.28, 0.32],   // amber
  [1.0, 0.48, 0.12, 0.2],    // ember
  [0.8, 0.89, 1.0, 0.05],    // a rare cold fleck
  [1.0, 0.45, 0.55, 0.03],   // a rare rose fleck
];

function buildCore(): THREE.BufferGeometry {
  const pos: number[] = [], axis: number[] = [], speed: number[] = [], kind: number[] = [];
  const seed: number[] = [], along: number[] = [], size: number[] = [], color: number[] = [];
  const push = (p: THREE.Vector3, ax: THREE.Vector3, sp: number, k: number, a: number, s: number, palette = GOLD) => {
    pos.push(p.x, p.y, p.z);
    axis.push(ax.x, ax.y, ax.z);
    speed.push(sp);
    kind.push(k);
    seed.push(Math.random());
    along.push(a);
    size.push(s);
    const c = pick(palette);
    const v = rand(0.82, 1.08);
    color.push(c[0] * v, c[1] * v, c[2] * v);
  };

  const SHELLS = 7;
  for (let k = 0; k < SHELLS; k++) {
    const R = 0.36 + k * 0.135;
    const shellAxis = randomUnit();
    const shellSpeed = (k % 2 ? 1 : -1) * rand(0.06, 0.3);

    // Broken arcs as lines of sand: grains along great-circle segments, each
    // shaken a little off the line so the arc reads as grains, not a stroke.
    const arcs = 6 + k * 2;
    for (let a = 0; a < arcs; a++) {
      const n = randomUnit();
      const u = new THREE.Vector3().crossVectors(n, randomUnit()).normalize();
      const v = new THREE.Vector3().crossVectors(n, u);
      const start = rand(0, TAU);
      const span = rand(0.35, 2.4);
      const count = Math.round(span * R * 190);
      for (let i = 0; i < count; i++) {
        const f = i / Math.max(1, count - 1);
        const th = start + span * f;
        const p = u.clone().multiplyScalar(Math.cos(th) * R).addScaledVector(v, Math.sin(th) * R);
        p.addScaledVector(randomUnit(), Math.abs(gauss()) * 0.005);
        push(p, shellAxis, shellSpeed, 0, f, rand(3.2, 5.2));
      }
      for (const end of [start, start + span]) {
        if (Math.random() < 0.55) continue;
        const base = u.clone().multiplyScalar(Math.cos(end) * R).addScaledVector(v, Math.sin(end) * R);
        const dir = base.clone().normalize();
        const len = rand(0.03, 0.09);
        for (let i = 0; i < 12; i++) push(base.clone().addScaledVector(dir, (i / 11) * len), shellAxis, shellSpeed, 2, i / 11, 3.6);
      }
    }

    if (k >= SHELLS - 3) {
      for (let g = 0; g < 2; g++) {
        const n = randomUnit();
        const u = new THREE.Vector3().crossVectors(n, randomUnit()).normalize();
        const v = new THREE.Vector3().crossVectors(n, u);
        const ringR = R + 0.05 + g * 0.03;
        for (let i = 0; i < 360; i++) {
          const th = (i / 360) * TAU + rand(-0.004, 0.004);
          push(u.clone().multiplyScalar(Math.cos(th) * ringR).addScaledVector(v, Math.sin(th) * ringR),
            n, shellSpeed * 1.6, 1, i / 360, rand(2.8, 4.2));
        }
      }
    }
  }

  // Loose grains filling the volume between shells — the sphere's own dust.
  const still = new THREE.Vector3(0, 1, 0);
  for (let i = 0; i < 900; i++) {
    push(randomUnit().multiplyScalar(Math.pow(Math.random(), 0.6) * 1.25), randomUnit(), rand(-0.2, 0.2), 5, 0, rand(2.6, 4.4));
  }

  // Nucleus: a dense knot of grains plus spiral arms in three planes.
  const HOT = [[1.0, 0.97, 0.9, 0.55], [1.0, 0.85, 0.55, 0.35], [1.0, 0.68, 0.3, 0.1]];
  for (let i = 0; i < 1600; i++) {
    const r = Math.abs(gauss()) * 0.07;
    push(randomUnit().multiplyScalar(r), still, 0.4, 3, 0, rand(3.4, 5.6), HOT);
  }
  for (let plane = 0; plane < 3; plane++) {
    const n = randomUnit();
    const u = new THREE.Vector3().crossVectors(n, randomUnit()).normalize();
    const v = new THREE.Vector3().crossVectors(n, u);
    for (let arm = 0; arm < 2; arm++) {
      for (let i = 0; i < 480; i++) {
        const f = i / 480;
        const th = arm * Math.PI + f * TAU * 2.2;
        const r = 0.03 + 0.26 * f;
        const p = u.clone().multiplyScalar(Math.cos(th) * r).addScaledVector(v, Math.sin(th) * r);
        p.addScaledVector(randomUnit(), 0.006);
        push(p, n, 0.9 + plane * 0.2, 3, f, rand(2.8, 4.4), HOT);
      }
    }
  }

  for (let sIdx = 0; sIdx < 26; sIdx++) {
    const dir = randomUnit();
    const from = rand(0.25, 0.6);
    const to = from + rand(0.35, 0.95);
    for (let i = 0; i < 46; i++) {
      const f = i / 45;
      push(dir.clone().multiplyScalar(from + (to - from) * f).addScaledVector(randomUnit(), 0.005),
        still, 0.12, 4, f, 3.0 * (1 - f * 0.5));
    }
  }

  const g = new THREE.BufferGeometry();
  g.setAttribute("position", new THREE.Float32BufferAttribute(pos, 3));
  g.setAttribute("aAxis", new THREE.Float32BufferAttribute(axis, 3));
  g.setAttribute("aColor", new THREE.Float32BufferAttribute(color, 3));
  g.setAttribute("aSpeed", new THREE.Float32BufferAttribute(speed, 1));
  g.setAttribute("aKind", new THREE.Float32BufferAttribute(kind, 1));
  g.setAttribute("aSeed", new THREE.Float32BufferAttribute(seed, 1));
  g.setAttribute("aAlong", new THREE.Float32BufferAttribute(along, 1));
  g.setAttribute("aSize", new THREE.Float32BufferAttribute(size, 1));
  return g;
}

/** A faint warmth the core sits in. Kept weak: the light should come from grains. */
function glowTexture(): THREE.Texture {
  const c = document.createElement("canvas");
  c.width = c.height = 256;
  const g = c.getContext("2d")!;
  const r = g.createRadialGradient(128, 128, 0, 128, 128, 128);
  r.addColorStop(0, "rgba(255,230,190,1)");
  r.addColorStop(0.22, "rgba(255,170,70,0.35)");
  r.addColorStop(0.6, "rgba(255,110,30,0.06)");
  r.addColorStop(1, "rgba(0,0,0,0)");
  g.fillStyle = r;
  g.fillRect(0, 0, 256, 256);
  return new THREE.CanvasTexture(c);
}

// ---------------------------------------------------------------------------
// Dust — a field of grains with a denser, more coloured band through it
// ---------------------------------------------------------------------------

const DUST_VERT = /* glsl */ `
  attribute vec3 aColor;
  attribute float aSeed;
  attribute float aSize;
  uniform float uTime, uPixel, uDim;
  varying vec3 vColor;
  varying float vA;
  void main() {
    float s = aSeed;
    float a = uTime * 0.01 * (0.4 + s);
    vec3 p = vec3(position.x * cos(a) - position.z * sin(a), position.y,
                  position.x * sin(a) + position.z * cos(a));
    p += vec3(sin(uTime * 0.13 + s * 40.0), cos(uTime * 0.11 + s * 70.0), sin(uTime * 0.09 + s * 20.0)) * 0.04;
    vec4 mv = modelViewMatrix * vec4(p, 1.0);
    gl_Position = projectionMatrix * mv;
    gl_PointSize = min(aSize * uPixel / -mv.z, uPixel * 1.2);
    vColor = aColor;
    vA = (0.35 + 0.65 * (0.5 + 0.5 * sin(uTime * (0.4 + s * 1.6) + s * 50.0))) * uDim * 0.9;
  }
`;

function buildDust(count: number): THREE.BufferGeometry {
  // Mostly white, with coloured flecks — the band carries more colour.
  const FIELD = [[0.92, 0.94, 1.0, 0.7], [0.45, 0.62, 1.0, 0.1], [0.66, 0.46, 1.0, 0.08],
    [1.0, 0.36, 0.5, 0.06], [1.0, 0.72, 0.32, 0.06]];
  const BAND = [[0.9, 0.9, 1.0, 0.42], [0.46, 0.55, 1.0, 0.18], [0.72, 0.42, 1.0, 0.16],
    [1.0, 0.34, 0.52, 0.14], [1.0, 0.7, 0.3, 0.1]];
  const pos: number[] = [], col: number[] = [], seed: number[] = [], size: number[] = [];
  for (let i = 0; i < count; i++) {
    const inBand = i < count * 0.55;
    let x: number, y: number, z: number;
    if (inBand) {
      x = rand(-9, 9);
      y = gauss() * (0.28 + Math.abs(x) * 0.025) + x * 0.05;
      z = rand(-4.5, 0.6);
    } else {
      const p = randomUnit().multiplyScalar(rand(2.5, 14));
      x = p.x; y = p.y * 0.75; z = p.z - 3;
    }
    // Nothing between the lens and the core: a grain a hair from the camera
    // gets a huge point size (size / distance) and blooms into a blob.
    pos.push(x, y, Math.min(z, 1.2));
    const c = pick(inBand ? BAND : FIELD);
    const v = rand(0.6, 1.05);
    col.push(c[0] * v, c[1] * v, c[2] * v);
    seed.push(Math.random());
    // A few larger, softer stars among the pinpoints.
    size.push(Math.random() < 0.025 ? rand(5.5, 8.5) : rand(2.8, 4.6));
  }
  const g = new THREE.BufferGeometry();
  g.setAttribute("position", new THREE.Float32BufferAttribute(pos, 3));
  g.setAttribute("aColor", new THREE.Float32BufferAttribute(col, 3));
  g.setAttribute("aSeed", new THREE.Float32BufferAttribute(seed, 1));
  g.setAttribute("aSize", new THREE.Float32BufferAttribute(size, 1));
  return g;
}

// ---------------------------------------------------------------------------
// Wordmark — a cloud of sand that settles into J.A.R.V.I.S, then flows into the core
// ---------------------------------------------------------------------------

const WORD_VERT = /* glsl */ `
  attribute vec3 aFrom;
  attribute vec3 aTo;
  attribute float aSeed;
  attribute float aShade;
  uniform float uForm, uCollapse, uTime, uPixel, uGain;
  varying vec3 vColor;
  varying float vA;
  float ease(float t) { return t < 0.5 ? 4.0*t*t*t : 1.0 - pow(-2.0*t + 2.0, 3.0) / 2.0; }
  void main() {
    float s = aSeed;
    float f = ease(clamp(uForm * 1.3 - s * 0.3, 0.0, 1.0));
    vec3 text = position + vec3(sin(uTime * 1.1 + s * 40.0), cos(uTime * 0.9 + s * 30.0), sin(uTime * 0.7 + s * 17.0)) * 0.006;
    vec3 p = mix(aFrom, text, f);
    float c = ease(clamp(uCollapse * 1.4 - s * 0.4, 0.0, 1.0));
    // On the way into the core each grain swirls rather than travelling straight.
    vec3 mid = mix(p, aTo, 0.5) + vec3(sin(s * 60.0), cos(s * 60.0), 0.0) * 0.5 * sin(c * 3.14159);
    p = mix(mix(p, mid, c), mix(mid, aTo, c), c);
    vec4 mv = modelViewMatrix * vec4(p, 1.0);
    gl_Position = projectionMatrix * mv;
    gl_PointSize = min((3.2 + s * 1.8) * uPixel / -mv.z, uPixel * 1.4);
    vColor = mix(vec3(0.95, 0.96, 1.0), vec3(1.0, 0.75, 0.35), c);
    vA = (0.4 + 0.6 * f) * aShade * uGain * (1.0 - c * c) * (0.78 + 0.22 * sin(uTime * 2.0 + s * 80.0));
  }
`;

function buildWordmark(text: string, width: number, step = 3): THREE.BufferGeometry {
  const cv = document.createElement("canvas");
  cv.width = 1400;
  cv.height = 260;
  const ctx = cv.getContext("2d")!;
  ctx.fillStyle = "#fff";
  ctx.textAlign = "center";
  ctx.textBaseline = "middle";
  ctx.font = '400 210px "Geist Sans", "Geist", system-ui, sans-serif';
  ctx.letterSpacing = "18px";
  ctx.fillText(text, cv.width / 2, cv.height / 2);
  const img = ctx.getImageData(0, 0, cv.width, cv.height).data;
  const pos: number[] = [], from: number[] = [], to: number[] = [], seed: number[] = [], shade: number[] = [];
  const scale = width / cv.width;
  for (let y = 0; y < cv.height; y += step) {
    for (let x = 0; x < cv.width; x += step) {
      if (img[(y * cv.width + x) * 4 + 3] < 128) continue;
      pos.push((x - cv.width / 2) * scale + rand(-0.004, 0.004), -(y - cv.height / 2) * scale + rand(-0.004, 0.004), rand(-0.02, 0.02));
      // Start as a volumetric cloud around where the word will settle.
      from.push(gauss() * 1.8, gauss() * 0.7, gauss() * 1.2 - 0.5);
      const t = randomUnit().multiplyScalar(Math.pow(Math.random(), 0.5) * 0.5);
      to.push(t.x, t.y, t.z);
      seed.push(Math.random());
      shade.push(rand(0.45, 1.0));
    }
  }
  const g = new THREE.BufferGeometry();
  g.setAttribute("position", new THREE.Float32BufferAttribute(pos, 3));
  g.setAttribute("aFrom", new THREE.Float32BufferAttribute(from, 3));
  g.setAttribute("aTo", new THREE.Float32BufferAttribute(to, 3));
  g.setAttribute("aSeed", new THREE.Float32BufferAttribute(seed, 1));
  g.setAttribute("aShade", new THREE.Float32BufferAttribute(shade, 1));
  return g;
}

// ---------------------------------------------------------------------------
// The field
// ---------------------------------------------------------------------------

export class Field {
  private renderer: THREE.WebGLRenderer;
  private composer: EffectComposer;
  private bloom: UnrealBloomPass;
  private scene = new THREE.Scene();
  private camera = new THREE.PerspectiveCamera(38, 1, 0.1, 60);
  private coreMat: THREE.ShaderMaterial;
  private dustMat: THREE.ShaderMaterial;
  private wordMat: THREE.ShaderMaterial;
  private core: THREE.Points;
  private word: THREE.Points;
  private glow: THREE.Sprite;
  private clock = new THREE.Clock();
  private target = STATE.waking;
  private pointer = new THREE.Vector2();
  private level = 0;
  private stream = 0;
  private dim = 1;
  private focusX = 0;
  private focusY = 0.2;
  private paused = false;
  private raf = 0;
  private last = 0;
  private stage: "forming" | "held" | "collapsing" | "live" = "forming";
  private stageT = 0;
  private reduced = matchMedia("(prefers-reduced-motion: reduce)").matches;
  levelSource: () => number = () => 0;

  static supported(): boolean {
    try {
      const c = document.createElement("canvas");
      return !!c.getContext("webgl2");
    } catch {
      return false;
    }
  }

  constructor(private canvas: HTMLCanvasElement) {
    this.renderer = new THREE.WebGLRenderer({ canvas, antialias: false, alpha: false, powerPreference: "high-performance" });
    this.renderer.setClearColor(0x000000, 1);
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio, 1.5));

    // Point size in px = aSize * uPixel / distance: a grain of aSize 4 at the
    // core's distance is a ~4 px quad, of which the crisp centre is ~1.5 px.
    const uPixel = { value: this.renderer.getPixelRatio() * 4.5 };
    const common = { transparent: true, depthWrite: false, blending: THREE.AdditiveBlending, fragmentShader: GRAIN_FRAG };
    const narrow = window.innerWidth < 700;

    this.dustMat = new THREE.ShaderMaterial({
      ...common, vertexShader: DUST_VERT,
      uniforms: { uTime: { value: 0 }, uPixel, uDim: { value: 1 } },
    });
    this.scene.add(new THREE.Points(buildDust(narrow ? 5200 : 13000), this.dustMat));

    this.coreMat = new THREE.ShaderMaterial({
      ...common, vertexShader: CORE_VERT,
      uniforms: {
        uTime: { value: 0 }, uSpin: { value: STATE.waking.spin }, uEnergy: { value: 0.25 },
        uScale: { value: 0.92 }, uStreamPhase: { value: 0 }, uJitter: { value: 1 },
        uReveal: { value: 0 }, uLevel: { value: 0 }, uPixel,
      },
    });
    this.core = new THREE.Points(buildCore(), this.coreMat);
    this.core.scale.setScalar(0.56);
    this.core.position.y = 0.2;
    this.scene.add(this.core);
    this.glow = new THREE.Sprite(new THREE.SpriteMaterial({
      map: glowTexture(), color: 0xffb547, transparent: true, depthWrite: false,
      blending: THREE.AdditiveBlending, opacity: 0,
    }));
    this.glow.scale.setScalar(2.4);
    this.core.add(this.glow);

    this.wordMat = new THREE.ShaderMaterial({
      ...common, vertexShader: WORD_VERT,
      uniforms: {
        uForm: { value: 0 }, uCollapse: { value: 0 }, uTime: { value: 0 }, uPixel,
        // Denser phone sampling packs ~2.2x the grains into the same strokes.
        uGain: { value: narrow ? 0.55 : 1 },
      },
    });
    // Narrow screens scale the word down ~2x; sample twice as densely so the
    // shrunken strokes stay continuous instead of breaking into loose grains.
    this.word = new THREE.Points(buildWordmark("J.A.R.V.I.S", 3.3, narrow ? 2 : 3), this.wordMat);
    this.scene.add(this.word);

    // Bloom is a faint lift on the hottest grains only (high threshold), never
    // the source of the light: at the strength it used to run, every arc
    // smeared into a tube and the individual grains disappeared.
    this.composer = new EffectComposer(this.renderer);
    this.composer.addPass(new RenderPass(this.scene, this.camera));
    this.bloom = new UnrealBloomPass(new THREE.Vector2(256, 256), 0.32, 0.25, 0.55);
    this.composer.addPass(this.bloom);
    this.composer.addPass(new OutputPass());

    if (this.reduced) {
      this.stage = "held";
      this.wordMat.uniforms.uForm.value = 1;
    }
    addEventListener("resize", () => this.resize());
    addEventListener("pointermove", (e) => {
      this.pointer.set(e.clientX / innerWidth - 0.5, e.clientY / innerHeight - 0.5);
    });
    document.addEventListener("visibilitychange", () => (document.hidden ? this.stop() : this.start()));
    this.resize();
    this.start();
  }

  private resize(): void {
    const w = innerWidth, h = innerHeight;
    this.renderer.setSize(w, h, false);
    this.composer.setSize(w, h);
    this.bloom.resolution.set(Math.round(w / 2), Math.round(h / 2));
    this.camera.aspect = w / h;
    // Keep the core the same apparent size on a phone as on a desktop.
    this.camera.position.set(0, 0, w < 700 ? 6.2 : 4.3);
    this.camera.updateProjectionMatrix();
    // The wordmark is 3.3 units wide; on a phone only ~2 units are in view.
    // Grain size is NOT scaled with the fit — the phone camera already sits
    // farther back, and scaling again made the word vanish (measured).
    const halfW = Math.tan(THREE.MathUtils.degToRad(this.camera.fov / 2)) * this.camera.position.z * this.camera.aspect;
    this.word?.scale.setScalar(Math.min(1, (halfW * 2 * 0.86) / 3.3));
  }

  /** The user entered: the sand flows into the core and the core lights. */
  enter(): void {
    if (this.stage === "live" || this.stage === "collapsing") return;
    this.stage = "collapsing";
    this.stageT = 0;
    if (this.reduced) {
      this.stage = "live";
      this.word.visible = false;
      this.coreMat.uniforms.uReveal.value = 1;
    }
  }

  setState(s: CoreState): void {
    this.target = STATE[s] || STATE.idle;
  }

  setDim(d: number): void {
    this.dim = d;
  }

  /** Centre the core over the screen point (px) of the space the layout leaves
   *  free, so it never sits under the dialogue. */
  setFocus(px: number, py = innerHeight * 0.46): void {
    const halfH = Math.tan(THREE.MathUtils.degToRad(this.camera.fov / 2)) * this.camera.position.z;
    const halfW = halfH * this.camera.aspect;
    this.focusX = (px / innerWidth - 0.5) * 2 * halfW;
    this.focusY = 0.1 + (0.5 - py / innerHeight) * 2 * halfH;
  }

  setPaused(p: boolean): void {
    this.paused = p;
    if (p) this.stop();
    else this.start();
  }

  private start(): void {
    if (this.raf || this.paused || document.hidden) return;
    this.clock.getDelta();
    const loop = (now: number) => {
      this.raf = requestAnimationFrame(loop);
      if (now - this.last < 1000 / 61) return;          // cap at 60 fps
      this.last = now;
      this.frame(this.clock.getDelta());
    };
    this.raf = requestAnimationFrame(loop);
  }

  private stop(): void {
    cancelAnimationFrame(this.raf);
    this.raf = 0;
  }

  private frame(rawDt: number): void {
    // Motion easing uses a clamped step so a hitch never makes the core jump;
    // the arrival timeline uses wall-clock time so a slow machine sees the
    // same formation instead of a crawl (a throttled window ran rAF at 2/s).
    const dt = Math.min(rawDt, 0.05);
    const wall = Math.min(rawDt, 0.5);
    const speed = this.reduced ? 0.25 : 1;
    const u = this.coreMat.uniforms;
    u.uTime.value += dt * speed;
    this.dustMat.uniforms.uTime.value = u.uTime.value;
    this.wordMat.uniforms.uTime.value = u.uTime.value;

    this.stageT += wall;
    const wu = this.wordMat.uniforms;
    if (this.stage === "forming") {
      wu.uForm.value = Math.min(1, this.stageT / 3.0);
      if (wu.uForm.value >= 1) this.stage = "held";
    } else if (this.stage === "collapsing") {
      wu.uCollapse.value = Math.min(1, this.stageT / 1.8);
      u.uReveal.value = ease(Math.min(1, Math.max(0, (this.stageT - 0.6) / 1.5)));
      if (this.stageT > 2.3) {
        this.stage = "live";
        this.word.visible = false;
        u.uReveal.value = 1;
      }
    }

    // Ease every state uniform toward its target — the core never snaps.
    const k = 1 - Math.pow(0.04, dt);
    this.level += (this.levelSource() - this.level) * Math.min(1, dt * 14);
    u.uSpin.value += (this.target.spin - u.uSpin.value) * k;
    u.uEnergy.value += (this.target.energy - u.uEnergy.value) * k;
    u.uScale.value += (this.target.scale + this.level * 0.04 - u.uScale.value) * k;
    this.stream += (this.target.stream - this.stream) * k;
    if (this.target.stream > 0) u.uStreamPhase.value += dt * speed * this.stream * 1.6;
    else u.uStreamPhase.value *= Math.exp(-dt * 1.4);          // flow home
    u.uJitter.value += (this.target.jitter - u.uJitter.value) * k;
    u.uLevel.value = this.level;
    this.dustMat.uniforms.uDim.value += (this.dim - this.dustMat.uniforms.uDim.value) * k;

    const coreDim = 0.18 + 0.82 * this.dim;
    if (this.stage === "live") u.uReveal.value = coreDim;
    (this.glow.material as THREE.SpriteMaterial).opacity =
      u.uReveal.value * (0.02 + u.uEnergy.value * 0.04 + this.level * 0.1);
    this.core.rotation.y += dt * 0.05 * speed;
    const fx = this.stage === "live" ? this.focusX : 0;
    const fy = this.stage === "live" ? this.focusY : 0.2;
    this.core.position.x += (fx - this.core.position.x) * k;
    this.core.position.y += (fy - this.core.position.y) * k;

    const cam = this.camera.position;
    cam.x += (this.pointer.x * 0.35 - cam.x) * 0.03;
    cam.y += (-this.pointer.y * 0.25 + 0.1 - cam.y) * 0.03;
    this.camera.lookAt(0, 0.1, 0);
    this.composer.render();
  }
}
