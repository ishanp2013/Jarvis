"use strict";
// Shared by the dashboard (app.js) and the floating orb (overlay.js). Reads the page's globals:
// state, level (mic loudness) and voiceLevel (Jarvis's voice loudness).
// ------------------------------------------------------------ orb animation
// A gold holographic sigil: a glowing iris, broken concentric rings, a tilted orbit, star lines,
// circuit traces and drifting sparks. It swells and throws sparks with Jarvis's voice while speaking.
function startOrb(c) {
  const g = c.getContext("2d");
  const W = c.width, R = W / 2, TAU = Math.PI * 2;
  const tint = { idle: [255, 176, 64], listening: [255, 214, 120], transcribing: [255, 196, 96],
    thinking: [255, 150, 40], speaking: [255, 186, 72], starting: [200, 130, 50] };
  const rnd = (a, b) => a + Math.random() * (b - a);
  // Fixed pieces of the sigil, made once: broken ring segments, circuit traces, star lines.
  const rings = [0.2, 0.27, 0.36, 0.44, 0.52, 0.6, 0.7, 0.8].map((f, i) => ({
    r: f * R, speed: (i % 2 ? -1 : 1) * rnd(0.05, 0.3), width: i % 3 === 0 ? 2.2 : 1,
    segs: Array.from({ length: 3 + (i % 4) }, () => [rnd(0, TAU), rnd(0.2, 1.4)]), dash: i % 2 === 1, alpha: rnd(0.35, 0.8) }));
  const traces = Array.from({ length: 46 }, () => {
    const a = rnd(0, TAU), r0 = rnd(0.3, 0.92) * R, len = rnd(10, 46);
    return { a, r0, len, bend: rnd(-0.5, 0.5), phase: rnd(0, TAU), speed: rnd(0.5, 2.5) };
  });
  const stars = Array.from({ length: 7 }, (_, k) => ({ a: (k / 7) * TAU + rnd(-0.1, 0.1), reach: rnd(0.75, 1.05) }));
  let sparks = [], t = 0, amp = 0, last = 0;
  const reduced = matchMedia("(prefers-reduced-motion: reduce)").matches;

  function spawn(n, energy) {
    for (let k = 0; k < n && sparks.length < 260; k++) {
      const a = rnd(0, TAU), r = rnd(0.12, 0.3) * R, v = rnd(0.4, 1.6) * (1 + energy * 3);
      sparks.push({ x: R + Math.cos(a) * r, y: R + Math.sin(a) * r, vx: Math.cos(a) * v + rnd(-0.3, 0.3),
        vy: Math.sin(a) * v + rnd(-0.3, 0.3), life: rnd(0.6, 1.6), age: 0, size: rnd(0.6, 2.2) });
    }
  }

  function frame(now) {
    requestAnimationFrame(frame);
    if (document.hidden || window.gameMode) return; // game mode: no drawing, no CPU
    const busy = state !== "idle";
    if (now - last < (busy ? 16 : 40)) return; // ~25 fps when idle keeps the CPU low
    const dt = Math.min(0.05, (now - last) / 1000 || 0.016); last = now; t += reduced ? dt * 0.25 : dt;
    const target = state === "speaking" ? 0.25 + voiceLevel * 1.6 : state === "listening" ? 0.15 + level * 3
      : state === "thinking" || state === "transcribing" ? 0.3 + 0.12 * Math.sin(t * 6) : 0.06;
    amp += (Math.min(1.4, target) - amp) * (target > amp ? 0.45 : 0.12);
    const [cr, cg, cb] = tint[state] || tint.idle;
    const col = (a, w = 0) => `rgba(${Math.min(255, cr + w)},${Math.min(255, cg + w)},${Math.min(255, cb + w)},${Math.max(0, a)})`;
    const spin = state === "thinking" ? 3 : 1 + amp;

    g.globalCompositeOperation = "source-over";
    g.clearRect(0, 0, W, W);
    g.globalCompositeOperation = "lighter";

    // haze
    const haze = g.createRadialGradient(R, R, 0, R, R, R);
    haze.addColorStop(0, col(0.22 + amp * 0.25)); haze.addColorStop(0.3, col(0.07 + amp * 0.08)); haze.addColorStop(1, col(0));
    g.fillStyle = haze; g.fillRect(0, 0, W, W);

    // tilted orbit rings (the big ellipse sweeping across the sigil)
    for (const [tilt, sq, sp, a] of [[0.35, 0.42, 0.18, 0.5], [-0.5, 0.3, -0.12, 0.3]]) {
      g.save(); g.translate(R, R); g.rotate(tilt + Math.sin(t * sp) * 0.15); g.scale(1, sq + amp * 0.05);
      g.beginPath(); g.arc(0, 0, R * (0.86 + amp * 0.05), 0, TAU);
      g.lineWidth = 2.4; g.strokeStyle = col(a * (0.6 + amp)); g.stroke(); g.restore();
    }

    // star lines: long thin rays crossing the centre
    g.save(); g.translate(R, R); g.rotate(t * 0.04 * spin);
    g.lineWidth = 0.8;
    for (let k = 0; k < stars.length; k++) {
      const s = stars[k], s2 = stars[(k + 3) % stars.length];
      g.beginPath();
      g.moveTo(Math.cos(s.a) * R * s.reach, Math.sin(s.a) * R * s.reach);
      g.lineTo(Math.cos(s2.a) * R * s2.reach, Math.sin(s2.a) * R * s2.reach);
      g.strokeStyle = col(0.18 + amp * 0.25); g.stroke();
    }
    g.restore();

    // broken concentric rings, each turning its own way
    for (const ring of rings) {
      const rr = ring.r * (1 + amp * 0.06);
      g.lineWidth = ring.width;
      g.setLineDash(ring.dash ? [2, 6] : []);
      for (const [a0, len] of ring.segs) {
        const a = a0 + t * ring.speed * spin;
        g.beginPath(); g.arc(R, R, rr, a, a + len);
        g.strokeStyle = col(ring.alpha * (0.55 + amp * 0.6)); g.stroke();
      }
    }
    g.setLineDash([]);

    // tick ring
    g.save(); g.translate(R, R); g.rotate(-t * 0.2 * spin);
    for (let k = 0; k < 90; k++) {
      g.rotate(TAU / 90);
      g.fillStyle = col(k % 6 ? 0.18 : 0.6);
      g.fillRect(R * 0.9, -0.6, k % 6 ? 5 : 11, 1.2);
    }
    g.restore();

    // circuit traces: short bent lines that flicker
    g.lineWidth = 1;
    for (const tr of traces) {
      const on = 0.5 + 0.5 * Math.sin(t * tr.speed * spin + tr.phase);
      if (on < 0.25) continue;
      const x0 = R + Math.cos(tr.a) * tr.r0, y0 = R + Math.sin(tr.a) * tr.r0;
      const x1 = x0 + Math.cos(tr.a + tr.bend) * tr.len, y1 = y0 + Math.sin(tr.a + tr.bend) * tr.len;
      g.beginPath(); g.moveTo(x0, y0); g.lineTo(x1, y1); g.lineTo(x1 + Math.cos(tr.a) * tr.len * 0.4, y1 + Math.sin(tr.a) * tr.len * 0.4);
      g.strokeStyle = col(on * (0.25 + amp * 0.5)); g.stroke();
      g.fillStyle = col(on * 0.8, 40); g.fillRect(x1 - 1, y1 - 1, 2, 2);
    }

    // iris: bright ring with a dark centre, pulsing with the voice
    const core = R * (0.11 + amp * 0.05);
    const iris = g.createRadialGradient(R, R, core * 0.45, R, R, core * 2.4);
    iris.addColorStop(0, col(0)); iris.addColorStop(0.32, col(0.95, 60)); iris.addColorStop(0.45, col(0.5));
    iris.addColorStop(1, col(0));
    g.fillStyle = iris; g.beginPath(); g.arc(R, R, core * 2.4, 0, TAU); g.fill();
    g.lineWidth = 2; g.strokeStyle = col(0.9, 50); g.beginPath(); g.arc(R, R, core, 0, TAU); g.stroke();
    g.lineWidth = 1; g.strokeStyle = col(0.5); g.beginPath(); g.arc(R, R, core * 1.5, t * 2, t * 2 + 4); g.stroke();

    // sparks: a few always drift; speaking throws more out with each syllable
    spawn(state === "speaking" ? Math.round(voiceLevel * 9) : busy ? 1 : Math.random() < 0.3 ? 1 : 0, amp);
    sparks = sparks.filter((p) => (p.age += dt) < p.life);
    for (const p of sparks) {
      p.x += p.vx; p.y += p.vy; p.vx *= 0.985; p.vy *= 0.985;
      const a = 1 - p.age / p.life;
      g.fillStyle = col(a * 0.9, 60); g.fillRect(p.x, p.y, p.size, p.size);
    }
    g.globalCompositeOperation = "source-over";
  }
  requestAnimationFrame(frame);
}
