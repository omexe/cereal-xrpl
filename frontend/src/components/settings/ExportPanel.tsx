import { Download01 } from '@untitledui/icons';
import { api, ApiError, type Decimal } from '../../api';
import { formatAmount } from '../../format';
import { plural, RefreshButton, Section, useRead } from './parts';

/** /export.json: every row (settled, failed or pending) plus totals over the settled payments only. */
interface ExportJson { rows: unknown[]; totals?: { payments?: number; rlusd?: Decimal } }

/** GET /export.json, read to count its records. Errors read like the shared client's (api.ts). */
async function readExport(): Promise<ExportJson> {
  let res: Response;
  try { res = await fetch(api.exportUrl('json')); }
  catch { throw new ApiError('network', 'The cereal service is not reachable.'); }
  const text = await res.text();
  let data: unknown = null;
  try { data = text ? JSON.parse(text) : null; } catch { data = text; }
  if (!res.ok) {
    const detail = data && typeof data === 'object' && 'detail' in data ? String((data as { detail: unknown }).detail) : undefined;
    throw new ApiError('http', detail ?? (res.status >= 500 ? 'The cereal service is not reachable.' : `${res.status} ${res.statusText}`), res.status, data);
  }
  const body = data as ExportJson | null;
  if (!body || typeof body !== 'object' || !Array.isArray(body.rows)) throw new Error('The service did not return an export.');
  return body;
}

/** The download attribute only works on the app's own origin; a cross-origin API base opens in a new tab instead. */
function downloadProps(href: string, file: string) {
  const sameOrigin = new URL(href, window.location.href).origin === window.location.origin;
  return sameOrigin ? { href, download: file } : { href, download: file, target: '_blank', rel: 'noreferrer' };
}

/** I07: the accounting export, every payment across wallets and rails, as CSV and JSON downloads. */
export function ExportPanel() {
  const { data, loading, error, reload } = useRead(readExport);
  const settled = data?.totals?.payments;
  return <Section name="exports" title="Exports" action={<RefreshButton label="Refresh export count" busy={loading} onClick={reload} />}>
    <p className="settings-note">Every payment across wallets and rails, with its transaction, for finance.</p>
    {error
      ? <p className="settings-error" role="alert" data-field="export-count">Could not read the export: {error}</p>
      : <p className="settings-export-count" role="status" data-field="export-count">{data
        ? `${plural(data.rows.length, 'record')}${settled === undefined ? '' : ` · ${plural(settled, 'settled payment')}`} · ${formatAmount(data.totals?.rlusd)} settled`
        : 'Counting records…'}</p>}
    <div className="settings-downloads">
      <a className="settings-download" {...downloadProps(api.exportUrl('csv'), 'cereal-payments.csv')}><Download01 aria-hidden="true" />Download CSV</a>
      <a className="settings-download" {...downloadProps(api.exportUrl('json'), 'cereal-payments.json')}><Download01 aria-hidden="true" />Download JSON</a>
    </div>
  </Section>;
}
