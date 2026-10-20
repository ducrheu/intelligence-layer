#!/usr/bin/env python3
"""run_benchmark.py — customer-research 的 benchmark。

判定：全部通过才 exit 0。
  1. evals/evals.json 结构合法（每条有 input + 至少 2 条 expect）
  2. 阳性对照：fixtures/brief-expected.md 必须 lint 通过（exit 0）
  3. 阴性对照：fixtures/brief-invalid.md 必须被 lint 拒绝（exit != 0）
  4. 真实运行：evals/runs/ 下至少一份简报必须 lint 通过
说明：QA 脚本能区分好坏是"机制可信"的证据；第 4 项是"真的跑过一次"的证据。
"""
import json, subprocess, sys
from pathlib import Path

HERE = Path(__file__).resolve().parent          # scripts/
CAND = HERE.parent                              # candidates/customer-research
LINT = HERE / "check_research_brief.py"
fails = []

def run_lint(p):
    return subprocess.run([sys.executable, str(LINT), str(p)],
                          capture_output=True, text=True).returncode

# 1
ev = CAND / "evals" / "evals.json"
try:
    d = json.loads(ev.read_text(encoding="utf-8"))
    es = d.get("evals", [])
    assert es, "evals 为空"
    for e in es:
        assert e.get("input"), f"{e.get('name')}: 缺 input"
        assert len(e.get("expect") or []) >= 2, f"{e.get('name')}: expect < 2 条"
    print(f"[1/4] evals.json OK ({len(es)} evals)")
except Exception as ex:
    fails.append(f"evals.json: {ex}")
    print(f"[1/4] evals.json FAIL: {ex}")

# 2 阳性对照
good = CAND / "evals" / "fixtures" / "brief-expected.md"
rc = run_lint(good)
if rc == 0:
    print("[2/4] 阳性对照通过（好简报被接受）")
else:
    fails.append("阳性对照被误杀")
    print(f"[2/4] 阳性对照 FAIL (exit={rc})")

# 3 阴性对照
bad = CAND / "evals" / "fixtures" / "brief-invalid.md"
rc = run_lint(bad)
if rc != 0:
    print("[3/4] 阴性对照通过（坏简报被拦下）")
else:
    fails.append("阴性对照漏过")
    print("[3/4] 阴性对照 FAIL（坏简报竟然通过）")

# 4 真实运行
runs = sorted((CAND / "evals" / "runs").glob("*.md"))
if not runs:
    fails.append("evals/runs/ 没有真实运行产出")
    print("[4/4] 真实运行 FAIL：先按 SKILL.md 真跑一遍产出简报")
else:
    ok = [r for r in runs if run_lint(r) == 0]
    if ok:
        print(f"[4/4] 真实运行通过：{', '.join(r.name for r in ok)}")
    else:
        fails.append("真实运行产出未通过 QA")
        print("[4/4] 真实运行产出未通过 QA")

print()
if fails:
    print("BENCHMARK: FAIL")
    for f in fails:
        print("  ✗", f)
    sys.exit(1)
print("BENCHMARK: PASS (4/4)")
sys.exit(0)
