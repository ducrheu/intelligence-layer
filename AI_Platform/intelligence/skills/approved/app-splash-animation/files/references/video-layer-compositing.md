# 视频 / 角色图层的合成与融合

动画里叠一段角色素材（视频或静帧）时，成败几乎全在“接缝”上。下面是接缝为什么会出现，
以及每种情况的确定做法。

## 一、三条机制：为什么“边缘渐隐”经常不起作用

### 1. 父元素的 transform 会把 mix-blend-mode 锁死

`transform` / `filter` / `opacity<1` 都会在父元素上**创建层叠上下文**。`mix-blend-mode` 的
混合范围被限制在这个上下文内部 —— 子元素只能和“空的父层”混合，等于**混合完全没生效**。

症状：元素变成一块**不透明方块**直接盖住背景（该透明的暗部不透明了），
表现为“画面上有个暗矩形，四周比中间亮”。

修法：不要用 `transform:translateY(-50%)` 做垂直居中，改用百分比定位：

```css
/* 错：父层 transform 把子层的 screen 混合关在里头 */
.vwrap { position:absolute; top:50%; right:0; height:74%; aspect-ratio:16/9;
         transform:translateY(-50%); }
/* 对：把一半余量直接算进 top */
.vwrap { position:absolute; top:13.2%; right:0; height:74%; aspect-ratio:16/9; }
```

### 2. CSS mask 不裁切带 mix-blend-mode 的子元素

Chromium 里，父元素的 `mask-image` **不会裁切**带 `mix-blend-mode` 的子元素；
把 mask 挪到该元素**自己身上也一样无效**。`mask-composite` 也不可靠 —— 多层遮罩往往只剩
一层生效，而且**失效的方式是“本该柔化的边缘变成硬直线”**，不是“什么都没发生”，
很容易被误判成“参数还不够柔”而反复加宽渐隐。

另一个容易漏的点：**mask 的百分比是相对宿主元素自身尺寸算的**。遮罩写在铺满全屏的包裹层上、
而视频只占其中 74% 高时，渐隐区会落在**视频边界之外**，视频边缘依然是硬的。
（把包裹层做成与视频同尺寸 —— `height:74%; aspect-ratio:16/9` —— 百分比才对得上。）

### 3. 可靠做法：在 canvas 里做遮罩

alpha 在画布内生成，不与混合模式打架，`mask-composite` 那套坑完全绕开。

```js
var v = document.querySelector('.fgv')      // video 仍在播放，只是不可见
var c = document.querySelector('.fgcanvas')
var ctx = c.getContext('2d')
var gH, gV                                  // 渐变对象缓存，别每帧新建

function loop() {
  if (v.readyState >= 2) {
    ctx.globalCompositeOperation = 'source-over'
    ctx.drawImage(v, 0, 0, c.width, c.height)
    ctx.globalCompositeOperation = 'destination-in'
    ctx.fillStyle = gH; ctx.fillRect(0, 0, c.width, c.height)
    ctx.fillStyle = gV; ctx.fillRect(0, 0, c.width, c.height)
  }
  requestAnimationFrame(loop)
}
```

`destination-in` 连用两次 = 取交集。canvas 元素本身带 `mix-blend-mode: screen` —— 它没有
额外的 CSS mask，混合正常工作。video 用 `opacity:0` 而不是 `display:none`
（后者可能让渲染器不再产新帧，canvas 一直画旧帧）。

## 二、渐隐宽度：先量边缘亮度，再定

**别凭感觉。** 先探素材四条边各区域的平均亮度：

```bash
probe() {  # $1=时刻  $2=crop参数 W:H:X:Y
  ffmpeg -v error -ss "$1" -i v.mp4 -frames:v 1 \
    -vf "crop=$2,scale=1:1" -f rawvideo -pix_fmt gray - | od -An -tu1 | tr -d ' '
}
```

实测一例（角色素材，值 0–255）：

| 区域 | 虚幻阶段 | 实体化后 | 结论 |
|---|---|---|---|
| 左 0–8% | 0 | 0 | 纯黑 → **不要渐隐** |
| 右 92–100% | 0 | 12 | 纯黑 → **不要渐隐** |
| 顶部 0–5% | 0 | 22 | 近黑 → 只给 3–4% |
| 底部 88–100% | 113 | 61 | 有内容 → 保留渐隐 |

规则：

- **亮度≈0 的边在 `screen` 混合下本来就透明，加渐隐纯粹是在削掉角色本体。**
  典型症状是头顶光环被切平、飘带/光带出现垂直切线 —— 用户会说“有明显的截断感”。
