import { useEffect, useRef, useState, type FormEvent } from 'react';
import { api, ApiError, describeError, type Site, type SiteProbe } from '../api';
import type { AppActions } from '../appActions';
import { loadSession, saveSession, type Session } from '../session';
import { Dialog } from './Dialog';
import { sitesChanged } from './sites/events';
import { ProbeFindings, TrustNote } from './sites/SiteChecks';
import { blockedText, refusalMessage, TRUST_LABEL, trustOf } from './sites/siteText';

/** "example.com/page" → "https://example.com/page"; "localhost:8004/x" → "http://localhost:8004/x" (local test
 * merchants speak plain http). Anything else with a scheme ("ftp://", "mailto:") is left for the service to judge. */
export function normalizeUrl(input: string): string {
  const text = input.trim();
  if (!text || /^[a-z][a-z0-9+.-]*:\/\//i.test(text)) return text;
  if (/^[a-z][a-z0-9+.-]*:(?!\d)/i.test(text)) return text;  // a scheme without "//"; "host:port" has a digit after ":"
  const rest = text.replace(/^\/+/, '');
  const local = /^(localhost|127\.0\.0\.1|\[::1\]|[^/:]+\.localhost)(:\d+)?(\/|$)/i.test(rest);
  return `${local ? 'http' : 'https'}://${rest}`;
}

/** Sites (live only): sign in if needed, enter a URL, see the probe card, add it to my sites. */
export function AddSiteDialog({ app, url }: { app: AppActions; url?: string }) {
  if (!app.session) return <SignInDialog app={app} />;
  return <AddSite app={app} url={url} />;
}

function SignInDialog({ app }: { app: AppActions }) {
  const [name, setName] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const mounted = useRef(true);
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; }; }, []);

  async function signIn(event: FormEvent) {
    event.preventDefault();
    const text = name.trim();
    if (!text || busy) return;
    setBusy(true); setError(null);
    try {
      const out = await api.createSession(text);
      const next: Session = { user: out.user, token: out.token };
      // api.ts sends the token it finds in localStorage: if the browser will not keep it, every site call would fail.
      saveSession(next);
      if (loadSession()?.token !== out.token) {
        if (mounted.current) setError('This browser blocks site storage, so cereal cannot keep you signed in. Allow storage for this site and try again.');
        return;
      }
      app.setSession(next);  // the dialog continues as Add a site
    } catch (e) {
      if (mounted.current) setError(e instanceof ApiError && e.status === 404 ? 'This cereal service does not offer sites yet.' : describeError(e));
    } finally { if (mounted.current) setBusy(false); }
  }

  return <Dialog title="Sign in to use sites" onClose={app.close}><form onSubmit={signIn}>
    <p className="dialog-description">Your sites are private to you. Nobody else sees your list, only your wallets can pay
      your private sites, and your Ledger signs every one of those payments.</p>
    <label>Your name<input name="name" value={name} maxLength={40} autoFocus autoComplete="nickname" disabled={busy}
      placeholder="e.g. Ana" onChange={event => setName(event.target.value)} /></label>
    <p className="demo-note">cereal keeps a sign-in token in this browser. It is not a wallet key and moves no money.</p>
    {busy && <p className="site-progress" role="status">Signing in…</p>}
    {error && <p className="site-error" role="alert">{error}</p>}
    <button className="primary-button form-submit" disabled={!name.trim() || busy}>Sign in</button>
  </form></Dialog>;
}

type Busy = 'checking' | 'adding' | null;
interface Failure { message: string; site?: Site }

