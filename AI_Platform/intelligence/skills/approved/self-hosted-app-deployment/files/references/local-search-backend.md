# 自建搜索后端（SearXNG 型）：引擎裁剪与 Hermes 接线

适用：让 agent 的 `web_search` 不再依赖第三方付费/不稳定后端，在本机跑一个元搜索实例。本文件是那份 skill 第 7 节的深度展开。

## 1. 先量出真实用量，再决定要不要自建

从运行时自己的库数调用次数（会话库的 `messages.tool_calls` 里按 `web_search` / `web_extract` 计数，或运行时的审计日志），不要凭印象估。本机实测 18 个活跃日 1220 次 → 月化约 2000 次。拿这个数去比免费档：某家是 1000 credits/月且**用尽即停到下月重置**，也就是「月末静默失效」，比原来的不稳定后端更糟。数量级不匹配时，自建（无上限）比挑档位省事。

## 2. 安装（本机 `python3 -m venv` 不可用）

```bash
git clone --depth 1 https://github.com/searxng/searxng.git ~/searxng
cd ~/searxng
uv venv venv --python 3.12
uv pip install --python venv/bin/python -r requirements.txt
```

依赖里 `lxml` 有 manylinux wheel，本机缺 `gcc`/`make` 也照样装得上。

## 3. settings.yml（放 `~/.config/<app>/`，用环境变量指过去）

必须覆盖的键，以及不设的后果：

| 键 | 值 | 不设的后果 |
|---|---|---|
| `server.bind_address` | `127.0.0.1` | 暴露到局域网 |
| `server.secret_key` | 随机 32 字节 hex | 启动告警、会话不可用 |
| `server.limiter` | `false` | 本机没有 valkey/redis，反复报错 |
| `search.formats` | `[html, json]` | **默认只有 html，调用方拿到 HTML** |
| `ui.default_locale` | `en` | **`"zh-CN"` 不是合法值 → 每个请求 500** |

`secret_key` 用 `python3 -c "import secrets;print(secrets.token_hex(32))"` 生成后**直接写进文件**，不进对话。

## 4. 引擎裁剪：按这台机器实际能到的上游选

默认引擎集在有墙／无代理的机器上**全部超时**：每次查询返回空结果，并列出 `unresponsive_engines`。

先测可达性：

```bash
for u in https://www.google.com https://cn.bing.com https://www.baidu.com https://duckduckgo.com; do
  printf "%-32s " "$u"; curl -s -m 8 -o /dev/null -w "%{http_code}\n" "$u"
done
# 本机（无代理）：cn.bing.com 200、baidu 200、google/duckduckgo 000
```

然后只保留能通的：

```yaml
use_default_settings:
  engines:
    keep_only: [bing, baidu, quark, sogou]

engines:
  - name: bing
    disabled: false
    base_url: "https://cn.bing.com"   # 上游注释自己写了：中国境内实例用 cn.bing.com
  - name: baidu
    disabled: true                     # 本机实测每次 CAPTCHA
  - name: quark
    disabled: true                     # 同上（阿里反爬，引擎随后被挂起 900s）
  - name: sogou
    disabled: false
```

- `bing` 引擎**默认 `disabled: true`** 且指向 `www.bing.com`，两处都要改。
- 被 CAPTCHA 的引擎留着的唯一作用是把首个查询拖慢，之后它们进入 suspension；禁掉是净收益。
- 删掉 `keep_only` 即恢复上游默认全集——**日后加了代理再把境外引擎加回来**，不要重新发明这份清单。
- `bing news` / `bing images` / `duckduckgo web` 等是**独立引擎条目**，`keep_only` 只提 `bing` 不会带上它们。

## 5. 验证（三层，缺一层都可能误判）

```bash
# 1) 直接打服务——解析响应体，不是看状态码
curl -s "http://127.0.0.1:8888/search?q=量化金融&format=json" \
  | python3 -c "import sys,json;d=json.load(sys.stdin);print(len(d['results']), d.get('unresponsive_engines'))"
# 期望：结果数 > 0 且 unresponsive 为空

# 2) 走宿主应用自己的代码路径（用它的 venv，别用系统 python3）
/home/<user>/hermes/venv/bin/python -c "
import sys; sys.path.insert(0,'/home/<user>/hermes/app')
from tools.web_tools import web_search_tool
print(web_search_tool('某个中文查询', limit=3)[:300])"

# 3) 确认请求真的到了自建实例（而不是被探测链前面的后端截胡）
journalctl --user -u <unit> --since '5 min ago' --no-pager | tail
```

第 3 层是唯一能证明「走的是它」的证据：前两层在探测链选到别的后端时同样会绿。

## 6. Hermes 侧接线

```bash
hermes config set web.backend searxng     # 显式指定
# SEARXNG_URL 写进 Hermes 的 env 文件（os.environ 亦可），不能只写 config.yaml 顶层键
```

- 读取链：`tools/web_tools.py::_env_value` → `os.environ` → `hermes_cli/config.py::get_env_value` → `load_env()`（Hermes 的 env 文件）。**config.yaml 的顶层键不在这个链里。**
- 不带 scheme/端口的裸 host 值得照抄 `http://127.0.0.1:8888` 的完整形态，避免解析歧义。
- 后端探测链（源码 `web_tools.py` 的候选表）：tavily → perplexity → exa → parallel → keenable → firecrawl（**含 tool-gateway 形态**）→ searxng → brave-free → ddgs。**靠后的后端必须显式指定**，否则被前面的截胡且完全不报错。
- 改完 env 后，**当前正在运行的 backend／gateway 仍持有旧值**；新会话或重启才生效。
