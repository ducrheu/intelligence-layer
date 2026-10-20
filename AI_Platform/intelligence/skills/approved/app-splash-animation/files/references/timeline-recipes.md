# 动画分阶段配方与循环预览

## 用 CSS 统一周期，不要用 JS 定时器

所有元素写成 `animation: <name> 5s <easing> infinite`，用**百分比**错开相位。
JS 定时器方案在重播/清理时容易出 bug（旧 timer 没清、死代码残留）。

生产版时长 4 s；预览版把周期拉到 5 s 并无限循环，看得清楚。

## 4 s 时间轴（映射到 5 s 周期的百分比）

| 阶段 | 画面 |
|---|---|
| 0–20% | 径向辉光淡入（`scale(.6)→1`，opacity 0→1）；主体从 `opacity 0, translateY(28px), scale(.72), blur(10px), brightness(.5)` 到清晰 |
| 20–78% | 主体 `sin` 漂浮 ±6–8 px；扩散环每 ~1.1 s 一个，`scale(.45)→2.5`、opacity `.75→0` |
| 30–74% | 配文逐字浮现，每字错开 ~100 ms |
| 78–88% | 主体上浮 + 提亮（`brightness(1.5)`）+ 淡出；文字同步淡出 |

入场缓动固定用 `cubic-bezier(.2,.8,.25,1)`；漂浮用 `ease-in-out`。

## 关键片段

主体（注意：辉光在子 `<svg>` 上用 CSS drop-shadow，像素单位，不随缩放变）：

```css
.hero svg { filter: drop-shadow(0 0 22px rgba(87,134,254,.8))
                   drop-shadow(0 0 58px rgba(87,134,254,.45)); }
.hero { position:absolute; left:50%; top:44%; width:300px; height:300px;
        margin:-150px 0 0 -150px;
        animation: heroIn 5s cubic-bezier(.2,.8,.25,1) infinite; }
@keyframes heroIn {
  0%   { opacity:0; transform:translateY(28px) scale(.72); filter:blur(10px) brightness(.5); }
  20%  { opacity:1; transform:translateY(0)    scale(1);   filter:blur(0)    brightness(1);   }
  30%  { transform:translateY(-8px) scale(1.02); }
  46%  { transform:translateY(4px)  scale(1);    }
  62%  { transform:translateY(-7px) scale(1.02); }
  78%  { opacity:1; transform:translateY(0) scale(1); }
  88%  { opacity:0; transform:translateY(-14px) scale(1.06); filter:blur(4px) brightness(1.5); }
  100% { opacity:0; transform:translateY(-14px) scale(1.06); }
}
```

逐字浮现（每字一个 `<span>`，nth-child 逐个加 100 ms 延迟）：

```css
.caption span { display:inline-block; opacity:0; transform:translateY(10px);
                animation: charIn 5s ease-out infinite; }
@keyframes charIn {
  0%  { opacity:0; transform:translateY(10px); filter:blur(6px); }
  10% { opacity:1; transform:translateY(0);    filter:blur(0);   }
  74% { opacity:1; }
  88% { opacity:0; transform:translateY(-6px); filter:blur(4px); }
  100%{ opacity:0; }
}
```

扩散环（同一个 keyframes 配不同 `animation-delay` 复用）：

```css
.ring { position:absolute; left:50%; top:44%; width:200px; height:200px;
        border-radius:50%; border:1px solid rgba(120,160,255,.5);
        transform:translate(-50%,-50%); animation: ringOut 5s ease-out infinite; }
@keyframes ringOut {
  0%  { opacity:0;   transform:translate(-50%,-50%) scale(.45); }
  8%  { opacity:.75; }
  40% { opacity:0;   transform:translate(-50%,-50%) scale(2.5); }
  100%{ opacity:0;   transform:translate(-50%,-50%) scale(2.5); }
}
```

## 按时刻抓帧验证

```python
for wait, tag in [(1.05, 'early'), (2.30, 'full')]:
    goto_url('file:///.../splash.html?t=' + tag)   # query 绕开缓存
    wait_for_load(); time.sleep(wait)
    print(tag, capture_screenshot())
```

常见的两个翻车点，都在第一张图上就能看出来：
- 主体发糊/重影 → SVG 内部 `<filter>` 被缩放放大了，换成 CSS `drop-shadow`。
- 文字位置偏上/与主体挤在一起 → 中文字形高度和行高比英文大，主体再往上提一点、文字再往下放一点。
