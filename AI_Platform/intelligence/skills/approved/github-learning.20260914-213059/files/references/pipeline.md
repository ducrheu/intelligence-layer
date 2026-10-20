# 八步流水线 · 详细做法

> 每一步都写清：**做什么 / 判据 / 产物**。判据不满足就不许进下一步。

## 0. 查重（防重复学习）

```bash
python3 learning/github/scripts/ghl.py lookup <关键词…>
```
- 判据：告示是 `NEW` 才继续；`ALREADY KNOWN` / `PARTIAL` 先读命中项。
- 命中 `ALREADY KNOWN` 时只回答四个问题：过期了吗？版本变了吗？有新能力吗？有失败经验吗？
- 产物：无（一次命令的结论）。

## 1. Discovery

- 做什么：确定它**解决什么问题 / 主要用户 / 核心技术 / 版本与版本来源 /
  文档入口（README·docs·examples·tests·scripts·architecture·changelog）**。
- 只读和本次目标有关的内容；在 `discovery.md` 里写明「明确不读什么」。
- 判据：能一句话说清「这个仓库的类型（单项目/技能库/工具集）和这次要学什么」。
- 产物：`knowledge/<project>/discovery.md`，registry 状态 `DISCOVERED`。
- 命令：`ghl.py new <project> --repo <o/r> --license <L> --goal "…"`

## 2. Extraction

- 做什么：按十个维度抽：核心概念 / 使用场景 / API·CLI / 最小可运行示例 /
  配置方式 / 常见错误 / 限制 / 安全问题 / 性能问题 / 与 OpenClaw 的结合方式。
- 方法：`git clone --depth 1` 到 `/tmp/ghl/`，然后
  `find -maxdepth 2` 看结构 → `grep -rn` 定位 → **只读命中的片段**。
- 判据：每条抽出来的事实都有 `file:line` 或 URL。
- 产物：素材与出处；registry 状态 `EXTRACTED`。

## 3. Distillation

- 做什么：把素材写成五个文件，每条知识回答八问：
  何时用 / 为什么 / 怎么用 / 最小实现 / 什么时候不要用 / 常见错误 / 如何验证 /
  如何和现有系统结合。
- **禁止**大段复制 README。原文留在仓库或 `knowledge/<p>/raw/`。
- 判据：`ghl.py check` 无 error；无法指导行动的条目已删除。
- 产物：`overview.md` `patterns.md` `pitfalls.md` `tool-selection.md` `sources.md`；
  状态 `DISTILLED`。

## 4. Validation

- 命令：`ghl.py check`（脚本 `scripts/validate_learning.py`）。
- 查：知识文件齐全/非空/非转述；技能 frontmatter、小节、references、evals、STATUS、
  交叉引用。
- 判据：0 error。warning 要么修，要么在 `sources.md` 里写明为何接受。

## 5. Skillization

- 只有知识足够成熟（能指导行动、有来源、经得起追问）才建技能。
- 位置：`learning/github/candidates/<name>/`（**绝不能**放在 `skills/` 下）。
- `SKILL.md` 只写：Trigger / Preconditions / Decision rules / Workflow /
  Tool selection / Failure handling / QA / Human handoff。理论进 `references/`。
- `description` 里必须含**用户真会说的触发词**，否则永远不会被选中。
- 判据：`SKILL.md` 能一次读完（目标 ≤10KB）；`description` ≤1024 字符且含触发语。
- 产物：候选技能目录；状态 `CANDIDATE`。

## 6. Benchmark

- `evals/evals.json` **先写**（test-first）：每条 `input` + `expect[]`，
  只有 expect 全满足才算 pass。
- `scripts/run_benchmark.py` 必须**可复现执行**：至少包含
  阳性对照（好产出被接受）+ 阴性对照（坏产出被拦下）+ 一次真实运行。
- 命令：`ghl.py benchmark <skill>`；结果写进 `BENCHMARK.md`。
- 判据：PASS。**失败只能 `CANDIDATE` / `NEEDS_REPAIR`，不许写「文档声明通过」。**
- 产物：状态 `BENCHMARKED` → `VALIDATED`。

## 7. Experience

- 每个真实任务/benchmark 之后写一条：task / tool / version / input / result /
  failure / fix / lesson / reusable_pattern。
- lesson 必须写成 **「以后再遇到 X，做 Y，不做 Z」**，不是「这次学到了很多」。
- 失败方案进 `experience/rejected/`，不删。

## 8. Approval

- 人工把 `candidates/<name>/STATUS` 改成 `APPROVED`（这是**唯一**的批准动作）。
- 命令：`ghl.py promote <skill>`（门禁：STATUS=APPROVED 且 benchmark PASS；
  覆盖线上同名技能会先备份）。
- 团队/共享 Gateway：改用 `openclaw skills workshop propose-create` → `evaluate` → `apply`。
- 最后：`ghl.py report <project>` 生成 `reports/<date>-<project>-learning-report.md`。
