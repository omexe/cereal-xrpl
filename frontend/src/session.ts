/** The signed-in Sites user (docs/SITES.md). The service issues a random bearer token once; the browser keeps it so
 * this user's private sites and site wallets stay theirs. It is a session token, never a wallet seed or a key. */
export interface SessionUser { id: string; name: string }
export interface Session { user: SessionUser; token: string }

export const SESSION_KEY = 'cereal-session';

export function loadSession(): Session | null {
  try {
    const value: unknown = JSON.parse(localStorage.getItem(SESSION_KEY) ?? 'null');
    if (!value || typeof value !== 'object') return null;
    const s = value as Session;
    return typeof s.token === 'string' && s.user && typeof s.user.id === 'string' && typeof s.user.name === 'string' ? s : null;
  } catch { return null; }
}

export function saveSession(session: Session | null): void {
  try {
    if (session) localStorage.setItem(SESSION_KEY, JSON.stringify(session));
    else localStorage.removeItem(SESSION_KEY);
  } catch { /* storage unavailable: the session lasts until reload */ }
}
