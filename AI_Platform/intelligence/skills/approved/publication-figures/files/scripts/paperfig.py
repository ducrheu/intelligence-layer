#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""paperfig —— 出版级科研绘图引擎（Hermes skill `publication-figures` 的核心）。

设计原则（不可协商）：
  1. 尺寸在创建时定死：所有尺寸用 mm 指定，导出即为最终尺寸，绝不"画大字再缩小"。
  2. 一次 setup() 定全局样式，不在每张图里改 rcParams。
  3. 矢量主件（PDF/SVG/EPS）+ 300dpi PNG 预览同时交付。
  4. 颜色色盲安全 + 灰度可辨；禁止 jet/rainbow/tab10 等默认色板。
  5. 导出前自审（字号下限、图宽、字体族、PNG 实际像素）——把"看起来还行"变成可核对的数字。

用法::

    import paperfig as pf
    pf.setup("nature")                      # 期刊预设，一次性
    fig, ax = pf.subplots("single", height_mm=58)
    pf.line_ci(ax, x, y, lo, hi, label="方法 A")
    pf.finish(ax)
    pf.save(fig, "fig1_trend", claim="A 的误差随样本量单调下降")

中文报告 / 课程设计::

    pf.setup("report", lang="zh")
    fig, ax = pf.subplots("double", height_mm=70)

自检::

    python paperfig.py --selftest
