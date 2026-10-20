#!/usr/bin/env node
/**
 * math-render.mjs — DRAFT (research) math typesetting engine for chat surfaces.
 *
 * Pipeline:  markdown text  →  segment (text | math)  →  KaTeX syntax gate  →
 *            MathJax SVG  →  normalized SVG  →  PNG (rsvg-convert, Nx scale)  →  manifest
 *
 * Deliberately dependency-light and browser-free: no Chromium, no headless DOM.
 * Requires research-local node_modules: katex, mathjax-full (+ system rsvg-convert).
 *
 * Usage:
 *   node math-render.mjs check  <file.md|-->            # syntax gate only (exit 1 on error)
 *   node math-render.mjs render <file.md|--> -o <dir> [--scale 3] [--theme light|dark]
 */
import fs from 'node:fs';
import fs2 from 'node:fs';
import path from 'node:path';
import path2 from 'node:path';
import os2 from 'node:os';
import { execFileSync } from 'node:child_process';
import katex from 'katex';
import { mathjax } from 'mathjax-full/js/mathjax.js';
import { TeX } from 'mathjax-full/js/input/tex.js';
import { SVG } from 'mathjax-full/js/output/svg.js';
import { liteAdaptor } from 'mathjax-full/js/adaptors/liteAdaptor.js';
import { RegisterHTMLHandler } from 'mathjax-full/js/handlers/html.js';
import { AllPackages } from 'mathjax-full/js/input/tex/AllPackages.js';

// ── 1. segmentation ──────────────────────────────────────────────────────────

const DELIMS = [
  { open: '$$', close: '$$', display: true },
  { open: '\\[', close: '\\]', display: true, latexDelim: true },
  { open: '\\(', close: '\\)', display: false, latexDelim: true },
  { open: '$', close: '$', display: false, currencyGuard: true },
];

