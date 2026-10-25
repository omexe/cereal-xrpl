/** Explicit data mode. live (default for `npm run dev`): every number comes from the cereal service on XRPL testnet,
 * nothing is seeded. mock (`npm run dev:mock`, the original Playwright suite): browser-only demo data. */
export type Mode = 'live' | 'mock';
export const MODE: Mode = import.meta.env.VITE_CEREAL_MODE === 'mock' ? 'mock' : 'live';
export const isLive = MODE === 'live';
/** The Vite dev server proxies /api to the cereal service (CEREAL_API, default http://127.0.0.1:8001). */
export const API_BASE = import.meta.env.VITE_CEREAL_API_BASE ?? '/api';
export const EXPLORER = 'https://testnet.xrpl.org';
