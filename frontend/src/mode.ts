/** Explicit data mode. live (default for `npm run dev`): every number comes from the cereal service on XRPL testnet,
 * nothing is seeded. mock (`npm run dev:mock`, the original Playwright suite): browser-only demo data. */
export type Mode = 'live' | 'mock';
const pathname = typeof window === 'undefined' ? '' : window.location.pathname;
/** Explicit sandbox routes share fixtures and storage; the live workspace never reads them. */
export const isTestEnvironment = ['/test-wallets', '/fixture-chat'].includes(pathname.replace(/\/$/, ''));
export const WALLET_PATH = isTestEnvironment ? '/test-wallets' : '/';
export const CHAT_PATH = isTestEnvironment ? '/fixture-chat' : '/demo-chat';
export const MODE: Mode = pathname.replace(/\/$/, '') === '/test-chat' ? 'live' : isTestEnvironment || import.meta.env?.VITE_CEREAL_MODE === 'mock' ? 'mock' : 'live';
export const isLive = MODE === 'live';
/** The Vite dev server proxies /api to the cereal service (CEREAL_API, default http://127.0.0.1:8001). */
export const API_BASE = import.meta.env?.VITE_CEREAL_API_BASE ?? '/api';
export const EXPLORER = 'https://testnet.xrpl.org';