/** Split markdown into segments, protecting fenced/inline code first. */
export function segment(markdown) {
  const protectedSpans = [];
  let masked = markdown.replace(/```[\s\S]*?```|~~~[\s\S]*?~~~/g, (m) => {
    protectedSpans.push(m);
    return `\u0000CODE${protectedSpans.length - 1}\u0000`;
  });
  masked = masked.replace(/`[^`\n]*`/g, (m) => {
    protectedSpans.push(m);
    return `\u0000CODE${protectedSpans.length - 1}\u0000`;
  });

  const out = [];
  let buf = '';
  let i = 0;
  while (i < masked.length) {
    const d = DELIMS.find((x) => masked.startsWith(x.open, i));
    if (!d) { buf += masked[i++]; continue; }
    // currency guard: `$` immediately followed by a digit and closed by a non-`$` far away → treat as text
    if (d.currencyGuard) {
      const next = masked[i + 1] ?? '';
      if (next === '' || /\s/.test(next)) { buf += masked[i++]; continue; }
    }
    const closeAt = findClose(masked, i + d.open.length, d);
    if (closeAt === -1) { buf += masked[i++]; continue; }
    const body = masked.slice(i + d.open.length, closeAt);
    if (d.currencyGuard) {
      // heuristic: `$100 ... $` with no LaTeX-ish content → plain text (currency)
      if (!/[\\^_{}]/.test(body) && /^[\d.,\s%×x-]+$/.test(body)) { buf += masked[i++]; continue; }
    }
    if (buf) { out.push({ type: 'text', text: buf }); buf = ''; }
    out.push({ type: 'math', tex: d.latexDelim ? body : body, display: d.display, raw: masked.slice(i, closeAt + d.close.length) });
    i = closeAt + d.close.length;
  }
  if (buf) out.push({ type: 'text', text: buf });

  // restore protected code spans
  for (const seg of out) {
    if (seg.type !== 'text') continue;
    seg.text = seg.text.replace(/\u0000CODE(\d+)\u0000/g, (_, n) => protectedSpans[Number(n)]);
  }
  return out;
}

function findClose(s, from, d) {
  if (d.open === d.close) {
    let idx = s.indexOf(d.close, from);
    while (idx !== -1) {
      if (s[idx - 1] !== '\\') return idx;
      idx = s.indexOf(d.close, idx + 1);
    }
    return -1;
  }
  return s.indexOf(d.close, from);
}

// ── 2. KaTeX syntax gate ─────────────────────────────────────────────────────

export function validate(segments) {
  const problems = [];
  segments.filter((s) => s.type === 'math').forEach((s, n) => {
    try {
      katex.renderToString(s.tex, { displayMode: s.display, throwOnError: true, strict: 'ignore' });
      s.katex = 'PASS';
    } catch (e) {
      s.katex = 'FAIL';
      s.error = e.message;
      problems.push({ index: n, tex: s.tex, error: e.message });
    }
  });
  return problems;
}

// ── 3. SVG → PNG rendering (MathJax + rsvg-convert) ──────────────────────────

const adaptor = liteAdaptor();
RegisterHTMLHandler(adaptor);
const tex = new TeX({ packages: AllPackages });
const svgOut = new SVG({ fontCache: 'local' });
const doc = mathjax.document('', { InputJax: tex, OutputJax: svgOut });

export function mathToSvgPng(seg, outDir, { scale = 3, theme = 'light', em = 16 } = {}) {
  const node = doc.convert(seg.tex, { display: seg.display, em, ex: em / 2, containerWidth: 10000 });
  const outer = adaptor.outerHTML(node);
  const inner = outer.match(/<svg[\s\S]*<\/svg>/)?.[0] ?? outer;
  const firstTag = inner.match(/<svg[^>]*>/)?.[0] ?? '';
  const toPx = (v) => {
    const m = String(v ?? '').match(/^([\d.]+)(ex|em|px)$/);
    if (!m) return null;
    const n = Number(m[1]);
    return m[2] === 'ex' ? n * (em / 2) : m[2] === 'em' ? n * em : n;
  };
  const vb = firstTag.match(/viewBox="([-\d.]+) ([-\d.]+) ([\d.]+) ([\d.]+)"/);
  let normalized = inner;
  let widthPx = null;
  let heightPx = null;
  const withDims = (w, h) => inner.replace(/<svg([^>]*)>/, (m, attrs) =>
    `<svg${attrs.replace(/\s(width|height)="[^"]*"/g, '')} width="${w.toFixed(2)}" height="${h.toFixed(2)}">`);
  if (vb) {
    const [, , , w, h] = vb.map(Number);
    widthPx = (w / 1000) * em; heightPx = (h / 1000) * em;
    normalized = withDims(widthPx, heightPx);
  } else {
    const w = toPx(firstTag.match(/width="([^"]+)"/)?.[1]);
    const h = toPx(firstTag.match(/height="([^"]+)"/)?.[1]);
    if (w && h) { widthPx = w; heightPx = h; normalized = withDims(w, h); }
  }
  if (widthPx === null) {
    // unmeasurable (\tag / equation-with-tag): caller must treat as unsupported
    return { ok: false, reason: 'unmeasurable svg (no viewBox, width not in ex/em/px) — likely \\tag or equation numbering' };
  }
  for (const mathml of normalized.matchAll(/<mjx-container[\s\S]*?<\/mjx-container>/g)) void mathml;

  fs.mkdirSync(outDir, { recursive: true });
  const svgPath = path.join(outDir, `math-${seg.id}.svg`);
  const pngPath = path.join(outDir, `math-${seg.id}.png`);
  fs.writeFileSync(svgPath, normalized);
  const bg = theme === 'dark' ? '#1e1e1e' : 'white';
  execFileSync('rsvg-convert', ['-z', String(scale), '-b', bg, '-o', pngPath, svgPath], { stdio: 'pipe' });
  const fg = theme === 'dark' ? '#ffffff' : '#000000';
  if (fg !== '#000000') {
    // recolor for dark mode: keep white glyphs on dark background
    execFileSync('convert', [pngPath, '-alpha', 'off', '-fill', fg, '-colorize', '100', pngPath], { stdio: 'pipe' });
  }
  return { ok: true, svgPath, pngPath, widthPx, heightPx, pngBytes: fs.statSync(pngPath).size };
}

// ── 4. CLI ───────────────────────────────────────────────────────────────────

if (import.meta.url === `file://${process.argv[1]}`) {
  const [cmd, file, ...rest] = process.argv.slice(2);
  if (cmd === 'selftest') {
    // 依赖自检：缺什么就明说，不要静默降级
    const checks = [];
    const run = (name, fn) => { try { const v = fn(); checks.push({ name, ok: true, detail: String(v).slice(0, 80) }); } catch (e) { checks.push({ name, ok: false, detail: String(e.message).slice(0, 120) }); } };
    run('node', () => process.version);
    run('katex', () => `v${JSON.parse(fs2.readFileSync(new URL('../node_modules/katex/package.json', import.meta.url), 'utf8')).version}`);
    run('mathjax-full', () => `v${JSON.parse(fs2.readFileSync(new URL('../node_modules/mathjax-full/package.json', import.meta.url), 'utf8')).version}`);
    run('rsvg-convert', () => execFileSync('rsvg-convert', ['--version'], { stdio: 'pipe' }).toString().trim());
    run('imagemagick(convert)', () => execFileSync('convert', ['--version'], { stdio: 'pipe' }).toString().split('\n')[0]);
    run('montage', () => execFileSync('montage', ['--version'], { stdio: 'pipe' }).toString().split('\n')[0]);
    run('CJK font (fc-match sans:lang=zh)', () => execFileSync('fc-match', ['-f', '%{family}', 'sans:lang=zh'], { stdio: 'pipe' }).toString());
    run('smoke render', () => {
      const tmp = fs2.mkdtempSync(path2.join(os2.tmpdir(), 'math-selftest-'));
      const seg = { id: 'smoke', tex: '\\frac{a}{b}', display: false };
      const r = mathToSvgPng(seg, tmp, { scale: 2 });
      if (!r.ok) throw new Error(r.reason);
      if (!r.pngBytes) throw new Error('empty png');
      fs2.rmSync(tmp, { recursive: true, force: true });
      return `${r.pngBytes} bytes`;
    });
    const bad = checks.filter((c) => !c.ok);
    console.log(JSON.stringify({ ok: bad.length === 0, checks }, null, 1));
    process.exit(bad.length ? 1 : 0);
  }
  if (!cmd || !file) {
    console.error('usage: math-render.mjs <check|render|selftest> <file|-> [-o outdir] [--scale N] [--theme light|dark]');
    process.exit(2);
  }
  const input = file === '-' ? fs.readFileSync(0, 'utf8') : fs.readFileSync(file, 'utf8');
  const segs = segment(input);
  const problems = validate(segs);
  const mathSegs = segs.filter((s) => s.type === 'math');
  console.log(JSON.stringify({
    segments: segs.length,
    mathSegments: mathSegs.length,
    display: mathSegs.filter((s) => s.display).length,
    inline: mathSegs.filter((s) => !s.display).length,
    validationProblems: problems.length,
  }, null, 1));
  for (const p of problems) console.log(`  FAIL #${p.index}: ${p.tex.slice(0, 80)} :: ${p.error}`);

  if (cmd === 'check') process.exit(problems.length ? 1 : 0);

  const outIdx = rest.indexOf('-o');
  const outDir = outIdx >= 0 ? rest[outIdx + 1] : 'math-out';
  const scaleIdx = rest.indexOf('--scale');
  const scale = scaleIdx >= 0 ? Number(rest[scaleIdx + 1]) : 3;
  const themeIdx = rest.indexOf('--theme');
  const theme = themeIdx >= 0 ? rest[themeIdx + 1] : 'light';

  const t0 = performance.now();
  const images = [];
  let n = 0;
  for (const s of segs) {
    if (s.type !== 'math' || s.katex !== 'PASS') continue;
    s.id = `${String(++n).padStart(2, '0')}${s.display ? 'd' : 'i'}`;
    const r = mathToSvgPng(s, outDir, { scale, theme });
    images.push({ id: s.id, display: s.display, tex: s.tex, ...r, placeholder: `[[math:${s.id}]]` });
    if (!r.ok) console.log(`  render FAIL #${s.id}: ${r.reason}`);
  }
  const ms = performance.now() - t0;
  const manifest = {
    generatedAt: new Date().toISOString(),
    theme, scale,
    totalMs: Number(ms.toFixed(0)),
    images,
    // text with image placeholders, in order
    outboundText: segs.map((s) => (s.type === 'text' ? s.text : s.katex === 'PASS' && s.id ? `[[math:${s.id}]]` : s.raw ?? s.tex)).join(''),
  };
  fs.mkdirSync(outDir, { recursive: true });
  fs.writeFileSync(path.join(outDir, 'manifest.json'), JSON.stringify(manifest, null, 1));
  console.log(`rendered ${images.length} images in ${ms.toFixed(0)}ms, total ${(images.reduce((a, b) => a + (b.pngBytes ?? 0), 0) / 1024).toFixed(1)}KB`);
  console.log(`manifest: ${path.join(outDir, 'manifest.json')}`);
}
