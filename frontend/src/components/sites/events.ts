/** "The signed-in user's site list changed" (add, remove, buy, a site blocked after a purchase). The sidebar reloads
 * on it, so every view that writes a site does not need a handle on the sidebar. */
const EVENT = 'cereal:sites-changed';

export function sitesChanged(): void { window.dispatchEvent(new Event(EVENT)); }

export function onSitesChanged(listener: () => void): () => void {
  window.addEventListener(EVENT, listener);
  return () => window.removeEventListener(EVENT, listener);
}
