# 验证动画的某一帧（CSS/HTML 原型阶段）

做启动动画时需要逐相位验收（字标亮起时、标语浮现时、尾部淡出前）。
WSL 里 Chromium 的安装与基本截图规则见 `headless-ui-verification`；本文件只讲动画特有的几步。

## 冻结相位，不要 sleep

`--virtual-time-budget` 会**推进** CSS 动画，能把画面送过动画末尾 —— 截回来是全黑或淡出后的空帧。
`sleep N` 又要和页面加载时间赛跑，同一条命令两次结果不同。让页面自己停在某一相位：

```js
// 页面加：?freeze=2.6  → 所有动画定格在 2.6 s
var t = parseFloat(location.search.match(/freeze=([\d.]+)/)?.[1] ?? 'NaN');
if (!isNaN(t)) addEventListener('load', () => {
  document.querySelectorAll('*').forEach(el => {
    var n = getComputedStyle(el).animationName;
    if (n && n !== 'none') {
      el.style.setProperty('animation-delay', -t + 's', 'important');
      el.style.setProperty('animation-play-state', 'paused', 'important');
    }
  });
});
```

之后照常截图（仍给 `--virtual-time-budget` 让字体/资源就位：动画已 paused，不再被推进）。
同一个 URL 在任何机器、任何引擎上都定格在同一帧，所以可以直接跨引擎比对。
一个动画周期里挑 3 个时刻（早/中/尾）分别截，基本能覆盖全部状态。

## 别用 `filter: blur()` 做“聚焦”入场

动画里写 `blur(12px) → blur(0)` 看着收尾就清晰了，**实际不会**：Chromium 会把该元素
保留成一个模糊合成层，即使插值到 `blur(0)`，文字在整段动画里都保持发虚。
改用 `opacity` + `transform: translateY()/scale()` 做聚焦感，视觉接近且没有这个副作用。

## 中文发虚而英文锐利：先怀疑 CSS，别怪字体

同一页里英文锐利、只有中文发虚，很容易误判为“缺中文字体”。
用另一引擎交叉验证 —— 从 WSL 调 Windows 的 Chrome 截同一页面（同一个 `?freeze=` 相位）：

```bash
"/mnt/c/Program Files/Google/Chrome/Application/chrome.exe" --headless=new --disable-gpu \
  --hide-scrollbars --window-size=960,540 --virtual-time-budget=1500 \
  --screenshot="C:\\path\\out.png" "file:///C:/path/page.html?freeze=2.6"
```

- 两边一样糊 = CSS 问题（高频原因是上面那条 `filter: blur()`）。
- 只有 WSL 侧糊 = 字体回退问题（可把 `"Noto Sans SC"` 加进字体栈）。
- `--headless=new` 对 Windows 的 chrome.exe 可用；`headless-ui-verification` 里
  `--headless=old` 那条规则是针 WSL 里 Playwright 那个构建的。
- 输出路径必须是 Windows 路径，输入页也得先拷到 Windows 可读的位置。
- Windows 侧只用来判断**字形锐利度**，颜色不要以它为准。
