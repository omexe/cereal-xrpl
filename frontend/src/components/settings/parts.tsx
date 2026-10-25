import { useCallback, useEffect, useRef, useState, type ReactNode } from 'react';
import { RefreshCw01 } from '@untitledui/icons';
import { describeError } from '../../api';

/** Only http(s) URLs from backend data become links; anything else renders as plain text. */
export function safeHref(url?: string | null): string | undefined {
  return url && /^https?:\/\//i.test(url) ? url : undefined;
}

export function ExternalLink({ href, title, children }: { href?: string | null; title?: string; children: ReactNode }) {
  const safe = safeHref(href);
  if (!safe) return <span title={title}>{children}</span>;
  return <a href={safe} target="_blank" rel="noreferrer" title={title}>{children}</a>;
}

/** One titled block of the live Settings dialog; `name` is also its data-section. */
export function Section({ name, title, action, children }: { name: string; title: string; action?: ReactNode; children: ReactNode }) {
  const id = `settings-${name}`;
  return <section className="settings-section" data-section={name} aria-labelledby={id}>
    <div className="settings-section-head"><h3 id={id}>{title}</h3>{action}</div>
    {children}
  </section>;
}

export function RefreshButton({ label, busy, onClick }: { label: string; busy: boolean; onClick: () => void }) {
  return <button type="button" className="settings-refresh" aria-label={label} aria-busy={busy} disabled={busy} onClick={onClick}>
    <RefreshCw01 aria-hidden="true" /><span>{busy ? 'Refreshing…' : 'Refresh'}</span>
  </button>;
}

export function formatTime(at?: string | number | null): string {
  if (at === null || at === undefined || at === '') return '—';
  const date = new Date(at);
  if (Number.isNaN(date.getTime())) return String(at);
  return date.toLocaleString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit', second: '2-digit' });
}

export const plural = (count: number, one: string, many = `${one}s`) => `${count} ${count === 1 ? one : many}`;

/** A read the panel owns: loading and error states, a reload, and only the latest reply is shown.
 * `read` must be stable (defined at module scope). */
export function useRead<T>(read: () => Promise<T>, auto = true) {
  const [data, setData] = useState<T>();
  const [loading, setLoading] = useState(auto);
  const [error, setError] = useState<string>();
  const alive = useRef(true);
  const latest = useRef(0);
  const reload = useCallback(async () => {
    const ticket = ++latest.current;
    setLoading(true); setError(undefined);
    try {
      const value = await read();
      if (alive.current && ticket === latest.current) setData(value);
    } catch (e) {
      if (alive.current && ticket === latest.current) setError(describeError(e));
    } finally {
      if (alive.current && ticket === latest.current) setLoading(false);
    }
  }, [read]);
  useEffect(() => {
    alive.current = true;
    if (auto) reload();
    return () => { alive.current = false; };
  }, [auto, reload]);
  return { data, loading, error, reload };
}
