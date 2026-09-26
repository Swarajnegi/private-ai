import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import { EffectComposer } from "three/addons/postprocessing/EffectComposer.js";
import { RenderPass } from "three/addons/postprocessing/RenderPass.js";
import { UnrealBloomPass } from "three/addons/postprocessing/UnrealBloomPass.js";
import { OutputPass } from "three/addons/postprocessing/OutputPass.js";

export type CoreState =
  "idle" | "listening" | "transcribing" | "thinking" | "speaking" | "offline";
/** One persistent perspective scene: camera shifts, never CSS-stretches the sphere. */
export function createScene(canvas: HTMLCanvasElement) {
  const reduced = matchMedia("(prefers-reduced-motion: reduce)");
  let paused = reduced.matches,
    state: CoreState = "offline",
    amplitude = 0,
    offset = 0,
    panel = false,
    frame = 0,
    last = 0,
    time = 0,
    slow = 0,
    quality = 1,
    lost = false;
  let renderer: THREE.WebGLRenderer;
  try {
    renderer = new THREE.WebGLRenderer({
      canvas,
      alpha: true,
      antialias: false,
      powerPreference: "high-performance",
    });
  } catch {
    canvas.classList.add("fallback");
    return {
      setState(_s: CoreState) {},
      setAmplitude(_n: number) {},
      setPanel(_b: boolean) {},
      toggle() {
        return true;
      },
      reset() {},
      get paused() {
        return true;
      },
    };
  }
  renderer.setPixelRatio(Math.min(devicePixelRatio, 1.5));
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  renderer.toneMappingExposure = 1.05;
  const scene = new THREE.Scene(),
    camera = new THREE.PerspectiveCamera(42, 1, 0.1, 100);
  camera.position.set(0, 0.12, 4.7);
  const controls = new OrbitControls(camera, canvas);
  controls.enableDamping = true;
  controls.dampingFactor = 0.055;
  controls.enablePan = false;
  controls.minDistance = 3.4;
  controls.maxDistance = 6.8;
  controls.rotateSpeed = 0.45;
  controls.autoRotate = false;
  const composer = new EffectComposer(renderer);
  composer.addPass(new RenderPass(scene, camera));
  const bloom = new UnrealBloomPass(new THREE.Vector2(1, 1), 0.65, 0.65, 0.48);
  composer.addPass(bloom);
  composer.addPass(new OutputPass());
  const group = new THREE.Group();
  scene.add(group);
  const count = 50000,
    positions = new Float32Array(count * 3),
    seeds = new Float32Array(count * 3);
  let seed = 170919;
  const random = () => {
    seed = (Math.imul(seed, 1664525) + 1013904223) >>> 0;
    return seed / 4294967296;
  };
  for (let i = 0; i < count; i++) {
    const a = i * 2.39996323,
      z = random() * 2 - 1,
      rr = Math.sqrt(1 - z * z);
    let r = 0.72 + random() * 0.26;
    if (i % 5 === 0) r = Math.cbrt(random()) * 0.88;
    let x = Math.cos(a) * rr * r,
      y = z * r,
      depth = Math.sin(a) * rr * r;
    if (i % 7 === 0) {
      r = 1.02 + random() * 0.43;
      x = Math.cos(a) * r;
      y = (random() - 0.5) * 0.12 + Math.sin(a) * r * 0.22;
      depth = Math.sin(a) * r;
    }
    positions.set([x, y, depth], i * 3);
    seeds.set([random(), random(), random()], i * 3);
  }
  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute("position", new THREE.BufferAttribute(positions, 3));
  geometry.setAttribute("seed", new THREE.BufferAttribute(seeds, 3));
  const uniforms = {
    time: { value: 0 },
    energy: { value: 0 },
    level: { value: 0 },
    pixelRatio: { value: renderer.getPixelRatio() },
    intro: { value: reduced.matches ? 1 : 0 },
  };
  const material = new THREE.ShaderMaterial({
    uniforms,
    transparent: true,
    depthWrite: false,
    blending: THREE.AdditiveBlending,
    vertexShader: `attribute vec3 seed; uniform float time,energy,level,pixelRatio,intro; varying float alpha; varying float hue;
 void main(){vec3 p=position;float r=length(p);float phase=seed.x*6.283;
 float breath=sin(time*.85)*.025; p*=1.+breath+level*.035+sin(time*1.6+phase)*energy*.02;
 float turn=time*(.045+energy*.025)*(r>1.?-.7:1.);p.xz=mat2(cos(turn),-sin(turn),sin(turn),cos(turn))*p.xz;
 p+=vec3(sin(time*.23+phase),cos(time*.3+phase),sin(time*.19+phase))*.012;
 p*=mix(2.8,1.,intro);vec4 mv=modelViewMatrix*vec4(p,1.);gl_Position=projectionMatrix*mv;
 gl_PointSize=clamp((1.2+seed.y*1.5)*pixelRatio*3.3/-mv.z,.6,6.);
 alpha=(.16+seed.z*.36)*(1.+energy*.18)*intro;hue=seed.y;}`,
    fragmentShader: `varying float alpha;varying float hue;void main(){float d=length(gl_PointCoord-.5)*2.;if(d>1.)discard;vec3 gold=mix(vec3(.82,.49,.22),vec3(1.,.85,.62),hue);gl_FragColor=vec4(gold,alpha*exp(-d*d*3.));}`,
  });
  const particles = new THREE.Points(geometry, material);
  group.add(particles);
  const lattice = new THREE.LineSegments(
    new THREE.WireframeGeometry(new THREE.IcosahedronGeometry(0.51, 1)),
    new THREE.LineBasicMaterial({
      color: 0xe3bd82,
      transparent: true,
      opacity: 0.22,
      depthWrite: false,
      blending: THREE.AdditiveBlending,
    }),
  );
  group.add(lattice);
  const halo = new THREE.Mesh(
    new THREE.PlaneGeometry(4.5, 4.5),
    new THREE.ShaderMaterial({
      transparent: true,
      depthWrite: false,
      blending: THREE.AdditiveBlending,
      vertexShader: `varying vec2 uvPosition;void main(){uvPosition=uv;gl_Position=projectionMatrix*modelViewMatrix*vec4(position,1.);}`,
      fragmentShader: `varying vec2 uvPosition;void main(){vec2 p=uvPosition-.5;float glow=exp(-dot(p,p)*25.)*.045;gl_FragColor=vec4(.75,.42,.16,glow);}`,
    }),
  );
  halo.position.z = -0.3;
  group.add(halo);
  const starGeo = new THREE.BufferGeometry(),
    starPositions = new Float32Array(1600 * 3);
  for (let i = 0; i < 1600; i++)
    starPositions.set(
      [(random() - 0.5) * 17, (random() - 0.5) * 10, -2 - random() * 8],
      i * 3,
    );
  starGeo.setAttribute("position", new THREE.BufferAttribute(starPositions, 3));
  const stars = new THREE.Points(
    starGeo,
    new THREE.PointsMaterial({
      color: 0x6e89aa,
      size: 0.008,
      transparent: true,
      opacity: 0.42,
      depthWrite: false,
    }),
  );
  scene.add(stars);
  function resize() {
    const w = canvas.clientWidth,
      h = canvas.clientHeight;
    if (!w || !h) return;
    renderer.setSize(w, h, false);
    camera.aspect = w / h;
    camera.updateProjectionMatrix();
    composer.setSize(w, h);
  }
  new ResizeObserver(resize).observe(canvas);
  resize();
  let yaw = 0;
  const start = performance.now();
  function tick(now: number) {
    frame = requestAnimationFrame(tick);
    if (document.hidden || lost) return;
    const dt = last ? Math.min((now - last) / 1000, 0.1) : 0.016;
    if (quality < 1 && now - last < 32) return;
    last = now;
    if (!paused) {
      time += dt;
      group.rotation.y = yaw + time * 0.06;
      group.rotation.z = Math.sin(time * 0.12) * 0.065;
      lattice.rotation.y = -time * 0.1;
      stars.rotation.y = time * 0.002;
    }
    uniforms.time.value = time;
    uniforms.intro.value = paused ? 1 : Math.min(1, (now - start) / 1800);
    const target =
      state === "thinking"
        ? 0.7
        : state === "transcribing"
          ? 0.4
          : state === "speaking"
            ? 0.25 + amplitude
            : state === "listening"
              ? amplitude
              : 0;
    uniforms.energy.value += (target - uniforms.energy.value) * 0.09;
    uniforms.level.value = amplitude;
    offset = panel
      ? -Math.tan(THREE.MathUtils.degToRad(camera.fov / 2)) *
        camera.position.length() *
        camera.aspect *
        0.61
      : 0;
    group.position.x += (offset - group.position.x) * 0.07;
    group.position.y += (0.18 - group.position.y) * 0.07;
    const scale = panel ? 0.64 : 0.84;
    group.scale.lerp(new THREE.Vector3(scale, scale, scale), 0.07);
    controls.enabled = !document.body.classList.contains("modal-open");
    if (!paused) controls.update();
    composer.render();
    if (dt > 0.04) slow++;
    else slow = Math.max(0, slow - 1);
    if (slow > 90 && quality === 1) {
      quality = 0.7;
      geometry.setDrawRange(0, 32000);
      renderer.setPixelRatio(1);
      uniforms.pixelRatio.value = 1;
      resize();
      canvas.dataset.quality = "balanced";
    }
  }
  frame = requestAnimationFrame(tick);
  canvas.addEventListener("webglcontextlost", (e) => {
    e.preventDefault();
    lost = true;
    canvas.classList.add("fallback");
  });
  canvas.addEventListener("webglcontextrestored", () => {
    lost = false;
    canvas.classList.remove("fallback");
    resize();
  });
  canvas.addEventListener("keydown", (e) => {
    if (e.key === "Home") controls.reset();
    if (["ArrowLeft", "ArrowRight"].includes(e.key)) {
      e.preventDefault();
      yaw += e.key === "ArrowLeft" ? -0.15 : 0.15;
      group.rotation.y = yaw + time * 0.06;
    }
  });
  reduced.addEventListener("change", () => {
    paused = reduced.matches;
  });
  addEventListener("pagehide", () => {
    cancelAnimationFrame(frame);
    controls.dispose();
    geometry.dispose();
    material.dispose();
    lattice.geometry.dispose();
    lattice.material.dispose();
    halo.geometry.dispose();
    halo.material.dispose();
    starGeo.dispose();
    stars.material.dispose();
    composer.dispose();
    renderer.dispose();
  });
  return {
    setState(s: CoreState) {
      state = s;
      canvas.dataset.state = s;
    },
    setAmplitude(n: number) {
      amplitude = Math.max(0, Math.min(1, n));
    },
    setPanel(open: boolean) {
      panel = open;
    },
    toggle() {
      paused = !paused;
      return paused;
    },
    reset() {
      yaw = 0;
      controls.reset();
    },
    get paused() {
      return paused;
    },
  };
}
