#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""demo_gallery.py —— 论文 / 实验报告 / 课程设计的高频图型样板。

既是"这套引擎能出什么"的目录，也是每次改引擎后的回归测试：

    ~/.venvs/figures/bin/python demo_gallery.py            # 全部生成到 figures/
    ~/.venvs/figures/bin/python demo_gallery.py --outdir /tmp/g --sheet

每张图都演示了本 skill 的硬规则：尺寸按期刊列宽、字号不越下限、
误差含义写清楚、色盲安全、矢量+位图双交付、并在 figure_manifest.csv 里登记 claim。
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import paperfig as pf

rng = np.random.default_rng(7)


# --------------------------------------------------------------------------- #
def fig1_trend_ci(out):
    """折线 + 置信带，并标出机制/临界点（"Depth" 那一轴）。"""
    pf.setup("nature", verbose=False)
    x = np.linspace(0, 60, 61)
    y = 0.92 * np.exp(-x / 22) + 0.08 + 0.004 * x / 60
    lo, hi = y - 0.03 - 0.02 * np.exp(-x / 40), y + 0.03 + 0.02 * np.exp(-x / 40)
    fig, ax = pf.subplots("single", height_mm=56)
    pf.line_ci(ax, x, y, lo, hi, label="Our method (95% CI)", color=pf.C[0], lw=1.2)
    pf.line_ci(ax, x, y + 0.06, lo + 0.06, hi + 0.06, label="Baseline", color=pf.C[2],
               lw=1.0, ls="--", band=False)
    ax.axvline(22, color=pf.C.GREY, lw=0.6, ls=":")
    pf.direct_label(ax, 22, 0.34, r"$t_{1/2}$ = 22 s", color=pf.C.GREY, dx=3)
    ax.annotate("", xy=(22, 0.30), xytext=(0, 0.30), arrowprops=dict(arrowstyle="<->", lw=0.6, color=pf.C.GREY))
    ax.text(11, 0.315, "decay regime", ha="center", fontsize=6, color=pf.C.GREY)
    ax.set_xlabel(r"Time $t$ (s)")
    ax.set_ylabel(r"Normalized error $\varepsilon$ (-)")
    ax.set_xlim(0, 60)
    ax.set_ylim(0, 1.05)
    pf.finish(ax, legend="out")
    return pf.save(fig, "fig1_trend_ci", out, claim="误差随训练时间指数衰减，半衰期 22 s")


def fig2_grouped_bars(out):
    """分组柱 + 误差棒 + 个体点 + 显著性括号（实验报告的主力图）。"""
    pf.setup("report", lang="zh", verbose=False)
    cats = ["基线", "方法 A", "方法 B", "本文方法"]
    means = np.array([[0.612, 0.735], [0.654, 0.781], [0.681, 0.802], [0.742, 0.869]])
    errs = np.array([[0.021, 0.018], [0.019, 0.022], [0.023, 0.017], [0.014, 0.012]])
    pts = np.stack([means + rng.normal(0, 0.012, means.shape) for _ in range(6)])
    fig, ax = pf.subplots("single", height_mm=62)
    pf.bars(ax, cats, means, errs=errs, err_label="95% CI", points=pts,
            series_names=["验证集", "测试集"])
    ax.set_ylabel("准确率 (%)")
    ax.set_ylim(0, 1.32)
    ax.set_yticks([0, 0.2, 0.4, 0.6, 0.8, 1.0], ["0", "20", "40", "60", "80", "100"])
    pf.sig_bracket(ax, 2, 3, 1.02, p=0.004)
    pf.sig_bracket(ax, 0, 3, 0.94, p=0.0002)
    # 汉字与 $公式$ 混排一律走 mixed_text：直接写在一条 text 里汉字会变方框
    pf.mixed_text(ax, 0.02, 1.0, "误差棒 = 95% CI；$n$ = 6 次重复",
                  transform=ax.transAxes, va="top", fontsize=7, color=pf.C.GREY)
    pf.finish(ax, legend="out")
    return pf.save(fig, "fig2_grouped_bars_zh", out, claim="本文方法在两个测试集上均显著优于基线")


