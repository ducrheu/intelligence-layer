#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""critique.py —— 绘图脚本的静态质检门（在你看图之前先挡住机械性错误）。

    ~/.venvs/figures/bin/python critique.py scripts/fig1_trend.py
    ~/.venvs/figures/bin/python critique.py --glob "scripts/fig*.py" --json

区分两类问题：
  FAIL —— 期刊一定会退回/审稿人一定会挑：默认色板、jet/彩虹色图、3D、饼图、
          只出 PNG、dpi<300、没做样式设定（掉进 DejaVu 默认观感）、随机无种子。
  WARN —— 需要你自己判断：没有误差表示、图例压在数据上、轴标签缺单位、
          多面板缺 a/b/c 标签、内联数据过多（不可复现）。

退出码：有 FAIL 则 1（可挂 CI / pre-commit），否则 0。
"""
from __future__ import annotations

import argparse
import glob as _glob
import json
import re
import sys
from pathlib import Path

# (规则号, 级别, 正则, 说明)
RULES = [
    ("C1", "FAIL", r"cmap\s*=\s*['\"](jet|rainbow|hsv|turbo|gist_rainbow|nipy_spectral)['\"]",
     "用 jet/rainbow 类色图：亮度非单调，会伪造数据形态；改用 perceptually uniform（viridis/cividis）或 pf.C.SEQ / pf.C.DIV"),
    ("C2", "FAIL", r"['\"](jet|rainbow|hsv|turbo)['\"]",
     "出现 jet/rainbow 类色图名"),
    ("C3", "FAIL", r"\b(tab10|tab20|tab20b|tab20c|Set1|Set2|Set3|Paired|Accent|Dark2)\b",
     "用 matplotlib/ColorBrewer 默认定性色板：一眼就是『没设计过』；改用 pf.colors() / pf.C"),
    ("P1", "FAIL", r"projection\s*=\s*['\"]3d['\"]|Axes3D",
     "3D 图：除极少数场景外都是信息失真 + 不可读，改二维（必要时用小倍数面板）"),
    ("P2", "FAIL", r"\.pie\s*\(|donut|\.bar\([^)]*width\s*=\s*2\s*\*?\s*np\.pi",
     "饼图/环形图：角度比较不可靠，改用排序条形或（占比才是重点时）堆叠条形"),
    ("S1", "FAIL", r"savefig\([^)]*\.png['\"]",
     "只存 PNG：正文图必须给矢量主件（PDF/SVG/EPS），PNG 只做预览；用 pf.save() 一次出全套"),
    ("S2", "FAIL", r"dpi\s*=\s*\d{1,2}\b",
     "dpi 过低（<100）：位图至少 300dpi；用 pf.save() 的默认值"),
    ("S3", "WARN", r"savefig\([^)]*dpi\s*=\s*(1\d\d|2\d\d)\b",
     "dpi 低于 300：线稿建议 600dpi，照片 ≥300dpi"),
    ("R1", "FAIL", r"(np\.random\.(?!seed)|default_rng\(\)|random\.uniform|random\.normal)(?!(?![\s\S]{0,400})?(seed|default_rng\(\s*\d))",
     "有随机性但没固定种子：图不可复现；在文件开头调 pf.seed(0)"),
    ("E1", "WARN", r"\b(bar|barh)\s*\(",
     "用了柱状图：确认是否叠加了误差/分布（pf.bars 可一次给误差棒+个体点），并说明误差是 SD/SEM/CI 还是范围"),
    ("E2", "WARN", r"(?s)(?=.*\b(error|err|std|sem|ci|conf|signific|p\s*[<=]|auc|acc)\b)(?!.*(errorbar|yerr|xerr|fill_between|band|errs|confidence|std_|_std|ci_|_ci))",
     "出现统计量/误差字眼但没有画任何误差表示：加误差棒或置信带，并在图注里写清含义"),
    ("E3", "WARN", r"\.legend\s*\(\s*\)",
     "图例用默认位置（loc='best' 会压在数据上）：用 pf.legend_outside() 或显式 loc 并确认不遮数据"),
    ("A1", "WARN", r"(?s)(?=.*plt\.subplots\([^)]*ncols\s*=\s*[2-9])(?!.*panel_label)",
     "多面板但没有 a/b/c 面板标签：用 pf.panel_labels(axes)"),
    ("A2", "WARN", r"set_(x|y)label\(\s*['\"][^()\[\]（]{3,}['\"]\s*\)",
     "轴标签里没有单位/符号括号：写成『应力 (MPa)』『时间 $t$ (s)』"),
    ("A3", "WARN", r"fontsize\s*=\s*([1-4](\.\d)?)\b",
     "出现 <5pt 的字号：最终尺寸下不可读（Nature 下限 5pt，IEEE 8pt）"),
    ("A4", "WARN", r"(?s)(?=.*[\u4e00-\u9fff])(?=.*\$[^$\n]+\$)",
     "汉字与 $…$ 混排：mathtext 不做字形回退，汉字会变方框；用 pf.mixed_text() 或 Unicode 变量名"),
    ("D1", "WARN", r"(?:[-\d.]+\s*,\s*){25,}",
     "疑似内联了 25 个以上数据点：数据应来自文件（CSV/npz），否则图不可复现、也无法复核"),
]

# 逐行判断的特殊规则（避免误报）：A4 只在该行不含 mixed_text 时才算问题
PER_LINE_SKIP = {"A4": ("mixed_text",)}

OK = "\033[32m✓\033[0m"
BAD = "\033[31m✗\033[0m"
WARN = "\033[33m!\033[0m"


def critique(path: Path, style: str | None = None) -> dict:
    text = path.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()
    findings = []
    for rid, level, pat, msg in RULES:
        try:
            rx = re.compile(pat, re.M)
        except re.error as e:
            findings.append({"rule": rid, "level": "WARN", "line": 0,
                             "msg": f"规则本身无效（{e}）"})
            continue
        skip = PER_LINE_SKIP.get(rid, ())
        if skip:                              # 逐行规则：只对不含豁免关键字的行匹配
            ln = None
            for i, line in enumerate(lines, start=1):
                if any(k in line for k in skip):
                    continue
                if rx.search(line):
                    ln = i
                    break
        else:                                 # 整文件规则：一次搜索（含跨行断言）
            m = rx.search(text)
            ln = (text[:m.start()].count("\n") + 1) if m else None
        if ln is not None:
            findings.append({"rule": rid, "level": level, "line": ln, "msg": msg,
                             "code": lines[ln - 1].strip()[:100] if ln - 1 < len(lines) else ""})

    # 文件级检查：全脚本没有任何样式设定 → 一定会掉进 DejaVu 默认观感
    if not re.search(r"pf\.setup\(|paperfig|paper_style\(|plt\.style\.use|rcParams(\.update|\s*\[)", text):
        findings.append({"rule": "F2", "level": "FAIL", "line": 1, "code": "",
                         "msg": "全脚本没有任何样式设定（pf.setup / plt.style.use / rcParams）："
                                "会掉进 DejaVu 默认观感，字号也不受期刊下限约束"})

    fails = [f for f in findings if f["level"] == "FAIL"]
    warns = [f for f in findings if f["level"] == "WARN"]

    print(f"\n=== critique: {path} ===")
    print(f"预设：{style or '脚本内自定'}  行数：{len(lines)}")
    if not findings:
        print(f"{OK} 机械检查全部通过（结论是否站得住，还要人工过 quality 四轴）")
    for f in fails:
        print(f"{BAD} [{f['rule']}] L{f['line']}: {f['msg']}")
        if f.get("code"):
            print(f"      {f['code']}")
    for f in warns:
        print(f"{WARN} [{f['rule']}] L{f['line']}: {f['msg']}")
    print(f"\n结果：{len(fails)} FAIL / {len(warns)} WARN"
          + ("   → 先修 FAIL 再谈观感" if fails else "   → 无硬性阻塞项"))
    return {"path": str(path), "fails": fails, "warns": warns, "ok": not fails}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="绘图脚本静态质检")
    ap.add_argument("scripts", nargs="*", help="要检查的 .py 文件")
    ap.add_argument("--glob", help="用通配符指定，如 'scripts/fig*.py'")
    ap.add_argument("--style", help="目标预设（仅用于打印）")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    targets = [Path(p) for p in args.scripts]
    if args.glob:
        targets += [Path(p) for p in sorted(_glob.glob(args.glob))]
    if not targets:
        ap.print_help()
        return 2

    results = [critique(p, args.style) for p in targets if p.exists()]
    missing = [str(p) for p in targets if not p.exists()]
    for m in missing:
        print(f"{BAD} 找不到文件：{m}")
    if args.json:
        print(json.dumps(results, ensure_ascii=False, indent=2))
    bad = sum(1 for r in results if not r["ok"])
    print(f"\n[critique] {len(results)} 个脚本，{bad} 个存在 FAIL")
    return 1 if (bad or missing) else 0


if __name__ == "__main__":
    raise SystemExit(main())
