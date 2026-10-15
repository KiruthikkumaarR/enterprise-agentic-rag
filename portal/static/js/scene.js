// 3D scenes: the background globe (company sites network) and the document "knowledge galaxy".
import * as THREE from "/static/vendor/three.module.min.js";

const SITES = [
  ["Tampere Works", 61.50, 23.79, true], ["Gdansk Assembly", 54.35, 18.65], ["Porto Foundry", 41.15, -8.61], ["Brno Machining", 49.19, 16.61],
  ["Lyon Systems", 45.76, 4.84], ["Bilbao Plant", 43.26, -2.93], ["Graz Electronics", 47.07, 15.44], ["Aarhus Service Centre", 56.16, 10.20],
];
const reduced = matchMedia("(prefers-reduced-motion: reduce)").matches;

function latLon(lat, lon, r) {
  const phi = (90 - lat) * Math.PI / 180, th = (lon + 180) * Math.PI / 180;
  return new THREE.Vector3(-r * Math.sin(phi) * Math.cos(th), r * Math.cos(phi), r * Math.sin(phi) * Math.sin(th));
}

function glowTexture(color = "#ffffff") {
  const c = document.createElement("canvas"); c.width = c.height = 64;
  const g = c.getContext("2d"), grad = g.createRadialGradient(32, 32, 0, 32, 32, 32);
  grad.addColorStop(0, color); grad.addColorStop(.25, color); grad.addColorStop(1, "rgba(0,0,0,0)");
  g.fillStyle = grad; g.fillRect(0, 0, 64, 64);
  return new THREE.CanvasTexture(c);
}

