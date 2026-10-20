#!/usr/bin/env node
/**
 * math-to-image.mjs — 把一条含公式的消息变成「能直接发出去的东西」。
 *
 * 输入：一条消息的 markdown 文本（含 $...$ / $$...$$ / \(...\) / \[...\]）
 * 输出：
 *   <outdir>/math-*.png        每个公式一张图
 *   <outdir>/sheet-*.png       块级公式拼页（默认高度 ≤2000px，超了自动分页）
 *   <outdir>/reply.txt         可直接作为回复发出的正文（含 MEDIA: 行）
 *   <outdir>/manifest.json     全部元数据
 *
 * 用法：
 *   node math-to-image.mjs <file.md|-> -o <outdir> [--scale 3] [--theme light|dark]
 *                          [--max-sheet-height 2000] [--max-width 1800] [--no-sheet]
 */
import fs from 'node:fs';
import path from 'node:path';
import { execFileSync } from 'node:child_process';
import { segment, validate, mathToSvgPng } from './math-render.mjs';

const argv = process.argv.slice(2);
const flag = (name, dflt) => {
  const i = argv.indexOf(name);
  return i >= 0 ? argv[i + 1] : dflt;
};
const file = argv[0];
if (!file || flag('-o') === undefined) {
  console.error('usage: math-to-image.mjs <file.md|-> -o <outdir> [--scale 3] [--theme light|dark] [--max-sheet-height 2000] [--max-width 1800] [--no-sheet]');
  process.exit(2);
}
const outDir = flag('-o');
const scale = Number(flag('--scale', '3'));
const theme = flag('--theme', 'light');
const maxSheetHeight = Number(flag('--max-sheet-height', '2000'));
const maxWidth = Number(flag('--max-width', '1800'));
const inlineMode = flag('--inline', 'keep'); // keep | image
const wantSheet = !argv.includes('--no-sheet');

const text = file === '-' ? fs.readFileSync(0, 'utf8') : fs.readFileSync(file, 'utf8');
const segs = segment(text);
const problems = validate(segs);

const mathSegs = segs.filter((s) => s.type === 'math');
const stats = {
  segments: segs.length,
  math: mathSegs.length,
  inline: mathSegs.filter((s) => !s.display).length,
  display: mathSegs.filter((s) => s.display).length,
  validationProblems: problems.length,
};
console.log(JSON.stringify(stats, null, 1));
if (problems.length) {
  for (const p of problems) console.log(`  FAIL: ${p.tex.slice(0, 70)} :: ${p.error}`);
  console.log('语法闸门未通过 —— 按技能规则：先修 LaTeX，不要发送。');
  process.exit(1);
}

fs.mkdirSync(outDir, { recursive: true });
const images = [];
let n = 0;
for (const s of segs) {
  if (s.type !== 'math') continue;
  s.id = `${String(++n).padStart(2, '0')}${s.display ? 'd' : 'i'}`;
  const r = mathToSvgPng(s, outDir, { scale, theme });
  if (!r.ok) {
    images.push({ id: s.id, display: s.display, tex: s.tex, ok: false, reason: r.reason });
    continue;
  }
  images.push({
    id: s.id, display: s.display, tex: s.tex, ok: true,
    png: r.pngPath, widthPx: Math.round(r.widthPx * scale), heightPx: Math.round(r.heightPx * scale), bytes: r.pngBytes,
  });
}

// ── 块级公式拼页 ────────────────────────────────────────────────────────────
const sheets = [];
if (wantSheet) {
  const displays = images.filter((i) => i.display && i.ok);
  if (displays.length > 1) {
    let page = [];
    let h = 0;
    const pad = 36; // 每式上下留白
    for (const img of displays) {
      if (page.length && h + img.heightPx + pad * 2 > maxSheetHeight) { sheets.push(page); page = []; h = 0; }
      page.push(img); h += img.heightPx + pad * 2;
    }
    if (page.length) sheets.push(page);
  }
}
const sheetFiles = [];
sheets.forEach((page, idx) => {
  const out = path.join(outDir, `sheet-${idx + 1}.png`);
  execFileSync('montage', [
    ...page.map((p) => p.png),
    '-tile', '1x', '-geometry', '+40+18', '-background', theme === 'dark' ? '#1e1e1e' : 'white',
    '-bordercolor', theme === 'dark' ? '#1e1e1e' : 'white', '-border', '20', out,
  ], { stdio: 'pipe' });
  const dims = execFileSync('identify', ['-format', '%wx%h', out]).toString();
  const [w, h] = dims.split('x').map(Number);
  if (w > maxWidth) {
    execFileSync('convert', [out, '-resize', `${maxWidth}x`, out], { stdio: 'pipe' });
  }
  const finalDims = execFileSync('identify', ['-format', '%wx%h', out]).toString();
  sheetFiles.push({ file: out, dims: finalDims, bytes: fs.statSync(out).size, formulas: page.map((p) => p.id) });
});

