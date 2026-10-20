#!/usr/bin/env bash
# setup_env.sh —— 一次装好绘图环境（幂等，可重复跑）。
#
#   bash ~/.hermes/skills/creative/publication-figures/scripts/setup_env.sh
#
# 做四件事：
#   1. 建 venv（默认 ~/.venvs/figures）并装 matplotlib/seaborn/pandas/scipy/pytest
#   2. 装合规字体（免 sudo）：Liberation Sans/Serif = Arial/Times New Roman 度量兼容；
#      Noto Sans SC = 中文标签用（中文报告/课设必需）
#   3. 让 `import paperfig` 在任何目录都可用（往 site-packages 写 .pth）
#   4. 跑自检，打印实际可用字体与预设
set -euo pipefail

SKILL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV="${PAPERFIG_VENV:-$HOME/.venvs/figures}"
PY="$VENV/bin/python"
FONTDIR="$HOME/.local/share/fonts"
PKGS="matplotlib seaborn numpy pandas scipy pypdf pytest"

log() { printf '\033[36m[setup]\033[0m %s\n' "$*"; }
die() { printf '\033[31m[setup] %s\033[0m\n' "$*" >&2; exit 1; }

# ---------------------------------------------------------------- 1. venv
if [ ! -x "$PY" ]; then
  log "建 venv → $VENV"
  if command -v uv >/dev/null 2>&1; then
    uv venv "$VENV" --python 3.12 >/dev/null
  else
    python3 -m venv "$VENV"
  fi
fi

if ! "$PY" -c "import matplotlib" 2>/dev/null; then
  log "装依赖：$PKGS"
  if command -v uv >/dev/null 2>&1; then
    uv pip install --python "$PY" -q $PKGS
  else
    "$PY" -m pip install -q --upgrade pip $PKGS
  fi
fi
"$PY" -c "import matplotlib,sys;print('[setup] matplotlib', matplotlib.__version__, 'on', sys.version.split()[0])"

# ---------------------------------------------------------------- 2. 字体
mkdir -p "$FONTDIR/liberation" "$FONTDIR/noto-cjk"
NEED_CACHE=0

want_lib=(LiberationSans-Regular.ttf LiberationSans-Bold.ttf LiberationSans-Italic.ttf
          LiberationSerif-Regular.ttf LiberationSerif-Bold.ttf)
if [ ! -f "$FONTDIR/liberation/${want_lib[0]}" ]; then
  log "装 Liberation（Arial/Times 度量兼容，OFL 许可）"
  TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT
  DEB_URL="https://archive.ubuntu.com/ubuntu/pool/main/f/fonts-liberation/fonts-liberation_2.1.5-3_all.deb"
  if curl -fsSL -o "$TMP/lib.deb" "$DEB_URL" && dpkg-deb -x "$TMP/lib.deb" "$TMP/x"; then
    cp "$TMP"/x/usr/share/fonts/truetype/liberation/*.ttf "$FONTDIR/liberation/"
    NEED_CACHE=1
  else
    log "⚠ Liberation 下载失败：拉丁字体将回退到 Nimbus Sans（Helvetica 克隆，观感亦可）"
  fi
else
  log "Liberation 已存在，跳过"
fi

if [ ! -f "$FONTDIR/noto-cjk/NotoSansSC-Regular.otf" ]; then
  log "装 Noto Sans SC（中文标签 + SIL OFL）"
  for w in Regular Bold; do
    curl -fsSL -o "$FONTDIR/noto-cjk/NotoSansSC-$w.otf" \
      "https://raw.githubusercontent.com/notofonts/noto-cjk/main/Sans/SubsetOTF/SC/NotoSansSC-$w.otf" \
      || log "⚠ Noto Sans SC 下载失败：中文会渲染成方框"
  done
  NEED_CACHE=1
else
  log "Noto Sans SC 已存在，跳过"
fi

if [ "$NEED_CACHE" = 1 ]; then
  command -v fc-cache >/dev/null 2>&1 && fc-cache -f >/dev/null 2>&1 || true
  rm -rf "$HOME/.cache/matplotlib"   # 清掉字体缓存，否则新字体不被识别
  log "字体已装好并刷新缓存"
fi

# ---------------------------------------------------------------- 3. import 路径
SP="$("$PY" -c 'import site;print(site.getsitepackages()[0])')"
printf '%s\n' "$SKILL_DIR/scripts" > "$SP/paperfig-path.pth"
log "写入 $SP/paperfig-path.pth → import paperfig 全局可用"

# ---------------------------------------------------------------- 4. 自检
if "$PY" -c "import paperfig" 2>/dev/null; then
  "$PY" -c "
import paperfig as pf
from matplotlib import font_manager as fm
avail={f.name for f in fm.fontManager.ttflist}
for n in ['Arial','Helvetica','Liberation Sans','Nimbus Sans','Times New Roman','Liberation Serif','Noto Sans SC']:
    print(f'  {n:18} {\"✓ 可用\" if n in avail else \"— 未装（会按栈顺序回退）\"}')
print('  预设：', ', '.join(pf.SPECS))
"
  "$PY" "$SKILL_DIR/scripts/paperfig.py" --selftest | tail -2
else
  die "import paperfig 失败，请检查 $SKILL_DIR/scripts"
fi

log "完成。画图脚本用这个解释器跑：$PY"
log "示例：$PY $SKILL_DIR/scripts/demo_gallery.py --outdir figures --sheet"
