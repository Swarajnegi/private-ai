/* LAYER: Body. One deterministic 3D hologram, shared by idle, thinking and speech.
 * Layered spherical circuits, radial fibres and moving packets use additive light.
 * A square CSS viewport and aspect-correct projection preserve the globe's shape.
 */
(() => {
 'use strict';
 const TAU=Math.PI*2, instances=new Map(), reduced=matchMedia('(prefers-reduced-motion: reduce)');
 let paused=reduced.matches,busy=false,speaking=false,wordEnergy=0,energy=0,t=0,last=0,raf=0,scroll=0;
 const vertex=`precision mediump float;
 attribute vec3 position; attribute vec4 signal;
 uniform float time,aspect,ratio,energy,pass,scroll;
 varying mediump float light; varying mediump float heat;
 void main(){
  vec3 p=position;
  float turn=time*(.115+energy*.065)*signal.z;
  p.xz=mat2(cos(turn),-sin(turn),sin(turn),cos(turn))*p.xz;
  float tilt=.23+sin(time*.09)*.045+scroll*.08;
  p.yz=mat2(cos(tilt),-sin(tilt),sin(tilt),cos(tilt))*p.yz;
  float lean=-.18;
  p.xy=mat2(cos(lean),-sin(lean),sin(lean),cos(lean))*p.xy;
  p*=1.+sin(time*1.3)*.008+energy*.012;
  float projection=3.5/(3.5-p.z*.32);
  gl_Position=vec4(p.x*.78*projection/aspect,p.y*.78*projection,0.,1.);
  float packet=pow(max(0.,sin(signal.x*6.283-time*(1.6+energy))),24.);
  float depth=smoothstep(-1.1,1.1,p.z);
  float radius=length(position);
  float centre=1.-smoothstep(.05,.46,radius);
  float scan=pow(max(0.,cos(p.y*3.-time*.9)),16.);
  light=signal.y*(.06+depth*.58)+packet*.3+scan*.08+centre*.06;
  light*=1.+energy*.27;
  heat=centre*.8+packet*.3;
  gl_PointSize=(pass>1.5?10.+centre*12.:1.2+signal.w*1.8+packet*1.5)*ratio*projection;
 }`;
 const fragment=`precision mediump float;
 uniform float pass; varying mediump float light; varying mediump float heat;
 void main(){
  float a=light;
  if(pass>.5){float d=length(gl_PointCoord-.5)*2.;if(d>1.)discard;a*=exp(-d*d*(pass>1.5?5.:3.));}
  if(pass>1.5)a*=.09;
  vec3 gold=vec3(1.,.46,.035), hot=vec3(1.,.88,.48);
  gl_FragColor=vec4(mix(gold,hot,clamp(heat+light*.23,0.,1.)),min(a,.88));
 }`;
 let seed=170919; const random=()=>{seed=(Math.imul(seed,1664525)+1013904223)>>>0;return seed/4294967296;};
 const sphere=(a,b,r)=>[Math.cos(a)*Math.cos(b)*r,Math.sin(b)*r,Math.sin(a)*Math.cos(b)*r];
 function geometry(){
  const lines=[],points=[];
  function route(vertices,power=1,speed=1){const phase=random(),spark=random();for(let n=1;n<vertices.length;n++){const s=[phase+n*.017,power,speed,spark];lines.push(...vertices[n-1],...s,...vertices[n],...s);}if(random()>.45)points.push(...vertices.at(-1),phase,power,speed,spark);}
  // Broken arcs form thick, independently turning shells, with open space between.
  for(let shell=0;shell<3;shell++)for(let row=-12;row<=12;row++){
   const b=row*.112,rad=.83+shell*.075;
   for(let segment=0;segment<9;segment++){
    if(random()<.22)continue;
    const a=segment*TAU/9+random()*.12,len=.18+random()*.42,vs=[];
    for(let n=0;n<=22;n++)vs.push(sphere(a+n*len/22,b,rad));
    route(vs,.35+random()*.55,shell===1?-.55:1);
   }
  }
  // Small right-angle branches are actual world-space paths rather than a texture.
  for(let n=0;n<460;n++){
   let a=random()*TAU,b=Math.asin(random()*1.94-.97),r=.81+random()*.18;
   const vs=[sphere(a,b,r)],steps=2+Math.floor(random()*5);
   for(let j=0;j<steps;j++){
    const length=.025+random()*.12,dir=random()>.3?1:-1;
    for(let k=0;k<5;k++){if(j%2===0)a+=dir*length/5;else b=Math.max(-1.45,Math.min(1.45,b+dir*length/8));vs.push(sphere(a,b,r));}
   }
   route(vs,.3+random()*.85,1);
  }
  // Radial bundles converge off-centre as in the supplied film reference.
  for(let n=0;n<110;n++){
   const a=random()*TAU,b=Math.asin(random()*2-1),end=sphere(a,b,.84+random()*.13),vs=[];
   for(let k=0;k<=8;k++){const u=k/8;vs.push([end[0]*u+.035*(1-u),end[1]*u-.035*(1-u),end[2]*u]);}
   route(vs,.14+random()*.31,1);
  }
  for(let band=0;band<16;band++){
   const r=.22+random()*.68,tilt=random()*TAU,a=random()*TAU,vs=[];
   for(let j=0;j<110;j++){const x=a+j*TAU/130,y=Math.sin(x)*r;vs.push([Math.cos(x)*r,y*Math.cos(tilt),y*Math.sin(tilt)]);}
   route(vs,.25+random()*.65,-.65);
  }
  for(let n=0;n<1600;n++){
   const a=random()*TAU,b=Math.asin(random()*2-1),r=n<80?Math.pow(random(),2)*.3:.65+random()*.35;
   points.push(...sphere(a,b,r),random(),.18+random()*.9,n<80?-.65:1,random());
  }
  return {lines:new Float32Array(lines),points:new Float32Array(points)};
 }
 const geo=geometry();
 function create(canvas){
  const gl=canvas.getContext('webgl',{alpha:true,antialias:true,depth:false,powerPreference:'low-power'});
  if(!gl){canvas.classList.add('core-fallback');return{draw(){},dispose(){}};}
  let program,buffers=[],shaders=[],uniforms={},position,signal,lost=false;
  function init(){
   program=gl.createProgram();
   try{
    for(const[type,src]of[[gl.VERTEX_SHADER,vertex],[gl.FRAGMENT_SHADER,fragment]]){const s=gl.createShader(type);shaders.push(s);gl.shaderSource(s,src);gl.compileShader(s);if(!gl.getShaderParameter(s,gl.COMPILE_STATUS))throw Error(gl.getShaderInfoLog(s));gl.attachShader(program,s);}
    gl.linkProgram(program);if(!gl.getProgramParameter(program,gl.LINK_STATUS))throw Error(gl.getProgramInfoLog(program));
    position=gl.getAttribLocation(program,'position');signal=gl.getAttribLocation(program,'signal');
    for(const n of ['time','aspect','ratio','energy','pass','scroll'])uniforms[n]=gl.getUniformLocation(program,n);
    for(const data of[geo.lines,geo.points]){const b=gl.createBuffer();buffers.push(b);gl.bindBuffer(gl.ARRAY_BUFFER,b);gl.bufferData(gl.ARRAY_BUFFER,data,gl.STATIC_DRAW);}
    gl.enable(gl.BLEND);gl.blendFunc(gl.SRC_ALPHA,gl.ONE);canvas.classList.remove('core-fallback');
   }catch(e){console.error('Hologram renderer:',e.message);canvas.classList.add('core-fallback');program=null;}
  }
  const lose=e=>{e.preventDefault();lost=true;canvas.classList.add('core-fallback');},restore=()=>{lost=false;buffers=[];shaders=[];init();refresh();};
  canvas.addEventListener('webglcontextlost',lose);canvas.addEventListener('webglcontextrestored',restore);init();
  return{draw(){
   const rect=canvas.getBoundingClientRect();if(!program||lost||!rect.width||!rect.height||rect.bottom<0||rect.top>innerHeight||canvas.closest('[hidden]'))return;
   const ratio=Math.min(devicePixelRatio||1,2),w=Math.round(rect.width*ratio),h=Math.round(rect.height*ratio);
   if(canvas.width!==w||canvas.height!==h){canvas.width=w;canvas.height=h;}
   gl.viewport(0,0,w,h);gl.clearColor(0,0,0,0);gl.clear(gl.COLOR_BUFFER_BIT);gl.useProgram(program);
   for(const[n,v]of Object.entries({time:t,aspect:w/h,ratio,energy,scroll}))gl.uniform1f(uniforms[n],v);
   const draw=(b,data,mode,pass)=>{gl.bindBuffer(gl.ARRAY_BUFFER,b);gl.enableVertexAttribArray(position);gl.vertexAttribPointer(position,3,gl.FLOAT,false,28,0);gl.enableVertexAttribArray(signal);gl.vertexAttribPointer(signal,4,gl.FLOAT,false,28,12);gl.uniform1f(uniforms.pass,pass);gl.drawArrays(mode,0,data.length/7);};
   draw(buffers[0],geo.lines,gl.LINES,0);draw(buffers[1],geo.points,gl.POINTS,2);draw(buffers[1],geo.points,gl.POINTS,1);
  },dispose(){canvas.removeEventListener('webglcontextlost',lose);canvas.removeEventListener('webglcontextrestored',restore);if(!lost){buffers.forEach(b=>gl.deleteBuffer(b));shaders.forEach(s=>gl.deleteShader(s));if(program)gl.deleteProgram(program);gl.getExtension('WEBGL_lose_context')?.loseContext();}}};
 }
 function draw(){for(const instance of instances.values())instance.draw();}
 function tick(now){raf=0;if(document.hidden){last=0;return;}if(now-last>=1000/30){const dt=last?Math.min((now-last)/1000,.1):0;t+=dt;last=now;wordEnergy*=.88;const target=speaking?.6+wordEnergy:busy?.65:0;energy+=(target-energy)*.12;draw();}if(!paused)raf=requestAnimationFrame(tick);}
 function refresh(){document.body.dataset.motionPaused=String(paused);if(document.hidden){cancelAnimationFrame(raf);raf=0;last=0;return;}draw();if(!paused&&!raf){last=0;raf=requestAnimationFrame(tick);}}
 let queued=false;function scan(){queued=false;for(const[c,i]of instances)if(!c.isConnected){i.dispose();instances.delete(c);}document.querySelectorAll('canvas[data-core]').forEach(c=>{if(!instances.has(c))instances.set(c,create(c));});refresh();}
 new MutationObserver(()=>{if(!queued){queued=true;queueMicrotask(scan);}}).observe(document.body,{childList:true,subtree:true});
 new ResizeObserver(refresh).observe(document.body);document.addEventListener('visibilitychange',refresh);
 reduced.addEventListener('change',()=>{paused=reduced.matches;cancelAnimationFrame(raf);raf=0;refresh();document.dispatchEvent(new Event('jarvis:motionchange'));});
 window.JarvisCore={setBusy(v){busy=Boolean(v);refresh();},setSpeaking(v){speaking=Boolean(v);refresh();},word(){wordEnergy=1;},setScroll(v){scroll=Math.max(0,Math.min(1,v));},togglePause(){paused=!paused;cancelAnimationFrame(raf);raf=0;refresh();return paused;},get paused(){return paused;}};
 scan();
})();
