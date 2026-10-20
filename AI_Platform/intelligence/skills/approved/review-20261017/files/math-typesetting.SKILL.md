---
name: math-typesetting
description: 在聊天渠道写数学（QQ / WebChat）：默认写成"手写体"纯文本（Unicode 上下标 + √ ∫ Σ 希腊字母），既不是 LaTeX 源码，也不是图片。当回复里要写公式、推导、极限/积分/矩阵/概率公式，或用户抱怨"公式变成源码 / 看不懂 / 我要的是手写那样 / 不要图片"时使用。触发词：数学公式、公式、推导、公式变源码、公式显示不对、手写体、Unicode 公式、math rendering、typesetting。只有用户明确要"公式图/图片"时才走 §0.1 的出图管线。
---

# Math Typesetting Skill

**核心事实（先读，别凭感觉）**：本机所有聊天渠道**都没有数学渲染器**。

- QQ：官方 Markdown 子集没有数学能力（`FACT`，QQ 机器人官方文档 Markdown 消息页）。文本以 `msg_type=2` 发出去，`\frac{a}{b}` 就是源码。
- WebChat / Control UI：bundle 里没有 KaTeX/MathJax 资源（`FACT`，静态分析 `dist/control-ui/assets/*`）。
- 结论：**LaTeX 在本机任何聊天渠道都只会变成源码**。所以要"看起来像手写"，办法不是让渠道渲染，而是**直接用 Unicode 数学字符把公式写出来**（§0.0）。出图（§0.1）是备选，不是默认——小主人 2026-09-23 明确说过：**"我不是要图片，就是写出数学公式，看上去和手写没两样"**。

## 0.0 默认写法：Unicode 手写体（聊天渠道一律用这个）

直白说：**把 LaTeX 手工"翻译"成能在任何字体里正常显示的字符**。正文里不出现 `$`、不出现任何反斜杠命令。

### 0.0.1 对照表（左 = 别写，右 = 就这么写）

| LaTeX | 写法 | 例 |
|---|---|---|
| `\frac{a}{b}` | `a/b`，分子分母是复合式时各自加括号 | `x²/(1+√(1−x²))`、`λ/2`、`2(Cμ_p−A)/D` |
| `x^{2}` `x^{n}` `x^{-1}` | `x²` `xⁿ` `x⁻¹` | `σ_p²`、`Σ⁻¹` |
| `x^{2n}`（多位上标） | `x^(2n)` | `e^(−t²)` |
| `x_0` `x_1` | `x₀` `x₁` | `∫₀¹` |
| `x_{p}` `x_{min}`（多位下标） | 保留下划线 | `μ_p`、`σ₁₂`、`w_min` |
| `\sqrt{x}` `\sqrt[3]{x}` | `√x` `∛x` | `√(1−x²)` |
| `\int_0^1` `\int_0^{2x}` | `∫₀¹` `∫₀^(2x)` | `∫₀¹ x² dx` |
| `\sum_{i=1}^{n}` `\prod` | `Σ_(i=1)^n` `Π` | `Σ_(i=1)^n xᵢ` |
| `\lim_{x\to 0}` | `lim_(x→0)` | |
| `\partial` `\nabla` `\Delta` | `∂` `∇` `Δ` | `∂L/∂w = 2Σw − λμ − γ1` |
| `\cdot` `\times` `\div` | `·` `×` `÷` | `2x·sin(1/x)`、`300×417` |
| `\le \ge \ne \approx \infty \pm` | `≤` `≥` `≠` `≈` `∞` `±` | |
| `\to` `\Rightarrow` `\in` | `→` `⇒` `∈` | 推导用 `⇒` 收口，映射用 `→` |
| `\langle a,b\rangle` | `⟨a,b⟩` 或 `a·b` | |
| `w^{\mathsf{T}}` | `wᵀ` | `wᵀΣw` |
| `\mathrm{d}x` | `dx` | `∫₀¹ x² dx`（`d` 不加斜体处理） |
| 希腊字母 | 直接打字符 | `α β γ δ ε θ λ μ ν ξ π ρ σ τ φ ω Γ Ω` |
| `\begin{cases}` / `\begin{aligned}` | 用 ``` 代码块逐行写，行尾用 `⇒`/`= ` 对齐 | 见 §0.2 |
| `\mathbb{R}` | `ℝ`（或直接写 R） | |
| `x̄`（均值）`x'`（导数） | `x̄` `x′`（U+2032） | |

### 0.0.2 硬规则

