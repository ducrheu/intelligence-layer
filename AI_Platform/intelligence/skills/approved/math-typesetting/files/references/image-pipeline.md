# 图片分支：LaTeX → 公式图

**何时读这个文件**：只有 `SKILL.md` §0.1 的出图分支被触发时才读——小主人明确要“公式图 / 图片”，
或材料要给外人看、必须印刷体排版。聊天里写公式一律用 `SKILL.md` §0.0 的 Unicode 手写体。

下面沿用原 SKILL.md 的编号（§0.1.1、§0.2、§1–§6），便于和旧引用对照。

### 0.1.1 无人值守会话的唯一命令形状（2026-09-23 加）

如果你的 `exec` 是 `security=allowlist`（`tools.exec.mode=ask`），那么**只有单段、无重定向、
无 `$()` 的命令能自动跑**：`cat > msg.md <<EOF`（heredoc）、`>`、`$(...)`、`cd X && node ...`
一律弹审批，而 cron / 派发 / CLI 会话**没有人能点那个审批**——会话会卡在
`blocked_tool_call`，表现为"你不回复"。所以后台/无人值守场景不要自己拼管道，用共享入口：

```bash
node /mnt/d/OpenClaw/workspace/skills/math-typesetting/bin/render-math.mjs \
     --out <你工作区内的目录> --text '<含公式的 markdown>' --scale 3
```

一条命令、一次 exec 调用：它自己写源文件、自检依赖、跑语法闸门、渲染、把可直接发出的
`reply.txt` 打到 stdout。配套审批允许项（由操作者在 exec approvals 里配一次，全 agent 可复用）：

- `pattern=/usr/bin/node`，`argPattern=^/mnt/d/OpenClaw/workspace/skills/math-typesetting/bin/render-math\.mjs( .*)?$`

`--out` 必须落在**你自己 agent 的工作区内**（MEDIA 附件按工作区白名单判定），例如 mentor 用
`/mnt/d/OpenClaw/workspace/agents/mentor/tmp/math/out`。`main` 不受此限（`mode=full`）。

**不要先探测环境**：`ls`、`which node`、`node --version`、`cat SKILL.md | head` 这类预热命令在
allowlist 模式下同样可能弹审批，而无人值守会话付不起这个代价——直接跑上面那一行命令形状。
同一会话里第一次被审批拦下时，别反复重试另一种写法：换行只会再卡一次。

**也别在无人值守会话里做数值自检**：`python3 -c "..."` 属"严格内联求值"，在 allowlist 模式下
一律被拦（实测 mentor / study-planner / project-manager 都倒在这一条上，会话直接卡住）。
要验算就在正文里给**解析验算**（回代恒等式、量纲、边界值、几何意义），或读现成的解析材料。

### 0.2 写正文的硬规则（image 渠道）

因为公式只能整张出图，**不要在句子里写行内 `$...$`**：所有需要被看到的数学都写成独立成行的块级公式，它会被收进拼页；行内公式在大段中文里既渲染不了也进不了拼页，只会以源码形式留在正文里。

## 1. Generation Rules（怎么写）

1. 只用 **KaTeX 0.16.22 能解析的子集**；不确定先跑闸门（§6）。
2. 数学里**只用 ASCII + LaTeX 命令**，禁止裸 Unicode：
   `·`→`\cdot`、`°`→`{}^\circ`、`−`→`-`、`×`→`\times`、`≈`→`\approx`、`≥`→`\ge`、`μ`→`\mu`。
   （裸 Unicode 会让 KaTeX 静默排错，不报错——`study-notes` 的 Check 2 专治此病。）
3. **禁用命令**：`\tag{}`、`\begin{equation}`（服务端出图会产废图，见 references §3）、
   `\href{}`、`\url{}`、`\includegraphics{}`（安全 + 兼容）、`\SI/\qty/\si`（siunitx 不支持）、
   `\boxed{}`（在彩色容器里会盖住公式；聊天场景直接不用）。
