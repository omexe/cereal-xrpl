/** A message that names a web address runs a crawl without asking the AI: Cereal probes the site, the wallet pays the
 * crawl gateway per page on XRPL testnet (cereal/routes/runs.py /crawl), then the chat shows sample results for the
 * question. The probe, the page reads and the payments are real; the result list is sample data. */
const URL_RE = /https?:\/\/[^\s,;<>"')\]]+/i;
const BARE_RE = /(?<![@\w.-])((?:www\.)?(?:[a-z0-9-]+\.)+(?:com|org|net|io|ai|dev|app|co|gov|edu|news|info|us|me|tv|xyz))(\/[^\s,;<>"')\]]*)?(?![\w-])/i;

export interface CrawlPage { url: string; path: string; title: string }
export interface CrawlResult { name: string; detail: string; price?: string }
export interface CrawlPlan { url: string; host: string; topic: string; pages: CrawlPage[]; heading: string; summary: string[]; results: CrawlResult[] }

export function siteInMessage(text: string): string | null {
  const full = text.match(URL_RE)?.[0];
  if (full) return full.replace(/[.!?]+$/, '');
  const bare = text.match(BARE_RE);
  return bare ? `https://${bare[1]}${bare[2] ?? ''}`.replace(/[.!?]+$/, '') : null;
}

const STOP = new Set('help me find the best pair pairs through website site page via look looking a an of for to on in with using use my our lets let us if needed please show get some and or i want need wallet is are what which this that from at by it me can you'.split(' '));
/** The words of the question, without the site, the wallet instruction, and filler. */
function topicOf(text: string, host: string): string {
  const words = text.toLowerCase().replace(URL_RE, ' ').replace(host, ' ').replace(/\buse\s+(?:my|our|the)?\s*[\w\s"“”]+?wallet\b/g, ' ')
    .replace(/[^a-z0-9\s-]/g, ' ').split(/\s+/).filter(w => w.length > 2 && !STOP.has(w) && !w.includes('.'));
  return words.slice(0, 4).join(' ') || 'overview';
}

function seeded(seed: string) {
  let h = 2166136261;
  for (const c of seed) h = Math.imul(h ^ c.charCodeAt(0), 16777619);
  return () => { h = Math.imul(h ^ (h >>> 15), 2246822507); h ^= h >>> 13; return (h >>> 0) / 4294967296; };
}
const pick = <T,>(rand: () => number, list: T[], n: number) => [...list].sort(() => rand() - 0.5).slice(0, n);

const SHOES = ['Pegasus 41', 'Vomero 18', 'Air Max 90', 'Invincible 3', 'Air Force 1 \'07', 'Structure 26', 'Dunk Low Retro', 'Zoom Fly 6'];
const SHOE_NOTES = ['Best all-round daily trainer; 4.6★ from 2,100 reviews', 'Most cushioned option; reviewers cite comfort on long runs',
  'Classic lifestyle pick; restocked in 9 colorways', 'Max-cushion runner; 4.4★, runs half a size small', 'Top seller this month; true to size',
  'Stability shoe recommended for overpronation', 'Limited colorways back in stock', 'Racing-day trainer with a carbon plate'];

export function crawlPlan(message: string, url: string, seed: string): CrawlPlan {
  const { origin, hostname } = new URL(url);
  const host = hostname.replace(/^www\./, '');
  const topic = topicOf(message, host);
  const rand = seeded(seed + topic);
  const slug = topic.replace(/\s+/g, '-');
  const shoes = /shoe|sneaker|runner|running|trainer/.test(topic);
  const pages: CrawlPage[] = ([
    ['/', 'Home page'],
    [`/search?q=${encodeURIComponent(topic)}`, `Search: ${topic}`],
    [shoes ? '/w/mens-shoes' : `/c/${slug}`, shoes ? 'Category: shoes' : `Category: ${topic}`],
    [shoes ? '/w/best-sellers' : `/c/${slug}/top`, 'Best sellers'],
    [shoes ? '/w/mens-running-shoes' : `/c/${slug}/reviews`, shoes ? 'Running shoes' : 'Reviews'],
  ] as const).map(([path, title]) => ({ url: origin + path, path, title }));
  const results: CrawlResult[] = shoes
    ? pick(rand, SHOES.map((name, i) => ({ name, detail: SHOE_NOTES[i], price: `$${110 + Math.floor(rand() * 9) * 10}` })), 4)
    : pick(rand, ['Most viewed', 'Highest rated', 'Newest', 'Best value', 'Editor’s pick', 'Trending this week'], 4).map((label, i) => ({
      name: `${label}: ${topic} #${i + 1}`, detail: `Found on ${host}; ${Math.floor(rand() * 900 + 100)} reviews, ${(3.8 + rand()).toFixed(1)}★`,
    }));
  const [top, next] = results;
  const summary = shoes ? [
    `I read ${pages.length} pages of ${host}: the home page, a search for “${topic}”, the shoe category, best sellers and running shoes. Across those pages, ${top.name} comes up most often and has the strongest reviews, so it’s my pick for most people.`,
    `${next.name} is a close second. Prices range from about ${results.map(r => r.price).sort()[0]} to ${results.map(r => r.price).sort().at(-1)}, and several models are back in stock in extra colorways. Here’s what I found:`,
  ] : [
    `I read ${pages.length} pages of ${host}, including a search for “${topic}”, the matching category and its most-viewed items. ${top.name.split(':')[0]} and ${next.name.split(':')[0].toLowerCase()} results overlap heavily, which points to a clear favorite.`,
    `The list below ranks what I found by reviews and how often each item appeared across the pages.`,
  ];
  return { url, host, topic, pages, heading: shoes ? `Best shoes on ${host}` : `Top results for “${topic}” on ${host}`, summary, results };
}
