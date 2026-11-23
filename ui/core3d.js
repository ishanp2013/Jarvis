// The 3D Jarvis core: a holographic arc-reactor built with Three.js (bundled in ui/vendor, works offline).
// It reads the page's live state through window.orbState() -> {state, level, voiceLevel, gameMode} and reacts:
// pulses with your voice and Jarvis's, spins faster while thinking, tilts toward the mouse, and stops drawing
// when hidden or in game mode. On machines without WebGL the 2D orb (orb.js) is used instead.
import * as THREE from "./vendor/three.module.min.js";

const TINT = {
  idle: [1.0, 0.69, 0.25], listening: [0.45, 0.85, 1.0], transcribing: [0.6, 0.8, 1.0],
  thinking: [1.0, 0.55, 0.15], speaking: [1.0, 0.75, 0.32], starting: [0.8, 0.5, 0.2],
};

function glowTexture() {  // a soft round light, drawn once
  const c = document.createElement("canvas"); c.width = c.height = 128;
  const g = c.getContext("2d"), r = g.createRadialGradient(64, 64, 0, 64, 64, 64);
  r.addColorStop(0, "rgba(255,255,255,1)"); r.addColorStop(0.25, "rgba(255,255,255,.55)");
  r.addColorStop(0.6, "rgba(255,255,255,.12)"); r.addColorStop(1, "rgba(255,255,255,0)");
  g.fillStyle = r; g.fillRect(0, 0, 128, 128);
  const t = new THREE.CanvasTexture(c); t.colorSpace = THREE.SRGBColorSpace; return t;
}

