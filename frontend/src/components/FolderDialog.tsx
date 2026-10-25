import type { AppActions } from '../appActions';
import { isLive } from '../mode';
import { Dialog } from './Dialog';

/** A05: New folder. Mock: browser state. Live: POST /folders. */
export function FolderDialog({ app }: { app: AppActions }) {
  return <Dialog title="New folder" onClose={app.close}><form onSubmit={event => {
    event.preventDefault(); const name = String(new FormData(event.currentTarget).get('name')).trim(); if (!name) return;
    if (isLive) { app.notify('Live folders are not connected yet.', true); return; }
    app.setWorkspace(previous => ({ ...previous, folders: [...previous.folders, { id: crypto.randomUUID(), name }] })); app.close();
  }}><label>Folder name<input name="name" required maxLength={60} autoFocus /></label><button className="primary-button form-submit">Create folder</button></form></Dialog>;
}
