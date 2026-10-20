# Compatibility Reference — Math Typesetting

证据来源与复现命令见文末。所有结论标记为 `FACT` / `EXPERIMENT` / `NOT YET VERIFIED`。

## 1. 渠道能力（本机实测/静态分析）

| 渠道 | 渲染数学 | 证据 |
|---|---|---|
| QQ 单聊/群聊 | ❌ | `FACT` QQ 官方文档"Markdown 消息"支持格式列表：标题/样式/链接/图片/列表/引用/分割线/换行——无数学、无代码块 |
| WebChat / Control UI | ❌ | `FACT` `dist/control-ui/assets/` 无 katex 资源；`markdown-runtime-*.js` 内 `katex` 命中 0 |
| study-notes HTML | ✅ | `FACT` 该技能模板显式加载 KaTeX 0.16.9 + auto-render |

## 2. 分隔符支持矩阵（EXPERIMENT E5 / E-Seg）

| 分隔符 | markdown-it-katex（Markdown 渠道） | 本技能服务端脚本 | GitHub（官方文档） |
|---|---|---|---|
| `$...$` | ✅ | ✅ | ✅ |
| `$$...$$`（独立成行） | ✅ | ✅ | ✅ |
| `$$...$$`（与中文同行） | ❌ 不渲染 | ✅（能识别） | ❌ |
| `\(...\)` | ❌ 被转义成 `(...)` | ✅ | ❌ 未列出 |
| `\[...\]` | ❌ 被转义成 `[...]` | ✅ | ❌ 未列出 |
| ```` ```math ```` | — | 不处理 | ✅ |

其他实测行为：

- 代码块（``` 与 `` ` ``）内的 `$` 受保护，不会被当公式（KaTeX auto-render 默认 `ignoredTags` 含 `pre`/`code`）。
- 货币串 `$100 ... $1.05` 未被误判为公式。
- KaTeX **auto-render 默认分隔符无 `$`**（源码注释：`// $ must come after $$` 且 `$` 那行被注释掉）。

## 3. 渲染器实测（EXPERIMENT E2/E4）

| 项目 | KaTeX 0.16.22 | MathJax 3.2.2 |
|---|---|---|
| 50 例基准 | 49/50（唯一失败=测试集设计问题） | 49/50 |
| `\tag{1}` | ✅ 正常 | ❌ 输出 `width="100%"` 且无 viewBox → 栅格化 1×64px 废图 |
| 平均耗时 | ~0.6ms/式 | ~3.3ms/式 |
| 服务端出图 | 需浏览器 | ✅ 原生 SVG |

建议用途：**KaTeX = 语法闸门**（快、严格）；**MathJax = 服务端出图**（无浏览器）。若要浏览器内渲染，用 KaTeX + CSS/字体（`study-notes` 已跑通）。

## 4. 已知坏写法（本机实测）

| 写法 | 后果 | 证据 |
|---|---|---|
| `\(...\)` / `\[...\]` 走 Markdown 客户端 | 变成 `(...)` / `[...]`，静默无报错 | E5 |
| `$$` 与中文同行 | 整段变纯文本 | E5 |
| `\tag{1}` / `\begin{equation}` 走服务端 SVG→PNG | 1×64px 废图 | E4 #44 |
| `\,` `\{` `\\` 走 OpenClaw IR / stripMarkdown | 反斜杠被 CommonMark 吃掉（`\,`→`,`、`\\`→`\`） | E1a |
| 数学内裸 Unicode（`·` `°` `−` `×`） | KaTeX 静默排错 | study-notes Check 2 + E2 strict 警告 |
| `\boxed{}` 套在彩色容器里 | 灰块盖住公式 | study-notes Check 3（既有经验） |
| `x_1 * y_2` 直接写在 QQ 正文（不在公式内） | 可能被 QQ Markdown 当斜体吃掉 | `NOT YET VERIFIED`（推断） |

## 5. 图片规格（EXPERIMENT E3/E4/E7）

| 参数 | 建议值 | 实测 |
|---|---|---|
| 光栅倍率 | `-z 3`（≈216dpi） | 单式 345×112px / 12.8KB |
| 背景 | 白（浅色主题） | `rsvg-convert -b white` |
| 深色主题 | `-b '#1e1e1e'` + 白字重着色 | 脚本 `--theme dark` |
| 多公式合成 | `montage` 竖排 | 21 式 → 2 页（1248×1907 / 1757×1758）共 147KB；脚本自动分页 |
| 整条消息卡片 | 浏览器截图 | 1857×6714px / 408KB → **太高，不推荐** |
| 高度上限 | ≤ 2000px | 手机可读性 + 避免客户端压缩 |
| 单条消息附图 | ≤ 3 张 | 避免刷屏（QQ 每条媒体消息占一条） |

## 6. QQ 侧硬限制（FACT，官方文档）

- 发送类型：`msg_type=0`(文本) / `2`(Markdown) / `3`(Ark) / `7`(富媒体)；单聊/群聊 Markdown 只发不收。
- 图片：jpg/png/gif/webp/bmp；软限制 20MB（超出降级为文件），硬限制 200MB；需先上传换 `file_info`（插件已实现）。
- **Markdown 内嵌图片只认公网 URL**（官方："对于 markdown 消息内的图片资源，请使用可在公网访问的资源 url"）→ 本机没有公网 URL，所以**公式不能和文字同行显示，只能是独立的图片消息**。
  - 本机插件里有个 `formatQQMarkdownImage()`（生成 `![img #WxH](url)`）但**没有任何调用点**（死代码），印证内嵌图这条路没接通。
- 文本分块：本机 QQ 渠道 `textChunkLimit = 5000`。
- 本地图片路径白名单：静态根 + 当前 agent 工作区（往工作区写 PNG 合法）。

## 6.5 投递路径实测（2026-09-17，本机）

| 路径 | 带 MEDIA 附件 | 证据 |
|---|---|---|
| 会话回复（用户在 QQ/WebChat 里对话 → 回复带 `MEDIA:`） | ✅ | WebChat 已实测；QQ 走同一适配器路径 |
| cron/automation announce | ❌ `AGENT_SELECTION_REQUIRED` | 3 次复现；纯文本可投递（20:46:46 `200 OK`） |
| `openclaw message send --channel qqbot --media` | ❌ `Bot "default" not running` | CLI 进程里插件 bot 未启动 |


## 7. 字体（EXPERIMENT）

- 本机 CJK 字体：`/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf`（`FACT`，`fc-match sans:lang=zh` 回退到它）→ `\text{中文}` 能出图。
- 无 Noto Sans CJK / 思源黑体（`FACT`）→ 中文公式字形质量一般；要"更像教材"可装 Noto Sans CJK SC（系统改动，需批准）。
- 无 LaTeX 发行版、无 matplotlib（`FACT`）→ 不要设计依赖 `latex`/`dvipng`/matplotlib 的方案。

## 8. 复现命令

```bash
cd /mnt/d/OpenClaw/workspace/research/math-rendering-2026-09-17
node tools/e2-katex-validate.mjs            # KaTeX 语法闸门（50 例）
node tools/e4-mathjax-svg-png.mjs           # MathJax→SVG→PNG（49 张图 + 尺寸表）
node tools/e5-markdown-math-integration.mjs # Markdown 分隔符/误判测试
node tools/e6-chunk-boundary.mjs            # 5000 字符分块边界
node tools/e7-message-card.mjs benchmark/real-samples/sample-1.md
node tools/census.mjs ; node tools/census-surfaces.mjs   # 线上真实输出统计（只读）
```