"""
from __future__ import annotations

import csv
import datetime as _dt
import os
import random
import re
import struct
import sys
from pathlib import Path

import matplotlib

if (not os.environ.get("DISPLAY") and not os.environ.get("WAYLAND_DISPLAY")
        and sys.platform.startswith("linux")):
    matplotlib.use("Agg")

import matplotlib as mpl
import matplotlib.pyplot as plt
import numpy as np
from matplotlib import font_manager as _fm
from matplotlib.colors import LinearSegmentedColormap

__all__ = [
    "setup", "spec", "subplots", "save", "audit_fig", "finish", "despine",
    "panel_labels", "line_ci", "bars", "scatter_fit", "heatmap", "sig_bracket",
    "legend_outside", "direct_label", "mixed_text", "seed", "colors", "C", "MM", "mm", "cm", "SPECS",
]

MM = 1.0 / 25.4                    # mm -> inch
mm = lambda v: v * MM              # noqa: E731
cm = lambda v: v * 10 * MM         # noqa: E731

# --------------------------------------------------------------------------- #
# 期刊预设：数字全部来自各刊官方投稿指南（见 references/journal-specs.md）
# --------------------------------------------------------------------------- #
SPECS = {
    "nature": dict(
        cn="Nature 及自然子刊",
        width=dict(single=89, onehalf=120, double=183), max_height=247,
        base_pt=7, min_pt=5, panel_pt=8, panel_fmt="a",
        family="sans", line_pt=0.75, spine_pt=0.5, dpi=300,
        formats=("pdf", "png", "svg"),
        note="正文≤7pt、最小5pt；面板标签 8pt 粗体正体 a/b/c；线宽 0.25–1pt；文字不可栅格化（Nature 官方）",
    ),
    "science": dict(
        cn="Science / AAAS",
        width=dict(single=57, onehalf=121, double=174), max_height=235,
        base_pt=7, min_pt=5, panel_pt=8, panel_fmt="a",
        family="sans", line_pt=0.75, spine_pt=0.5, dpi=300,
        formats=("pdf", "eps", "png"),
        note="单栏 57mm（很窄，需极简）；1.5栏 121mm；通栏 174mm。Helvetica 优先",
    ),
    "cell": dict(
        cn="Cell / Cell Press",
        width=dict(single=85, onehalf=114, double=174), max_height=230,
        base_pt=7, min_pt=5.5, panel_pt=9, panel_fmt="a",
        family="sans", line_pt=0.6, spine_pt=0.5, dpi=300,
        formats=("pdf", "png", "svg"),
        note="字号 6–8pt，面板字母 8–10pt 粗体；线宽 0.5–1pt",
    ),
    "ieee": dict(
        cn="IEEE Transactions / Letters",
        width=dict(single=88.9, onehalf=137, double=181.9), max_height=241.3,
        base_pt=8, min_pt=8, panel_pt=8, panel_fmt="(a)",
        family="serif", line_pt=0.8, spine_pt=0.6, dpi=600,
        formats=("pdf", "eps", "png"),
        note="最终尺寸下字号 ≥8pt；线稿 600dpi、照片 300dpi；Times/Helvetica/Arial；面板标签带括号 (a)",
    ),
    "acs": dict(
        cn="ACS（JACS / ACS Nano 等）",
        width=dict(single=84.7, onehalf=127, double=177.8), max_height=233.4,
        base_pt=8, min_pt=8, panel_pt=9, panel_fmt="(A)",
        family="sans", line_pt=0.75, spine_pt=0.5, dpi=300,
        formats=("pdf", "png", "eps"),
        note="字号 ≥8pt 是硬要求；TOC 图 82.55×44.45mm；线宽 0.5–1pt",
    ),
    "elsevier": dict(
        cn="Elsevier / 工程类期刊",
        width=dict(single=90, onehalf=140, double=190), max_height=240,
        base_pt=8, min_pt=6, panel_pt=9, panel_fmt="(a)",
        family="sans", line_pt=0.75, spine_pt=0.5, dpi=300,
        formats=("pdf", "png", "eps"),
        note="单栏 90mm、1.5栏 140mm、通栏 190mm；字号 6–8pt",
    ),
    "neurips": dict(
        cn="NeurIPS / ICML / ICLR（机器学习）",
        width=dict(single=139.7, onehalf=139.7, double=139.7), max_height=None,
        base_pt=9, min_pt=7, panel_pt=10, panel_fmt="(a)",
        family="serif", line_pt=0.8, spine_pt=0.6, dpi=300,
        formats=("pdf", "png", "svg"),
        note="正文栏宽 5.5in=139.7mm；正文 10pt 时图内 7–9pt 可读",
    ),
    # ---- 非投稿场景（国内教学/汇报最常见） ----
    "report": dict(
        cn="实验报告 / 课程设计 / 毕业论文（中文）",
        width=dict(single=120, onehalf=140, double=155), max_height=None,
        base_pt=9, min_pt=7, panel_pt=10.5, panel_fmt="(a)",
        family="sans", line_pt=0.9, spine_pt=0.7, dpi=300,
        formats=("png", "pdf", "svg"),
        note="A4 正文宽 155mm；图内 9–10.5pt 与五号/小四正文协调；默认出 300dpi PNG 便于插入 Word，同时留矢量件",
    ),
    "slide": dict(
        cn="幻灯片 / 海报 / 答辩 PPT",
        width=dict(single=150, onehalf=200, double=300), max_height=None,
        base_pt=14, min_pt=11, panel_pt=18, panel_fmt="(a)",
        family="sans", line_pt=1.4, spine_pt=1.0, dpi=200,
        formats=("png", "pdf"),
        note="远距离阅读：字号 ≥11pt（推荐 14pt+），线宽加粗，去细节保结论",
    ),
}

FONT_STACKS = {
    "sans": ["Helvetica", "Arial", "Liberation Sans", "Nimbus Sans", "DejaVu Sans"],
    "serif": ["Times New Roman", "Liberation Serif", "Nimbus Roman", "DejaVu Serif"],
}
CJK_SANS = ["Noto Sans SC", "Noto Sans CJK SC", "Source Han Sans SC", "Microsoft YaHei", "SimHei", "Droid Sans Fallback"]
CJK_SERIF = ["Noto Serif CJK SC", "Source Han Serif SC", "SimSun", "Droid Sans Fallback"]

# Wong (2011) Nature Methods 色盲安全色板，顺序即默认类别顺序
PALETTES = {
    "okabe": ["#0072B2", "#E69F00", "#009E73", "#D55E00",
              "#56B4E9", "#CC79A7", "#F0E442", "#333333"],
    # 知性低饱和期刊色（CNS 常用观感）
    "journal": ["#2166AC", "#B2182B", "#1B7837", "#F1A340",
                "#762A83", "#666666", "#4393C3", "#D6604D"],
    # 灰度打印安全序列（黑白论文/复印件）
    "print": ["#1A1A1A", "#7F7F7F", "#BFBFBF", "#000000", "#555555", "#999999"],
}

_SEQ_BLUE = ["#F7FBFF", "#C6DBEF", "#6BAED6", "#2171B5", "#08306B"]
_SEQ_RED = ["#FFF5F0", "#FCBBA1", "#FB6A4A", "#CB181D", "#67000D"]
_DIV = ["#053061", "#4393C3", "#F7F7F7", "#D6604D", "#67001F"]
_DIV_SAFE = ["#0072B2", "#7BB5D6", "#F5F5F5", "#F0A860", "#D55E00"]

STATE = {
    "style": None,
    "spec": None,
    "lang": "en",
    "palette": "okabe",
    "stack": [],
    "cjk": [],
    "cmaps": False,
}


# --------------------------------------------------------------------------- #
# 注册自定义色图
# --------------------------------------------------------------------------- #
def _register_cmaps() -> None:
    if STATE["cmaps"]:
        return
    defs = {"pf_seq": _SEQ_BLUE, "pf_seq_r": _SEQ_RED, "pf_div": _DIV,
            "pf_div_safe": _DIV_SAFE, "pf_grey": ["#FFFFFF", "#E8E8E8", "#9A9A9A", "#3A3A3A", "#000000"]}
    for name, cols in defs.items():
        try:
            mpl.colormaps.register(LinearSegmentedColormap.from_list(name, cols), name=name, force=True)
        except Exception:
            pass
    STATE["cmaps"] = True


# --------------------------------------------------------------------------- #
# setup / spec
# --------------------------------------------------------------------------- #
def _pick(styles: list[str]) -> tuple[list[str], str]:
    """返回 (可用的字体族栈, 第一个可用字体名)。"""
    avail = {f.name for f in _fm.fontManager.ttflist}
    ok = [f for f in styles if f in avail]
    return (ok or ["DejaVu Sans"]), (ok[0] if ok else "DejaVu Sans")


def setup(style: str = "nature", lang: str = "auto", palette: str = "okabe",
          usetex: bool = False, grid: bool = False, base_pt: float | None = None,
          space: str = "constrained", verbose: bool = True) -> dict:
    """设定全局绘图样式，返回该预设的 spec。之后所有 figure 都继承它。

    style   : SPECS 的键（nature/science/cell/ieee/acs/elsevier/neurips/report/slide）
    lang    : "auto"（默认）拉丁字体打底 + 中文字体兜底，出现汉字不会变方框；
              "zh" 同上并明确按中文排版（报告/课设用它）；"en" 只用拉丁字体
              （投稿英文刊时用它，审计会对混进图里的汉字直接报错）
    palette : okabe（默认，色盲安全）/ journal / print（灰度）
    space   : "constrained"（默认，自动防重叠）/ "tight" / None
    """
    if style not in SPECS:
        raise ValueError(f"未知预设 {style!r}，可选：{', '.join(SPECS)}")
    spec_ = dict(SPECS[style])
    _register_cmaps()

    latin, chosen_latin = _pick(FONT_STACKS[spec_["family"]])
    want_cjk = lang not in ("en", "EN", "latin")
    cjk_ok, chosen_cjk = ([], "")
    if want_cjk:
        cjk_ok, chosen_cjk = _pick(CJK_SANS if spec_["family"] == "sans" else CJK_SERIF)
    stack = latin + cjk_ok if cjk_ok else latin
    base = float(base_pt or spec_["base_pt"])
    tick_pt = max(base - 0.5, spec_["min_pt"])   # 刻度/图例字号不得跌破该刊下限

    rc = {
        # 字体与字号。
        # 关键：font.family 必须直接给"字体名列表"，matplotlib 才会逐字形回退
        # （缺字时自动去下一个字体找）。若写成泛名 'sans-serif' 再靠 font.sans-serif
        # 列字体，回退不生效，中文会渲染成方框——这是实测结论，不要改回去。
        "font.family": stack,
        ("font.sans-serif" if spec_["family"] == "sans" else "font.serif"): stack,
        "font.size": base,
        "axes.titlesize": base,
        "axes.labelsize": base,
        "xtick.labelsize": tick_pt,
        "ytick.labelsize": tick_pt,
        "legend.fontsize": tick_pt,
        "figure.titlesize": base + 1,
        # 版式
        "axes.spines.top": False,
        "axes.spines.right": False,
        "axes.linewidth": spec_["spine_pt"],
        "axes.edgecolor": "#222222",
        "xtick.direction": "out",
        "ytick.direction": "out",
        "xtick.major.width": spec_["spine_pt"],
        "ytick.major.width": spec_["spine_pt"],
        "xtick.major.size": 2.6,
        "ytick.major.size": 2.6,
        "lines.linewidth": spec_["line_pt"],
        "lines.markersize": 3.2,
        "legend.frameon": False,
        "legend.handlelength": 1.6,
        "legend.columnspacing": 1.0,
        "legend.borderaxespad": 0.3,
        "axes.grid": bool(grid),
        "grid.linewidth": 0.35,
        "grid.color": "#DDDDDD",
        "grid.alpha": 0.6,
        "axes.axisbelow": True,
        # 导出
        "pdf.fonttype": 42,        # TrueType 嵌入（文字可编辑，不转曲）
        "ps.fonttype": 42,
        "svg.fonttype": "none",    # SVG 保留可编辑文字
        "savefig.bbox": "standard",  # 保持创建尺寸，不做 tight 裁剪
        "savefig.pad_inches": 0.02,
        "figure.constrained_layout.use": space == "constrained",
        "figure.constrained_layout.h_pad": 0.02,
        "figure.constrained_layout.w_pad": 0.02,
        "figure.dpi": 100,
        "text.usetex": bool(usetex),
        "axes.unicode_minus": False,   # 用字体自带减号，避免 CJK 字体缺字
    }
    # 数学字体与正文一致（无 LaTeX 也拿得到出版级公式）
    if usetex:
        rc["text.latex.preamble"] = r"\usepackage{amsmath}\usepackage{amssymb}"
    else:
        if cjk_ok or chosen_latin != "DejaVu Sans":
            rc.update({
                "mathtext.fontset": "custom",
                "mathtext.rm": chosen_latin,
                "mathtext.it": f"{chosen_latin}:italic",
                "mathtext.bf": f"{chosen_latin}:bold",
                "mathtext.sf": chosen_latin,
                "mathtext.tt": f"{chosen_latin}",
                "mathtext.cal": f"{chosen_latin}:italic",
            })
        else:
            rc["mathtext.fontset"] = "dejavusans"

    mpl.rcParams.update(rc)
    STATE.update(style=style, spec=spec_,
                 lang=("zh" if str(lang).lower() in ("zh", "cn", "zh-cn") else ("auto" if cjk_ok else "en")),
                 palette=palette, stack=stack, cjk=cjk_ok)

    if verbose:
        msg = [f"[paperfig] 预设 {style}（{spec_['cn']}）  基准 {base}pt / 最小 {spec_['min_pt']}pt"]
        msg.append(f"  拉丁字体 → {chosen_latin}" + ("" if chosen_latin in ("Arial", "Helvetica", "Times New Roman") else "（Arial/Helvetica/Times 未安装时的度量兼容替代）"))
        if cjk_ok:
            msg.append(f"  中文字体 → {chosen_cjk}（兜底，不影响拉丁字形）")
        elif STATE["lang"] == "zh":
            msg.append("  ⚠ 未找到中文字体：先跑 scripts/setup_env.sh 装 Noto Sans SC，否则中文会变方框")
        msg.append(f"  列宽 单栏 {spec_['width']['single']}mm / 1.5栏 {spec_['width']['onehalf']}mm / 通栏 {spec_['width']['double']}mm"
                   + (f" / 页深上限 {spec_['max_height']}mm" if spec_["max_height"] else ""))
        print("\n".join(msg))
    return spec_


def spec() -> dict:
    """当前预设。"""
    if STATE["spec"] is None:
        setup(verbose=False)
    return STATE["spec"]


def colors(n: int | None = None, palette: str | None = None) -> list[str]:
    """取 n 个类别色（不足则循环，超出会有重复——请改用更少类别或分组）。"""
    pal = PALETTES[palette or STATE["palette"]]
    if n is None:
        return list(pal)
    if n > len(pal):
        print(f"[paperfig] ⚠ 请求 {n} 个颜色但色板只有 {len(pal)} 个：图例条目过多，考虑合并类别或直接标注")
    return [pal[i % len(pal)] for i in range(n)]


class _C:
    """语义色（Nature/Cell 惯用）：蓝=基准/对照，红=强调/风险，绿=处理/改善，灰=背景。

    也支持取值：``C[0]`` / ``C[:3]`` 等价于当前色板的类别色，便于"默认顺序"随手取。
    """
    BLUE, RED, GREEN, ORANGE, PURPLE, GREY, BLACK = "#2166AC", "#B2182B", "#1B7837", "#F1A340", "#762A83", "#999999", "#222222"
    SEQ, SEQ_RED, DIV, DIV_SAFE, GREY_CMAP = "pf_seq", "pf_seq_r", "pf_div", "pf_div_safe", "pf_grey"

    def __getitem__(self, i):
        return colors()[i]

    def __len__(self):
        return len(colors())

    @staticmethod
    def cat(n=None):
        return colors(n)


C = _C()


def seed(n: int = 0) -> None:
    """固定随机种子（任何含随机性的图发布前必调）。"""
    np.random.seed(n)
    random.seed(n)


# --------------------------------------------------------------------------- #
# 画布
# --------------------------------------------------------------------------- #
def _width_mm(width) -> float:
    s = spec()
    if isinstance(width, str):
        if width not in s["width"]:
            raise ValueError(f"width 只能是 {list(s['width'])} 或 mm 数值")
        return float(s["width"][width])
    return float(width)


def subplots(width="single", height_mm: float | None = None, ratio: float = 0.62,
             nrows: int = 1, ncols: int = 1, **kw):
    """按 mm 建画布。返回 (fig, ax) 或 (fig, axes 数组)。

    width : "single" / "onehalf" / "double"（按当前预设）或直接给 mm
    height_mm : 不给则按 ratio 推（ratio=0.62 接近黄金比，单轴图观感稳）
    """
    w = _width_mm(width)
    h = float(height_mm) if height_mm else w * ratio * nrows / max(ncols, 1) * (1.15 if nrows > 1 else 1.0)
    fig, axes = plt.subplots(nrows, ncols, figsize=(w * MM, h * MM), **kw)
    if nrows == 1 and ncols == 1:
        return fig, axes
    return fig, np.atleast_1d(axes).ravel()   # 统一展平：axes[0]..axes[n-1]


# --------------------------------------------------------------------------- #
# 常用元件
# --------------------------------------------------------------------------- #
def despine(ax, keep=("left", "bottom")) -> None:
    """只留需要的轴脊（默认左+下）。"""
    for side in ("top", "right", "left", "bottom"):
        ax.spines[side].set_visible(side in keep)


def finish(ax, legend: bool | str = False, despine_axes: bool = True, tight_ylim: bool = False):
    """收尾：去多余轴脊 + 图例（"out" 放轴外，"in" 放轴内空白角）。"""
    if despine_axes:
        despine(ax)
    if tight_ylim:
        from matplotlib.ticker import MaxNLocator
        ax.yaxis.set_major_locator(MaxNLocator(nbins=6))
    if legend == "out":
        legend_outside(ax)
    elif legend:
        ax.legend(loc="best")
    return ax


def legend_outside(ax, ncol: int | None = None, anchor=(1.02, 1.0), loc="upper left"):
    """图例移到轴外（不要压在数据上）。"""
    h, l = ax.get_legend_handles_labels()
    if not h:
        return None
    ncol = ncol or (1 if len(h) <= 5 else 2)
    return ax.legend(h, l, loc=loc, bbox_to_anchor=anchor, ncol=ncol, borderaxespad=0.0)


def direct_label(ax, x, y, text, color=None, dx=2, dy=0, ha="left", va="center", **kw):
    """直接把标签写在曲线末端（顶替图例，减少一次视线跳转）。"""
    return ax.annotate(text, (x, y), textcoords="offset points", xytext=(dx, dy),
                       ha=ha, va=va, color=color, **kw)


def mixed_text(ax, x, y, s, fontsize=None, ha="left", va="baseline", transform=None,
               color=None, gap_pt=0.6, **kw):
    """写"汉字 + $公式$"混排的文本。

    为什么需要它：matplotlib 的 mathtext 不做逐字形字体回退 —— 只要一个字符串里出现
    ``$...$``，整串的非公式部分就只用第一个字体渲染，汉字会变成方框（matplotlib 3.11
    实测，与 mathtext.fontset 无关）。这里按 ``$`` 拆段、逐段量宽度后依次摆放，
    视觉上与单条文本一致。

    限制：x 轴为对数坐标时宽度换算不准，改用两个独立 text() 手工定位。
    返回各段落 text 对象列表。
    """
    segs = [t for t in re.split(r"(\$[^$]*\$)", s) if t]
    tr = ax.transData if transform is None else transform
    if len(segs) <= 1 or not STATE["cjk"]:
        return [ax.text(x, y, s, fontsize=fontsize, ha=ha, va=va, transform=tr,
                        color=color, **kw)]

    fig = ax.figure
    fig.canvas.draw()                       # 需要 renderer 才能量文字宽度
    rnd = fig.canvas.get_renderer()
    ax_px = ax.get_window_extent(rnd).width
    if tr is ax.transAxes:
        scale = 1.0 / ax_px                 # 换算成"轴宽比例"
    else:
        x0, x1 = ax.get_xlim()
        scale = (x1 - x0) / ax_px           # 换算成"数据单位"

    texts = [ax.text(0, 0, seg, fontsize=fontsize, ha="left", va=va, transform=tr,
                     color=color, **kw) for seg in segs]
    widths = [t.get_window_extent(rnd).width * scale for t in texts]
    gap = gap_pt * fig.dpi / 72.0 * scale   # 段间距（pt → 目标单位）
    total = sum(widths) + gap * (len(segs) - 1)
    start = x - total if ha == "right" else (x - total / 2 if ha == "center" else x)
    cur = start
    for t, w in zip(texts, widths):
        t.set_position((cur, y))
        cur += w + gap
    return texts


def line_ci(ax, x, y, lo=None, hi=None, label=None, color=None, alpha=0.22,
            marker=None, band=True, **kw):
    """带置信带的折线（半透明带优于密集误差棒）。返回 (line, band)。"""
    color = color or colors(1)[0]
    b = None
    if band and lo is not None and hi is not None:
        b = ax.fill_between(x, lo, hi, color=color, alpha=alpha, linewidth=0, label=kw.pop("band_label", None))
    ln, = ax.plot(x, y, color=color, label=label, marker=marker, **kw)
    return ln, b


def bars(ax, categories, values, errs=None, err_label=None, points=None,
         series_names=None, colors_=None, horizontal=False, annotate=False,
         value_fmt="{:.2f}", base0=True, bar_width=0.72, points_alpha=0.55,
         capsize=2, **kw):
    """柱状图（论文/报告里最常被滥用的图，这里把该有的都补齐）。

    values : shape (n_cat,) 单系列；shape (n_cat, n_series) 分组柱
    errs   : 同形状；配合 err_label 明确误差含义（"95% CI"/"SD"/"SEM"）——不写含义会被审稿人打回
    points : 同形状或 list of 1D；叠加个体数据点（避免"柱子掩盖分布"）
    """
    cats = list(categories)
    V = np.asarray(values, dtype=float)
    multi = V.ndim == 2
    ns = V.shape[1] if multi else 1
    cs = colors_ if colors_ else colors(ns)
    E = np.asarray(errs, dtype=float) if errs is not None else None
    y0 = 0 if base0 else None

    handles = []
    x = np.arange(len(cats))
    for j in range(ns):
        v = V[:, j] if multi else V
        e = (E[:, j] if multi else E) if E is not None else None
        off = (j - (ns - 1) / 2) * (bar_width / ns) if multi else 0.0
        w = bar_width / ns if multi else bar_width
        elab = err_label if (j == 0 and err_label) else None
        if horizontal:
            h = ax.barh(x + off, v, height=w, color=cs[j], label=(series_names[j] if series_names else None),
                        xerr=e, capsize=capsize, error_kw=dict(elinewidth=0.6, label=elab), **kw)
        else:
            h = ax.bar(x + off, v, width=w, color=cs[j], label=(series_names[j] if series_names else None),
                       yerr=e, capsize=capsize, error_kw=dict(elinewidth=0.6, label=elab), **kw)
        handles.append(h)
        if points is not None:
            try:
                P = points[j] if (not multi and isinstance(points, (list, tuple)) and ns == 1) else np.asarray(points, dtype=float)
                pj = P[:, j] if (P.ndim == 2 and multi) else P
                if pj.ndim == 1:
                    pj = pj.reshape(-1, 1) if not multi else pj
                for k in range(pj.shape[1] if pj.ndim == 2 else 1):
                    col = pj[:, k] if pj.ndim == 2 else pj
                    rng = np.random.default_rng(0)
                    jit = rng.uniform(-0.1, 0.1, size=len(col))
                    if horizontal:
                        ax.scatter(col, x + off + jit, s=5, color="#222222", alpha=points_alpha,
                                   linewidths=0, zorder=3)
                    else:
                        ax.scatter(x + off + jit, col, s=5, color="#222222", alpha=points_alpha,
                                   linewidths=0, zorder=3)
            except Exception:
                pass
        if annotate:
            for i, val in enumerate(v):
                txt = value_fmt.format(val)
                if horizontal:
                    ax.text(val, x[i] + off, " " + txt, va="center", ha="left", fontsize=mpl.rcParams["font.size"] - 1)
                else:
                    ax.text(x[i] + off, val, " " + txt, va="bottom", ha="center",
                            fontsize=mpl.rcParams["font.size"] - 1)

    if horizontal:
        ax.set_yticks(x, cats)
        ax.invert_yaxis()
        if base0:
            ax.set_xlim(left=0)
    else:
        ax.set_xticks(x, cats)
        if base0:
            ax.set_ylim(bottom=0)
    return handles


def scatter_fit(ax, x, y, color=None, fit=True, method="pearson", label=None,
                annotate_stat=True, dot_size=9, alpha=0.75, stat_xy=(0.03, 0.97)):
    """散点 + 回归线 + 相关系数标注（课程设计/实验报告的高频图）。"""
    color = color or colors(1)[0]
    x, y = np.asarray(x, float), np.asarray(y, float)
    ax.scatter(x, y, s=dot_size, color=color, alpha=alpha, linewidths=0, label=label)
    stat = ""
    if fit:
        k, b = np.polyfit(x, y, 1)
        xs = np.linspace(x.min(), x.max(), 100)
        ax.plot(xs, k * xs + b, color="#333333", linewidth=0.9, linestyle="--", zorder=1)
        if method == "pearson":
            r = np.corrcoef(x, y)[0, 1]
            stat = f"$r$ = {r:.3f}, $n$ = {len(x)}"
            if annotate_stat:
                import scipy.stats as st
                p = st.pearsonr(x, y).pvalue
                stat += f"\n$p$ {'<' if p < 0.001 else '='} {p:.3f}" if p >= 0.001 else "\n$p$ < 0.001"
        else:
            import scipy.stats as st
            tau, p = st.spearmanr(x, y)
            stat = f"$\\rho$ = {tau:.3f}, $p$ = {p:.3g}, $n$ = {len(x)}"
        ax.text(*stat_xy, stat, transform=ax.transAxes, ha="left", va="top",
                fontsize=mpl.rcParams["font.size"] - 0.5)
    return stat


def heatmap(ax, M, row_labels=None, col_labels=None, cmap=None, vmin=None, vmax=None,
            center=None, annot=False, fmt="{:.2f}", cbar=True, cbar_label=None,
            cbar_ax=None, annot_size=None, grid_color="#FFFFFF"):
    """热图/相关矩阵。center 给定即用发散色图（科学零点必须居中）。"""
    M = np.asarray(M, float)
    if cmap is None:
        if center is not None:
            lim = max(abs(M.min() - center), abs(M.max() - center)) or 1.0
            vmin, vmax, cmap = center - lim, center + lim, C.DIV
        else:
            cmap = C.SEQ
    im = ax.imshow(M, cmap=cmap, vmin=vmin, vmax=vmax, aspect="auto", interpolation="nearest")
    if row_labels is not None:
        ax.set_yticks(np.arange(len(row_labels)), row_labels)
    if col_labels is not None:
        ax.set_xticks(np.arange(len(col_labels)), col_labels, rotation=45, ha="right",
                      rotation_mode="anchor")
    if annot:
        mid = (vmin if vmin is not None else M.min()) + \
              ((vmax if vmax is not None else M.max()) - (vmin if vmin is not None else M.min())) / 2
        for i in range(M.shape[0]):
            for j in range(M.shape[1]):
                ax.text(j, i, fmt.format(M[i, j]), ha="center", va="center",
                        fontsize=annot_size or mpl.rcParams["font.size"] - 1,
                        color="#FFFFFF" if abs(M[i, j] - mid) > 0.45 * abs((vmax or M.max()) - mid) else "#222222")
    ax.set_xticks(np.arange(-.5, M.shape[1], 1), minor=True)
    ax.set_yticks(np.arange(-.5, M.shape[0], 1), minor=True)
    ax.grid(which="minor", color=grid_color, linewidth=0.5)
    ax.tick_params(which="minor", length=0)
    for s in ax.spines.values():
        s.set_visible(False)
    if cbar:
        cb = ax.figure.colorbar(im, ax=cbar_ax or ax, fraction=0.046, pad=0.02, aspect=18)
        if cbar_label:
            cb.set_label(cbar_label)
        cb.outline.set_visible(False)
    return im


def sig_bracket(ax, x1, x2, y, text=None, p=None, h=None, color="#333333", lw=None):
    """显著性括号。优先写精确 p 值；用星号时必须在图注里定义阈值。"""
    lw = lw or mpl.rcParams["axes.linewidth"]
    if text is None:
        if p is None:
            text = ""
        elif p < 0.001:
            text = "***"
        elif p < 0.01:
            text = "**"
        elif p < 0.05:
            text = "*"
        else:
            text = "n.s."
    h = h or 0.02 * (ax.get_ylim()[1] - ax.get_ylim()[0])
    ax.plot([x1, x1, x2, x2], [y, y + h, y + h, y], lw=lw, color=color, clip_on=False)
    ax.text((x1 + x2) / 2, y + h, text, ha="center", va="bottom",
            fontsize=mpl.rcParams["font.size"] - 0.5)
    return text


def panel_labels(fig_or_axes, start=0, style=None, offset=(-0.06, 1.04), **kw):
    """给多面板图标 a/b/c（Nature/Cell/Science 小写粗体正体；IEEE/ACS 带括号）。"""
    s = spec()
    fmt = style or s["panel_fmt"]
    axes = np.atleast_1d(fig_or_axes).ravel()
    labs = []
    for i, ax in enumerate(axes):
        if not ax.get_visible() or (not ax.has_data() and not ax.images and not ax.collections and not ax.patches):
            continue
        ch = chr(ord("a") + i + start)
        txt = f"({ch})" if "(" in fmt else (ch.upper() if fmt.isupper() else ch)
        ax.annotate(txt, xy=offset, xycoords="axes fraction", fontsize=s["panel_pt"],
                    fontweight="bold", va="bottom", ha="left", **kw)
        labs.append(txt)
    return labs


# --------------------------------------------------------------------------- #
# 自审 / 导出
# --------------------------------------------------------------------------- #
def audit_fig(fig, verbose=True) -> dict:
    """导出前的机械自审：字号下限、图宽上限、字体族一致、是否落到默认字体。"""
    s = spec()
    w_in, h_in = fig.get_size_inches()
    rep = {"width_mm": round(w_in * 25.4, 2), "height_mm": round(h_in * 25.4, 2),
           "font_sizes": [], "problems": [], "warnings": []}

    texts = [t for t in fig.findobj(mpl.text.Text) if (t.get_text() or "").strip()]
    sizes = sorted({round(float(t.get_fontsize()), 2) for t in texts})
    rep["font_sizes"] = sizes
    rep["n_text"] = len(texts)

    if not texts:
        rep["warnings"].append("图上没有任何文字：轴标签/单位/样本量缺失？")
    min_sz = min(sizes) if sizes else None
    if min_sz is not None and min_sz < s["min_pt"] - 1e-6:
        rep["problems"].append(f"最小字号 {min_sz}pt 低于 {STATE['style']} 下限 {s['min_pt']}pt")
    if rep["width_mm"] > s["width"]["double"] + 0.6:
        rep["problems"].append(f"图宽 {rep['width_mm']}mm 超过通栏 {s['width']['double']}mm")
    if s["max_height"] and rep["height_mm"] > s["max_height"]:
        rep["problems"].append(f"图高 {rep['height_mm']}mm 超过页深 {s['max_height']}mm")

    fams = {}
    for t in texts:
        for f in (t.get_fontfamily() or []):
            fams[f] = fams.get(f, 0) + 1
    primaries = {(t.get_fontfamily() or ["?"])[0] for t in texts}
    if primaries and all(p.startswith("DejaVu") for p in primaries):
        rep["warnings"].append(
            "文字实际落在 matplotlib 默认字体 DejaVu 上（Arial/Helvetica/Liberation 都没找到，"
            "或 setup() 没执行）——观感会明显不像论文")

    # 轴标签单位启发式（含数学符号 $...$ 的标签视为自带符号，不提醒）
    for ax in fig.get_axes():
        for lab in (ax.get_xlabel(), ax.get_ylabel()):
            l = (lab or "").strip()
            if l and "$" not in l and not any(k in l for k in ("(", "[", "/", "（", "每")):
                rep["warnings"].append(f"轴标签缺少单位：{l!r}（写成“应力 (MPa)”这样）")

    # 中文字形缺失（比"导出后看到方框"早一步发现）
    def _cjk(s: str) -> bool:
        return any("\u4e00" <= c <= "\u9fff" or "\u3000" <= c <= "\u303f"
                   or "\uff00" <= c <= "\uffef" for c in s)
    cjk_texts = sorted({t.get_text()[:14] for t in texts if _cjk(t.get_text())})
    if cjk_texts:
        if not STATE["cjk"]:
            rep["problems"].append(
                f"图中含中文但当前未加载中文字体（改用 lang='zh' 或先跑 scripts/setup_env.sh）：{cjk_texts[:3]}")
        elif STATE["lang"] != "zh" and STATE["style"] not in ("report", "slide"):
            rep["warnings"].append(
                f"投稿英文期刊的图里混进了中文：{cjk_texts[:2]}（若目标是中文期刊/报告可忽略）")

    # 汉字与 $公式$ 写在同一条文本里 → mathtext 不做字形回退，汉字必变方框（实测 3.11）
    mixed = sorted({t.get_text()[:24] for t in texts
                    if _cjk(t.get_text()) and "$" in t.get_text()})
    if mixed:
        rep["problems"].append(
            "汉字与 $…$ 混在同一条文本里，mathtext 不做字形回退，汉字会渲染成方框：" +
            f"{mixed[:2]}；改用 pf.mixed_text()（自动拆段）或把公式写成独立 text，"
            "中文报告里更简单的做法是用 Unicode 变量名（n、σ、p）")

    if verbose:
        print(f"[audit] {rep['width_mm']}×{rep['height_mm']} mm | 字号 {sizes} pt | 文本 {rep['n_text']} 处")
        for p in rep["problems"]:
            print(f"  ✗ {p}")
        for w in rep["warnings"]:
            print(f"  ! {w}")
        if not rep["problems"]:
            print("  ✓ 通过机械检查（结论是否站得住，还要按 references/craft-and-qa.md 人工过四轴）")
    return rep


def _png_size(path: Path) -> tuple[int, int]:
    with open(path, "rb") as fh:
        head = fh.read(24)
    return struct.unpack(">II", head[16:24])


def save(fig, name: str, outdir="figures", formats=None, dpi=None, claim=None,
         manifest: bool = True, close: bool = False, audit: bool = True, verbose=True):
    """导出：矢量主件 + 位图预览，并做尺寸/像素/字号自审。

    返回 {格式: Path}。提交正文的图务必带上 claim（这一张图要证明的一句话），
    它会写进 figure_manifest.csv —— 图注与交付清单都从它长出来。
    """
    if STATE["spec"] is None:
        setup(verbose=False)
    s = spec()
    out = Path(outdir).expanduser()
    out.mkdir(parents=True, exist_ok=True)
    dpi = int(dpi or s["dpi"])
    formats = list(formats or s["formats"])

    rep = audit_fig(fig, verbose=audit)
    paths = {}
    for f in formats:
        p = out / f"{name}.{f}"
        kw = {}
        if f in ("pdf", "ps"):
            kw["metadata"] = {"Creator": "paperfig", "Title": claim or name}
        fig.savefig(p, dpi=dpi, **kw)
        paths[f] = p
    if verbose:
        w_mm, h_mm = rep["width_mm"], rep["height_mm"]
        for f, p in paths.items():
            extra = ""
            if f == "png":
                px, py = _png_size(p)
                exp = (round(fig.get_size_inches()[0] * dpi), round(fig.get_size_inches()[1] * dpi))
                ok = abs(px - exp[0]) <= 1 and abs(py - exp[1]) <= 1   # 允许 1px 取整误差
                extra = f"  {px}×{py}px{' ✓' if ok else f' ✗ 期望 {exp[0]}×{exp[1]}'}"
            print(f"[save] {p}  ({w_mm:.1f}×{h_mm:.1f}mm @ {dpi}dpi){extra}")
    if close:
        plt.close(fig)

    if manifest:
        mf = out / "figure_manifest.csv"
        row = {
            "name": name, "style": STATE["style"], "claim": claim or "",
            "width_mm": rep["width_mm"], "height_mm": rep["height_mm"], "dpi": dpi,
            "min_font_pt": min(rep["font_sizes"]) if rep["font_sizes"] else "",
            "formats": "+".join(formats),
            "files": ";".join(str(p) for p in paths.values()),
            "script": Path(sys.argv[0]).name if sys.argv and sys.argv[0] else "",
            "created": _dt.datetime.now().strftime("%Y-%m-%d %H:%M"),
        }
        new = not mf.exists()
        with open(mf, "a", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=list(row))
            if new:
                w.writeheader()
            w.writerow(row)
    return paths


# --------------------------------------------------------------------------- #
# 自检
# --------------------------------------------------------------------------- #
def _selftest() -> int:
    import tempfile
    seed(0)
    tmp = Path(tempfile.mkdtemp(prefix="paperfig_selftest_"))
    fails = 0
    for style, lang in (("nature", "en"), ("ieee", "en"), ("report", "zh")):
        setup(style, lang=lang, verbose=True)
        fig, ax = subplots("single", height_mm=58)
        x = np.linspace(0, 10, 40)
        y = 1.0 - 0.06 * x + np.random.default_rng(0).normal(0, 0.05, x.size)
        line_ci(ax, x, y, y - 0.1, y + 0.1,
                label="Method A (95% CI)" if lang == "en" else "方法 A（95% CI）")
        ax.set_xlabel("Time (s)")
        ax.set_ylabel("Error (mm)" if lang == "en" else "相对误差 (%)")
        finish(ax, legend=True)
        p = save(fig, f"selftest_{style}", outdir=tmp / "figures", claim="自检：折线+置信带", verbose=True)
        rep = audit_fig(fig, verbose=False)
        pdf, png = p.get("pdf"), p.get("png")
        got = _png_size(png) if png else (0, 0)
        exp = (round(fig.get_size_inches()[0] * spec()["dpi"]), round(fig.get_size_inches()[1] * spec()["dpi"]))
        if got != exp or rep["problems"]:
            fails += 1
            print(f"  ✗ {style} 自检未通过")
        plt.close(fig)
    print(f"\n[selftest] {'全部通过' if fails == 0 else f'{fails} 项失败'}；输出目录 {tmp}")
    return 0 if fails == 0 else 1


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        raise SystemExit(_selftest())
    print(__doc__)
