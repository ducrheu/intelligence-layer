# Intelligence Layer · 受治理的共享知识库

两个 agent 运行时（**Hermes** = 学习与迭代面，**OpenClaw / Atlas** = 执行与扩展面）通过一个受治理的知识库交换产物。
知识库是媒介：一方把做过的事沉淀进来，另一方读它、蒸馏它、再回灌。

设计上的取舍只有一句：**自动化尽量高，但准入的质量门不能被绕过——人审是后移，不是消失。**

---

## 1. 为什么不用现成的知识库

市面上成熟的是**检索与浏览**（向量库、RAG 平台、UI），缺的是**准入治理**：候选→验证→批准的生命周期、作者/验证者/批准者的身份分离、可机器复核的证据、以及"能不能被证伪"的使用遥测。前一轮调研的结论是这一层没有等价商品，所以自己实现；而检索是任何方案里都要重写的同一件事，因此用成熟做法（词法 + 向量 + 融合 + 门槛）。

## 2. 核心不变量（可被测试断言的设计契约）

1. **库内文本一律当数据，不当指令**——读进来的内容不会变成命令。
2. **只读面在代码层面没有写路径**——适配器有测试断言其不含写入端点。
3. **生命周期没有直通车**：`candidate → experimental → validated → approved → deprecated → archived`，`candidate → approved` 会被拒绝。
4. **批准不由 HTTP 路由暴露**——批准权限只属于人类身份，由人在本地运行工具完成；网关刻意不提供该端点。
5. **作者 ≠ 验证者**——作者自己产出的"证据"不参与判定（作者不在验证者名单里）。
6. **退场靠状态转移而非删除**——`archived` 离开检索面，但审计与出处保留。

## 3. 目录结构

```
<repo root>/
├── README.md                本文件
├── .github/workflows/tests.yml   CI（无需模型服务，测试跑词法档）
└── AI_Platform/
    └── intelligence/
    ├── gateway/            领域层（纯标准库，无第三方依赖）
    │   ├── store.py            文件式存储；artifact_digest 的哈希缓存键
    │   ├── lifecycle.py        状态机（含"无直通车"约束）
    │   ├── schema.py           产物结构校验
    │   ├── service.py          所有状态变更的唯一入口（读写都经它）
    │   ├── policy.py           身份 → 权限（scope）表
    │   ├── auto_admission.py   分级自动准入策略（含 POLICY_VERSION）
    │   ├── attestation.py      证据与产物的绑定（digest + 文件哈希）
    │   ├── telemetry.py        使用遥测 → 复核旗标
    │   └── retrieval.py        混合检索（BM25 + 向量 + RRF + 门槛 + 分块）
    ├── experimental/
    │   ├── api/server.py       HTTP 网关（stdlib，127.0.0.1:8765）
    │   ├── hermes_consumer.py  消费端示例
    │   ├── backup.py           备份/恢复
    │   └── API.md              接口说明
    ├── knowledge/ experience/ skills/ sources/   产物本体（按状态分目录）
    ├── qa/
    │   ├── audit.jsonl         追加式审计（每个动作一行，含身份）
    │   ├── events.jsonl        生命周期事件流（仅元数据，可安全转发）
    │   ├── usage.json          使用遥测聚合（命中 / 零结果查询）
    │   ├── governance-config.json  分级引擎的 store 级配置
    │   └── identity_tokens.json    令牌的 sha256（明文刻意不放这里）
    ├── schemas/                产物结构定义
    ├── tests/                  9 个测试文件（见 §8）
    ├── adapters/ benchmarks/   适配层与基准
    └── API.md
```

### 仓库之外的部分（尚未整合，见 §10）

运行时工具当前仍在 OpenClaw 的工具目录下，本仓库只包含知识库本体：

| 工具 | 位置 | 职责 |
|---|---|---|
| MCP 读适配器 | `/mnt/d/OpenClaw/tools/intelligence-mcp/server.py` | 只读面（5 个工具，无写路径） |
| MCP 写适配器 | `/mnt/d/OpenClaw/tools/intelligence-mcp/write_server.py` | 只能造候选（提交/请求提升/撤回） |
| 技能回流阀门 | `/mnt/d/OpenClaw/tools/hermes-skill-backflow.py` | 把技能作为候选投递，跑测试后由 QA 校验 |
| QA 校验 | `/mnt/d/OpenClaw/tools/intelligence-validate.py` | 记录证据 + 校验（`validate:candidate`） |
| 人类批准 | `/mnt/d/OpenClaw/tools/intelligence-approve.py` | **只有人跑**（`approve`） |
| 自动准入驱动 | `/mnt/d/OpenClaw/tools/intelligence-auto-admit.py` | 本地驱动分级引擎（影子/强制） |
| 使用报告 | `/mnt/d/OpenClaw/tools/intelligence-usage-report.py` | 使用旗标与零结果查询 |
| 只读面板 | `/mnt/d/OpenClaw/tools/intelligence-dashboard.py` | 中文只读视图（静态或 `--serve`） |
| 检索评测 | `/mnt/d/OpenClaw/tools/intelligence-retrieval-eval.py` | 动检索前必须先跑的度量 |

