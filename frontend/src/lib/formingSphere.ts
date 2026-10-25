/** The wallet being written on Home: sparse lattice dots that hover and twinkle where the new sphere will sit, filling
 * in as the sentence pins the wallet down. Drawn on its own canvas over the sphere map, in the same coordinates. */
import { SIZE, dots, type Position } from './walletSpheres';

const TAU = Math.PI * 2;
const BUCKETS = 4;
// Stable per-dot randomness, so a dot keeps its phase and its place in the fill order from frame to frame.
const noise = (i: number, salt: number) => { const x = Math.sin(i * 12.9898 + salt * 78.233) * 43758.5453; return x - Math.floor(x); };

export function createFormingSphere(canvas: HTMLCanvasElement) {
  const context = canvas.getContext('2d');
  if (!context) return { update: (_at: Position, _progress: number) => {}, destroy: () => {} };
  const ctx = context;
  const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)');
  const color = getComputedStyle(canvas).getPropertyValue('--color-forming-particle').trim();
  let at: Position | null = null, progress = 0, density = 0, radius = 0, scale = 1, frame = 0;
  // Drawn larger than the slot while forming so it reads as the subject; it lands at the slot's size once created.
  const size = () => Math.max(at!.radius * 1.6, 44) * (.85 + .15 * progress);
  const target = () => .2 + .55 * progress;

  function draw(now: number) {
    ctx.setTransform(scale, 0, 0, scale, 0, 0);
    ctx.clearRect(0, 0, SIZE, SIZE);
    if (!at) return;
    // Ease toward the target, so each new condition visibly thickens the sphere.
    density += (target() - density) * .06;
    radius += (size() - radius) * .06;
    const reach = radius * 1.45, t = reducedMotion.matches ? 0 : now;
    const paths = Array.from({ length: BUCKETS }, () => new Path2D());
    dots.forEach((dot, i) => {
      const dx = dot.x - at!.x, dy = dot.y - at!.y;
      if (Math.abs(dx) > reach || Math.abs(dy) > reach) return;
      const distance = Math.hypot(dx, dy) / radius;
      // Inside the sphere dots fill in with progress; a thin halo of strays hovers around it.
      const chance = distance < 1 ? density : distance < 1.45 ? .05 * (1.45 - distance) / .45 : 0;
      if (noise(i, 1) >= chance) return;
      const phase = noise(i, 2) * TAU;
      const x = dot.x + Math.sin(t * .0011 + phase) * 1.6, y = dot.y + Math.cos(t * .0009 + phase * 1.7) * 1.6;
      const glow = .5 + .5 * Math.sin(t * .0022 + phase);
      const r = 1.05 + .6 * glow;
      const path = paths[Math.min(BUCKETS - 1, Math.floor(glow * BUCKETS))];
      path.moveTo(x + r, y);
      path.arc(x, y, r, 0, TAU);
    });
    ctx.fillStyle = color;
    paths.forEach((path, i) => { ctx.globalAlpha = .35 + .65 * (i + 1) / BUCKETS; ctx.fill(path); });
    ctx.globalAlpha = 1;
  }
  function loop(now: number) {
    draw(now);
    frame = reducedMotion.matches ? 0 : requestAnimationFrame(loop);
  }
  function settle() { cancelAnimationFrame(frame); density = target(); if (at) radius = size(); loop(0); }
  function resize() {
    const pixels = Math.max(1, Math.round(canvas.getBoundingClientRect().width * Math.min(devicePixelRatio || 1, 2)));
    canvas.width = canvas.height = pixels;
    scale = pixels / SIZE;
    draw(performance.now());
  }
  const observer = new ResizeObserver(resize);
  observer.observe(canvas);
  reducedMotion.addEventListener('change', settle);
  return {
    update(next: Position, nextProgress: number) {
      const first = !at;
      at = next; progress = nextProgress;
      if (first) { radius = size() * .5; frame = requestAnimationFrame(loop); }
      if (reducedMotion.matches) settle();
    },
    destroy() { cancelAnimationFrame(frame); observer.disconnect(); reducedMotion.removeEventListener('change', settle); },
  };
}
