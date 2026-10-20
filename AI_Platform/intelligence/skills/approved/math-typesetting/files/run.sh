#!/usr/bin/env bash
# run.sh — 一条命令把含公式的消息变成可发送的正文 + 图片。
#
#   bash /mnt/d/OpenClaw/workspace/skills/math-typesetting/run.sh <message.md> [outdir] [scale]
#
# 输出：outdir/reply.txt（正文 + MEDIA 行，直接作为回复发出即可）
#       outdir/sheet-*.png（块级公式拼页）
set -euo pipefail

SKILL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MSG="${1:?usage: run.sh <message.md> [outdir] [scale]}"
OUT="${2:-/tmp/math-out-$(date +%H%M%S)}"
SCALE="${3:-3}"

node "$SKILL_DIR/scripts/math-render.mjs" selftest >/dev/null || {
  echo "❌ 依赖自检失败，请先看：node $SKILL_DIR/scripts/math-render.mjs selftest" >&2
  exit 1
}

node "$SKILL_DIR/scripts/math-to-image.mjs" "$MSG" -o "$OUT" --scale "$SCALE"

echo
echo "=== 可直接作为回复发出的正文（含 MEDIA 行）==="
cat "$OUT/reply.txt"
echo "=== 结束 ==="
