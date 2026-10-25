import type { AppActions } from '../appActions';
import { Dialog } from './Dialog';

/** Sites (live only): sign in if needed, enter a URL, see the probe card, add it to my sites (unit 5). */
export function AddSiteDialog({ app, url }: { app: AppActions; url?: string }) {
  return <Dialog title="Add a site" onClose={app.close}><p className="dialog-description">{url ?? ''}</p></Dialog>;
}
