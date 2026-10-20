#!/usr/bin/env node
/**
 * render-math.mjs — 共享技能库的**单一入口**。给"没有 write 工具、exec 走 allowlist"
 * 的 agent 一条能无人值守跑通的命令形状。
 *
 *   node /mnt/d/OpenClaw/workspace/skills/math-typesetting/bin/render-math.mjs \
 *        --out <dir> --text '<含公式的 markdown>' [--scale 3] [--theme light|dark]
 *
 * 为什么要有它（2026-09-23 Hermes 侧记）：
 *   - 各 agent 的 exec 是 `security=allowlist`：只有"单段、无重定向、无命令替换"的命令能
 *     自动运行；heredoc（cat > file <<EOF）、`>`、`$()` 一律弹审批，而无人值守会话没有人能点。
 *   - 所以"把正文写成文件再渲染"这条路在后台会话里走不通；本脚本自己写临时文件，
 *     调用方只需要一条命令 + 一个 --text 参数。
 *   - 配套的 approvals 允许项（每条一行，path-only 或 argPattern 收紧到本脚本）：
 *       pattern=/usr/bin/node
 *       argPattern=^/mnt/d/OpenClaw/workspace/skills/math-typesetting/bin/render-math\.mjs( .*)?$
 *
 * 本脚本自身做文件 I/O（不是 shell 重定向），因此不受"allowlist 模式不支持重定向"限制。
 */
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { execFileSync } from 'node:child_process';

const SKILL_DIR = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const argv = process.argv.slice(2);
const flag = (name, dflt) => {
  const i = argv.indexOf(name);
  return i >= 0 ? argv[i + 1] : dflt;
};

if (argv.includes('--help') || argv.includes('-h')) {
  console.log(`usage: node ${path.relative(process.cwd(), fileURLToPath(import.meta.url))} ` +
    `--out <dir> (--text '<markdown>' | --in <file.md>) [--scale 3] [--theme light|dark]\n` +
    `\n注意：--out 必须在**你自己 agent 的工作区内**（MEDIA 附件白名单按工作区判定）。`);
  process.exit(0);
}

const outDir = flag('--out', null);
const text = flag('--text', null);
const inFile = flag('--in', null);
const scale = flag('--scale', '3');
const theme = flag('--theme', 'light');

if (!outDir || (!text && !inFile)) {
  console.error('render-math: 需要 --out <dir> 以及 --text 或 --in 之一');
  process.exit(2);
}

const absOut = path.resolve(outDir);
fs.mkdirSync(absOut, { recursive: true });

// 1) 源消息落到 outDir/message.md（本脚本自己写，不经 shell 重定向）
const msgFile = path.join(absOut, 'message.md');
const body = inFile ? fs.readFileSync(inFile, 'utf8') : text;
fs.writeFileSync(msgFile, body, 'utf8');

// 2) 依赖自检（失败会明说缺什么）
try {
  execFileSync('node', [path.join(SKILL_DIR, 'scripts', 'math-render.mjs'), 'selftest'],
    { cwd: SKILL_DIR, stdio: 'pipe' });
} catch (err) {
  console.error('render-math: 依赖自检失败 —— 先跑 node scripts/math-render.mjs selftest');
  process.stderr.write(err.stdout ? err.stdout.toString() : '');
  process.stderr.write(err.stderr ? err.stderr.toString() : '');
  process.exit(1);
}

// 3) 渲染（语法闸门不过会以非 0 退出，透传它的输出）
try {
  const out = execFileSync('node',
    [path.join(SKILL_DIR, 'scripts', 'math-to-image.mjs'), msgFile, '-o', absOut,
      '--scale', String(scale), '--theme', String(theme)],
    { cwd: SKILL_DIR, stdio: 'pipe' });
  process.stdout.write(out.toString());
} catch (err) {
  process.stdout.write(err.stdout ? err.stdout.toString() : '');
  process.stderr.write(err.stderr ? err.stderr.toString() : '');
  console.error('render-math: 渲染失败（语法闸门或依赖问题），详见上面的输出');
  process.exit(1);
}

// 4) 把可直接发出的正文（含 MEDIA 行）打到 stdout
const reply = path.join(absOut, 'reply.txt');
if (fs.existsSync(reply)) {
  console.log('=== reply.txt（正文 + MEDIA 行，直接作为回复发出） ===');
  process.stdout.write(fs.readFileSync(reply, 'utf8'));
  console.log('=== 结束 ===');
} else {
  console.error('render-math: 没有产出 reply.txt，检查上面的统计输出');
  process.exit(1);
}