- 只有实测有内容的边才需要渐隐。
- 用户报“截断”时，先怀疑渐隐太宽，再怀疑素材本身被裁过。

## 三、素材不要裁成方块

为了让角色“出现在画面右侧”而 `crop` 出一个正方形，会同时造成两件事：角色被直线切断
（头发 / 飘带 / 尾巴），**而且那个方块边本身就是接缝**。

改用：**保留完整画面 → 缩小 → 贴边定位**，左侧空出的地方由同一段素材的模糊版补上。

```css
.fgcanvas { position:absolute; inset:0; width:100%; height:100%;
            mix-blend-mode:screen;
            filter:brightness(1.02) contrast(1.55) saturate(1.08); }
```

对比度那一项是有用的：它把视频暗部压到接近纯黑，在 `screen` 下就成了透明，只留角色亮部。
试过 `mix-blend-mode: lighten` 反而更糟 —— 背景亮部会“吃掉”角色的暗部、把环境光保留下来，
方块感更明显。

## 四、“两块拼图”：背景必须和前景同源

常见错误组合是**左边文字用 CSS 渐变背景、右边角色是视频画面**。两种质感并排，
边缘渐隐再柔和也有一条材质分界线。

治法：**背景也用同一段素材** —— 第二个 video 铺满全屏 + 重度模糊，作为氛围底。

```css
.bgv { position:absolute; inset:0; width:100%; height:100%; object-fit:cover;
       filter:blur(78px) brightness(.86) saturate(1.32);
       transform:scale(1.55); opacity:.85; }   /* bgv 无混合模式，transform 安全 */
```

背景 video 复用前景的 `src`（`bg.src = fg.src`），HTML 里不用写两份 base64。

两个配套动作：

- **别在左侧另加一层重压暗**（`radial-gradient(at 20% 48%, rgba(0,0,0,.74))` 之类）——
  它自己就是一条左右分界线。要压暗就用**左右完全一致**的均匀暗层，
  文字可读性交给 `text-shadow`。
- **光晕层要中心对称**（`at 50%`），别偏向角色那一侧。

自查：在**矩形内外的左上/右下四角**取样亮度，差值应落在个位数内；差十几个灰阶就是接缝。

## 五、逐帧录制：给用户看完整过程

用户看静止帧无法判断动态融合，而实时录屏在这类环境里不可控。
**逐帧 seek + 截图 + 合成**最稳：

```python
goto_url(page)                      # 整个循环只加载一次
wait_for_load(); time.sleep(3)

for i in range(N):
    t = i * step                    # step 取 1/25 s 之类
    js("""(()=>{
      document.getAnimations().forEach(function(a){try{a.pause();a.currentTime=%d;}catch(e){}});
      document.querySelectorAll('video').forEach(function(v){try{v.pause();v.currentTime=%s;}catch(e){}});
      return 1;
    })()""" % (t * 1000, t))
    time.sleep(0.25)                # 等 canvas 画完 seek 后的那一帧
    shutil.copy(capture_screenshot(), '/tmp/f/%03d.png' % i)
```

```bash
ffmpeg -y -framerate 25 -i /tmp/f/%03d.png -c:v libx264 -pix_fmt yuv420p -crf 20 out.mp4
```

两点提醒：

- 截图前必须 `video.pause()`。页面里若有一个“定时 `play()` 兜底”的看门狗，它会把时间轴推走，
  截到的帧和你要的时刻对不上（表现为明明 seek 到实体化，截出来还是线稿）。
- 逐帧暂停会把 **CSS 驱动的粒子 / 循环动画相位固定住**，录出来像是静止的。
  交付时要说明“实际播放时这些是动的”，否则用户会以为特效坏了。

## 六、接缝自查清单

交付前逐项过：

1. 每个阶段（虚幻 / 过渡 / 成形 / 停留）各抓一帧 —— **线稿 / 能量体阶段最容易露馅**，
   实体化之后反而不明显。
2. 看有没有**矩形或直线的亮度边界**，尤其放大看四角。
3. 角色的头发、飘带、尾巴、光环**有没有被切断**。
4. 取矩形内外的四角亮度，差值应在个位数。
5. 中文文案是否清晰 —— **别用 `filter: blur()` 做文字入场**：Chromium 即使插值到 `blur(0)`
   仍保留模糊合成层，文字会永久发虚；改用位移 + 缩放做聚焦感。