4. 上下标多字符必须配 `{}`：`x^{2n}` ✅ / `x^2n` ❌。
5. 函数名用命令：`\sin \lim \log \ln \exp \operatorname{Var} \operatorname{Cov}`，不要斜体裸写 `sin`。
6. 微分用直立 d：`\mathrm{d}x`，细空用 `\,`。
7. 中文进公式用 `\text{...}`，且**不要**把整句话塞进数学模式。

## 2. Delimiter Rules（什么时候用什么括起来）

**关键：分隔符规则是按"谁负责渲染"定的，不是按数学书定的。**（实测依据见 references §2）

| 输出目标 | 行内 | 块级 | 禁止 |
|---|---|---|---|
| 不支持数学渲染的聊天渠道（QQ / WebChat） | 不用 LaTeX，走 `SKILL.md` §0.0 的 Unicode | 同左 | `$...$` `$$...$$` `\(...\)` `\[...\]` 全部不用 |
| 服务端出图管线（本技能脚本） | `$...$` 或 `\(...\)` 都能识别 | `$$...$$` 或 `\[...\]` 都能识别 | 无（但建议统一 `$`/`$$`） |
| HTML 材料（study-notes） | `$...$` | `$$...$$` | 同上（其 auto-render 配置只开了 `$`/`$$`） |
| 纯文本 / 日志 | 不用 LaTeX | 不用 LaTeX | 全部 |

补充硬规则（`EXPERIMENT` 实测）：

- 块级公式**必须独立成行**：`所以$$x=1$$成立` 不会渲染（也不是源码高亮，就是纯文本）。
- KaTeX `auto-render` 的**默认分隔符里没有 `$`**（默认只有 `$$`、`\(`、`\[`、equation/align 家族）。任何"让客户端自动渲染"的方案都必须显式把 `$` 加进 `delimiters`。
- 正文里的货币 `$100`/`$1.05` 不会被误判（markdown-it-katex 已实测），但仍建议货币场景避写 `$`，改用"100 美元"或 `\$100`。

## 3. Structure Rules（结构）

| 需求 | 写法 | 状态 |
|---|---|---|
| 分数 | `\frac{a}{b}`；行内大分数用 `\dfrac`；嵌套 ≤ 2 层 | ✅ 已验证 |
| 根号 | `\sqrt{x}`、`\sqrt[3]{x}` | ✅ |
| 极限 | `\lim_{x\to 0}`（块级上下限在下方） | ✅ |
| 积分 | `\int_0^1`、`\iint_D`、`\iiint_\Omega` | ✅ |
| 求和 | `\sum_{i=1}^{n}`、`\prod` | ✅ |
| 多行推导 | `\begin{aligned} ... &= ... \\ ... &= ... \end{aligned}` | ✅ |
| 分段函数 | `\begin{cases} ... & x\ge 0 \\ ... & x<0 \end{cases}` | ✅ |
| 矩阵/行列式 | `pmatrix` / `bmatrix` / `vmatrix` | ✅ |
| 公式编号 | **不用** `\tag`/`equation`；在正文写"式(1)"或用 `aligned` 右侧文字 | ✅（`\tag` 会坏） |
| 多公式连续 | 每个各自独立成行；≥3 个块级公式时优先考虑合并成一张公式图（§4.3） | ✅ |

## 4. Compatibility Rules（各渠道怎么落地）

### 4.1 渠道能力矩阵

| 渠道 | 能渲染数学？ | 策略 |
|---|---|---|
| QQ（单聊/群聊） | ❌（官方 Markdown 子集无数学） | 正文文本 + **公式图**（媒体消息）；正文里不要把 LaTeX 当"给人看的"内容 |
| WebChat / Control UI | ❌（bundle 无 KaTeX） | 同上；长推导改出 HTML 材料 |
| 未知/未来渠道 | 默认 ❌ | 先按"不能渲染"处理，出图；确认支持后再改文本 LaTeX |

### 4.2 出图流程（本技能脚本）