// ── 组装可直接发出的正文 ────────────────────────────────────────────────────
// 公式 id -> 所属拼页（0-based）；不在任何拼页里的（拼页关闭或只有单个块级公式）单独附图
const sheetOf = new Map();
sheetFiles.forEach((s, idx) => s.formulas.forEach((id) => sheetOf.set(id, idx)));
const emittedSheets = new Set();
let inlineN = 0;
const bodyParts = [];
for (const s of segs) {
  if (s.type === 'text') { bodyParts.push(s.text); continue; }
  if (!s.display) {
    inlineN++;
    if (inlineMode === 'image') bodyParts.push(`MEDIA:${images.find((i) => i.id === s.id)?.png ?? ''}`);
    // 默认 keep：保留原文（技能规定 image 渠道不要写行内公式，这里只是不丢内容）
    else bodyParts.push(s.raw ?? `$${s.tex}$`);
    continue;
  }
  const sheetIdx = sheetOf.get(s.id);
  if (sheetIdx !== undefined) {
    if (emittedSheets.has(sheetIdx)) { bodyParts.push(''); continue; }
    emittedSheets.add(sheetIdx);
    bodyParts.push(`MEDIA:${sheetFiles[sheetIdx].file}`);
    continue;
  }
  bodyParts.push(`MEDIA:${images.find((i) => i.id === s.id)?.png ?? ''}`);
}
const replyText = bodyParts.join('').replace(/\n{3,}/g, '\n\n').trim();

fs.writeFileSync(path.join(outDir, 'reply.txt'), replyText + '\n');
const manifest = {
  generatedAt: new Date().toISOString(),
  scale, theme, maxSheetHeight, maxWidth, inlineMode,
  stats, images, sheets: sheetFiles,
  replyFile: path.join(outDir, 'reply.txt'),
  notes: [
    `行内公式处理：${inlineMode}（keep = 保留 $...$ 原文，不丢内容；image = 每个行内公式单独附图）`,
    'QQ 的 Markdown 内嵌图片只认公网 URL，本地文件无法内嵌 → 公式只能作为独立图片消息（msg_type=7）发送。',
    `拼页规则：块级公式按序拼成若干张，单张高度 ≤ ${maxSheetHeight}px，宽度压到 ≤ ${maxWidth}px。`,
    '投递：整段 reply.txt 作为文本发出，MEDIA: 行会让 OpenClaw 把图作为附件发送。',
  ],
};
fs.writeFileSync(path.join(outDir, 'manifest.json'), JSON.stringify(manifest, null, 1));

const totalBytes = images.reduce((a, b) => a + (b.bytes ?? 0), 0) + sheetFiles.reduce((a, b) => a + b.bytes, 0);
console.log(`公式图 ${images.length} 张（${(totalBytes / 1024).toFixed(1)}KB total）｜拼页 ${sheetFiles.length} 张 ${sheetFiles.map((s) => s.dims).join(', ') || '-'}`);
console.log(`正文已写好：${manifest.replyFile}`);
if (inlineMode === 'keep' && stats.inline > 0) {
  console.log(`\n⚠️ 检测到 ${stats.inline} 处行内公式：在不能渲染数学的渠道（QQ/WebChat）里它们会以源码形式出现在正文中。`);
  console.log('   建议：把这些公式改写为独立成行的块级公式（会被收进拼页图），句子里用自然语言指代。');
  console.log('   如确需逐式附图：加 --inline image（会多出 N 条图片消息，慎用）。');
}