// ---------------------------------------------------------------------------- background globe
export function createBackground(canvas) {
  const renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true });
  renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(42, 1, 0.1, 100);
  camera.position.set(0, 0, 7.4);
  const world = new THREE.Group();
  scene.add(world);
  const R = 1.85;

  // dotted sphere (fibonacci lattice)
  const N = 5200, pos = new Float32Array(N * 3), col = new Float32Array(N * 3);
  const c1 = new THREE.Color("#5b8cff"), c2 = new THREE.Color("#3fd6c4");
  for (let i = 0; i < N; i++) {
    const y = 1 - (i / (N - 1)) * 2, rr = Math.sqrt(1 - y * y), th = i * 2.399963;
    pos.set([Math.cos(th) * rr * R, y * R, Math.sin(th) * rr * R], i * 3);
    const c = c1.clone().lerp(c2, (y + 1) / 2);
    col.set([c.r, c.g, c.b], i * 3);
  }
  const dotsGeo = new THREE.BufferGeometry();
  dotsGeo.setAttribute("position", new THREE.BufferAttribute(pos, 3));
  dotsGeo.setAttribute("color", new THREE.BufferAttribute(col, 3));
  world.add(new THREE.Points(dotsGeo, new THREE.PointsMaterial({ size: 0.022, vertexColors: true, transparent: true, opacity: 0.55, depthWrite: false })));

  // inner occluder + atmosphere
  world.add(new THREE.Mesh(new THREE.SphereGeometry(R * 0.985, 48, 48), new THREE.MeshBasicMaterial({ color: "#070c18" })));
  const atm = new THREE.Sprite(new THREE.SpriteMaterial({ map: glowTexture("rgba(63,214,196,0.55)"), transparent: true, depthWrite: false, blending: THREE.AdditiveBlending }));
  atm.scale.set(R * 3.3, R * 3.3, 1); scene.add(atm);

  // latitude rings
  for (const lat of [-45, 0, 45]) {
    const r = R * Math.cos(lat * Math.PI / 180) * 1.003, pts = [];
    for (let i = 0; i <= 128; i++) { const a = i / 128 * Math.PI * 2; pts.push(new THREE.Vector3(Math.cos(a) * r, R * Math.sin(lat * Math.PI / 180), Math.sin(a) * r)); }
    world.add(new THREE.Line(new THREE.BufferGeometry().setFromPoints(pts), new THREE.LineBasicMaterial({ color: "#2a3f6e", transparent: true, opacity: 0.35 })));
  }

  // sites, pulses and arcs from HQ
  const markerTex = glowTexture("rgba(120,255,235,1)");
  const hq = latLon(SITES[0][1], SITES[0][2], R);
  const packets = [], pulses = [];
  for (const [name, lat, lon, isHq] of SITES) {
    const p = latLon(lat, lon, R * 1.01);
    const s = new THREE.Sprite(new THREE.SpriteMaterial({ map: markerTex, transparent: true, depthWrite: false, blending: THREE.AdditiveBlending }));
    s.position.copy(p); s.scale.setScalar(isHq ? 0.24 : 0.14); world.add(s);
    const ring = new THREE.Mesh(new THREE.RingGeometry(0.028, 0.034, 40), new THREE.MeshBasicMaterial({ color: "#3fd6c4", transparent: true, side: THREE.DoubleSide, depthWrite: false }));
    ring.position.copy(p); ring.lookAt(p.clone().multiplyScalar(2)); world.add(ring); pulses.push({ ring, t: Math.random() });
    if (isHq) continue;
    const mid = hq.clone().add(p).multiplyScalar(0.5);
    mid.setLength(R + hq.distanceTo(p) * 0.45);
    const curve = new THREE.QuadraticBezierCurve3(hq.clone().setLength(R * 1.01), mid, p);
    world.add(new THREE.Line(new THREE.BufferGeometry().setFromPoints(curve.getPoints(64)),
      new THREE.LineBasicMaterial({ color: "#5b8cff", transparent: true, opacity: 0.45, blending: THREE.AdditiveBlending })));
    const pk = new THREE.Sprite(new THREE.SpriteMaterial({ map: markerTex, transparent: true, depthWrite: false, blending: THREE.AdditiveBlending, color: "#9ec0ff" }));
    pk.scale.setScalar(0.08); world.add(pk); packets.push({ pk, curve, t: Math.random(), speed: 0.12 + Math.random() * 0.1 });
  }

  // starfield
  const S = 1400, sp = new Float32Array(S * 3);
  for (let i = 0; i < S; i++) { const v = new THREE.Vector3().randomDirection().multiplyScalar(14 + Math.random() * 26); sp.set([v.x, v.y, v.z], i * 3); }
  const starGeo = new THREE.BufferGeometry(); starGeo.setAttribute("position", new THREE.BufferAttribute(sp, 3));
  const stars = new THREE.Points(starGeo, new THREE.PointsMaterial({ size: 0.06, color: "#8fa6d8", transparent: true, opacity: 0.7, depthWrite: false }));
  scene.add(stars);

  world.rotation.set(0.62, -1.83, 0.08);    // Europe towards the camera
  let mode = "login", target = { x: 0, y: 0 }, mouse = { x: 0, y: 0 }, intro = 0, running = true;
  addEventListener("pointermove", e => { target.x = (e.clientX / innerWidth - .5); target.y = (e.clientY / innerHeight - .5); });

  function resize() {
    const w = innerWidth, h = innerHeight;
    renderer.setSize(w, h, false); camera.aspect = w / h; camera.updateProjectionMatrix();
    layout();
  }
  function layout() {   // globe on the left at login, small and dim behind the app
    const wide = innerWidth > 980;
    const goal = mode === "login" ? (wide ? new THREE.Vector3(-1.45, -1.05, 0) : new THREE.Vector3(0, -1.2, -1)) : new THREE.Vector3(2.9, -1.4, -3.5);
    world.userData.goal = goal; atm.userData.goal = goal;
    if (!world.userData.placed) { world.position.copy(goal); world.userData.placed = true; }   // no slide on first paint
  }
  addEventListener("resize", resize); resize();

  const clock = new THREE.Clock();
  function tick() {
    if (!running) return;
    const dt = Math.min(clock.getDelta(), 0.05), t = clock.elapsedTime;
    intro = Math.min(1, intro + dt * 0.6);
    mouse.x += (target.x - mouse.x) * 0.04; mouse.y += (target.y - mouse.y) * 0.04;
    if (!reduced) world.rotation.y += dt * 0.045;
    world.position.lerp(world.userData.goal, 0.035); atm.position.copy(world.position);
    const s = 0.6 + 0.4 * (1 - Math.pow(1 - intro, 3)); world.scale.setScalar(s); atm.scale.setScalar(R * 3.3 * s);
    camera.position.x = mouse.x * 0.6; camera.position.y = -mouse.y * 0.4; camera.lookAt(0, 0, 0);
    stars.rotation.y = t * 0.004;
    for (const p of packets) { p.t = (p.t + dt * p.speed) % 1; p.pk.position.copy(p.curve.getPoint(p.t)); p.pk.material.opacity = Math.sin(p.t * Math.PI); }
    for (const p of pulses) { p.t = (p.t + dt * 0.5) % 1; p.ring.scale.setScalar(1 + p.t * 2.2); p.ring.material.opacity = (1 - p.t) * 0.7; }
    renderer.render(scene, camera);
    requestAnimationFrame(tick);
  }
  tick();
  return {
    setMode(m) { mode = m; layout(); canvas.style.transition = "opacity .8s"; canvas.style.opacity = m === "login" ? 1 : 0.45; },
    pause() { running = false; }, resume() { if (!running) { running = true; clock.getDelta(); tick(); } },
  };
}

