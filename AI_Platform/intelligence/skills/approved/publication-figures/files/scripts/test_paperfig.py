#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""paperfig 回归测试。跑法：

    ~/.venvs/figures/bin/python -m pytest -q test_paperfig.py

每个测试都对应一条"踩过的坑"，删测试之前先想清楚为什么它在那儿。
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import matplotlib
matplotlib.use("Agg")
import matplotlib as mpl
import matplotlib.pyplot as plt
import paperfig as pf


@pytest.fixture(autouse=True)
def _clean():
    mpl.rcParams.update(mpl.rcParamsDefault)
    pf.STATE.update(style=None, spec=None, lang="auto", palette="okabe", stack=[], cjk=[], cmaps=True)
    yield
    plt.close("all")


# --------------------------------------------------------------- 期刊规格
def test_official_column_widths():
    """尺寸必须来自各刊官方投稿指南，不能凭印象改。"""
    assert pf.SPECS["nature"]["width"]["single"] == 89
    assert pf.SPECS["nature"]["width"]["double"] == 183
    assert pf.SPECS["nature"]["max_height"] == 247
    assert pf.SPECS["nature"]["min_pt"] == 5 and pf.SPECS["nature"]["base_pt"] == 7
    assert pf.SPECS["ieee"]["width"]["single"] == 88.9
    assert pf.SPECS["ieee"]["width"]["double"] == 181.9
    assert pf.SPECS["ieee"]["min_pt"] >= 8          # IEEE 硬性 ≥8pt
    assert pf.SPECS["science"]["width"]["double"] == 174
    assert pf.SPECS["cell"]["width"]["single"] == 85
    assert pf.SPECS["acs"]["width"]["single"] == 84.7
    assert pf.SPECS["elsevier"]["width"]["double"] == 190


def test_figure_size_equals_request_in_mm():
    pf.setup("nature", verbose=False)
    fig, ax = pf.subplots("single", height_mm=58)
    w, h = fig.get_size_inches() * 25.4
    assert abs(w - 89) < 0.2 and abs(h - 58) < 0.2


def test_ieee_tick_labels_never_below_min():
    """IEEE 下限 8pt：刻度/图例字号不得因为 base-0.5 掉到 7.5pt（曾经的 bug）。"""
    pf.setup("ieee", verbose=False)
    assert mpl.rcParams["xtick.labelsize"] >= pf.SPECS["ieee"]["min_pt"]
    assert mpl.rcParams["legend.fontsize"] >= pf.SPECS["ieee"]["min_pt"]


# --------------------------------------------------------------- 字体 / 中文
def test_font_family_is_explicit_list_for_fallback():
    """font.family 必须是字体名列表：写成泛名 'sans-serif' 时逐字形回退不生效。"""
    pf.setup("nature", verbose=False)
    fam = mpl.rcParams["font.family"]
    assert isinstance(fam, (list, tuple)) and len(fam) >= 1
    assert "sans-serif" not in fam


def test_cjk_renders_without_missing_glyph(capfd):
    """纯中文标签不得出现缺字（方框）。缺字提示来自 C++ 层，走 fd 而非 warnings。"""
    pf.setup("report", lang="zh", verbose=False)
    if not pf.STATE["cjk"]:
        pytest.skip("本机没有中文字体（先跑 scripts/setup_env.sh）")
    fig, ax = pf.subplots("single", height_mm=40)
    ax.set_xlabel("时间 (s)")
    ax.set_ylabel("相对误差 (%)")
    ax.set_title("中文标题")
    fig.savefig("/tmp/_pf_cjk.png", dpi=120)
    assert "does not have a glyph" not in capfd.readouterr().err