def fig3_distribution(out):
    """分布比较：小提琴 + 个体散点 + 中位数标注（比纯柱图信息量大）。"""
    pf.setup("nature", verbose=False)
    groups = ["Ctrl", "Low", "Mid", "High"]
    data = [rng.normal(m, s, 28) for m, s in
            [(0.0, 0.9), (0.6, 1.0), (1.4, 1.1), (2.1, 1.3)]]
    fig, ax = pf.subplots("single", height_mm=56)
    vp = ax.violinplot(data, showextrema=False, widths=0.75)
    for i, b in enumerate(vp["bodies"]):
        b.set_facecolor(pf.colors(4)[i])
        b.set_alpha(0.35)
        b.set_edgecolor("#333333")
        b.set_linewidth(0.5)
    for i, d in enumerate(data):
        jit = rng.uniform(-0.10, 0.10, d.size)
        ax.scatter(i + 1 + jit, d, s=5, color="#222222", alpha=0.5, linewidths=0, zorder=3)
        ax.plot([i + 0.85, i + 1.15], [np.median(d)] * 2, color="#000000", lw=1.2, zorder=4)
    ax.set_xticks(range(1, 5), groups)
    ax.set_xlabel("Dose level")
    ax.set_ylabel(r"Response $y$ (a.u.)")
    ax.set_ylim(bottom=min(min(d) for d in data) - 1.1)
    ax.axhline(0, color=pf.C.GREY, lw=0.5, ls="--")
    ax.text(0.98, 0.03, "Line = median; each dot = one independent run ($n$ = 28/group)",
            transform=ax.transAxes, ha="right", fontsize=6, color=pf.C.GREY)
    pf.finish(ax)
    return pf.save(fig, "fig3_distribution", out, claim="响应随剂量单调上升且组内异质性增大")


def fig4_corr_heatmap(out):
    """相关矩阵：发散色图必须以 0 居中，否则正负相关被压扁。"""
    pf.setup("nature", verbose=False)
    labels = ["PM2.5", "PM10", "NO2", "SO2", "CO", "O3", "T", "RH"]
    k = len(labels)
    A = rng.normal(size=(200, 2))
    X = np.empty((200, k))
    X[:, 0] = A[:, 0] + rng.normal(0, 0.3, 200)
    X[:, 1] = A[:, 0] + rng.normal(0, 0.4, 200)
    X[:, 2] = 0.8 * A[:, 0] - 0.4 * A[:, 1] + rng.normal(0, 0.4, 200)
    X[:, 3] = A[:, 0] + rng.normal(0, 0.6, 200)
    X[:, 4] = 0.6 * A[:, 0] + rng.normal(0, 0.5, 200)
    X[:, 5] = -A[:, 1] + rng.normal(0, 0.5, 200)
    X[:, 6] = A[:, 1] + rng.normal(0, 0.7, 200)
    X[:, 7] = -0.6 * A[:, 1] + rng.normal(0, 0.6, 200)
    M = np.corrcoef(X.T)
    fig, ax = pf.subplots("single", height_mm=74)
    pf.heatmap(ax, M, labels, labels, center=0, annot=True, fmt="{:.2f}",
               cbar_label="Pearson $r$", annot_size=5)
    ax.tick_params(labelsize=6.5)
    return pf.save(fig, "fig4_corr_heatmap", out, claim="PM2.5 与 PM10/NO2 强相关，O3 与 NO2 反向")


