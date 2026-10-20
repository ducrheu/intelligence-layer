#!/usr/bin/env python3
"""check_research_brief.py — 需求研究简报的确定性 QA。

只读、不改文件。退出码 0=过，1=有 error（warning 不影响）。
用法:
  python3 scripts/check_research_brief.py research/xxx.md [--json]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

REQUIRED_SECTIONS = [
    ("## 0.", "研究模式"),
    ("## 1.", "任务与场景"),
    ("## 2.", "客户语言库"),
    ("## 3.", "主题"),
    ("## 4.", "异议与风险"),
    ("## 5.", "交付与报价口径"),
    ("## 6.", "待确认问题"),
    ("## 7.", "来源与置信度"),
]

PROMO_WORDS = ["全方位", "一站式", "赋能", "助力", "致力于", "打造", "卓越", "无缝",
               "保驾护航", "量身定制", "值得信赖", "高效可靠", "优质服务", "深度赋能"]

FABRICATION_WORDS = ["五星好评", "客户好评", "好评如潮", "已成交", "我服务过",
                     "我的客户", "老客户介绍", "口碑极佳"]

MIN_SOURCE_MARKS = 5
MIN_THEMES = 3

errors: list[str] = []
warnings: list[str] = []


def err(line_no: int, msg: str) -> None:
    errors.append(f"L{line_no}: {msg}" if line_no else msg)


def warn(line_no: int, msg: str) -> None:
    warnings.append(f"L{line_no}: {msg}" if line_no else msg)


def check(path: Path) -> None:
    text = path.read_text(encoding="utf-8", errors="ignore")
    lines = text.splitlines()

    # 1) 必需小节
    for prefix, label in REQUIRED_SECTIONS:
        if not any(l.strip().startswith(prefix) for l in lines):
            err(0, f"缺小节 {prefix} {label}")

    # 2) 主题块
    blocks: list[tuple[int, list[str]]] = []
    cur: tuple[int, list[str]] | None = None
    for i, l in enumerate(lines, 1):
        if re.match(r"^###\s+主题", l.strip()):
            if cur:
                blocks.append(cur)
            cur = (i, [l])
        elif cur is not None and re.match(r"^#{2,3}\s", l.strip()):
            blocks.append(cur)
            cur = None
        elif cur is not None:
            cur[1].append(l)
    if cur:
        blocks.append(cur)

    if len(blocks) < MIN_THEMES:
        err(0, f"主题数 {len(blocks)} < {MIN_THEMES}；§3 至少要 3 个「### 主题 n」块")
    for ln, body in blocks:
        b = "\n".join(body)
        if "原话" not in b:
            err(ln, "主题块里没有「原话」")
        if "来源:" not in b and "来源：" not in b:
            err(ln, "主题块里没有「来源:」标注")
        if not re.search(r"频次|强度", b):
            err(ln, "主题块里没有「频次」或「强度」，无法说明排序依据")

    # 3) 全文来源标注数量
    n_src = len(re.findall(r"来源\s*[:：]", text))
    if n_src < MIN_SOURCE_MARKS:
        err(0, f"全文「来源:」只有 {n_src} 处 < {MIN_SOURCE_MARKS}，多数结论没有出处")

    # 4) 宣传词
    for i, l in enumerate(lines, 1):
        for w in PROMO_WORDS:
            if w in l:
                err(i, f"企业宣传词「{w}」，改成动作和结果")

    # 5) 编造类词
    for i, l in enumerate(lines, 1):
        for w in FABRICATION_WORDS:
            if w in l:
                err(i, f"疑似编造事实「{w}」；有真实出处才可写，否则删掉")

    # 6) 报价口径
    sec5 = _section_text(lines, "## 5.")
    if sec5 is not None:
        if "¥" not in sec5 and "区间" not in sec5:
            err(0, "§5 报价口径里既没有 ¥ 也没有「区间」")
        if "pricing.md" not in sec5:
            warn(0, "§5 没有引用 freelance/shop/pricing.md")
    sec7 = _section_text(lines, "## 7.")
    if sec7 is not None and "置信度" not in sec7:
        err(0, "§7 没有写「置信度」")
    sec3 = _section_text(lines, "## 3.")
    if sec3 is not None and re.search(r"n\s*=\s*[0-9]", text):
        m = re.search(r"n\s*=\s*([0-9]+)", text)
        if m and int(m.group(1)) < 10 and "频次" in sec3:
            warn(0, f"样本量 n={m.group(1)} < 10 却用了「频次」聚类；按 SKILL.md 只列事实")


def _section_text(lines: list[str], prefix: str) -> str | None:
    out, on = [], False
    for l in lines:
        if l.strip().startswith(prefix):
            on = True
            continue
        if on and re.match(r"^##\s", l):
            break
        if on:
            out.append(l)
    return "\n".join(out) if on else None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("file")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    p = Path(args.file)
    if not p.exists():
        print(f"文件不存在: {p}")
        return 1
    check(p)
    if args.json:
        print(json.dumps({"file": str(p), "errors": errors, "warnings": warnings},
                         ensure_ascii=False, indent=2))
    else:
        for e in errors:
            print("  ✗", e)
        for w in warnings:
            print("  ⚠", w)
        print(f"\ncheck_research_brief: {len(errors)} error / {len(warnings)} warning — {p}")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