export function startCore3D(host) {
  const probe = document.createElement("canvas");
  if (!(probe.getContext("webgl2") || probe.getContext("webgl"))) return null;

  const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true, powerPreference: "low-power" });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 1.5));
  renderer.setClearColor(0x000000, 0);
  host.appendChild(renderer.domElement);
  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(38, 1, 0.1, 100);
  camera.position.set(0, 0, 14.5);  // far enough that the outer rings never touch the edge of the drawing area
  const root = new THREE.Group(); scene.add(root);
  const add = (o) => (root.add(o), o);
  const glow = glowTexture();
  const color = new THREE.Color(1, 0.69, 0.25);
  const additive = (opts) => ({ transparent: true, depthWrite: false, blending: THREE.AdditiveBlending, ...opts });

  // core: a fresnel-lit sphere (bright edges, see-through middle) around a hot white centre
  const coreMat = new THREE.ShaderMaterial(additive({
    uniforms: { uColor: { value: color }, uPulse: { value: 0 }, uTime: { value: 0 } },
    vertexShader: `varying vec3 vN; varying vec3 vV; uniform float uPulse; uniform float uTime;
      void main(){ vec3 p = position * (1.0 + uPulse*0.08 + sin(uTime*2.0 + position.y*4.0)*0.012);
        vec4 mv = modelViewMatrix * vec4(p,1.0); vN = normalize(normalMatrix*normal); vV = normalize(-mv.xyz);
        gl_Position = projectionMatrix * mv; }`,
    fragmentShader: `varying vec3 vN; varying vec3 vV; uniform vec3 uColor; uniform float uPulse;
      void main(){ float f = pow(1.0 - max(dot(vN, vV), 0.0), 2.2);
        gl_FragColor = vec4(uColor * (0.25 + f*1.6 + uPulse*0.6), f*0.95 + 0.06); }`,
  }));
  const core = add(new THREE.Mesh(new THREE.IcosahedronGeometry(1.05, 5), coreMat));
  const heart = add(new THREE.Sprite(new THREE.SpriteMaterial(additive({ map: glow, color: 0xffffff }))));
  heart.scale.set(2.6, 2.6, 1);
  const halo = add(new THREE.Sprite(new THREE.SpriteMaterial(additive({ map: glow, color, opacity: 0.35 }))));
  halo.scale.set(9, 9, 1);

  // wireframe shell
  const shell = add(new THREE.LineSegments(new THREE.WireframeGeometry(new THREE.IcosahedronGeometry(1.55, 1)),
    new THREE.LineBasicMaterial(additive({ color, opacity: 0.22 }))));

  // particle sphere
  const N = 1400, pos = new Float32Array(N * 3), base = new Float32Array(N * 3);
  for (let i = 0; i < N; i++) {
    const u = Math.random() * 2 - 1, th = Math.random() * Math.PI * 2, r = 1.9 + Math.random() * 0.5, s = Math.sqrt(1 - u * u);
    base.set([r * s * Math.cos(th), r * u, r * s * Math.sin(th)], i * 3);
  }
  pos.set(base);
  const pGeo = new THREE.BufferGeometry(); pGeo.setAttribute("position", new THREE.BufferAttribute(pos, 3));
  const points = add(new THREE.Points(pGeo, new THREE.PointsMaterial(additive({ map: glow, color, size: 0.07, opacity: 0.85 }))));

  // rings: solid tilted rings, a dashed ring and a tick ring, each turning its own way
  const rings = [];
  const ring = (radius, tube, tilt, speed, opacity) => {
    const m = add(new THREE.Mesh(new THREE.TorusGeometry(radius, tube, 8, 180), new THREE.MeshBasicMaterial(additive({ color, opacity }))));
    m.rotation.set(tilt[0], tilt[1], 0); rings.push({ m, speed }); return m;
  };
  ring(2.75, 0.012, [1.25, 0.2], 0.25, 0.9);
  ring(3.05, 0.008, [-1.1, 0.5], -0.18, 0.6);
  ring(3.45, 0.018, [Math.PI / 2, 0], 0.08, 0.5);
  const arcs = add(new THREE.Group());
  for (let k = 0; k < 6; k++) {  // broken arc segments
    const a = new THREE.Mesh(new THREE.TorusGeometry(3.9, 0.03, 6, 40, 0.5 + Math.random() * 0.6),
      new THREE.MeshBasicMaterial(additive({ color, opacity: 0.75 })));
    a.rotation.z = (k / 6) * Math.PI * 2; arcs.add(a);
  }
  const ticks = add(new THREE.Group());
  for (let k = 0; k < 120; k++) {
    const big = k % 10 === 0, t = new THREE.Mesh(new THREE.PlaneGeometry(big ? 0.28 : 0.12, big ? 0.03 : 0.015),
      new THREE.MeshBasicMaterial(additive({ color, opacity: big ? 0.9 : 0.4, side: THREE.DoubleSide })));
    const ang = (k / 120) * Math.PI * 2; t.position.set(Math.cos(ang) * 4.35, Math.sin(ang) * 4.35, 0); t.rotation.z = ang; ticks.add(t);
  }

  // orbiting sparks
  const sparks = [];
  for (let k = 0; k < 10; k++) {
    const s = add(new THREE.Sprite(new THREE.SpriteMaterial(additive({ map: glow, color, opacity: 0.9 }))));
    s.scale.set(0.22, 0.22, 1);
    sparks.push({ s, r: 2.4 + Math.random() * 1.6, sp: (Math.random() * 0.6 + 0.3) * (k % 2 ? 1 : -1),
      ph: Math.random() * 6.28, tilt: Math.random() * 1.2 - 0.6 });
  }

  // sizing, mouse parallax
  const resize = () => {
    const w = host.clientWidth || 1, h = host.clientHeight || 1;
    renderer.setSize(w, h, false); camera.aspect = w / h; camera.updateProjectionMatrix();
  };
  new ResizeObserver(resize).observe(host); resize();
  let mx = 0, my = 0;
  window.addEventListener("pointermove", (e) => { mx = e.clientX / innerWidth - 0.5; my = e.clientY / innerHeight - 0.5; });

  let t = 0, last = 0, amp = 0, spin = 1;
  const reduced = matchMedia("(prefers-reduced-motion: reduce)").matches;
  function frame(now) {
    requestAnimationFrame(frame);
    const st = window.orbState ? window.orbState() : { state: "idle", level: 0, voiceLevel: 0 };
    if (document.hidden || st.gameMode) return;  // no drawing, no CPU
    const busy = st.state !== "idle";
    if (now - last < (busy ? 16 : 33)) return;  // ~30 fps idle keeps the laptop cool
    const dt = Math.min(0.05, (now - last) / 1000 || 0.016); last = now; t += reduced ? dt * 0.3 : dt;
    const target = st.state === "speaking" ? 0.25 + st.voiceLevel * 1.8 : st.state === "listening" ? 0.15 + st.level * 3
      : st.state === "thinking" || st.state === "transcribing" ? 0.35 + 0.15 * Math.sin(t * 6) : 0.06 + 0.03 * Math.sin(t * 1.5);
    amp += (Math.min(1.5, target) - amp) * (target > amp ? 0.4 : 0.1);
    spin += ((st.state === "thinking" ? 3.2 : 1 + amp) - spin) * 0.05;
    const c = TINT[st.state] || TINT.idle;
    color.lerp(new THREE.Color(c[0], c[1], c[2]), 0.08);

    coreMat.uniforms.uPulse.value = amp; coreMat.uniforms.uTime.value = t;
    core.rotation.y += dt * 0.3 * spin;
    heart.scale.setScalar(2.2 + amp * 1.8); heart.material.opacity = 0.8 + amp * 0.2;
    halo.scale.setScalar(8 + amp * 3); halo.material.opacity = 0.22 + amp * 0.25;
    shell.rotation.y -= dt * 0.15 * spin; shell.rotation.x += dt * 0.05 * spin;
    shell.scale.setScalar(1 + amp * 0.12);
    for (const r of rings) r.m.rotation.z += dt * r.speed * spin;
    arcs.rotation.z -= dt * 0.12 * spin; ticks.rotation.z += dt * 0.05 * spin;
    // particles breathe outward with the voice
    const k = 1 + amp * 0.25;
    for (let i = 0; i < N; i++) {
      const j = i * 3, w = 1 + Math.sin(t * 2 + i) * 0.015 * (1 + amp * 4);
      pos[j] = base[j] * k * w; pos[j + 1] = base[j + 1] * k * w; pos[j + 2] = base[j + 2] * k * w;
    }
    pGeo.attributes.position.needsUpdate = true;
    points.rotation.y += dt * 0.08 * spin;
    points.material.size = 0.06 + amp * 0.05;
    for (const s of sparks) {
      const a = s.ph + t * s.sp * spin;
      s.s.position.set(Math.cos(a) * s.r, Math.sin(a) * s.r * Math.sin(s.tilt) , Math.sin(a) * s.r * Math.cos(s.tilt));
    }
    root.rotation.y += ((mx * 0.6) - root.rotation.y) * 0.05;
    root.rotation.x += ((my * 0.4) - root.rotation.x) * 0.05;
    renderer.render(scene, camera);
  }
  requestAnimationFrame(frame);
  return { renderer };
}