def fig5_scatter_fit(out):
    """散点 + 拟合 + r/n 标注；无数据处的空白留给结论标注。"""
    pf.setup("nature", verbose=False)
    x = rng.normal(50, 12, 80)
    y = 0.8 * x + rng.normal(0, 7, 80) + 12
    fig, ax = pf.subplots("single", height_mm=58)
    pf.scatter_fit(ax, x, y, color=pf.C.BLUE, method="pearson")
    ax.set_xlabel(r"Predicted score $S_{\mathrm{pred}}$ (-)")
    ax.set_ylabel(r"Measured score $S_{\mathrm{obs}}$ (-)")
    ax.axhline(y.mean(), color=pf.C.GREY, lw=0.5, ls=":")
    ax.text(0.98, 0.06, "Dashed line = linear fit; dotted = mean", transform=ax.transAxes,
            ha="right", fontsize=6, color=pf.C.GREY)
    pf.finish(ax)
    return pf.save(fig, "fig5_scatter_fit", out, claim="预测分数与实测分数线性一致（r 见图中标注）")


def fig6_multipanel(out):
    """2×2 多面板：统一面板尺寸、a–d 标签、共享图例、一张图讲一条证据链。"""
    pf.setup("nature", verbose=False)
    fig, axes = pf.subplots("double", nrows=2, ncols=2, height_mm=118)
    a, b, c, d = axes

    x = np.linspace(0, 10, 50)
    for i, (lab, col) in enumerate(zip(["run 1", "run 2", "run 3"], pf.colors(3))):
        y = np.sin(x + i * 0.4) * np.exp(-x / 6) + 0.05 * i
        a.plot(x, y, color=col, label=lab, lw=1.0)
    a.set_xlabel("Cycle (-)")
    a.set_ylabel(r"Drift (mV)")
    pf.finish(a, legend=True)

    cats = ["A", "B", "C"]
    pf.bars(b, cats, np.array([0.72, 0.81, 0.66]), errs=np.array([0.03, 0.02, 0.04]),
            err_label="SD", colors_=pf.colors(3))
    b.set_ylabel("Score (-)")
    b.set_xlabel("Condition")
    b.set_ylim(0, 0.95)
    pf.finish(b)

    m = rng.normal(0, 1, (12, 9))
    pf.heatmap(c, m, row_labels=[f"r{i+1}" for i in range(12)],
               col_labels=[f"c{j+1}" for j in range(9)], center=0, cbar_label=r"$z$ score")
    c.set_xlabel("Sample")
    c.set_ylabel("Feature")

    e = rng.normal(0, 0.22, 200)
    d.hist(e, bins=22, color=pf.C.BLUE, alpha=0.75, edgecolor="white", linewidth=0.4)
    d.axvline(0, color=pf.C.RED, lw=0.8, ls="--")
    d.set_xlabel("Residual (a.u.)")
    d.set_ylabel("Count (-)")
    d.text(0.97, 0.9, r"$\mu$ = %.2f , $s$ = %.2f" % (e.mean(), e.std()),
           transform=d.transAxes, ha="right", fontsize=6.5)
    pf.finish(d)

    pf.panel_labels(axes)
    return pf.save(fig, "fig6_multipanel", out, claim="漂移可控、条件 B 最优、残差近似零均值")


