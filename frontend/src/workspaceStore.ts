import { useEffect, useSyncExternalStore } from 'react';
import { loadWorkspace, STORAGE_KEY, type Workspace } from './wallets';
import { advanceResearch, reconcilePayments } from './researchDemo';

const emptyWorkspace: Workspace = { wallets: [], folders: [] };
let snapshot: Workspace | undefined;
function getSnapshot() { return snapshot ??= loadWorkspace(); }
let storageError = '';
const listeners = new Set<() => void>();
const emit = () => listeners.forEach(listener => listener());
function refresh() { if (snapshot) { snapshot = loadWorkspace(); emit(); } }
if (typeof window !== 'undefined') {
  window.addEventListener('storage', event => { if (event.key === STORAGE_KEY || event.key === null) refresh(); });
  window.addEventListener('focus', refresh);
}
const subscribe = (listener: () => void) => { listeners.add(listener); return () => { listeners.delete(listener); }; };

/** One shared document + a browser-wide lock: wallet edits and payments cannot overwrite each other. */
export async function mutateWorkspace<T>(mutate: (state: Workspace) => T): Promise<T> {
  try {
    if (!navigator.locks) throw new Error('This demo needs a browser with Web Locks. Open it on localhost in a current Chrome, Edge, or Safari browser.');
    return await navigator.locks.request(`${STORAGE_KEY}-workspace`, () => {
      const draft = structuredClone(loadWorkspace());
      const result = mutate(draft);
      reconcilePayments(draft);
      const serialized = JSON.stringify(draft);
      if (localStorage.getItem(STORAGE_KEY) !== serialized) localStorage.setItem(STORAGE_KEY, serialized);
      const changed = JSON.stringify(snapshot) !== serialized || storageError !== '';
      storageError = '';
      if (changed) { snapshot = draft; emit(); }
      return result;
    });
  } catch (error) {
    storageError = error instanceof Error ? error.message : 'Could not save the demo. Check browser storage and try again.';
    emit(); throw error;
  }
}

export function useWorkspace(enabled = true) {
  const workspace = useSyncExternalStore(subscribe, () => enabled ? getSnapshot() : emptyWorkspace);
  const error = useSyncExternalStore(subscribe, () => enabled ? storageError : '');
  function setWorkspace(update: Workspace | ((previous: Workspace) => Workspace)) {
    return mutateWorkspace(state => Object.assign(state, typeof update === 'function' ? update(state) : update)).catch(() => undefined);
  }
  return { workspace, setWorkspace, error };
}

/** Either open tool can drive the demo. Multiple tabs serialize through the same lock. */
export function useResearchRunner(enabled = true) {
  useEffect(() => {
    if (!enabled) return;
    void mutateWorkspace(() => undefined).catch(() => undefined);
    let stopped = false;
    let timer: number;
    async function tick() {
      if (snapshot?.researchRuns?.some(run => run.status === 'running' || run.status === 'waiting')) {
        try {
          await mutateWorkspace(state => {
            for (const run of state.researchRuns ?? []) advanceResearch(state, run.id);
          });
        } catch { /* surfaced through useWorkspace; no payment state is committed on failure */ }
      }
      if (!stopped) timer = window.setTimeout(tick, 700);
    }
    timer = window.setTimeout(tick, 700);
    return () => { stopped = true; clearTimeout(timer); };
  }, [enabled]);
}
