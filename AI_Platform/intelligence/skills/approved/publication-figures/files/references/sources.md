# 借鉴来源与取舍

本 skill 是在调研 GitHub 上现有"论文配图"类 agent skill 之后**自己重写**的：保留经过验证的
规范与实践，去掉与 Hermes 无关的编排层（那套是 Claude Code 的插件/斜杠命令结构），并把若干
在 Hermes 环境下**实测踩到的坑**固化成代码与测试。

## 调研的仓库

| 仓库 | 许可 | 借鉴了什么 |
|---|---|---|
| [garrettj403/SciencePlots](https://github.com/garrettj403/SciencePlots) | MIT | 期刊 `.mplstyle` 思路与 `journal/*`、`language/cjk-*-font` 预设；本引擎改成"运行时一套 rcParams + SPECS 表"，不再依赖 style 文件与 LaTeX |
| [TingxiYu/academic-figure-skill](https://github.com/TingxiYu/academic-figure-skill) | Apache-2.0 | CNS 排版基线（Arial/Liberation、5pt 下限、89/183mm）、样式/导出基线必须"抄到脚本顶部"的纪律、29 类图的清单式覆盖；其 150MB 预览图与 16 篇参考文档未收录（按需时再查） |
| [TAO-QKV/Icarus-Figures](https://github.com/TAO-QKV/Icarus-Figures) | 见仓库 LICENSE | "四轴质量标准"（深度/优雅/不可指摘/一眼是论文）、图注陈述结论、脚本可复现的硬规则、`critique.py` 式静态质检门；**未采用**其 `paperfig` 包（与本引擎同名不同物）与 26MB 示例资产 |
| [sai-tv/academic-figures](https://github.com/sai-tv/academic-figures) | 见仓库 LICENSE | 多刊规格表（Nature/Science/Cell/ACS/IEEE/Elsevier/NeurIPS）、"矢量可编辑 SVG 层"的思路（本引擎用 TikZ/matplotlib 替代手工 SVG） |
| [tvhahn/matplotlib-skill](https://github.com/tvhahn/matplotlib-skill) | 见仓库 LICENSE | 图型模板化的组织方式（P1 横条、P3 时间序列带滚动平均、P8 多面板等） |
| [K-Dense-AI/scientific-agent-skills](https://github.com/K-Dense-AI/scientific-agent-skills) | 见仓库 LICENSE | 期刊规格与"面向 AI agent 的 skills 目录"结构参考 |

## 本实现新增的、上面仓库没有的东西

1. **客观尺寸校验**：导出时读 PNG 的 IHDR 与 PDF 的 mediabox，核对"mm×dpi"是否与实际像素/页宽一致
   —— 尺寸跑偏是投稿被退的第一大原因，且肉眼看不出来。
2. **字号/单位/中文字形自动审计**（`audit_fig`）：把"最小 5pt""轴标签要带单位""中文不能是方框"
   变成可打印的检查结果，而不是提示词里的一句叮嘱。
3. **实测坑位固化**（附回归测试，见 `scripts/test_paperfig.py`）：
   - 只有 `font.family` 直接给字体名列表时，matplotlib 才做逐字形回退；靠 `font.sans-serif` +
     泛名 `sans-serif` 解析**不会**回退 → 中文变方框。
   - 只要字符串里出现 `$...$`，mathtext 就不走字体回退，整串汉字变方框 → 提供 `mixed_text()` 自动拆段。
   - IEEE 的刻度字号若按"基准 −0.5"会掉到 7.5pt < 8pt 下限 → 下限硬约束。
   - EPS 后端不支持半透明（置信带会变实心块）。
4. **中文/教学场景预设**（`report`/`slide`）：这些仓库清一色面向英文投稿，没有覆盖
   "实验报告 / 课程设计 / 毕业论文"这类最常见的实际需求。
