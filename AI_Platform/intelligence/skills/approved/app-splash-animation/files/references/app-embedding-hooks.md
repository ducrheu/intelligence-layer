# 把启动动画接进应用：扩展面判定与资产层注入

`SKILL.md` 的「接进应用」一节给档位，这里给判定方法与第 2 档（资产层注入）的完整配方。

## 一、先判定应用的扩展面（十分钟，别跳过）

三档选错，后面全白做。按这个顺序查，查到的第一条就是答案：

| 查什么 | 命中意味着 | 怎么查 |
|---|---|---|
| 官方用户插件目录 + 挂载点清单 | 可能是第 1 档 | 源码里 `desktop-plugins` / `extensions` / `src/sdk/areas.ts` 一类；**必须确认有 UI 挂载点**，不是有 plugins 就算 |
| 前端资源是否由本地文件服务 | 第 2 档可用 | `curl -sI http://<本地服务>/` 拿到 HTTP 200，且文件在磁盘上是实体（`dist/control-ui/index.html` 之类） |
| 有没有源码 + 构建依赖 | 第 4 档是否可行 | `ls node_modules/.bin | grep -E '^(tsc\|vite\|asar)$'` —— 只有 `electron` 这类运行时依赖 = 构建链不完整 |
| 启动流程里有没有原生钩子 | 有没有第 0 档捷径 | grep `splash` / `boot` / onboarding 组件 |

**“有空状态字标”不等于“有启动闪屏”。** 空聊天页的品牌字标、首次配置的进度条组件，都容易被
误认成启动画面；它们只在特定状态下出现，不是每次启动都有的那个东西。

**插件目录存在 ≠ 有 UI 插槽。** 把插件 SDK 的挂载点列表读出来看：只有 `statusBar` / `titleBar` /
`panes` / channel / provider / tool / hook 这类，就说明它是后端或边栏扩展面，挂不了全屏启动动画。

## 二、资产层注入配方

以「gateway 从 `dist/control-ui/` 提供前端」的自托管 Web 应用为例。三个文件：

```
<served-dir>/index.html          注入一行 <script src="./boot-anim.js">（备份成 index.html.orig）
<served-dir>/boot-anim.html      动画本体，自包含，视频 base64 内嵌
<served-dir>/boot-anim.js        同源引导脚本，约 1.5 KB
```

引导脚本（同源 + 只播一次 + 不响应嵌套 iframe）：

```js
(function () {
  try {
    if (window.top !== window.self) return;                     // 被自己嵌进 iframe 时不重播
    if (sessionStorage.getItem('ocl-boot-played') === '1') return;
    sessionStorage.setItem('ocl-boot-played', '1');
  } catch (e) { return; }

  function mount() {
    var fr = document.createElement('iframe');
    fr.id = 'ocl-boot-layer';
    fr.src = './boot-anim.html';                                // 同源，CSP frame-src 'self' 放行
    fr.setAttribute('aria-hidden', 'true');
    fr.style.cssText = 'position:fixed;top:0;left:0;width:100vw;height:100vh;border:0;' +
      'margin:0;padding:0;z-index:2147483000;pointer-events:none;display:block;background:#05070e;';
    (document.body || document.documentElement).appendChild(fr);
    setTimeout(function(){ fr.style.transition='opacity 620ms ease-out'; fr.style.opacity='0'; }, 5350);
    setTimeout(function(){ fr.parentNode && fr.parentNode.removeChild(fr); }, 6100);
  }
  if (document.body) mount();
  else document.addEventListener('DOMContentLoaded', mount, { once: true });
})();
```

要点：

- **`pointer-events:none`**：动画层万一没消失，用户点击也能穿透，不会把界面锁死。这是可撤销性的底线。
- **`window.top !== window.self` 守卫**：动画页自己被嵌进 iframe 播放时，若它也执行这段脚本就会
  套娃重播。
- **`sessionStorage` = 每次页面会话一次**：首次加载立即播（正好当预览），之后同一会话内导航不重播。
- 视频走 base64 内嵌在动画页里（`media-src` 允许 `data:` 时才可行），动画页与引导脚本都必须是
  **同源文件**，不能内联进 `index.html`。

## 三、验收：一律通过服务端口验，不要只读磁盘文件

服务端可能改写 HTML（注入 base-path、开关标记等），**磁盘上的字节数和服务出来的不是一份**。

```bash
curl -s -m 10 http://127.0.0.1:<port>/ | grep -c 'boot-anim.js'      # 注入是否真的在响应里
curl -s -m 10 -o /dev/null -w '%{http_code} %{size_download}\n' http://127.0.0.1:<port>/boot-anim.js
curl -s -m 10 -o /dev/null -w '%{http_code} %{size_download}\n' http://127.0.0.1:<port>/boot-anim.html
curl -sI -m 10 http://127.0.0.1:<port>/ | grep -iE 'cache-control|content-security-policy'
```

再用真实浏览器打开**被服务的那一页**并读视频的真实状态（不要用 `querySelector('video')` 抓第一个，
合成动画常有多个 `<video>`，背景那层本来就没 `src`）：

```js
(() => { const v = document.querySelector('.fgv');
  return {w:v.videoWidth, h:v.videoHeight, ready:v.readyState, paused:v.paused, dur:v.duration}; })()
// 期望 1280 / 720 / 4 / false / 5.125 —— readyState 0 才是真的没加载
```

`Cache-Control: no-cache` **不保证**用户立刻看到新版：装了 Service Worker 的 PWA 可能有自己一层缓存。
让用户硬刷新一次（Ctrl+Shift+R）再判断，别把缓存问题当成注入失败去改代码。

## 四、幂等补丁脚本骨架

包升级会覆盖 `dist/`，所以补丁必须可重复执行、且动画源留在包外。三个模式缺一不可：

```python
# apply（默认，幂等）：备份一次 index.html -> .orig；从包外源写回 boot-anim.html / boot-anim.js；
#                      index.html 里已有注入行就跳过，找不到 <body> 锚点就明确报错退出。
# --check：列出五个存在位（index.html / .orig / boot-anim.html / boot-anim.js / injected）并给结论。
# --revert：index.html 从 .orig 还原（没有就手工摘掉注入行），删掉两个新文件。
```

dist 或 served 目录优先用**相对 npm 全局根**定位，别把绝对路径写死：

```python
try:
    root = subprocess.check_output(['npm', 'root', '-g'], text=True).strip()
    cand = os.path.join(root, 'openclaw', 'dist', 'control-ui')
except Exception:
    pass
```

交付时把三个模式都实跑一遍再交给用户（还原 → 重新打 → 确认服务端口恢复提供），
用户才敢在升级后自己跑它。
