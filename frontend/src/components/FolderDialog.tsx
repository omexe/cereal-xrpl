import { useEffect, useRef, useState, type FormEvent } from 'react';
import { api, ApiError, describeError, type Folder } from '../api';
import type { AppActions } from '../appActions';
import { isLive } from '../mode';
import { Dialog } from './Dialog';

const MAX_NAME = 60;

/** Why the service refused a folder name, in words (POST /folders refusals). */
function folderError(error: unknown): string {
  if (error instanceof ApiError && error.kind === 'refused') {
    if (error.refused === 'folder_exists') return `A folder named “${(error.body as { folder?: Folder }).folder?.name ?? ''}” already exists.`;
    if (error.refused === 'invalid_folder_name') return `Folder names are 1 to ${MAX_NAME} printable characters.`;
  }
  return describeError(error);
}

/** A05: New folder. Mock: browser state. Live: POST /folders, then re-read; duplicate or invalid names show inline. */
export function FolderDialog({ app }: { app: AppActions }) {
  const [error, setError] = useState<string>();
  const [busy, setBusy] = useState(false);
  // A request can outlive the dialog (Escape while it runs): then report through the status line, and never close
  // whichever dialog the user opened since.
  const open = useRef(true);
  useEffect(() => { open.current = true; return () => { open.current = false; }; }, []);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const name = String(new FormData(event.currentTarget).get('name')).trim();
    if (!isLive) {
      if (!name) return;
      app.setWorkspace(previous => ({ ...previous, folders: [...previous.folders, { id: crypto.randomUUID(), name }] })); app.close();
      return;
    }
    if (!name) { setError('Name the folder.'); return; }
    const taken = app.workspace.folders.find(folder => folder.name.trim().toLowerCase() === name.toLowerCase());
    if (taken) { setError(`A folder named “${taken.name}” already exists.`); return; }
    setBusy(true); setError(undefined);
    let created: Folder;
    try { created = (await api.createFolder(name)).folder; }
    catch (e) {
      if (open.current) { setError(folderError(e)); setBusy(false); } else app.notify(`Folder not created. ${folderError(e)}`, true);
      return;
    }
    await app.live.refresh();
    if (open.current) app.close();
    app.notify(`Folder “${created.name}” created.`);
  }

  return <Dialog title="New folder" onClose={app.close}><form onSubmit={submit} noValidate={isLive}>
    <label>Folder name<input name="name" required maxLength={MAX_NAME} autoFocus aria-invalid={!!error}
      aria-describedby={error ? 'folder-error' : undefined} onChange={() => setError(undefined)} /></label>
    {error && <p id="folder-error" className="status-message error" role="alert">{error}</p>}
    <button className="primary-button form-submit" disabled={busy}>{busy ? 'Creating…' : 'Create folder'}</button>
  </form></Dialog>;
}
