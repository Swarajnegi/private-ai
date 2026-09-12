/* Original procedural particle core. No images, external renderer, or network requests. */
(() => {
  "use strict";
  const reduced = matchMedia("(prefers-reduced-motion: reduce)");
  const instances = new Map();
  let paused = reduced.matches, busy = false, scroll = 0, frame = 0, last = 0, time = 0;
  const vertex = `
    attribute vec4 seed;
    uniform float time, morph, aspect, pixelRatio, thinking;
    varying float alpha;
    const float PI = 3.14159265;
    void main() {
      float angle = seed.x * PI * 2.;
      float y = seed.y * 2. - 1.;
      float ring = sqrt(max(0., 1. - y*y));
      float radius = pow(seed.z, .48);
      vec3 sphere = vec3(cos(angle)*ring, y, sin(angle)*ring) * radius;
      float tube = seed.y * PI * 2.;
      vec3 orbit = vec3((.71 + .26*cos(tube)*radius)*cos(angle), .26*sin(tube)*radius, (.71 + .26*cos(tube)*radius)*sin(angle));
      float spiral = angle + seed.z*5.;
      vec3 cloud = vec3(cos(spiral)*radius, y*.24*radius, sin(spiral)*radius) * 1.12;
      vec3 p = mix(sphere, orbit, smoothstep(0., 1., morph));
      p = mix(p, cloud, smoothstep(1., 2., morph));
      float spin = time * (.08 + thinking*.065);
      p.xz = mat2(cos(spin), -sin(spin), sin(spin), cos(spin)) * p.xz;
      float tilt = .4 + morph*.19;
      p.yz = mat2(cos(tilt), -sin(tilt), sin(tilt), cos(tilt)) * p.yz;
      p *= .93 + .035*sin(time*1.05);
      p += .009*sin(time*.65 + seed.w*25.) * normalize(p);
      float depth = 2.7 / (2.7 - p.z*.4);
      gl_Position = vec4(p.x * .92 * depth / aspect, p.y * .92 * depth, 0., 1.);
      gl_PointSize = (1.3 + seed.w*1.6 + thinking*.35) * pixelRatio * depth;
      alpha = (.24 + .5*seed.w) * (.66 + .34*(p.z+1.)*.5);
    }`;
  const fragment = `
    precision mediump float;
    varying float alpha;
    void main() {
      float d = length(gl_PointCoord - .5)*2.;
      if (d > 1.) discard;
      float light = exp(-d*d*3.5);
      gl_FragColor = vec4(.2, .62, 1., light*alpha*1.75);
    }`;

  function create(canvas) {
    const gl = canvas.getContext("webgl", {alpha:true, antialias:false, depth:false, powerPreference:"low-power"});
    if (!gl) {
      canvas.classList.add("core-fallback");
      return {draw() {}, dispose() {}};
    }
    const shader = (type, source) => {
      const result = gl.createShader(type);
      gl.shaderSource(result, source); gl.compileShader(result);
      if (!gl.getShaderParameter(result, gl.COMPILE_STATUS)) { gl.deleteShader(result); throw new Error("Core shader unavailable"); }
      return result;
    };
    const program = gl.createProgram();
    const shaders = [shader(gl.VERTEX_SHADER, vertex), shader(gl.FRAGMENT_SHADER, fragment)];
    shaders.forEach(s => gl.attachShader(program, s)); gl.linkProgram(program);
    if (!gl.getProgramParameter(program, gl.LINK_STATUS)) throw new Error("Core renderer unavailable");
    gl.useProgram(program);
    const compact = canvas.dataset.core === "thinking";
    const count = compact ? 1200 : 8500;
    const points = new Float32Array(count*4);
    // Fixed seed means a stable identity across viewport changes and sessions.
    let random = 1709;
    for (let i=0; i<points.length; i++) { random = (Math.imul(random,1664525)+1013904223)>>>0; points[i] = random/4294967296; }
    const buffer = gl.createBuffer(); gl.bindBuffer(gl.ARRAY_BUFFER, buffer); gl.bufferData(gl.ARRAY_BUFFER, points, gl.STATIC_DRAW);
    const attribute = gl.getAttribLocation(program,"seed");
    gl.enableVertexAttribArray(attribute); gl.vertexAttribPointer(attribute,4,gl.FLOAT,false,0,0);
    const uniforms = Object.fromEntries(["time","morph","aspect","pixelRatio","thinking"].map(name=>[name,gl.getUniformLocation(program,name)]));
    gl.enable(gl.BLEND); gl.blendFunc(gl.SRC_ALPHA,gl.ONE);
    let currentMorph = 0;
    return {
      draw() {
        const rect = canvas.getBoundingClientRect();
        if (!rect.width || !rect.height || rect.bottom < 0 || rect.top > innerHeight) return;
        const ratio = Math.min(devicePixelRatio||1,2);
        const w = Math.round(rect.width*ratio), h = Math.round(rect.height*ratio);
        if (canvas.width !== w || canvas.height !== h) { canvas.width=w; canvas.height=h; gl.viewport(0,0,w,h); }
        gl.clearColor(0,0,0,0); gl.clear(gl.COLOR_BUFFER_BIT);
        const cycle = (1-Math.cos(time*.14))*.92;
        const target = paused ? 0 : Math.min(2, compact || busy ? .7 : Math.max(cycle,scroll*2));
        currentMorph += (target-currentMorph)*.025;
        if (paused) currentMorph=0;
        gl.uniform1f(uniforms.time,time); gl.uniform1f(uniforms.morph,currentMorph);
        gl.uniform1f(uniforms.aspect,w/h); gl.uniform1f(uniforms.pixelRatio,ratio);
        gl.uniform1f(uniforms.thinking,busy ? 1 : 0);
        gl.drawArrays(gl.POINTS,0,count);
      },
      dispose() { gl.deleteBuffer(buffer); shaders.forEach(s=>gl.deleteShader(s)); gl.deleteProgram(program); gl.getExtension("WEBGL_lose_context")?.loseContext(); }
    };
  }
  function draw() { for (const instance of instances.values()) instance.draw(); }
  function tick(now) {
    frame=0;
    if (document.hidden) { last=0; return; }
    if (now-last>=1000/30) { time += last ? Math.min((now-last)/1000,.1) : 0; last=now; draw(); }
    if (!paused) frame=requestAnimationFrame(tick);
  }
  function refresh() { draw(); if (!paused && !document.hidden && !frame) frame=requestAnimationFrame(tick); }
  function scan() {
    for (const [canvas,instance] of instances) if (!canvas.isConnected) { instance.dispose(); instances.delete(canvas); }
    document.querySelectorAll("canvas[data-core]").forEach(canvas=>{
      if (instances.has(canvas)) return;
      try { instances.set(canvas,create(canvas)); }
      catch { canvas.classList.add("core-fallback"); instances.set(canvas,{draw(){},dispose(){}}); }
    });
    refresh();
  }
  const observer = new MutationObserver(scan);
  observer.observe(document.body,{childList:true,subtree:true});
  const resize = new ResizeObserver(refresh); resize.observe(document.body);
  document.addEventListener("visibilitychange",refresh);
  reduced.addEventListener("change",()=>{paused=reduced.matches; refresh();});
  window.JarvisCore = {
    setBusy(value) { busy=Boolean(value); refresh(); },
    setScroll(value) { scroll=Math.max(0,Math.min(1,value)); },
    togglePause() { paused=!paused; if (paused && frame) {cancelAnimationFrame(frame); frame=0;} refresh(); return paused; },
    get paused() { return paused; }
  };
  scan();
})();
