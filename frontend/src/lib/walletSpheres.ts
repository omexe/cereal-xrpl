/** Detached wallet spheres on a regular hexagonal dot lattice.
 * Layout follows Figma 45:307; wallet IDs retain their positions through updates.
 */
export const SIZE = 727;
export const CORE = { x: 313, y: 328, radius: 97 };
/** Selecting this id highlights the aggregate core instead of a wallet sphere. */
export const CORE_ID = 'total-wallet';
export interface View { x: number; y: number; width: number; height: number }
/** The wallet page's crop, matching its 356 × 406 frame. Every sphere is placed inside it. */
export const VIEW: View = { x: 108, y: 94.5, width: 420, height: 479 };
/** Home's crop, matching its 640 × 620 frame; it contains VIEW, so every sphere shows on both pages. */
export const HOME_VIEW: View = { x: 78, y: 101.5, width: 480, height: 465 };
const TAU = Math.PI * 2;
export const DURATION = 320;
const clamp = (n: number, lo = 0, hi = 1) => Math.max(lo, Math.min(hi, n));
const mix = (a: number, b: number, t: number) => a + (b - a) * t;
interface Sphere { id: string; x: number; y: number; radius: number; blue: number }
export type Position = Pick<Sphere, 'x' | 'y' | 'radius'>;
// The reference's airy, asymmetric orbit, ordered with the initial wallet at lower right.
const referencePositions: Position[] = [
  { x: 455, y: 447, radius: 60 },
  { x: 280, y: 180, radius: 28 },
  { x: 150, y: 297, radius: 29 },
  { x: 439, y: 243, radius: 25 },
  { x: 222, y: 490, radius: 32 },
  { x: 375, y: 174, radius: 22 },
  { x: 178, y: 391, radius: 23 },
  { x: 327, y: 464, radius: 20 },
  { x: 189, y: 209, radius: 17 },
  { x: 466, y: 324, radius: 15 },
  { x: 289, y: 122, radius: 14 },
  { x: 220, y: 547, radius: 13 },
];
/** The shared dot lattice, in SIZE coordinates. */
export const dots = Array.from({ length: 160 * 185 }, (_, index) => {
  const row = Math.floor(index / 160), col = index % 160;
  return { x: col * 4.6 + (row % 2) * 2.3, y: row * 4.6 * Math.sqrt(3) / 2 };
});

/** Where the next wallet's sphere goes, given those already placed (in order): the reference orbit first, then the
 * largest free space inside VIEW. Home's forming sphere uses it, so a new wallet appears where it was forming. */
export function placeSphere(placed: Position[]): Position {
  if (placed.length < referencePositions.length) return referencePositions[placed.length];
  const occupied = [CORE, ...placed];
  let best = { x: 0, y: 0, radius: 0 };
  for (let y = VIEW.y + 40; y <= VIEW.y + VIEW.height - 40; y += 16) {
    for (let x = VIEW.x + 40; x <= VIEW.x + VIEW.width - 40; x += 16) {
      const radius = Math.min(32, ...occupied.map(sphere => Math.hypot(x - sphere.x, y - sphere.y) - sphere.radius - 18));
      if (radius > best.radius) best = { x, y, radius };
    }
  }
  return best;
}

