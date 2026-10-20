#!/usr/bin/env node
/**
 * check-print.mjs — 发送前的"印刷体闸门"。检查一条准备发给小主人的消息是否还带着
 * LaTeX / ASCII 近似 / 把数学塞进代码块这类会让它看起来不像印刷体的问题。
 *
 *   node bin/check-print.mjs <message.md>          # 只检查
 *   node bin/check-print.mjs <message.md> --fix    # 顺手用 latex-to-print 修掉 LaTeX
 *   echo '...' | node bin/check-print.mjs -
 *
 * 退出码：0 = 通过；1 = 有需要修的地方（输出里逐条列出，带行号）。
 */
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { execFileSync } from 'node:child_process';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const argv = process.argv.slice(2);
const file = argv.find((a) => !a.startsWith('-'));
const doFix = argv.includes('--fix');
const text = (!file || file === '-') ? fs.readFileSync(0, 'utf8') : fs.readFileSync(file, 'utf8');

const MATHY = /[²³ⁿ₀₁₂₃₄₅₆₇₈₉∫√Σ∂μσλπθ≤≥≠≈⇒∈·×−]|\bf\(|\\[a-zA-Z]/;
const problems = [];
const lines = text.split('\n');
let inFence = false;

lines.forEach((line, i) => {
  const n = i + 1;
  if (/^\s*```/.test(line)) { inFence = !inFence; return; }
  if (/\$/.test(line)) problems.push([n, 'LaTeX 分隔符 $ —— 渠道不渲染，会原样显示', line.trim()]);
  if (/\\[a-zA-Z]{2,}/.test(line)) problems.push([n, 'LaTeX 命令（\\frac 之类）', line.trim()]);
  if (inFence && MATHY.test(line)) {
    problems.push([n, '数学被放进了 ``` 代码块 —— 等宽字体看起来像代码，不像印刷体；改成普通段落', line.trim()]);
  }
  if (!inFence) {
    if (/<=|>=|!=|->|=>|\bsqrt\(/.test(line)) problems.push([n, 'ASCII 近似（<= >= != -> => sqrt(）应换成 ≤ ≥ ≠ → ⇒ √', line.trim()]);
    if (/[A-Za-z0-9]\^[0-9{]/.test(line) || /[A-Za-z]\)?_[0-9a-z]\b/.test(line)) problems.push([n, 'ASCII 上下标（^ _）应换成 ²/₀ 或 ^(...)/_(...)', line.trim()]);
  }
});

let out = text;
if (doFix && problems.length) {
  out = execFileSync('node', [path.join(HERE, 'latex-to-print.mjs'), '-'], { input: text }).toString();
}

if (!problems.length) {
  console.log('✅ 印刷体闸门通过（无 LaTeX、无 ASCII 近似、代码块里没有数学）');
  if (doFix) process.stdout.write(out);
  process.exit(0);
}

console.log(`⚠️ 印刷体闸门：${problems.length} 处要改`);
for (const [n, why, ctx] of problems.slice(0, 40)) console.log(`  L${n}: ${why}\n       ${ctx.slice(0, 90)}`);
console.log('\n改法：node ' + path.join(HERE, 'latex-to-print.mjs') + ' <你的消息.md> [-o 输出.md]  （把 LaTeX 转成印刷体字符）');
if (doFix) process.stdout.write(out);
process.exit(1);
