# 判断一个外部仓库是否值得信任 / 采用

用户丢来一个仓库说「看看这个」时，**默认动作不是读代码，是先判它的采用度是不是真的**。
热门 ≠ 可用；星数 ≠ 采用度。这个判断五分钟能做做完，能挡掉后面几小时的白工。

## 一、用 API 取元数据，不要刮 HTML 页面

仓库页与 `raw.githubusercontent.com` 的直接 curl 可能被拦；**API 稳定可读**：

```bash
curl -s -H "Accept: application/vnd.github+json" https://api.github.com/repos/<owner>/<repo>
```

一次拿全：`stargazers_count` / `subscribers_count`（= watchers）/ `forks_count` /
`open_issues_count` / `created_at` / `pushed_at` / `license.spdx_id` / `topics` / `language`。

README 走 Contents 端点（`content` 字段是 base64，本地解码），别去抓网页：

```bash
curl -s https://api.github.com/repos/<owner>/<repo>/readme
```

另外三个值得取的端点：

- **贡献者集中度** `/repos/<o>/<r>/contributors` —— **每页上限 100**。看前几名的提交数断崖在哪：
  头三名各几千次、第四名掉到两位数，说明「上百个贡献者」实际是三个人在做。
- **发版节奏** `/repos/<o>/<r>/releases` —— 几天内连发五个大版本 = 迭代极快，也可能是不稳定。
- ⚠️ `/repos/<o>/<r>/stargazers` 带 `starred_at` **需要认证**，匿名会 401。想核增速只能另找 star-history 图。

## 二、参与度指标要和对照组一起看，孤立看没有意义

**watcher/star 比**和 **issue/star 比**是识别灌水星最灵的两个指标——
机器人会 star，但不会 watch，也不会提 issue。

| 仓库 | stars | watchers | **w/s 比** | **issue/star** |
|---|---|---|---|---|
| 某个 6 个月大的新项目 | 194,186 | 632 | **0.33%** | **0.29%** |
| react/react | 251,004 | 6,608 | 2.63% | 0.57% |
| torvalds/linux | 251,763 | 8,468 | 3.36% | — |
| pytorch/pytorch | 104,793 | 1,804 | 1.72% | 16.9% |

读法：真实巨型项目的 w/s 比在 **1.7%–3.4%**；掉到 **0.3% 量级**就是低了一个数量级。
issue/star 同理（0.29% vs 16.9% 相差 59 倍——真有十万人在用的工具不可能只产生几百个 issue）。
再叠一条时间常识：6 个月拿到 19 万星 vs react 用 13.4 年拿到 25 万星。

## 三、结论分两句说，不要一律打成「假的」

- **项目是真的吗**：有代码、有发版、有提交者、有真实包与文档 → 是。
- **热度是真的吗**：指标互相矛盾 → 星数大概率不是采用度。

这两句必须分开讲。校准到「我在说它热度不可信，不是说我发现它造假」就够了；
不替用户判定动机，也不因此否掉它作为工具本身的价值。

## 四、顺手读它的免责声明与许可，当场划清帮手边界

README 的 Disclaimer / LICENSE 常自己划了线（授权使用范围、第三方商业工具必须合法取得、
不得绕过的保护措施）。**用户自述的用例若落在这些线外（克隆他人的付费功能、
破解商业软件授权、绕过保护措施），当场说清不参与，别等被追问。**
他如果只是「看着有意思想玩玩」，给一条：先记下来、别现在做——按他自己的纪律，
它属于「新战线」，而「是否开新战线」是另一个判据（见 `study-career-path-decision-analysis` 规则十五）。
