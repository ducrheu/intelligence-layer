#!/usr/bin/env python3
"""run_benchmark.py — github-learning 的 benchmark。

四项都过才 exit 0：
  1. 结构契约：scripts/validate_learning.py 退出码 0
  2. 查重闸生效：lookup 一个已知项目必须报 ALREADY KNOWN
  3. 门禁生效：未 APPROVED 的候选，promote 必须被拒（非 0 退出）
  4. 结构不变量：candidates/ 不在 skills/ 之下（否则候选会被当正式技能加载）
"""
import subprocess, sys
from pathlib import Path

def find_workspace() -> Path:
    """从脚本位置向上找 workspace 根（兼容候选目录与提升后的 skills/ 位置）。"""
    for parent in Path(__file__).resolve().parents:
        if (parent / "learning" / "github" / "scripts" / "ghl.py").exists():
            return parent
    raise SystemExit("找不到 workspace（没有 learning/github/scripts/ghl.py）")


WS = find_workspace()
GH = WS / "learning" / "github"
SKILLS = WS / "skills"
PY = sys.executable
fails = []

def run(args):
    return subprocess.run([PY, str(GH / "scripts" / "ghl.py")] + args,
                          cwd=WS, capture_output=True, text=True)

# 1
v = subprocess.run([PY, str(GH / "scripts" / "validate_learning.py")],
                   cwd=WS, capture_output=True, text=True)
if v.returncode == 0:
    print("[1/4] 结构契约 OK")
else:
    fails.append("validate_learning 有 error")
    print("[1/4] 结构契约 FAIL")
    print(v.stdout, v.stderr)

# 2
r = run(["lookup", "social-media-skills"])
if r.returncode == 0 and "ALREADY KNOWN" in r.stdout:
    print("[2/4] 查重闸 OK（已知项目被识别）")
else:
    fails.append("查重没有识别已知项目")
    print("[2/4] 查重 FAIL")
    print(r.stdout)

# 3 门禁：自造一个未批准的探针候选（不依赖真实技能的状态，测试才是稳定的）
import shutil
probe = GH / "candidates" / "_gate_probe"
try:
    probe.mkdir(parents=True, exist_ok=True)
    (probe / "SKILL.md").write_text(
        "---\nname: _gate_probe\ndescription: temporary gate probe\n---\n\nbody\n",
        encoding="utf-8")
    (probe / "STATUS").write_text("CANDIDATE\n", encoding="utf-8")
    r = run(["promote", "_gate_probe"])
    if r.returncode != 0 and "APPROVED" in (r.stdout + r.stderr):
        print("[3/4] 提升门禁 OK（未批准候选被拒）")
    else:
        fails.append("promote 门禁没拦住未批准候选")
        print(f"[3/4] 门禁 FAIL rc={r.returncode}")
        print(r.stdout, r.stderr)
finally:
    shutil.rmtree(probe, ignore_errors=True)

# 4
if not str(GH / "candidates").startswith(str(SKILLS) + "/"):
    print("[4/4] 结构不变量 OK（candidates 不在 skills/ 下）")
else:
    fails.append("candidates 竟在 skills/ 下，候选会被自动加载")
    print("[4/4] 结构不变量 FAIL")

print()
if fails:
    print("BENCHMARK: FAIL")
    for f in fails:
        print("  ✗", f)
    sys.exit(1)
print("BENCHMARK: PASS (4/4)")
sys.exit(0)
