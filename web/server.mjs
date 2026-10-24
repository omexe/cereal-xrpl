/**
 * Read-only dev server for the Cereal dashboard (Part 5).
 *
 * Serves static files from web/public on http://localhost:5173 (or PORT)
 * and proxies GET /api/* -> http://localhost:8001/*.
 *
 * Strictly enforces GET-only on /api/* so the dashboard can never mutate
 * state (never deploy, pay, reclaim, or revoke).
 */

import http from 'node:http';
import { readFile } from 'node:fs/promises';
import { dirname, extname, join, normalize } from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = dirname(fileURLToPath(import.meta.url));
const PUBLIC_DIR = join(HERE, 'public');
const PORT = Number(process.env.PORT || 5173);
const HOST = process.env.HOST || '127.0.0.1';
const UPSTREAM = (process.env.CEREAL_API_URL || 'http://127.0.0.1:8001').replace(/\/+$/, '');

const MIME_TYPES = {
  '.html': 'text/html; charset=utf-8',
  '.css': 'text/css; charset=utf-8',
  '.js': 'application/javascript; charset=utf-8',
  '.mjs': 'application/javascript; charset=utf-8',
  '.json': 'application/json; charset=utf-8',
  '.svg': 'image/svg+xml',
  '.png': 'image/png',
  '.ico': 'image/x-icon',
};

async function proxyGet(req, res, upstreamPath) {
  if (req.method !== 'GET' && req.method !== 'HEAD') {
    res.writeHead(405, {
      'Content-Type': 'application/json; charset=utf-8',
      Allow: 'GET, HEAD',
    });
    res.end(JSON.stringify({ ok: false, refused: 'read_only_dashboard', method: req.method }));
    return;
  }

  const targetUrl = `${UPSTREAM}${upstreamPath}`;
  try {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 15000);
    const upstreamResp = await fetch(targetUrl, {
      method: 'GET',
      headers: { Accept: 'application/json' },
      signal: controller.signal,
    });
    clearTimeout(timer);

    const body = await upstreamResp.text();
    res.writeHead(upstreamResp.status, {
      'Content-Type': upstreamResp.headers.get('content-type') || 'application/json; charset=utf-8',
      'Cache-Control': 'no-store',
    });
    res.end(req.method === 'HEAD' ? undefined : body);
  } catch (err) {
    res.writeHead(502, {
      'Content-Type': 'application/json; charset=utf-8',
      'Cache-Control': 'no-store',
    });
    res.end(
      JSON.stringify({
        ok: false,
        refused: 'upstream_unavailable',
        upstream: UPSTREAM,
        error: err?.message ?? String(err),
      })
    );
  }
}

const server = http.createServer(async (req, res) => {
  const url = new URL(req.url || '/', `http://${req.headers.host || 'localhost'}`);

  if (url.pathname === '/api' || url.pathname.startsWith('/api/')) {
    const upstreamPath = (url.pathname.slice(4) || '/') + url.search;
    await proxyGet(req, res, upstreamPath);
    return;
  }

  if (req.method !== 'GET' && req.method !== 'HEAD') {
    res.writeHead(405, { 'Content-Type': 'text/plain; charset=utf-8' });
    res.end('Method Not Allowed');
    return;
  }

  const safePath = normalize(url.pathname === '/' ? '/index.html' : url.pathname).replace(/^(\.\.(\/|\\|$))+/, '');
  const filePath = join(PUBLIC_DIR, safePath);

  try {
    const content = await readFile(filePath);
    const ext = extname(filePath).toLowerCase();
    res.writeHead(200, {
      'Content-Type': MIME_TYPES[ext] || 'application/octet-stream',
      'Cache-Control': 'no-cache',
    });
    res.end(req.method === 'HEAD' ? undefined : content);
  } catch {
    res.writeHead(404, { 'Content-Type': 'text/plain; charset=utf-8' });
    res.end('Not Found');
  }
});

server.listen(PORT, HOST, () => {
  console.log(`Cereal read-only dashboard listening on http://${HOST}:${PORT} (proxying GET /api/* -> ${UPSTREAM}/*)`);
});