## 4. 身份与权限

七个身份，权限即 scope 集合；**不以身份名作为凭据**（见 §7）：

| 身份 | 能做什么 |
|---|---|
| `local-hermes` | 只读已批准 + 治理元数据 |
| `local-hermes-writer` | 上述 + 读候选 + 写候选 + 请求提升 + 撤回 |
| `local-agent` | 读已批准 + 写候选 + 请求提升 + 撤回（执行侧，如 OpenClaw） |
| `local-qa` | 读已批准/候选 + 写验证证据 + 校验候选 |
| `local-human` | 批准、弃用、回滚、撤回任何（**人的手**） |
| `local-system` | 读写候选 + 校验 + 请求提升（系统作业） |
| `policy-auto` | 分级策略通过后，按策略版本自动校验/批准 |

## 5. 分级自动准入（`gateway/auto_admission.py`）

目的是"尽量自动化"，同时让越权面最小：

| 层级 | 含义 | 谁在动 |
|---|---|---|
| T0 | 影子：只判定、不动作 | 策略版本 + 判定记录进产物元数据 |
| T1/T2 | 低风险可自动入库 | `policy-auto`（受 scope 门 + 判定结果双重约束） |
| T3 | 必须人工 | `local-human` 本地工具 |
| T4 | 双人 / 仅人工 | — |

- 自动化条件（同时满足）：生产者可信 · scope ∈ {domain, local, project} · kind ∈ {knowledge, experience} · 设了复核期限 · 未声称权限 · 无未知字段 · 未自称已验证。
- **技能类**（可执行）另外要求：**可机器复核的验证证据**（见 §6）——网关自己从不执行作者的代码。
- 策略带版本号，判定连同版本写进产物元数据，可追溯到"当时依据哪版策略放行的"。

## 6. 证据：可机器复核，而不是"作者说测试过了"

`gateway/attestation.py`

- 证据绑定**产物摘要**（只覆盖作者声称的字段，排除网关自己写的批注——否则记录判定会让证据自我失效）。
- 证据还绑定**被执行文件的 sha256**，判定时从磁盘重算比对：事后换掉测试文件会让证据失效，而不是继承它。
- `recorded_by` / `recorded_at` / `subject_digest` 由网关强制覆写，调用方无法伪造。
- 作者不在验证者名单（`local-qa` / `local-system` / `policy-auto` / `local-human`）里。

## 7. 身份认证（正在迁移中，务必读完）

**曾经的做法**：`X-Intelligence-Token` 直接就是身份名——任何能访问回环端口的东西都能自称 `local-human`。这使"批准永远是人的手"和"生产者可信"都只是**请求**而非强制。

**现在**：每个身份铸了随机令牌；知识库只存 `sha256(token)`（`qa/identity_tokens.json`），**明文刻意放在仓库之外**（`~/.hermes/intelligence-identity-tokens.json`，600 权限）。网关先比哈希，身份名只在 `INTELLIGENCE_ALLOW_LEGACY_NAMES` 打开时接受。

| 现状 | 值 |
|---|---|
| 随机令牌 | 已铸，7 个身份 |
| 哈希表 | 在库内（哈希不是秘密，可随产物走） |
| 明文 | 仓库外，600 |
| **过渡开关** | **仍为打开**——即名字冒充目前仍可用 |
| 关掉它的前置条件 | 把 Hermes 的 MCP 面、CLI 工具、OpenClaw 的回流阀门逐个切到真令牌 |

**这一步没做完之前，"信任清单"之类的判定没有约束力。**

## 8. 检索（有实测数字，不靠感觉）

`gateway/retrieval.py`：BM25（词法） + 本地 `bge-m3` 向量（1024 维） + 加权倒排名融合（RRF） + 相关性门槛 + 按段落分块。纯标准库实现；嵌入按产物摘要缓存（内容改则重算，换模型则整库失效）。

默认参数（都写在 systemd 单元里，可见可改）：

```
INTELLIGENCE_EMBED_MODEL=bge-m3     INTELLIGENCE_RRF_K=10
INTELLIGENCE_RRF_WEIGHTS=1.0,0.25   INTELLIGENCE_MIN_COSINE=0.50
INTELLIGENCE_MIN_IDF_RATIO=0.6      INTELLIGENCE_CHUNK=1
INTELLIGENCE_PASSAGE_CHARS=600      INTELLIGENCE_RERANK=none
```

