#!/usr/bin/env node
// 小雅 / 理工智课 (ai-augmented.com) course scraper.
//
//   node xy-course.mjs pages
//   node xy-course.mjs open    <courseUrl>
//   node xy-course.mjs tree    <courseUrl>
//   node xy-course.mjs download <courseUrl> --out 'D:\dir' [--match 关键字] [--node id,id] [--dry-run] [--types 6,9]
//
// Attaches to an already-running Chrome (CDP_URL, default http://127.0.0.1:9222)
// so the user's own login session is reused. Never prints auth tokens or signed
// download URLs.
import { Cdp, ensureAuth, parseCourseUrl, bytes, winToWsl, IN_PAGE_JSON_GET, HEADER_ALLOW } from './lib.mjs';

const [, , cmd, ...rest] = process.argv;
const args = {};
const positional = [];
for (let i = 0; i < rest.length; i++) {
  const a = rest[i];
  if (a.startsWith('--')) {
    const k = a.slice(2);
    const v = rest[i + 1] && !rest[i + 1].startsWith('--') ? rest[++i] : true;
    args[k] = v;
  } else positional.push(a);
}

// type 6 = uploaded file, 9 = media (video); seen on 2026-09-16.
const DEFAULT_TYPES = [6, 9];

function wslToWin(p) {
  const m = /^\/mnt\/([a-z])\/(.*)$/.exec(p || '');
  if (!m) return null;
  return `${m[1].toUpperCase()}:\\${m[2].replace(/\//g, '\\')}`;
}

async function connectCourseTab(courseUrl) {
  const { origin } = parseCourseUrl(courseUrl);
  const cdp = await Cdp.connect();
  let page = (await cdp.pages()).find((t) => t.url.startsWith(origin));
  let opened = false;
  if (!page) {
    const targetId = await cdp.openTab(courseUrl);
    opened = true;
    await new Promise((r) => setTimeout(r, 6000));
    page = (await cdp.pages()).find((t) => t.targetId === targetId);
  }
  if (!page) throw new Error('could not open a course tab');
  const { sessionId } = await cdp.attach(page.targetId);
  return { cdp, sessionId, origin, opened, page };
}

/** Read the whole course tree. Returns [{id,parent_id,type,mimetype,name,resource_type}]. */
async function readTree(cdp, sessionId, courseId) {
  const path = `/api/jx-iresource/resource/queryCourseResources/v2?group_id=${courseId}`;
  const r = await cdp.evaluate(sessionId, `(${IN_PAGE_JSON_GET})(${JSON.stringify(path)})`);
  if (r.status !== 200 || !r.json) throw new Error(`tree request failed: ${r.status} ${r.text || ''}`);
  return r.json.data || [];
}

/** quote_id (the real file handle) for a tree node. */
async function readResource(cdp, sessionId, courseId, nodeId) {
  const path = `/api/jx-iresource/resource/queryResource/v3?node_id=${nodeId}&group_id=${courseId}`;
  const r = await cdp.evaluate(sessionId, `(${IN_PAGE_JSON_GET})(${JSON.stringify(path)})`);
  if (r.status !== 200 || !r.json?.data) return null;
  return r.json.data;
}

async function prepare(courseUrl) {
  const { courseId, origin } = parseCourseUrl(courseUrl);
  const { cdp, sessionId, opened } = await connectCourseTab(courseUrl);
  const auth = await ensureAuth(cdp, sessionId);
  if (auth.ok === false) {
    console.error('登录态没抓到：请在打开的标签页里登录，然后重跑。');
    process.exit(2);
  }
  return { cdp, sessionId, courseId, origin, opened, reloaded: auth.reloaded };
}

function printTree(nodes) {
  const byId = new Map(nodes.map((n) => [n.id, n]));
  const depth = (n) => { let d = 0, p = n.parent_id; while (p && byId.has(p)) { d++; p = byId.get(p).parent_id; } return d; };
  for (const n of nodes) {
    if (n.name === 'root') continue;
    const kind = n.type === 1 ? 'DIR ' : n.type === 6 ? 'FILE' : n.type === 9 ? 'MEDIA' : `t${n.type}`;
    const mt = n.mimetype ? n.mimetype.replace(/^application\/vnd\.openxmlformats-officedocument\./, 'ooxml.') : '';
    console.log(`${'  '.repeat(depth(n))}[${kind}] ${n.id}  ${n.name}${mt ? '  (' + mt + ')' : ''}`);
  }
}

