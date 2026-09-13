/*
 * LAYER: Body — procedural holographic JARVIS core.
 * THE BIG PICTURE: circuit traces form a hollow, luminous globe, inspired by
 * the owner's film reference. No media assets, libraries or invented telemetry.
 * THE FLOW: seeded geometry → GPU assembly/rotation → signal and glow passes.
 * One clock owns both sizes; hidden tabs and paused motion do no animation work.
 */
(() => {
  "use strict";
  const TAU = Math.PI * 2;
  const reduced = matchMedia("(prefers-reduced-motion: reduce)");
  const instances = new Map();
  let paused = reduced.matches, busy = false, scroll = 0;
  let frame = 0, last = 0, time = 0;
  const vertex = `
    precision mediump float;
    attribute vec3 position;
    attribute vec4 signal;
    uniform float time, age, aspect, pixelRatio, thinking, scroll, still, pass;
    varying float light;
    const float TAU = 6.28318530718;
    void main() {
      vec3 p = position;
      float built = mix(smoothstep(signal.w*.65, 2.4+signal.w*.65, age), 1., still);
      float spin = time * (.095 + thinking*.12) * signal.z + (1.-built)*1.4;
      p.xz = mat2(cos(spin), -sin(spin), sin(spin), cos(spin))*p.xz;
      float tilt = -.18 + sin(time*.12)*.09 + scroll*.24;
      p.yz = mat2(cos(tilt), -sin(tilt), sin(tilt), cos(tilt))*p.yz;
      p.x += (1.-built)*sign(p.x)*(.65+signal.w*.6);
      p.y *= .65 + .35*built;
      p *= 1. + .009*sin(time*1.2) + thinking*.015;
      float perspective = 3.6/(3.6-p.z*.4);
      gl_Position = vec4(p.x*.80*perspective/aspect, p.y*.80*perspective, 0., 1.);
      float pulse = pow(max(0., sin(signal.x*TAU-time*(1.3+thinking*1.5))), 18.);
      float sweep = pow(max(0., cos(atan(p.z,p.x)-time*.55)), 28.);
      float depth = smoothstep(-1.1, 1.1, p.z);
      light = ((.15+depth*.53)*signal.y + pulse*.44 + sweep*.22) * mix(.04,1.,built);
      gl_PointSize = (pass > 1.5 ? 9. : 1.6+2.*pulse) * pixelRatio * perspective;
    }`;
  const fragment = `
    precision mediump float;
    uniform float pass;
    uniform vec3 gold, hot;
    varying float light;
    void main() {
      float alpha = light;
      if (pass > .5) {
        float d = length(gl_PointCoord-.5)*2.;
        if (d > 1.) discard;
        alpha *= exp(-d*d*(pass > 1.5 ? 4.8 : 2.));
      }
      if (pass > 1.5) alpha *= .19;
      vec3 color = mix(gold,hot,smoothstep(.65,1.4,light));
      gl_FragColor = vec4(color,min(alpha,.9));
    }`;

  function geometry(compact) {
    const lines = [], nodes = [];
    let seed = 1709;
    const random = () => {
      seed = (Math.imul(seed,1664525)+1013904223) >>> 0;
      return seed/4294967296;
    };
    const sphere = (a,b,r) => [Math.cos(a)*Math.cos(b)*r,Math.sin(b)*r,Math.sin(a)*Math.cos(b)*r];
    function trace(points,strength,speed,phase = random()) {
      const sector = random();
      for (let i=1; i<points.length; i++) {
        const s = [phase+i*.012,strength,speed,sector];
        lines.push(...points[i-1],...s,...points[i],...s);
      }
      if (random()>.48) nodes.push(...points[points.length-1],phase,strength,speed,sector);
    }
    // Right-angle routes wrap the sphere; deliberate gaps keep it visibly hollow.
    for (let i=0; i<(compact ? 240 : 1150); i++) {
      let a=random()*TAU, b=Math.asin(random()*1.92-.96);
      const r=.91+random()*.075, points=[sphere(a,b,r)];
      const steps=3+Math.floor(random()*5);
      for (let j=0; j<steps; j++) {
        const length=.022+random()*.14, count=Math.ceil(length/.02);
        const direction=random()>.25 ? 1 : -1;
        for (let k=0; k<count; k++) {
          if (j%2===0) a+=direction*length/count;
          else b=Math.max(-1.43,Math.min(1.43,b+direction*length/count*.55));
          points.push(sphere(a,b,r));
        }
      }
      trace(points,.35+random()*.9,1);
    }
    for (let row=-9; row<=9; row++) {
      for (let section=0; section<6; section++) {
        const a=section*TAU/6+random()*.08, points=[];
        for (let j=0; j<=28; j++) points.push(sphere(a+j*.029,row*.145,1.015));
        trace(points,row%3===0 ? .8 : .32,1);
      }
    }
    for (let rail=0; rail<30; rail++) {
      const points=[];
      for (let j=0; j<=90; j++) points.push(sphere(rail*TAU/30,-1.35+j*.03,1.018));
      trace(points,rail%5===0 ? .85 : .23,1);
    }
    // Counter-rotating inner circuits are 3D geometry rather than flat overlays.
    for (let band=0; band<8; band++) {
      const r=.38+band*.074, tilt=band*.41, points=[];
      for (let j=0; j<=160; j++) {
        const a=j*TAU/160, y=Math.sin(a)*r;
        points.push([Math.cos(a)*r,y*Math.cos(tilt),y*Math.sin(tilt)]);
      }
      trace(points,.5+band*.04,-.6,band*.13);
    }
    for (let i=0; i<(compact ? 80 : 420); i++) {
      const a=random()*TAU, b=Math.asin(random()*2-1), r=.3+random()*.68;
      nodes.push(...sphere(a,b,r),random(),.35+random()*.9,-.6,random());
    }
    return {lines:new Float32Array(lines),nodes:new Float32Array(nodes)};
  }

  function create(canvas) {
    const gl=canvas.getContext("webgl",{alpha:true,antialias:true,depth:false,powerPreference:"low-power"});
    const compact=canvas.dataset.core==="thinking", born=time;
    let program, shaders=[], buffers=[], uniforms, position, signal, lost=false;
    const data=geometry(compact);
    const styles=getComputedStyle(document.documentElement);
    const rgb=name=>styles.getPropertyValue(name).trim().split(/\s+/).map(Number);
    const gold=rgb("--core-gold"), hot=rgb("--core-hot");
    function release() {
      buffers.forEach(b=>gl.deleteBuffer(b));
      shaders.forEach(s=>gl.deleteShader(s));
      if (program) gl.deleteProgram(program);
      buffers=[]; shaders=[]; program=null;
    }
    function initialize() {
      if (!gl) { canvas.classList.add("core-fallback"); return; }
      try {
        program=gl.createProgram();
        for (const [type,source] of [[gl.VERTEX_SHADER,vertex],[gl.FRAGMENT_SHADER,fragment]]) {
          const shader=gl.createShader(type);
          shaders.push(shader); gl.shaderSource(shader,source); gl.compileShader(shader);
          if (!gl.getShaderParameter(shader,gl.COMPILE_STATUS)) throw new Error(gl.getShaderInfoLog(shader) || "Core shader could not compile");
          gl.attachShader(program,shader);
        }
        gl.linkProgram(program);
        if (!gl.getProgramParameter(program,gl.LINK_STATUS)) throw new Error(gl.getProgramInfoLog(program) || "Core shader could not link");
        position=gl.getAttribLocation(program,"position"); signal=gl.getAttribLocation(program,"signal");
        uniforms=Object.fromEntries(["time","age","aspect","pixelRatio","thinking","scroll","still","pass","gold","hot"].map(n=>[n,gl.getUniformLocation(program,n)]));
        for (const vertices of [data.lines,data.nodes]) {
          const buffer=gl.createBuffer(); buffers.push(buffer);
          gl.bindBuffer(gl.ARRAY_BUFFER,buffer); gl.bufferData(gl.ARRAY_BUFFER,vertices,gl.STATIC_DRAW);
        }
        gl.enable(gl.BLEND); gl.blendFunc(gl.SRC_ALPHA,gl.ONE);
        canvas.classList.remove("core-fallback");
      } catch (error) {
        console.warn("JARVIS core: using static fallback.",error.message);
        release(); canvas.classList.add("core-fallback");
      }
    }
    function onLost(event) { event.preventDefault(); lost=true; canvas.classList.add("core-fallback"); }
    function onRestored() { lost=false; buffers=[]; shaders=[]; program=null; initialize(); refresh(); }
    canvas.addEventListener("webglcontextlost",onLost);
    canvas.addEventListener("webglcontextrestored",onRestored);
    initialize();
    return {
      draw() {
        const rect=canvas.getBoundingClientRect();
        if (!program || lost || !rect.width || !rect.height || rect.bottom<0 || rect.top>innerHeight) return;
        const ratio=Math.min(devicePixelRatio||1,2), w=Math.round(rect.width*ratio), h=Math.round(rect.height*ratio);
        if (canvas.width!==w || canvas.height!==h) { canvas.width=w; canvas.height=h; }
        gl.viewport(0,0,w,h); gl.clearColor(0,0,0,0); gl.clear(gl.COLOR_BUFFER_BIT); gl.useProgram(program);
        for (const [name,value] of Object.entries({time,age:compact?10:time-born,aspect:w/h,pixelRatio:ratio,thinking:busy?1:0,scroll,still:paused?1:0})) gl.uniform1f(uniforms[name],value);
        gl.uniform3fv(uniforms.gold,gold); gl.uniform3fv(uniforms.hot,hot);
        const pass=(buffer,vertices,mode,kind)=>{
          gl.bindBuffer(gl.ARRAY_BUFFER,buffer);
          gl.enableVertexAttribArray(position); gl.vertexAttribPointer(position,3,gl.FLOAT,false,28,0);
          gl.enableVertexAttribArray(signal); gl.vertexAttribPointer(signal,4,gl.FLOAT,false,28,12);
          gl.uniform1f(uniforms.pass,kind); gl.drawArrays(mode,0,vertices.length/7);
        };
        pass(buffers[0],data.lines,gl.LINES,0);
        pass(buffers[1],data.nodes,gl.POINTS,2);
        pass(buffers[1],data.nodes,gl.POINTS,1);
      },
      dispose() {
        canvas.removeEventListener("webglcontextlost",onLost);
        canvas.removeEventListener("webglcontextrestored",onRestored);
        if (gl && !lost) {
          release();
          gl.getExtension("WEBGL_lose_context")?.loseContext();
        }
      }
    };
  }
  function draw() { for (const instance of instances.values()) instance.draw(); }
  function tick(now) {
    frame=0;
    if (document.hidden) { last=0; return; }
    if (now-last>=1000/30) { time+=last?Math.min((now-last)/1000,.1):0; last=now; draw(); }
    if (!paused) frame=requestAnimationFrame(tick);
  }
  function refresh() {
    if (document.hidden) { if (frame) cancelAnimationFrame(frame); frame=0; last=0; return; }
    draw();
    if (!paused && !frame) { last=0; frame=requestAnimationFrame(tick); }
  }
  function scan() {
    for (const [canvas,instance] of instances) if (!canvas.isConnected) { instance.dispose(); instances.delete(canvas); }
    document.querySelectorAll("canvas[data-core]").forEach(canvas=>{
      if (!instances.has(canvas)) instances.set(canvas,create(canvas));
    });
    refresh();
  }
  new MutationObserver(scan).observe(document.body,{childList:true,subtree:true});
  new ResizeObserver(refresh).observe(document.body);
  document.addEventListener("visibilitychange",refresh);
  reduced.addEventListener("change",()=>{
    paused=reduced.matches;
    if(frame)cancelAnimationFrame(frame);
    frame=0;refresh();
    document.dispatchEvent(new Event("jarvis:motionchange"));
  });
  window.JarvisCore={
    setBusy(value) { busy=Boolean(value);refresh(); },
    setScroll(value) { scroll=Math.max(0,Math.min(1,value)); },
    togglePause() { paused=!paused;if(frame)cancelAnimationFrame(frame);frame=0;refresh();return paused; },
    get paused() { return paused; }
  };
  scan();
})();
