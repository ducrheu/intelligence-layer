# 浏览器接入（WSL → 用户的 Windows Chrome）

小雅站点要登录才能拿数据，而**本机 WSL 里的浏览器是无头的**（`openclaw browser status`
显示 `headless: true`，来源 `linux-display-fallback`，`DISPLAY` 为空），用户根本没窗口可点。
所以默认做法是：挂到 Windows 上那个已经在跑调试端口的 Chrome。

## 先确认端口活着

```bash
curl -s --max-time 3 http://127.0.0.1:9222/json/version
```

返回 `{"Browser": "Chrome/1xx..."}` 就说明能用（WSL2 下 `127.0.0.1` 有时走的是
mirrored networking，能直连；如果连不上，再看 WSL 里的 Windows 宿主 IP）。

`openclaw browser profiles` 里那个 `remote` profile（`cdpUrl: http://127.0.0.1:9222`,
`attachOnly: true`）**目前走不通**——`openclaw browser tabs --profile remote` 会报
`gateway browser.request requires credentials ... Config: /home/huyi/.openclaw-remote/openclaw.json`。
别在这上面浪费时间，直接用 `scripts/` 里的裸 CDP 客户端。

## 为什么不用 playwright

`playwright-core` 的 `chromium.connectOverCDP('http://127.0.0.1:9222')` 会挂在握手后：

```
<ws connected> ws://127.0.0.1:9222/devtools/browser/<id>
browserType.connectOverCDP: Timeout 30000ms exceeded.
```

同一时刻用裸 websocket 发 `Browser.getVersion`，几十毫秒就回。所以 `scripts/lib.mjs`
自己实现了最小 CDP 客户端（`Target.getTargets` / `Target.attachToTarget` +
`Runtime.evaluate` / `Page.captureScreenshot` / `Browser.setDownloadBehavior`）。

## 登录

课程页会 302 到 `infra.ai-augmented.com` 的登录页（手机号/统一身份认证/扫码）。这一步
必须人来做：

1. `node xy-course.mjs open <courseUrl>` 打开标签页（用用户自己的浏览器，他能看见）。
2. 告诉用户"在这个标签里登录，登完说一声"，**然后停下来等**。
3. 用户确认后 `node xy-course.mjs tree <courseUrl>` 复查。如果还在登录页，`prepare()`
   会因为抓不到 auth 而退出码 2。

标签页是用户自己的浏览器窗口，别关他的别的标签；要回收就 `cdp.send('Target.closeTarget', {targetId})`
只关我们开的那一个。

## 模块解析

`scripts/` 里没有 `node_modules`。`lib.mjs` 按顺序找 `ws`：

1. 从脚本位置正常 `require.resolve('ws')`
2. `OPENCLAW_NODE_MODULES`（默认 `/home/huyi/.npm-global/lib/node_modules/openclaw`）下的 `ws`

所以正常情况直接跑就行，换机器就设 `OPENCLAW_NODE_MODULES`。
