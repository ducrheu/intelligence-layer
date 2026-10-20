# 金融数据源全景（含本机实测）

价格与额度会变，**用之前重新核一遍官方页面**；本文件的价值在于「有哪些、各自边界在哪、哪些实测过」。

## 国内

### Tushare Pro（付费档 + 在校师生免费）

积分档（价格 / 每分钟频次）：120 免费（**仅非复权日线**）/ 2000（¥200）/ 5000（¥500）/ 10000（¥1000，含特色数据）/ 15000（¥1500）。

- **在校师生免费 2000 / 5000 积分** —— 写在**服务协议**第一条第 3 款，不在接口文档里。
- 学生免费通道（官方「学生免费积分获取」页的四步）：完善学校与个人信息并提交学生证 / 学信网截图 → 小红书关注点赞留言 → 把 Tushare 接入豆包一类 AI 平台 → 加高校 QQ 群，私信截图与 Tushare ID。**该页面没有提「每年若干篇案例文章」** —— 那条只出现在旧的「积分规则（初稿）」里，两条口径不一致，**以现行操作页为准但让用户进群确认**。
- **开课老师可批量为学生申请**（官方「高校老师免费积分获取」页：下载学生积分模板、由一名同学统一提交）—— 比个人申请省事，值得提醒用户去问一句。
- 积分**一年有效、不消耗不扣减** → 别早拿。
- **独立权限、不在积分内**：历史分钟单独 2000 元/年、实时分钟 1000 元/月、实时日线 200 元/月、港美股日线 / 美股财报各 2000 元/年、新闻资讯 / 公告各 1000 元/年。**真正的钱在分钟数据那一档，不在 200 那一档。**
- **同一平台有两个同为 ¥200 的产品**：日常充值（1:10，得 2000 积分）与「加入高级用户 QQ 群」，后者官方没写清是否给积分 —— 真要付就认准前者。

**实测权限边界**（本机账号、低档位）：`daily` / `index_daily` / `trade_cal` / `stock_basic` / `dividend` 正常；`daily_basic` / `adj_factor` 报**频率超限(1次/分钟)**；`income` / `balancesheet` / `cashflow` / `fina_indicator` / `forecast` 报**无访问权限**（财务域整体被挡）；`moneyflow` / `top_list` / `margin` / `stk_limit` 亦无权限。

> 注意：**官方权限表写「低档位：其他接口无法调取」，与上述实测不符** —— 表格没描述这个「有权限但限 1 次/分钟」的档。报告以实测为准。

### 免费且可程序化（本机实测可用）

| 数据 | AkShare | Baostock |
|---|---|---|
| 日线 | `stock_zh_a_hist` ✅ | `query_history_k_data_plus` ✅（`adjustflag` 控制复权） |
| 复权因子 | `stock_zh_a_daily(adjust="hfq-factor")` ✅ | 同 `adjustflag` ✅ |
| 财务三大表 | `stock_profit_sheet_by_report_em` ✅（实测 100+ 期 × 200+ 字段） | `query_profit_data` / `query_balance_data` / `query_cash_flow_data` ✅ |
| 全市场财报 | `stock_yjbb_em` ✅（一次万级行，等价于付费档的 VIP 接口） | 需逐股循环 |
| 财务摘要 / 指标 | `stock_financial_abstract`、`stock_financial_analysis_indicator` ✅ | 季频四类能力表 |
| 估值 / 市值 | `stock_zh_valuation_baidu` ✅；`stock_zh_a_spot_em` ❌ 会 `ConnectionError` | — |

- **Baostock 免 token、免注册**（`bs.login()` 即用）；财务记录自带 **`pubDate`（公告日）**。
- **AkShare 是爬第三方网页的封装**：接口名会随版本改（老教程里的名字可能已不存在，用 `dir(ak)` 或 `ak.search(...)` 现查），且会失效。

### 只有网页、没有 API

巨潮资讯 cninfo.com.cn（**公告原文 PDF，官方披露平台**）、东方财富数据中心、新浪财经。

### 在线平台（平台内免费，数据出不来）

聚宽 JoinQuant（云端 IDE，分钟级免费）、米筐 RiceQuant、优矿 Uqer（含 PIT 数据）。**共同风险是平台锁定** —— 策略与成果搬不出来。

### 券商量化通道（开通免费，但有资产门槛）

迅投 QMT / miniQMT（miniQMT 用本地 Python）、恒生 PTrade。官方渠道开通本身免费、不用买破解版；**门槛在券商侧**：miniQMT 常见要求资产 300 万，全功能 QMT 常见 10 万起，有的券商另收佣金或软件费。

### 机构付费（个人基本别碰）

Wind、东方财富 Choice、同花顺 iFinD —— 年费数千至数万，主要面向机构。

## 国外

| 类别 | 源 | 免费额度 |
|---|---|---|
| 财报（权威） | **SEC EDGAR XBRL API** | 完全免费无限制（`data.sec.gov/api/xbrl/companyfacts/CIK##########.json`） |
| 财报 | SimFin / FMP | 免费 key、支持全市场批量 / 250 次每天 |
| 行情 | **Polygon.io** | 历史 EOD 无限 |
| 行情 | **Tiingo** | 500 次/小时、1000 标的每天 |
| 行情 | Finnhub | 60 次/分钟 |
| 行情 | Twelve Data | 800 次/天 |
| 行情 | Stooq | 无限（走 pandas-datareader） |
| 行情 | Alpha Vantage | 25 次/天，**且单次只回 100 点** → 十年日线约需 26 次调用，超一整天额度 |
| 行情 | yfinance | 非官方爬虫，上游改版即断 |
| 宏观 | **FRED** | 1000 次/天、80 万+ 序列 |
| 宏观 | World Bank / BLS | 免费 / 500–2500 次每天 |
| 聚合器 | **OpenBB Platform** | `pip install openbb`，一个接口对接 100+ 源，自带 key |

## 搜索纪律

「最新数据 API 横评」这类文章混着大量推广稿：句式雷同（「综合首选」「断层领先」）、同一家霸榜、以推广收尾。**没实测的一致标「未核实」**，不要写进给用户的建议里。

## 装来试的最快路径

`uv venv <dir> && uv pip install --python <dir>/bin/python akshare baostock` —— 秒级装完，可直接跑接口探针。
