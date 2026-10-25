import type { AppActions } from '../appActions';

/** Sites (live only): one site's checks and trust, Open (free) or Buy (payable), and what was delivered (unit 5). */
export function SiteDetail({ app, siteId }: { app: AppActions; siteId: string }) {
  void app;
  return <article className="site-detail" aria-label="Site"><h1>{siteId}</h1></article>;
}
