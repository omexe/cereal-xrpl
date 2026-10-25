import { useCallback, useEffect, useRef, useState } from 'react';
import { Plus } from '@untitledui/icons';
import { api, ApiError, describeError, type Site } from '../api';
import type { AppActions } from '../appActions';
import { loadSession, SESSION_KEY } from '../session';
import { onSitesChanged } from './sites/events';
import { TrustMarker } from './sites/SiteChecks';
import { TRUST_LABEL, trustOf } from './sites/siteText';

const POLL_MS = 15000;

/** Why GET /sites failed, in plain words: an expired sign-in, a service without Sites yet, or the usual. */
export function sitesLoadError(error: unknown): { message: string; signedOut: boolean } {
  if (error instanceof ApiError && error.status === 401) {
    return { message: 'This cereal service no longer knows your sign-in. Sign in again to see your sites.', signedOut: true };
  }
  if (error instanceof ApiError && error.status === 404) return { message: 'This cereal service does not offer sites yet.', signedOut: false };
  return { message: describeError(error), signedOut: false };
}

/** Sites (live only): the signed-in user's private site list in the sidebar, with "Add site". */
export function SitesSection({ app }: { app: AppActions }) {
  const { session } = app;
  const token = session?.token;
  const [sites, setSites] = useState<Site[] | null>(null);
  const [error, setError] = useState<{ message: string; signedOut: boolean } | null>(null);
  // Signing in or out in another tab changes the token api.ts sends from this one: follow it, so this tab never
  // shows one user's name over another user's sites.
  const setSession = useRef(app.setSession);
  setSession.current = app.setSession;
  useEffect(() => {
    const onStorage = (event: StorageEvent) => {
      if (event.key !== null && event.key !== SESSION_KEY) return;
      const next = loadSession();
      if ((next?.token ?? null) !== (token ?? null)) setSession.current(next);
    };
    window.addEventListener('storage', onStorage);
    return () => window.removeEventListener('storage', onStorage);
  }, [token]);

  /** The latest read wins: a slow poll never puts back a list from before an add, a remove or a sign-out. */
  const seq = useRef(0);

  const load = useCallback(async () => {
    if (!token) return;
    const n = ++seq.current;
    try { const list = await api.sites(); if (n === seq.current) { setSites(list); setError(null); } }
    catch (e) { if (n === seq.current) setError(sitesLoadError(e)); }
  }, [token]);

  useEffect(() => {
    setSites(null); setError(null);
    if (!token) return;
    void load();
    const timer = window.setInterval(() => { void load(); }, POLL_MS);
    const stop = onSitesChanged(() => { void load(); });
    return () => { seq.current++; clearInterval(timer); stop(); };
  }, [token, load]);

  if (!session) return <section className="sidebar-section sites-section" aria-labelledby="sites-heading">
    <h2 id="sites-heading" className="section-heading">My sites</h2>
    <p className="sites-note">Give cereal any web address: it reads free pages and pays RLUSD paywalls. Your sites are private to you.</p>
    <button className="empty-wallets sites-signin" onClick={() => app.openAddSite()}>Sign in to use sites</button>
  </section>;

  return <section className="sidebar-section sites-section" aria-labelledby="sites-heading" data-signed-in="true">
    <div className="section-heading"><h2 id="sites-heading">My sites</h2>
      <button className="icon-button small" aria-label="Add site" onClick={() => app.openAddSite()}><Plus /></button></div>
    <p className="sites-session"><span>Signed in as <strong>{session.user.name}</strong></span>
      <button className="sites-signout" onClick={() => app.setSession(null)}>Sign out</button></p>
    <p className="sites-note">Private to you: nobody else sees this list, and only your wallets can pay these sites.</p>
    {error && <div className="sites-error" role="alert"><p>{error.message}</p>
      {error.signedOut && <button className="sites-signout" onClick={() => { app.setSession(null); app.openAddSite(); }}>Sign in again</button>}</div>}
    {sites === null && !error && <p className="sites-note" role="status">Loading your sites…</p>}
    {sites !== null && !sites.length && <button className="empty-wallets sites-empty" onClick={() => app.openAddSite()}>Add your first site</button>}
    {sites?.map(site => {
      const trust = trustOf(site);
      return <button key={site.id} className="site-row" data-site-id={site.id} data-trust={trust}
        aria-label={`Open ${site.name} (${TRUST_LABEL[trust]})`} title={site.url}
        aria-current={app.selectedSiteId === site.id ? 'true' : undefined} onClick={() => app.openSite(site.id)}>
        <TrustMarker trust={trust} /><span className="site-row-name">{site.name}</span>
        <span className="site-row-trust" aria-hidden="true">{trust}</span>
      </button>;
    })}
  </section>;
}
