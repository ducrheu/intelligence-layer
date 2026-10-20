# 期刊与场景规格速查

数字一律以**官方投稿指南**为源（见文末链接），`paperfig.SPECS` 里的预设与本文逐条对应。
量到"最终印刷尺寸"之后就不要再缩放——字号是在最终尺寸下有意义的。

## 一、主流期刊

| 预设键 | 刊别 | 单栏 | 1.5 栏 | 通栏 | 页深上限 | 图内字号 | 字体 | 线宽 | 位图 dpi | 首选格式 |
|---|---|---|---|---|---|---|---|---|---|---|
| `nature` | Nature 及子刊 | 89 mm | 120 mm | 183 mm | 247 mm | 基准 7pt，最小 **5pt** | 无衬线（Helvetica/Arial） | 0.25–1 pt | 300 | PDF/EPS + TIFF(照片) |
| `science` | Science / AAAS | 57 mm | 121 mm | 174 mm | ~235 mm | 基准 7pt，最小 5pt | 无衬线（Helvetica 优先） | 0.5–1 pt | 300 | PDF/EPS |
| `cell` | Cell / Cell Press | 85 mm | 114 mm | 174 mm | 230 mm | 6–8pt，面板 8–10pt | 无衬线 | 0.5–1 pt | 300 | PDF/EPS |
| `ieee` | IEEE Trans./Letters | 88.9 mm (3.5in) | 137 mm | 181.9 mm (7.16in) | 241.3 mm | **≥8pt** | 衬线为主（Times），亦接受 Helvetica/Arial | 0.75–1.5 pt | 线稿 **600**，照片 300 | PDF/EPS |
| `acs` | ACS（JACS 等） | 84.7 mm (3.33in) | 127 mm | 177.8 mm (7.0in) | 233.4 mm | **≥8pt** | Helvetica/Arial/Times | 0.5–1 pt | 300（线稿 600） | PDF/EPS/TIFF |
| `elsevier` | Elsevier/工程类 | 90 mm | 140 mm | 190 mm | 240 mm | 6–8pt | 视刊而定（默认无衬线） | 0.5–1 pt | 300（线稿 600） | PDF/EPS/TIFF |
| `neurips` | NeurIPS/ICML/ICLR | 5.5 in = 139.7 mm（单栏即正文宽） | 同 | 同 | — | 7–9pt（正文 10pt） | 常见衬线 | — | 300 | PDF |

**Nature 官方原话（可直接引）**：
- 字型：*"Lettering should be in a sans-serif typeface, preferably Helvetica or Arial, the same font throughout all figures in the paper."*
- 字号：*"Separate panels in multi-part figures should each be labelled with 8 pt bold, upright (not italic) a, b, c. Maximum text size for all other text should be 7 pt; minimum text size should be 5 pt."*
- 尺寸：*"Nature's standard figure sizes are 89 mm wide (single column) and 183 mm wide (double column). The full depth of a Nature page is 247 mm."*
- 线宽：*"Line weights and strokes should be set between 0.25 and 1 pt at the final size."*
- 光栅化：*"Please do not rasterize line art or text in submitted figures and wherever possible supply editable, unflattened vector artwork."*
- 色彩：RGB 推荐（*"Colour artwork can be provided in RGB (recommended) or CMYK"*）；Extended Data 图 ≤300 ppi、单文件 ≤10 MB。

**IEEE 要点**：最终尺寸下正文标签 ≥8pt；线稿/组合图 600 dpi、彩色照片 300 dpi（400 dpi 亦可）；单栏 3.5 in、双栏 7.16 in；黑白打印可读（不能只靠颜色区分系列）。

## 二、投稿通用硬规则（与具体刊无关）

1. **在最终尺寸下作图**：`pf.subplots("single")`，不要"画大图再缩"——缩完字号必然 <5pt。
2. **矢量主件 + 位图预览**：PDF/SVG/EPS 为正文用；PNG（≥300dpi）只做预览与 Word 插图。
3. **字体嵌入而非转曲**：`pdf.fonttype=42`（TrueType 嵌入，文字仍可编辑）；`svg.fonttype='none'`。审稿/排版要能改字，转曲会被退。
4. **文字与线条不栅格化**；只有照片/显微图用 TIFF/PNG。
5. **颜色用 RGB**，印刷转换让期刊做；灰阶可读（线型/标记冗余编码）。
6. **面板标签**：Nature/Cell/Science 小写粗体正体 `a`、`b`；IEEE/ACS 用 `(a)`、`(b)`（本引擎按预设自动切换）。
7. **误差必须定义**：误差棒是 SD / SEM / 95% CI / IQR 要在图注写清，`n` 也要写。
8. **单位用 SI，写在轴标签里**：`应力 σ (MPa)`；对数轴写成 `log10(浓度)` 而非"浓度"。
9. **每张图一个结论**：图注第一句就是这张图要证明的话（见 craft-and-qa.md）。

## 三、非投稿场景（国内最常见的两类）

### `report` —— 实验报告 / 课程设计 / 毕业论文
- 版心宽按 A4（左右各 27.5 mm 页边距）取 **155 mm 通栏 / 120 mm 单栏**；不要超过版心。
- 图内字号 **9–10.5pt**，与正文（五号 10.5pt / 小四 12pt）协调；刻度 8.5–10pt 仍清晰。
- 输出优先级：**300dpi PNG**（插 Word/WPS 最稳）+ PDF/SVG 备用。Word 里按"插入图片"后设宽度为版心宽度，别用手拉伸。
- 中文标签：用 `pf.setup("report", lang="zh")`；汉字与 `$公式$` 混排必须走 `pf.mixed_text()`。
- 图注在图**下方**，格式 `图 1 标题` ；表注在表**上方**`表 1 标题`（GB/T 7713 惯例）。图注里写清 `n`、误差含义、显著性阈值。
- 图形选择偏"信息量"：柱图叠加个体点、箱线/小提琴替代纯柱、相关性给散点+拟合+相关系数。

### `slide` —— 幻灯片 / 海报 / 答辩
- 字号 **≥11pt（推荐 14pt+）**，线宽加粗 1.2–1.5 倍，去掉一切可以去掉的刻度。
- 一张图只说一句话；颜色对比可以更强烈，但仍保持色盲安全。
- 输出 200dpi PNG 足够（投影/屏幕）；PDF 用于打印海报。

## 四、来源（一手链接）

- Nature — Final submission / figure preparation：<https://www.nature.com/nature/for-authors/final-submission>（含 Lettering / Sizing / Image types 小节）；研究配图指南：<https://research-figure-guide.nature.com/>
- IEEE Author Center — 图形与分辨率要求：<https://journals.ieeeauthorcenter.ieee.org/>（IEEE Transactions "Information for Authors"：单栏 21 pica = 3.5 in，600 dpi 线稿）
- Science/AAAS、Cell Press、ACS、Elsevier 的 artwork 指南：各自 Author Center 的 *Artwork / Figures* 页（尺寸与 dpi 与上表一致；具体刊可能有 ±5 mm 差异，投稿前以该刊当期指南为准）
- 色板原始出处：Wong B. *Points of view: Color blindness.* Nat Methods 8, 441 (2011)（Okabe–Ito 色板）
