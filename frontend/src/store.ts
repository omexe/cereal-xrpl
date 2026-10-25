/** I02/I03: live data from the cereal service. Polls the main wallet and the wallet list, and the selected wallet's
 * detail (which resolves pending x402 payments against the ledger). Never seeds mock data; failures are visible. */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { api, ApiError, describeError, type ApiRecord, type Folder, type MainWallet, type Vendor } from './api';
import { toWorkspace } from './live';
import type { Workspace } from './wallets';

export interface LiveData {
  enabled: boolean;
  status: 'loading' | 'ready' | 'error';
  error?: string;
  main?: MainWallet;
  records: ApiRecord[];
  vendors: Vendor[];
  folders: Folder[];
  workspace: Workspace;
  updatedAt?: number;
  /** Re-read everything now (after a write). */
  refresh: () => Promise<void>;
  /** Replace one record (e.g. from a write's response) without waiting for the next poll. */
  upsert: (rec: ApiRecord) => void;
}

const POLL_MS = 5000;
const VENDOR_POLL_MS = 60000;

export function useLiveData(enabled: boolean, selectedId?: string): LiveData {
  const [status, setStatus] = useState<LiveData['status']>('loading');
  const [error, setError] = useState<string>();
  const [main, setMain] = useState<MainWallet>();
  const [records, setRecords] = useState<ApiRecord[]>([]);
  const [vendors, setVendors] = useState<Vendor[]>([]);
  const [folders, setFolders] = useState<Folder[]>([]);
  const [updatedAt, setUpdatedAt] = useState<number>();
  const current = useRef<Promise<void> | null>(null);
  const vendorsAt = useRef(0);
  const selected = useRef(selectedId);
  selected.current = selectedId;

  const upsert = useCallback((rec: ApiRecord) => {
    setRecords(previous => previous.some(r => r.id === rec.id) ? previous.map(r => r.id === rec.id ? { ...r, ...rec } : r) : [rec, ...previous]);
  }, []);

  const load = useCallback(async () => {
    try {
      const [m, list] = await Promise.all([api.main(), api.wallets()]);
      let merged = list;
      const sel = selected.current;
      if (sel && list.some(r => r.id === sel)) {
        const detail = await api.wallet(sel).catch(() => null);
        if (detail) merged = list.map(r => r.id === sel ? detail : r);
      }
      setMain(m); setRecords(merged);
      if (Date.now() - vendorsAt.current > VENDOR_POLL_MS) {
        vendorsAt.current = Date.now();
        api.vendors().then(setVendors).catch(() => { vendorsAt.current = 0; });
        // /folders is the workspace router's (A05); until it answers, folders come from the records alone.
        api.folders().then(setFolders).catch(() => setFolders([]));
      }
      setStatus('ready'); setError(undefined); setUpdatedAt(Date.now());
    } catch (e) {
      setStatus('error');
      setError(e instanceof ApiError && e.kind !== 'refused' ? e.message : describeError(e));
    }
  }, []);

  /** Waits for any read in flight, then reads again, so a caller that just wrote sees its write. */
  const refresh = useCallback(async () => {
    if (!enabled) return;
    if (current.current) await current.current.catch(() => undefined);
    const run = load();
    current.current = run;
    try { await run; } finally { if (current.current === run) current.current = null; }
  }, [enabled, load]);

  useEffect(() => {
    if (!enabled) return;
    refresh();
    const timer = window.setInterval(() => { if (!current.current) refresh(); }, POLL_MS);
    return () => clearInterval(timer);
  }, [enabled, refresh]);

  // Selecting a wallet loads its detail right away instead of on the next tick.
  useEffect(() => { if (enabled && selectedId) refresh(); }, [enabled, selectedId, refresh]);

  const refreshAll = useCallback(async () => { vendorsAt.current = 0; await refresh(); }, [refresh]);
  const workspace = useMemo(() => toWorkspace(records, vendors, folders), [records, vendors, folders]);
  return { enabled, status, error, main, records, vendors, folders, workspace, updatedAt, refresh: refreshAll, upsert };
}