def fig7_roc_pr(out):
    """分类评估双面板：ROC + PR，报 AUC 而非"准确率"。"""
    pf.setup("ieee", verbose=False)
    fig, axes = pf.subplots("double", nrows=1, ncols=2, height_mm=62)
    r1, r2 = axes
    fpr = np.linspace(0, 1, 200)
    for name, auc, col, ls in [("Proposed", 0.94, "k", "-"), ("SVM", 0.86, "r", "--"),
                               ("Logistic", 0.81, "b", "-.")]:
        tpr = np.clip(fpr ** ((1 - auc) / auc), 0, 1)
        r1.plot(fpr, tpr, color=col, ls=ls, lw=1.0, label=f"{name} (AUC = {auc:.2f})")
    r1.plot([0, 1], [0, 1], color=pf.C.GREY, lw=0.5, ls=":")
    r1.set_xlabel("False positive rate (-)")
    r1.set_ylabel("True positive rate (-)")
    r1.set_xlim(0, 1)
    r1.set_ylim(0, 1.02)
    r1.set_aspect("equal")
    pf.finish(r1, legend=True)

    recall = np.linspace(0.05, 1, 200)
    for name, ap, col, ls in [("Proposed", 0.91, "k", "-"), ("SVM", 0.80, "r", "--"),
                              ("Logistic", 0.74, "b", "-.")]:
        prec = ap * (1 - 0.35 * recall ** 3) / (recall + 0.10 * (1 - ap))
        prec = np.clip(prec, 0, 1)
        r2.plot(recall, prec, color=col, ls=ls, lw=1.0, label=f"{name} (AP = {ap:.2f})")
    r2.set_xlabel("Recall (-)")
    r2.set_ylabel("Precision (-)")
    r2.axhline(0.5, color=pf.C.GREY, lw=0.5, ls=":")
    r2.set_xlim(0, 1)
    r2.set_ylim(0, 1.02)
    pf.finish(r2, legend=True)
    pf.panel_labels(axes)
    return pf.save(fig, "fig7_roc_pr", out, claim="本文方法在 ROC 与 PR 两个指标上均领先")


def fig8_ablation(out):
    """消融实验横向条形 + 直接标注数值（比纵向柱更省横向空间）。"""
    pf.setup("elsevier", verbose=False)
    names = ["w/o attention", "w/o pretrain", "w/o aug", "full model"]
    vals = np.array([0.61, 0.68, 0.79, 0.86])
    errs = np.array([0.04, 0.03, 0.02, 0.02])
    cols = [pf.C.GREY] * 3 + [pf.C.BLUE]
    fig, ax = pf.subplots("single", height_mm=52)
    pf.bars(ax, names, vals, errs=errs, err_label="SD", colors_=cols, horizontal=True,
            base0=False)
    ax.set_xlim(0.45, 1.02)
    ax.set_xlabel("AUC (-)")
    for i, (v, e) in enumerate(zip(vals, errs)):
        ax.text(v + e + 0.015, i, f"{v:.2f}", va="center", fontsize=7)
    ax.text(0.02, 0.05, "Grey = component removed; blue = full model", transform=ax.transAxes,
            fontsize=6.5, color=pf.C.GREY)
    pf.finish(ax)
    return pf.save(fig, "fig8_ablation", out, claim="三个组件缺一不可，注意力机制贡献最大")


FIGS = [fig1_trend_ci, fig2_grouped_bars, fig3_distribution, fig4_corr_heatmap,
        fig5_scatter_fit, fig6_multipanel, fig7_roc_pr, fig8_ablation]


# --------------------------------------------------------------------------- #
def contact_sheet(out: Path, name: str = "_gallery.png", cols: int = 2):
    """把 PNG 预览拼成一张对照图（便于一眼通检整组图的观感一致性）。"""
    pngs = sorted(p for p in out.glob("fig*.png"))
    if not pngs:
        return None
    imgs = [plt.imread(p) for p in pngs]
    rows = (len(imgs) + cols - 1) // cols
    fig, axes = plt.subplots(rows, cols, figsize=(9.0, 3.1 * rows), dpi=150)
    axes = np.atleast_1d(axes).ravel()
    for ax in axes:
        ax.axis("off")
    for ax, im, p in zip(axes, imgs, pngs):
        ax.imshow(im)
        ax.set_title(p.stem, fontsize=8, color="#333333")
    fig.tight_layout()
    path = out / name
    fig.savefig(path, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    print(f"[gallery] {path}  ({len(imgs)} 张预览)")
    return path


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--outdir", default="figures")
    ap.add_argument("--sheet", action="store_true", help="额外生成对照图 _gallery.png")
    args = ap.parse_args(argv)
    out = Path(args.outdir)
    out.mkdir(parents=True, exist_ok=True)
    for f in FIGS:
        f(out)
    if args.sheet:
        contact_sheet(out)
    print(f"\n[gallery] {len(FIGS)} 张图 → {out.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