评测结果（合成带标注语料 31 条查询 + 无关查询泄漏率，`intelligence-retrieval-eval.py`）：

| 决策 | 数据 | 结论 |
|---|---|---|
| 嵌入模型 | 向量单项 recall@1：`nomic-embed-text` 0.312 vs `bge-m3` **0.958** | 中文语料必须多语言模型 |
| RRF 的 k | k=60（论文默认）0.583，k=10 **0.750** | 论文的 60 是给上千文档的深排名用的 |
| 两路权重 | 向量降权 0.25：弱模型 0.500→0.750，强模型无损失 | 词法管精确率、向量管召回率 |
| 相关性门槛 | 0.45→召回 1.000/泄漏 0.375；**0.50→0.917/0.000** | 默认零泄漏档，取舍写进代码注释 |
| 分块 | 窗口外内容可检索：不分块 **0.00** → 分块 **1.00**；整体 recall@1 0.839→0.871 | 补的是向量那半的盲区（词法本来没有窗口） |

**已知未解决**：长而泛的文档在真实语料上仍会抢走具体查询——实测分块对此**无改善**（那是语料形状问题，不是检索参数问题）。可能的修法是重排（交叉编码器）或专指度加权，**目前都没有实测依据，因此不做**。

## 9. 可观测性与运维

- **使用遥测**：每次成功取回记一条 `used` 事件（仅元数据）；检索命中单独聚合（命中不等于被读）；**零结果查询**单独记账（最可操作的信号）。
- **复核旗标**：`never-used` / `surfaced-only` / `review-due` / `auto-admitted-unverified`。旗标驱动人去看，**永不删除**。
- **只读面板**：中文界面，治理词条与机器名并列显示；不含任何写操作。
- **推送**：定时报告经消息平台投递到人（当前接的是 QQ 官方机器人；主动消息可能受平台配额限制）。
- **服务**：用户级 systemd 单元；全部只绑回环。
- **定时任务**：治理反馈（`0 7-22/3 * * *`，有变化才唤醒 agent）、自动准入（`*/15 7-22 * * *`，纯脚本零 LLM，无事完全静默）、收获蒸馏（`30 7-22/6 * * *`）、使用巡检（`29 20 * * 0`，无事静默）。排程一律落在**供电窗口内**：本机每晚 23:00–次日 06:00 断电，笔记本靠电池撑到中途关机，通宵轮次必然丢失。窗口外的遗漏不会补跑成完整批次，只会变成唤醒时的迟到执行（catch-up），而那正是模型侧最不稳定的一刻（实测有一次 `RuntimeError: Connection error.`），所以宁可把窗口排窄。

## 10. 已知限制与路线图

1. **身份迁移未收尾**——过渡开关仍打开（优先级最高，见 §7）。
2. **运行时工具未整合进本仓库**——见 §3 表格；整合需要同步更新 systemd 单元、cron 包装脚本、MCP 注册与 OpenClaw 侧路径，必须一次性完成。
3. **闭环尚未真正跑起来**——知识库目前的内容多为建库与治理自身；**来源标注为"另一个 agent 的产出"的产物为 0 件**。缺两件事：执行侧的沉淀习惯，与学习侧的收获→蒸馏触发器。
4. **A2A 直连未启用**——对端要求 Bearer，本侧出站未配置；当前两个运行时只通过知识库交换。
5. **重排未启用**——必须在能显形的基准上证明自己（当前基准在 bge-m3 下已饱和）。
6. **治理代码曾经没有版本控制**——本提交是起点。

## 11. 自检与测试

```bash
# 全部测试（9 个文件；检索类测试刻意只跑词法，不依赖模型服务在不在跑）
cd /mnt/d/intelligence-layer
for t in AI_Platform/intelligence/tests/test_*.py; do
  PYTHONPATH=/mnt/d/intelligence-layer python3 "$t" || echo "FAILED: $t"
done

# 读面不变量（离线 + 在线两档）
python3 tests/read_surface.py --live

# 检索改动前必须先量
python3 intelligence-retrieval-eval.py --corpus synthetic --modes lexical,vector,hybrid

# 使用复核
python3 intelligence-usage-report.py --only-flagged
python3 intelligence-dashboard.py            # 生成只读面板
```

网关健康检查：`systemctl --user status intelligence-gateway`，或对 `http://127.0.0.1:8765/` 发一次带令牌的读取。

## 12. 许可证

未指定。仓库内产物（`knowledge/`、`skills/` 等）与代码的授权范围由所有者决定。