```bash
cd <skill-dir>
node scripts/math-render.mjs selftest                      # 依赖自检
node scripts/math-to-image.mjs <message.md> -o <outdir> --scale 3 --theme light
#   reply.txt / sheet-*.png / math-*.png / manifest.json
node scripts/math-render.mjs check   <message.md>           # 只做语法闸门，不写图
node scripts/math-render.mjs render  <message.md> -o <outdir> --scale 3   # 每个公式单独一张图
```

- 依赖：`katex`、`mathjax-full`（技能目录下的 node_modules）+ 系统 `rsvg-convert` / `convert` / `montage`。
- `--scale 3` ≈ 216dpi，肉眼即印刷体；`--scale 2` 体积更小。
- 拼页参数：`--max-sheet-height 2000`（默认）`--max-width 1800`（默认，超宽自动缩）。
- `--inline keep|image`：行内公式默认保原文不丢内容（`image` = 每个行内公式单独附图，一般别用）。
- 实测：单式典型 5–13KB；一条 30 个公式的真实消息 → 30 张图 428KB、拼 2 张页 1907px/1758px 高。

### 4.3 投递规则（按渠道）

- **QQ**：把 PNG 作为媒体发送（`MEDIA:<path>`，由该会话的回复带出）。本地路径需在 agent 工作区内（插件白名单规则）。
  - 一条消息附图 **1–3 张**：`math-to-image.mjs` 已自动把块级公式拼页，避免刷屏。
  - ⚠️ **不要用 cron/automation 的 announce 投递带附件**：本机实测必失败，报 `AGENT_SELECTION_REQUIRED`（3 次复现；`agents.defaults.systemAgent.agentId` 已是 main，非配置问题）。cron announce **纯文本可以投递**。
  - ⚠️ `openclaw message send --channel qqbot --media ...` 本机报 `Bot "default" not running`，也不要用。
  - 结论：**只有会话回复路径能把图发到 QQ**。
- **WebChat**：同样用 `MEDIA:<path>` 附件；正文写"推导见下图"。
- **纯文本/日志**：不出图，用 ASCII/Unicode 近似（如 `d/dx`、`∫`、`Σ`）。

### 4.4 正文与公式的分工（重要）

- 图片**只承载公式**，不要整条回复都做成图：否则不可复制、不可检索、无障碍全废。
- 正文里保留结论文字；公式图作为"看得见"的部分。
- 如果一条消息里公式特别多（>10），改写策略：正文给思路与结论，把完整推导做成 HTML 材料（study-notes），聊天里只发摘要 + 1 张公式页。

## 5. Fallback Rules（失败怎么办）

1. **语法闸门不过 → 不要发**：修 LaTeX 后重试。
2. **渲染失败（无 rsvg-convert / 无字体 / SVG 不可测）→ 文本降级**：原样发 `$...$` 源码，并**明确说明**"公式渲染失败，以下为 LaTeX 源码"。绝不静默丢内容（对齐 AGENTS.md）。
3. **图片发送失败 → 文本降级**：同上，并说明原因。
4. 任何降级都必须让用户知道，不允许假装成功。

## 6. Validation Rules（输出前自检清单）

- [ ] 分隔符成对：`$` 计数为偶且不跨行；`$$` 成对且独立成行。
- [ ] `{}` 配平；`\begin{...}` 与 `\end{...}` 数量与名称一致。
- [ ] KaTeX 逐段 parse 通过（`math-render.mjs check`）。
- [ ] 无禁用命令：`\tag` `\begin{equation}` `\href` `\url` `\includegraphics` `\SI` `\boxed`。
- [ ] 数学内无裸 Unicode 符号（`·` `°` `−` `×` `≈` `μ` …）。
- [ ] 代码块内没有数学被误当公式（脚本已保护 ``` 与 `` ` ``）。
- [ ] 渠道不支持的分隔符没用（Markdown 渠道禁 `\(` `\[`）。
- [ ] 分块：单条消息 ≤ 渠道上限（QQ 5000 字符）；块级公式前后有空行，别跨分块边界。
- [ ] 出图时：图片高度 ≤ 2000px、单条消息附图 ≤ 3 张、正文不是整段图片。