export function createWalletSpheres(canvas: HTMLCanvasElement, svg: SVGSVGElement) {
  const context = canvas.getContext('2d');
  if (!context) return { update: (_ids: string[], _selected?: string) => {}, destroy: () => {} };
  const ctx = context;
  const positions = new Map<string, Position>();
  const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)');
  let current: Sphere[] = [], targets: Sphere[] = [];
  let initialized = false, frame = 0, scale = 1;
  let hitTargets = new Map<string, SVGCircleElement>();
  // Resolve theme tokens through canvas, supporting any CSS color syntax.
  function rgb(token: string) {
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    ctx.fillStyle = getComputedStyle(canvas).getPropertyValue(token).trim();
    ctx.fillRect(0, 0, 1, 1);
    return Array.from(ctx.getImageData(0, 0, 1, 1).data).slice(0, 3);
  }
  const soft = rgb('--color-organism-soft'), accent = rgb('--color-organism-selected');
  const palette = Array.from({ length: 24 }, (_, step) => `rgb(${soft.map((n, i) => Math.round(mix(n, accent[i], step / 23))).join(',')})`);

  function draw() {
    ctx.setTransform(scale, 0, 0, scale, 0, 0);
    ctx.clearRect(0, 0, SIZE, SIZE);
    const paths = palette.map(() => new Path2D());
    let dotCount = 0;
    for (const sphere of current) {
      if (sphere.radius < .1) continue;
      const path = paths[Math.round(sphere.blue * (palette.length - 1))];
      for (const dot of dots) {
        const dx = dot.x - sphere.x, dy = dot.y - sphere.y;
        if (Math.abs(dx) > sphere.radius || Math.abs(dy) > sphere.radius) continue;
        const inset = sphere.radius - Math.hypot(dx, dy);
        if (inset <= .4) continue;
        // Uniform, closely packed dots with just a delicate taper at the silhouette.
        const radius = Math.min(1.65, inset * .75);
        path.moveTo(dot.x + radius, dot.y);
        path.arc(dot.x, dot.y, radius, 0, TAU);
        dotCount++;
      }
    }
    paths.forEach((path, i) => { ctx.fillStyle = palette[i]; ctx.fill(path); });
    canvas.dataset.dotCount = String(dotCount);
    for (const sphere of current) {
      const target = hitTargets.get(sphere.id);
      target?.setAttribute('cx', String(sphere.x));
      target?.setAttribute('cy', String(sphere.y));
      target?.setAttribute('r', String(sphere.radius));
    }
  }
  function resize() {
    const pixels = Math.max(1, Math.round(canvas.getBoundingClientRect().width * Math.min(devicePixelRatio || 1, 2)));
    canvas.width = canvas.height = pixels;
    scale = pixels / SIZE;
    draw();
  }
  // New and removed wallets scale in place, never connect to the aggregate.
  function tucked(sphere: Sphere): Sphere {
    return { ...sphere, radius: 0 };
  }
  const nextPosition = () => placeSphere([...positions.values()]);
  function settle() {
    cancelAnimationFrame(frame);
    current = targets;
    canvas.dataset.animating = 'false';
    draw();
  }
  function update(ids: string[], selected?: string) {
    cancelAnimationFrame(frame);
    // Keep archived positions reserved so restore returns to the same sphere.
    for (const id of ids) {
      if (!positions.has(id)) positions.set(id, nextPosition());
    }
    // The core is always present, so it only ever animates its color.
    targets = [{ id: CORE_ID, ...CORE, blue: selected === CORE_ID ? 1 : 0 }, ...ids.map(id => ({ id, ...positions.get(id)!, blue: id === selected ? 1 : 0 }))];
    hitTargets = new Map(Array.from(svg.querySelectorAll<SVGGElement>('.wallet-cluster')).map(group => [group.dataset.walletId!, group.querySelector<SVGCircleElement>('circle')!]));
    if (!initialized || reducedMotion.matches) { initialized = true; settle(); return; }
    const from = new Map(current.map(sphere => [sphere.id, sphere])), to = new Map(targets.map(sphere => [sphere.id, sphere]));
    const transitions = [...new Set([...from.keys(), ...to.keys()])].map(id => {
      const a = from.get(id) ?? tucked(to.get(id)!);
      return { a, b: to.get(id) ?? tucked(a) };
    });
    const start = performance.now();
    canvas.dataset.animating = 'true';
    function tick(now: number) {
      const progress = clamp((now - start) / DURATION), t = 1 - (1 - progress) ** 3;
      current = transitions.map(({ a, b }) => ({ ...b, x: mix(a.x, b.x, t), y: mix(a.y, b.y, t), radius: mix(a.radius, b.radius, t), blue: mix(a.blue, b.blue, t) }));
      draw();
      if (progress < 1) frame = requestAnimationFrame(tick);
      else settle();
    }
    tick(start);
  }
  const observer = new ResizeObserver(resize);
  observer.observe(canvas);
  reducedMotion.addEventListener('change', settle);
  resize();
  return { update, destroy() { cancelAnimationFrame(frame); observer.disconnect(); reducedMotion.removeEventListener('change', settle); } };
}