def test_mixed_text_avoids_tofu(capfd):
    """汉字与 $公式$ 混排：mixed_text() 拆段后不得缺字（直接写一条 text 会变方框）。"""
    pf.setup("report", lang="zh", verbose=False)
    if not pf.STATE["cjk"]:
        pytest.skip("本机没有中文字体")
    fig, ax = pf.subplots("single", height_mm=40)
    pf.mixed_text(ax, 0.05, 0.5, "误差棒 = 95% CI；$n$ = 6 次重复", transform=ax.transAxes)
    fig.savefig("/tmp/_pf_mixed.png", dpi=120)
    assert "does not have a glyph" not in capfd.readouterr().err
    assert len([t for t in ax.texts if t.get_text()]) >= 3   # 拆成了多段


def test_audit_flags_cjk_math_in_one_string():
    """审计必须拦住"汉字+$公式$写一条 text"这个必出方框的写法。"""
    pf.setup("report", lang="zh", verbose=False)
    fig, ax = pf.subplots("single", height_mm=40)
    ax.text(0.1, 0.5, "样本量 ($n$) = 6")
    rep = pf.audit_fig(fig, verbose=False)
    assert any("方框" in p for p in rep["problems"])


# --------------------------------------------------------------- 审计
def test_audit_flags_font_below_min_and_oversize_width():
    pf.setup("nature", verbose=False)
    fig, ax = pf.subplots("double", height_mm=100)
    ax.text(0.5, 0.5, "tiny", fontsize=3)
    rep = pf.audit_fig(fig, verbose=False)
    assert any("下限" in p for p in rep["problems"])

    big = plt.figure(figsize=(300 * pf.MM, 60 * pf.MM))
    big.add_subplot(111).plot([0, 1], [0, 1])
    rep2 = pf.audit_fig(big, verbose=False)
    assert any("超过通栏" in p for p in rep2["problems"])


def test_audit_warns_missing_units():
    pf.setup("nature", verbose=False)
    fig, ax = pf.subplots("single", height_mm=50)
    ax.set_xlabel("time")
    ax.set_ylabel("stress (MPa)")
    rep = pf.audit_fig(fig, verbose=False)
    assert any("time" in w for w in rep["warnings"])


# --------------------------------------------------------------- 导出
def test_save_writes_all_formats_and_png_pixels(tmp_path):
    pf.setup("nature", verbose=False)
    fig, ax = pf.subplots("single", height_mm=50)
    ax.plot([0, 1], [0, 1])
    ax.set_xlabel("x (s)")
    ax.set_ylabel("y (mm)")
    paths = pf.save(fig, "t1", outdir=tmp_path, claim="测试", verbose=False)
    for f in pf.SPECS["nature"]["formats"]:
        assert paths[f].exists() and paths[f].stat().st_size > 500
    assert (tmp_path / "figure_manifest.csv").exists()
    from paperfig import _png_size
    px, py = _png_size(paths["png"])
    assert abs(px - 89 * pf.MM * 300) <= 1 and abs(py - 50 * pf.MM * 300) <= 1
    # PDF 尺寸即创建尺寸（不做缩放）——用 pypdf 核对
    pypdf = pytest.importorskip("pypdf")
    box = pypdf.PdfReader(paths["pdf"]).pages[0].mediabox
    assert abs(float(box.width) - 89 * pf.MM * 72) < 1.5


# --------------------------------------------------------------- 颜色
def test_palette_is_colorblind_safe_and_not_default():
    okabe = pf.PALETTES["okabe"]
    assert okabe[:7] == ["#0072B2", "#E69F00", "#009E73", "#D55E00",
                         "#56B4E9", "#CC79A7", "#F0E442"]
    for banned in ("#1f77b4", "#ff7f0e", "#d62728", "#2ca02c"):   # matplotlib tab10 前四色
        assert banned not in [c.lower() for pal in pf.PALETTES.values() for c in pal]
    assert pf.colors(6) == okabe[:6]
    assert len(set(pf.colors(7))) == 7          # 类别色不重复


def test_seed_makes_random_reproducible():
    pf.seed(0)
    a = np.random.rand(3)
    pf.seed(0)
    assert np.allclose(a, np.random.rand(3))


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