function AddSite({ app, url }: { app: AppActions; url?: string }) {
  const [address, setAddress] = useState(url ?? '');
  const [probe, setProbe] = useState<SiteProbe>();
  const [busy, setBusy] = useState<Busy>(null);
  const [failure, setFailure] = useState<Failure>();
  const inFlight = useRef(false);
  const mounted = useRef(true);
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; }; }, []);
  const name = app.session?.user.name;

  async function check(event: FormEvent) {
    event.preventDefault();
    const target = normalizeUrl(address);
    if (!target || inFlight.current) return;
    inFlight.current = true;
    setBusy('checking'); setFailure(undefined); setProbe(undefined);
    if (target !== address) setAddress(target);
    try {
      const out = await api.probeSite(target);
      if (mounted.current) setProbe(out);
    } catch (e) {
      if (mounted.current) setFailure({ message: refusalMessage(e) });
    } finally { inFlight.current = false; if (mounted.current) setBusy(null); }
  }

  async function add() {
    if (!probe || inFlight.current) return;
    inFlight.current = true;
    setBusy('adding'); setFailure(undefined);
    try {
      const out = await api.addSite(probe.url);
      sitesChanged();
      // Closed mid-flight: the user moved on, so only the status line reports it; never steal the current view.
      const added = `${out.site.name} added to your sites as ${TRUST_LABEL[trustOf(out.site)].toLowerCase()}.`;
      if (mounted.current) { app.openSite(out.site.id, added); app.close(); } else app.notify(added);
    } catch (e) {
      const body = e instanceof ApiError && e.refused ? e.body as { refused?: string; reason?: string; site?: Site } : undefined;
      if (body?.site) sitesChanged();  // site_blocked: stored as blocked so the owner can see why
      let message = refusalMessage(e);
      if (body?.refused === 'site_blocked') {
        const why = body.site?.blocked_reason ?? body.reason ?? probe.verdict_reasons[0];
        message = `This site is blocked: ${blockedText(why)}${body.site ? ' It is in your sites as blocked, so you can see why; nothing can pay it.' : ''}`;
      } else if (body?.refused === 'not_accessible') {
        message = `${REFUSED_NOT_ACCESSIBLE} ${body.reason ?? probe.reason ?? ''}`.trim();
      }
      if (mounted.current) setFailure({ message, site: body?.site });
      else app.notify(message, true);
    } finally { inFlight.current = false; if (mounted.current) setBusy(null); }
  }

  const trust = probe ? trustOf(probe) : 'none';
  return <Dialog title="Add a site" onClose={app.close}>
    <form onSubmit={check}>
      <p className="dialog-description">Give cereal any web address. It reads free pages, pays paywalls that accept RLUSD on
        XRPL testnet, and refuses the rest with the reason. Nothing is paid until you buy.</p>
      <label>Site address<input name="url" type="text" inputMode="url" autoComplete="url" spellCheck={false} value={address}
        autoFocus={!url} disabled={!!busy} placeholder="https://example.com"
        onChange={event => { setAddress(event.target.value); setProbe(undefined); setFailure(undefined); }} /></label>
      <button className={probe ? 'secondary-button site-check-button' : 'primary-button form-submit'} disabled={!address.trim() || !!busy}>
        {busy === 'checking' ? 'Checking…' : probe ? 'Check again' : 'Check site'}</button>
    </form>
    {busy && <p className="site-progress" role="status">{busy === 'checking' ? 'Checking the site and its payee…' : 'Adding it to your sites…'}</p>}
    {probe && <section className="site-card" aria-label="Site check" data-kind={probe.kind} data-trust={trust}>
      <div className="site-card-head">
        <strong>{probe.title || probe.host}</strong>
        <span className="site-card-url">{probe.url}</span>
      </div>
      <ProbeFindings probe={probe} />
      <TrustNote trust={trust} prefix={trust === 'none' ? undefined : 'Will be added as'} />
    </section>}
    {failure && <div className="site-error" role="alert"><p>{failure.message}</p>
      {failure.site && <button className="sites-signout" onClick={() => { app.openSite(failure.site!.id); app.close(); }}>See the blocked site</button>}</div>}
    {probe && <button type="button" className="primary-button form-submit" disabled={!!busy} onClick={add}>
      {busy === 'adding' ? 'Adding…' : 'Add to my sites'}</button>}
    <p className="demo-note">Adding to {name ? `${name}’s` : 'your'} sites · private to you.</p>
  </Dialog>;
}

const REFUSED_NOT_ACCESSIBLE = 'An agent cannot use this site:';