if (cmd === 'pages') {
  const cdp = await Cdp.connect();
  for (const t of await cdp.pages()) console.log(`${t.targetId}  ${t.title.slice(0, 50)}  ${t.url.slice(0, 100)}`);
  cdp.close();
} else if (cmd === 'open') {
  const url = positional[0];
  const { cdp, sessionId, opened, reloaded } = await prepare(url);
  const info = await cdp.evaluate(sessionId, '({url: location.href, title: document.title, login: !/login/i.test(location.href)})');
  console.log(JSON.stringify({ ...info, openedNewTab: opened, reloaded }, null, 1));
  cdp.close();
} else if (cmd === 'tree') {
  const { cdp, sessionId, courseId } = await prepare(positional[0]);
  printTree(await readTree(cdp, sessionId, courseId));
  cdp.close();
} else if (cmd === 'download') {
  const courseUrl = positional[0];
  const outWin = args.out;
  if (!outWin) { console.error('需要 --out <Windows 目录，例如 D:\\OpenClaw\\tmp>'); process.exit(1); }
  const types = String(args.types || DEFAULT_TYPES.join(',')).split(',').map(Number);
  const { cdp, sessionId, courseId } = await prepare(courseUrl);

  const nodes = await readTree(cdp, sessionId, courseId);
  let wanted = nodes.filter((n) => types.includes(n.type));
  if (args.match) wanted = wanted.filter((n) => n.name.includes(args.match));
  if (args.node) {
    const ids = new Set(String(args.node).split(','));
    wanted = wanted.filter((n) => ids.has(n.id));
  }
  if (!wanted.length) { console.log('没有匹配的文件节点'); cdp.close(); process.exit(0); }

  await cdp.send('Browser.setDownloadBehavior', { behavior: 'allow', downloadPath: outWin, eventsEnabled: true });
  const outWsl = winToWsl(outWin);
  const results = [];

  for (const n of wanted) {
    const res = await readResource(cdp, sessionId, courseId, n.id);
    const entry = { name: n.name, node: n.id, quote: res?.quote_id || null, ok: false };
    if (!res?.quote_id) { entry.error = '没有 quote_id（可能只是目录或任务节点）'; results.push(entry); continue; }
    if (args['dry-run']) { entry.ok = null; results.push(entry); continue; }

    const before = outWsl ? await listDir(outWsl) : null;
    const fire = `(async () => {
      const path = '/api/jx-oresource/cloud/file_down/${res.quote_id}/v2?filename=' + encodeURIComponent(${JSON.stringify(n.name)});
      const cap = window.__cap || {};
      const h = {};
      for (const [k, v] of Object.entries(cap.headers || {})) {
        if (!${HEADER_ALLOW.toString()}.test(k)) continue;
        h[k] = v;
      }
      const r = await fetch(path, { credentials: 'include', headers: h });
      const j = await r.json();
      const url = j?.data?.download_url;
      if (!url) return { error: 'no download_url', status: r.status, keys: Object.keys(j?.data || {}) };
      const probe = await fetch(url, { headers: { Range: 'bytes=0-3' } });
      const a = document.createElement('a');
      a.href = url; a.download = ${JSON.stringify(n.name)}; a.rel = 'noopener';
      document.body.appendChild(a); a.click(); a.remove();
      return { host: new URL(url).host, rangeStatus: probe.status, declared: j.data.size ?? null };
    })()`;
    const r = await cdp.evaluate(sessionId, fire);
    if (r?.error) { entry.error = `${r.error} (status ${r.status}, keys ${JSON.stringify(r.keys)})`; results.push(entry); continue; }
    entry.host = r.host;
    entry.declared = r.declared;

    if (outWsl) {
      for (let i = 0; i < 60; i++) {
        await new Promise((res2) => setTimeout(res2, 1000));
        const after = await listDir(outWsl);
        const gained = [...after.entries()].filter(([f, s]) => !before.has(f) && s > 0);
        if (gained.some(([f]) => f === n.name || f.startsWith(n.name))) { entry.ok = true; break; }
        const partial = [...after.entries()].find(([f]) => f.includes('.crdownload'));
        if (!partial && i > 5 && gained.length) { entry.ok = true; break; }
      }
      if (!entry.ok) entry.error = '文件没出现在输出目录（可能被 Chrome 的"多文件下载"提示拦了，去浏览器允许一次）';
    } else {
      await new Promise((res2) => setTimeout(res2, 8000));
      entry.ok = null;
      entry.note = '输出目录不在 WSL 可见路径下，没做落盘校验';
    }
    results.push(entry);
  }

  console.log(JSON.stringify(results.map((r) => ({ ...r, declared: r.declared != null ? bytes(r.declared) : null })), null, 1));
  console.log(`\n输出目录: ${outWin}${outWsl ? `  (WSL: ${outWsl})` : ''}`);
  cdp.close();
} else {
  console.log('用法: node xy-course.mjs pages|open|tree|download ...');
  process.exit(1);
}

async function listDir(dir) {
  const { readdir, stat } = await import('node:fs/promises');
  const out = new Map();
  try {
    for (const f of await readdir(dir)) {
      if (f.endsWith('.crdownload')) continue;
      try { out.set(f, (await stat(`${dir}/${f}`)).size); } catch (_) {}
    }
  } catch (_) {}
  return out;
}
