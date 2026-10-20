<!-- external-refs: ok （本文通篇在描述上游仓库的技能名，不是本仓库技能） -->
# 成熟技能库的组织约定（跨仓库提炼）

> 来源：`social-media-skills/skills` @ `6e30eeb`、`coreyhaines31/marketingskills` @ `5b2c000`、
> `shir-danishyar/humanize` @ `024aa19`（均 MIT）。这些是「优秀技能长什么样」的可执行结论，
> 也是我们 `validate_learning.py` 的检查项来源。

## 1. 目录契约（CI 强制的）

```
skills/<name>/SKILL.md          # 决策 + 流程
skills/<name>/references/*.md   # 深度：枚举/评分表/例子
skills/<name>/evals/evals.json  # 场景测试（test-first）
scripts/validate-skills.sh      # 把契约写成脚本
```
- `social-media-skills` 的校验脚本 8 项：结构、frontmatter（name==目录名）、
  evals JSON 合法、交叉引用可解析、description ≤1024、plugin manifest、pack、禁用词。

## 2. description 是路由器，不是简介

- 上游把用户原话全列进去（write a hook / first three seconds / scroll-stopping），
  结尾写 `For full captions use caption-writer` 把近邻任务分流。
- 长度上限 1024 字符（AgentSkills 规范，claude.ai 上传也强制）。
- **反例**：一句「帮助用户做社交内容」→ 永不触发。

## 3. 渐进式披露

- 正文（4–11KB）只留：Step 1..N、决策规则、自检清单。
- 细节进 references，每个 2–5KB，一个文件一个主题（formats / mechanisms / scoring / examples）。
- 大技能（18KB）应拆；小技能（<3KB）别硬拆。

## 4. 每技能自带验收

- `evals/evals.json` 结构：`{skill, version, description, evals:[{name, input, expect[]}]}`。
- 判据是**期望行为清单**（reads brand-profile first / uses genuinely different mechanisms），
  不是自动跑分；需要按条判定。
- `shir-danishyar/humanize` 走得更远：`scripts/ai_pattern_lint.py` + `tests/fixtures/`
  （含 before/after 对照对），把「能判定」变成「能自动判定」。

## 5. 底座优先

- `brand-profile` 声明 `Use FIRST, before any other social media skill`；
  内容类技能第 0 步统一是 `Read the foundation first`。
- 我们的对应物：`freelance/style/VOICE.md` + `skills/shop-human-writing`。

## 6. 硬规则写死

- `never fabricate stats`、`hooks must be TRUE`——把不可妥协的约束单独写成一条，
  不放脚注。我们的对应物：不编客户/成交/评价。

## 7. 交叉引用必须可解析

- 技能之间用反引号名字互指，CI 检查每个引用都真实存在。 → 我们的 `X1` 检查。