1. **不出现** `$…$`、`$$…$$`、`\(`、`\[`，也不出现 `\frac`、`\sqrt`、`\sum` 这类命令——一律按上表换成字符。
2. **只用表里出现过的符号**。不确定某个字符在 QQ/WebChat 字体里有没有 → 不写它，改用文字（"趋于 0""约等于""无穷"）。别为了好看引入生僻符号。
3. **多字符上下标**用 `_(…)` / `^(…)`：`∫₀^(2x)`、`e^(−t²)`。单字符才用 `₀₁₂ₙ` / `²³ⁿ`。
4. **运算符两边留空格**：`a + b`、`wᵀμ = μ_p`；函数名与括号之间不留：`ln(1+x²)`、`sin²θ`。
5. **分式保持"能一眼读懂"**：`(Cμ_p−A)/D` 比 `Cμ_p−A/D` 清楚；分子分母都复合时**两个括号都要**。
6. **布局就是"印刷体感"的大头（2026-09-24 小主人 指出的差异点）**：
   - **不要把数学放进 ``` 代码块**。等宽字体让它看起来像程序，不像印刷体；而正文段落里的 Unicode 数学字符会走客户端的数学/衬线字体回退 —— 这才是"像印出来的一样"的来源。
   - 一条推导一行，**行与行之间空一行**（段落的呼吸感），不要挤在一个代码块里。
   - 续行用两个空格缩进，让 `=`/`⇒` 上下对齐：
     ```
     I = ∫₀¹ (1 − √(1−x²)) dx
       = ∫₀¹ 1 dx − ∫₀¹ √(1−x²) dx
       = 1 − π/4 ≈ 0.2146
     ```
     （上面这段是为了说明对齐规则才围起来的；**实际发送时不要围代码块**，就按普通段落发。）
   - 中文提示语用 **粗体**（`**从最大值点向两端泰勒展开**：`），数学本身不要加粗。
7. **中文与公式混排**时公式两侧各留一个空格：`把 1−cos²θ = (1−cosθ)(1+cosθ) 代进去`。
8. 写完后**自检一遍**：正文里若还剩 `\`、`$`，或数学还躺在 ``` 里，就等于没做。也可以直接跑闸门：
   `node /mnt/d/OpenClaw/workspace/skills/math-typesetting/bin/check-print.mjs <消息.md>`

### 0.0.3 工具：别手工翻 LaTeX

- **转换**：`node /mnt/d/OpenClaw/workspace/skills/math-typesetting/bin/latex-to-print.mjs --text '<含 LaTeX 的文本>'`
  或 `... <in.md> -o <out.md>`；`-` 读 stdin。它处理 `\frac`→`a/b`、`\sqrt`→`√(...)`、上下标→`²/₀/^(2n)`、
  希腊字母、`\mathbb`→`ℝ`、`\le`→`≤`、`\to`→`→`、`\bar/\hat`→组合重音、`\circ`→`°`、`-`→`−` 等。
- **闸门**：`node .../bin/check-print.mjs <消息.md>`（`--fix` 顺手转换）。退出码 0 才算过。
- 映射约定与社区现成做法一致（unicodeit、Pandoc `--to=plain` 的 unicode 数学输出、各家 LaTeX→Unicode
  转换器的公开映射说明）：**先把 LaTeX 翻成 Unicode 字符，再按段落排版**，而不是指望渠道渲染。

## 0. 快速决策树

```
这条消息里有数学吗？
├─ 没有 → 正常写，本技能不介入
└─ 有
   ├─ 面向聊天渠道（QQ / WebChat）发给小主人？
   │   ├─ 是 → 【默认】§0.0 Unicode 手写体，**不出图、不写 LaTeX**
   │   │        └─ 只有他明确说"要图片 / 公式图"，或材料要给外人看/必须印刷体排版 → 走 §0.1 出图
   │   └─ 否（要产出 HTML 学习材料）→ 交给 study-notes 技能（KaTeX + auto-render）
   └─ 目标是纯文本/日志/代码 → 同样用 §0.0 的写法（不要写 LaTeX）
```

> 判断依据（2026-09-23）：小主人要的是"看上去和手写没两样"的**文字**，不是图片。图片会挡住复制、检索和手机端的正文阅读；Unicode 文本在 QQ/WebChat 都是普通文本，任何字体都能显示。**默认永远选文本**。

### 0.1 一条命令（**仅当小主人明确要图时**）

> 默认不要走这里。只有他说"要图片 / 公式图 / 给我一张图"，或材料需要印刷体排版（给外人看）时，才出图。

```bash
cd /mnt/d/OpenClaw/workspace/skills/math-typesetting
node /mnt/d/OpenClaw/workspace/skills/math-typesetting/scripts/math-render.mjs selftest   # 依赖自检
node /mnt/d/OpenClaw/workspace/skills/math-typesetting/scripts/math-to-image.mjs <message.md> -o <outdir> --scale 3
#   → <outdir>/sheet-1.png ...（块级公式拼页，单张 ≤2000px）
#   → <outdir>/reply.txt（正文 + MEDIA: 行，可直接作为回复发出）
```

**脚本一律写绝对路径**（`/mnt/d/OpenClaw/workspace/skills/math-typesetting/scripts/...`）：
相对路径依赖 cwd，在你的工作区里根本不存在，而且 approvals 允许项是按解析后的 argv 匹配的。
无人值守会话直接跳到下面的 §0.1.1。

把 `reply.txt` 的内容作为回复文本发出即可；`MEDIA:` 行会让 OpenClaw 把图作为附件发送。
**QQ 的公式图只能作为独立图片消息发送**（`msg_type=7`）——QQ 的 Markdown 内嵌图片只认公网 URL，本地文件无法内嵌（本机插件里 `formatQQMarkdownImage` 是未接线的死代码）。所以不要指望公式和文字在同一行里。

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
| 走 Markdown 的渠道（QQ 文本、WebChat 文本） | `$...$` | `$$...$$`，**独立成行，前后空行** | `\(...\)` `\[...\]`（会被 CommonMark 吃掉反斜杠，静默变 `(...)`） |
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

## 7. 与现有资产的关系

- **study-notes** 技能：负责 HTML 学习材料（KaTeX 0.16.9 + auto-render + `build_and_check.py` 静态校验 + `fix_math.py`）。本技能**不**重复实现它；聊天里公式多到爆炸时，转交它产出材料。
- 本技能只解决**聊天消息里公式的可见性**。

## 8. 参考

- `references/compatibility.md` — 实测兼容矩阵、坏写法清单、证据来源与复现命令。
- 研究报告：`research/math-rendering-2026-09-17/MATH_RENDERING_RESEARCH_REPORT.md`
