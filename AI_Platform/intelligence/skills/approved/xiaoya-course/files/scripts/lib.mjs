// Shared raw-CDP helpers for the 小雅 / 理工智课 (ai-augmented.com) course platform.
//
// Why raw CDP instead of playwright: playwright-core's connectOverCDP hangs on
// Chrome 153 browser endpoints ("Timeout 30000ms exceeded" after <ws connected>),
// while plain websocket CDP commands answer immediately.
//
// Safety contract for this file: it never returns or logs an `authorization`
// header value. The token is captured inside the page (`window.__cap`) and used
// only by in-page fetch calls.

import { createRequire } from 'node:module';
import { pathToFileURL } from 'node:url';

const req = createRequire(import.meta.url);

export const DEFAULT_CDP = process.env.CDP_URL || 'http://127.0.0.1:9222';

async function importWs() {
  const candidates = [
    () => req.resolve('ws'),
    () => req.resolve('ws', { paths: [process.env.OPENCLAW_NODE_MODULES || '/home/huyi/.npm-global/lib/node_modules/openclaw'] }),
    () => req.resolve('ws', { paths: ['/usr/lib/node_modules'] }),
  ];
  for (const c of candidates) {
    try {
      return (await import(pathToFileURL(c()).href)).default;
    } catch (_) { /* try next */ }
  }
  throw new Error('cannot resolve the "ws" module; npm i ws or set OPENCLAW_NODE_MODULES to a dir that contains it');
}

export class Cdp {
  constructor(ws) { this.ws = ws; this.nextId = 1; this.pending = new Map(); this.events = []; }

  static async connect(cdpUrl = DEFAULT_CDP) {
    const WebSocket = await importWs();
    const ver = await (await fetch(`${cdpUrl}/json/version`)).json();
    const ws = new WebSocket(ver.webSocketDebuggerUrl, { origin: cdpUrl, maxPayload: 256 * 1024 * 1024 });
    await new Promise((res, rej) => { ws.on('open', res); ws.on('error', rej); });
    const cdp = new Cdp(ws);
    cdp.browser = ver.Browser;
    ws.on('message', (raw) => cdp._onMessage(raw));
    return cdp;
  }

  _onMessage(raw) {
    let msg;
    try { msg = JSON.parse(raw.toString()); } catch { return; }
    if (msg.id && this.pending.has(msg.id)) {
      const { resolve, reject } = this.pending.get(msg.id);
      this.pending.delete(msg.id);
      msg.error ? reject(new Error(JSON.stringify(msg.error))) : resolve(msg.result);
      return;
    }
    if (msg.method) this.events.push(msg);
  }

  send(method, params = {}, sessionId) {
    const id = this.nextId++;
    this.ws.send(JSON.stringify(sessionId ? { id, method, params, sessionId } : { id, method, params }));
    return new Promise((resolve, reject) => {
      // The timer is unref'd and cleared: a stray 120s timer keeps node alive
      // long after the work is done (this bit us during development).
      const timer = setTimeout(() => {
        if (this.pending.has(id)) { this.pending.delete(id); reject(new Error(`CDP timeout: ${method}`)); }
      }, 60000);
      timer.unref();
      this.pending.set(id, {
        resolve: (v) => { clearTimeout(timer); resolve(v); },
        reject: (e) => { clearTimeout(timer); reject(e); },
      });
    });
  }

  async pages() {
    const { targetInfos } = await this.send('Target.getTargets');
    return targetInfos.filter((t) => t.type === 'page');
  }

  /** Resolve a page by id prefix, by substring of its URL, or by index. */
  async resolvePage(key) {
    const list = await this.pages();
    if (key == null) return list[0];
    return list.find((t) => t.targetId.startsWith(key))
      || list.find((t) => t.url.includes(key))
      || list[Number(key)];
  }

  async attach(key) {
    const t = await this.resolvePage(key);
    if (!t) throw new Error(`no page target matched ${key}`);
    const { sessionId } = await this.send('Target.attachToTarget', { targetId: t.targetId, flatten: true });
    await this.send('Page.enable', {}, sessionId);
    await this.send('Runtime.enable', {}, sessionId);
    return { sessionId, target: t };
  }

  async openTab(url) {
    const { targetId } = await this.send('Target.createTarget', { url });
    return targetId;
  }

  async evaluate(sessionId, expression) {
    // Callers pass a complete expression (or an IIFE) — no auto-wrapping here:
    // guessing "is this a function?" rewraps expressions that are already called.
    const src = String(expression);
    const r = await this.send('Runtime.evaluate', {
      expression: src, awaitPromise: true, returnByValue: true, userGesture: true,
    }, sessionId);
    if (r.exceptionDetails) {
      throw new Error(r.exceptionDetails.text + ' ' + (r.exceptionDetails.exception?.description || ''));
    }
    return r.result?.value;
  }