// ---------------------------------------------------------------------------- knowledge galaxy
export const DEPT_COLORS = {
  "Executive Office": "#f5c76a", "Finance": "#3fd6c4", "Human Resources": "#ff8fb1", "Engineering": "#5b8cff", "Operations": "#ffa45b",
  "Sales": "#3fcf8e", "Marketing": "#c49bff", "Legal & Compliance": "#ff6b7d", "IT": "#64d2ff", "Quality": "#d4f06b", "Procurement": "#9fb3d9",
};

export function createGalaxy(canvas, docs, { onHover, onClick }) {
  const renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true });
  renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(50, 1, 0.1, 200);
  let dist = 26, rotX = 0.45, rotY = 0, vx = 0, vy = 0.0025;
  const root = new THREE.Group(); scene.add(root);
  const tex = glowTexture("rgba(255,255,255,1)");
  const depts = [...new Set(docs.flatMap(d => d.departments.slice(0, 1)))];
  const centers = {};
  depts.forEach((d, i) => {
    const a = i / depts.length * Math.PI * 2;
    centers[d] = new THREE.Vector3(Math.cos(a) * 10, Math.sin(i * 1.7) * 2.2, Math.sin(a) * 10);
    const halo = new THREE.Sprite(new THREE.SpriteMaterial({ map: tex, color: DEPT_COLORS[d] || "#fff", transparent: true, opacity: 0.16, depthWrite: false, blending: THREE.AdditiveBlending }));
    halo.position.copy(centers[d]); halo.scale.setScalar(7); root.add(halo);
    const label = makeLabel(d, DEPT_COLORS[d]); label.position.copy(centers[d]).add(new THREE.Vector3(0, 3.1, 0)); root.add(label);
  });
  // core
  const core = new THREE.Sprite(new THREE.SpriteMaterial({ map: tex, color: "#3fd6c4", transparent: true, opacity: 0.9, depthWrite: false, blending: THREE.AdditiveBlending }));
  core.scale.setScalar(3.2); root.add(core);
  const nodes = [];
  docs.forEach((d, i) => {
    const dept = d.departments[0], c = centers[dept] || new THREE.Vector3();
    const r = 1.2 + Math.random() * 2.4, a = Math.random() * Math.PI * 2, b = (Math.random() - .5) * Math.PI;
    const p = c.clone().add(new THREE.Vector3(Math.cos(a) * Math.cos(b) * r, Math.sin(b) * r * .8, Math.sin(a) * Math.cos(b) * r));
    const size = 0.55 + Math.min(1.6, Math.log10((d.chunks || 1) + 1) * 0.55);
    const m = new THREE.Sprite(new THREE.SpriteMaterial({ map: tex, color: DEPT_COLORS[dept] || "#fff", transparent: true, depthWrite: false, blending: THREE.AdditiveBlending }));
    m.position.copy(p); m.scale.setScalar(size); m.userData = { doc: d, base: size, phase: Math.random() * 6 }; root.add(m); nodes.push(m);
    const line = new THREE.Line(new THREE.BufferGeometry().setFromPoints([c, p]), new THREE.LineBasicMaterial({ color: DEPT_COLORS[dept] || "#fff", transparent: true, opacity: 0.12 }));
    root.add(line);
    if (d.level >= 3) {   // restricted documents get an orbit ring
      const ring = new THREE.Mesh(new THREE.RingGeometry(size * .42, size * .47, 32), new THREE.MeshBasicMaterial({ color: d.level === 4 ? "#ff6b7d" : "#f2b84b", transparent: true, opacity: .8, side: THREE.DoubleSide }));
      ring.position.copy(p); ring.userData.spin = true; root.add(ring); m.userData.ring = ring;
    }
  });
  depts.forEach(d => {
    const line = new THREE.Line(new THREE.BufferGeometry().setFromPoints([new THREE.Vector3(), centers[d]]), new THREE.LineBasicMaterial({ color: "#3fd6c4", transparent: true, opacity: 0.18 }));
    root.add(line);
  });

  const ptr = new THREE.Vector2(-9, -9);
  let hovered = null, dragging = false, last = null, moved = 0;
  canvas.addEventListener("pointerdown", e => { dragging = true; last = [e.clientX, e.clientY]; moved = 0; canvas.setPointerCapture(e.pointerId); });
  canvas.addEventListener("pointerup", e => { dragging = false; if (moved < 5 && hovered) onClick(hovered.userData.doc); });
  canvas.addEventListener("pointermove", e => {
    const r = canvas.getBoundingClientRect();
    ptr.set((e.clientX - r.left) / r.width * 2 - 1, -(e.clientY - r.top) / r.height * 2 + 1);
    if (dragging) { const dx = e.clientX - last[0], dy = e.clientY - last[1]; moved += Math.abs(dx) + Math.abs(dy); vy = dx * 0.0009; vx = dy * 0.0009; last = [e.clientX, e.clientY]; }
    onHover(hovered ? hovered.userData.doc : null, e.clientX - r.left, e.clientY - r.top);
  });
  canvas.addEventListener("pointerleave", () => { ptr.set(-9, -9); onHover(null); });
  canvas.addEventListener("wheel", e => { e.preventDefault(); dist = Math.max(10, Math.min(48, dist + e.deltaY * 0.02)); }, { passive: false });

  function resize() { const w = canvas.clientWidth, h = canvas.clientHeight; renderer.setSize(w, h, false); camera.aspect = w / h; camera.updateProjectionMatrix(); }
  const ro = new ResizeObserver(resize); ro.observe(canvas); resize();
  let alive = true, zoomIn = 0;
  const clock = new THREE.Clock();
  (function loop() {
    if (!alive) return;
    const dt = Math.min(clock.getDelta(), .05), t = clock.elapsedTime;
    zoomIn = Math.min(1, zoomIn + dt * 0.5);
    rotY += vy; rotX = Math.max(-1.2, Math.min(1.2, rotX + vx)); vx *= 0.92; vy = dragging ? vy : vy * 0.96 + 0.0025 * 0.04;
    const d = dist + (1 - (1 - Math.pow(1 - zoomIn, 3))) * 30;
    camera.position.set(Math.sin(rotY) * Math.cos(rotX) * d, Math.sin(rotX) * d, Math.cos(rotY) * Math.cos(rotX) * d); camera.lookAt(0, 0, 0);
    // screen-space picking: nearest node within a radius that grows with node size
    const w = canvas.clientWidth, h = canvas.clientHeight, px = (ptr.x + 1) / 2 * w, py = (1 - ptr.y) / 2 * h;
    let best = null, bestD = Infinity;
    for (const n of nodes) {
      const v = n.position.clone().project(camera);
      if (v.z >= 1) continue;
      const dd = Math.hypot((v.x + 1) / 2 * w - px, (1 - v.y) / 2 * h - py);
      if (dd < 10 + n.userData.base * 9 && dd < bestD) { best = n; bestD = dd; }
    }
    hovered = best; canvas.style.cursor = hovered ? "pointer" : (dragging ? "grabbing" : "grab");
    for (const n of nodes) {
      const target = (n === hovered ? 1.9 : 1) * n.userData.base * (1 + Math.sin(t * 1.6 + n.userData.phase) * 0.06);
      n.scale.setScalar(n.scale.x + (target - n.scale.x) * 0.15);
      if (n.userData.ring) { n.userData.ring.lookAt(camera.position); n.userData.ring.rotation.z = t; }
    }
    core.material.opacity = 0.75 + Math.sin(t * 2) * 0.15;
    renderer.render(scene, camera);
    requestAnimationFrame(loop);
  })();
  return { dispose() { alive = false; ro.disconnect(); renderer.dispose(); } };
}

function makeLabel(text, color) {
  const c = document.createElement("canvas"), g = c.getContext("2d");
  c.width = 512; c.height = 96;
  g.font = "600 40px -apple-system, Segoe UI, sans-serif"; g.textAlign = "center"; g.textBaseline = "middle";
  g.shadowColor = color; g.shadowBlur = 18; g.fillStyle = "#e8eefc"; g.fillText(text, 256, 48);
  const s = new THREE.Sprite(new THREE.SpriteMaterial({ map: new THREE.CanvasTexture(c), transparent: true, depthWrite: false }));
  s.scale.set(6.4, 1.2, 1);
  return s;
}