  close() { try { this.ws.close(); } catch (_) {} }
}

/** Percent-encode only the characters ow365/quote style URLs need (ported from the app itself). */
export function bytes(n) {
  if (n == null) return '?';
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / 1024 / 1024).toFixed(2)} MB`;
}

/** D:\OpenClaw\tmp -> /mnt/d/OpenClaw/tmp  (returns null when not a WSL-visible Windows path). */
export function winToWsl(p) {
  const m = /^([A-Za-z]):[\\/](.*)$/.exec(p || '');
  if (!m) return null;
  return `/mnt/${m[1].toLowerCase()}/${m[2].replace(/\\/g, '/')}`;
}

export const AUTH_HOOK = `(() => {
  if (window.__cap) return;
  window.__cap = { headers: {}, urls: [] };
  const note = (k, v) => {
    try {
      const lk = String(k).toLowerCase();
      window.__cap.headers[lk] = v;
      if (lk === 'authorization') window.__cap.auth = v;
    } catch (e) {}
  };
  const origOpen = XMLHttpRequest.prototype.open;
  const origSet = XMLHttpRequest.prototype.setRequestHeader;
  XMLHttpRequest.prototype.open = function (m, u, ...rest) {
    try { window.__cap.urls.push(String(u)); } catch (e) {}
    return origOpen.call(this, m, u, ...rest);
  };
  XMLHttpRequest.prototype.setRequestHeader = function (k, v) { note(k, v); return origSet.call(this, k, v); };
  const origFetch = window.fetch;
  window.fetch = function (input, init) {
    try {
      const src = (init && init.headers) || (input && input.headers) || null;
      if (src && typeof src.forEach === 'function' && typeof src.get === 'function') src.forEach((v, k) => note(k, v));
      else if (src) for (const k of Object.keys(src)) note(k, src[k]);
    } catch (e) {}
    return origFetch.apply(this, arguments);
  };
})();`;

/** Only these request headers are replayed; the hook also records our own probes
 *  (a stale `range` header once turned every replay into a 206 partial body). */
export const HEADER_ALLOW = /^(authorization|token|x-language|x-lrs-application|x-lrs-device|x-lrs-domain|content-type)$/;

/** In-page helper: replay an authenticated GET with the app's own headers. */
export const IN_PAGE_JSON_GET = `(async (path) => {
  const cap = window.__cap || {};
  const h = {};
  for (const [k, v] of Object.entries(cap.headers || {})) {
    if (!${HEADER_ALLOW.toString()}.test(k)) continue;
    h[k] = v;
  }
  const r = await fetch(path, { credentials: 'include', headers: h });
  const text = await r.text();
  let json = null;
  try { json = JSON.parse(text); } catch (e) {}
  return { status: r.status, json, text: json ? null : text.slice(0, 400) };
})`;

/** Install the auth hook and make sure `window.__cap.auth` is populated. */
export async function ensureAuth(cdp, sessionId, { reloadWaitMs = 12000 } = {}) {
  const alive = await cdp.evaluate(sessionId, '!!(window.__cap && window.__cap.auth)').catch(() => false);
  if (alive) return { reloaded: false };
  await cdp.send('Page.addScriptToEvaluateOnNewDocument', { source: AUTH_HOOK }, sessionId);
  await cdp.send('Page.reload', {}, sessionId);
  const deadline = Date.now() + reloadWaitMs;
  while (Date.now() < deadline) {
    await new Promise((r) => setTimeout(r, 800));
    const ok = await cdp.evaluate(sessionId, '!!(window.__cap && window.__cap.auth)').catch(() => false);
    if (ok) return { reloaded: true };
  }
  return { reloaded: true, ok: false };
}

/** Parse a course URL into { origin, courseId, nodeId }. */
export function parseCourseUrl(url) {
  const m = /^(https?:\/\/[^/]+)\/app\/jx-web\/mycourse\/(\d+)(?:\/resource\/(\d+))?/.exec(url);
  if (!m) throw new Error(`not a 小雅 course URL: ${url}`);
  return { origin: m[1], courseId: m[2], nodeId: m[3] || null };
}

export function redactUrl(u) {
  try { const p = new URL(u); return `${p.origin}${p.pathname.slice(0, 60)} (query ${p.search.length} chars)`; }
  catch { return '(unparsable url)'; }
}
