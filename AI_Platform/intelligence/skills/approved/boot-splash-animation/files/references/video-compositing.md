# 视频主体合入背景：配方与探针

配合 SKILL.md 第 5 节「视频主体合入背景（合成工艺）」。以下都是可直接抄的配方。

## 1. 量每条边的亮度（决定渐隐宽度）

把边带裁出来、缩到 1×1 取灰度均值：

```bash
SRC=boot-assets/preview.mp4
probe(){ # $1=时刻  $2=crop 参数 WxH:X:Y
  ffmpeg -v error -ss "$1" -i "$SRC" -frames:v 1 \
    -vf "crop=$2,scale=1:1" -f rawvideo -pix_fmt gray - 2>/dev/null \
  | od -An -tu1 | tr -d ' '
}
probe 1.60 "1280:36:0:0"        # 顶 0-5%
probe 1.60 "1280:50:640:670"    # 底 88-100%
probe 1.60 "102:720:0:0"        # 左 0-8%
probe 1.60 "102:720:1178:0"     # 右 92-100%
```

判读：0–12 = 纯黑，**不要渐隐**；>100 = 亮，必须渐隐。
同一素材至少量两个时刻（虚化阶段 / 实体阶段），边带亮度可以差一个量级。

## 2. canvas 遮罩（替代 CSS mask）

```js
var v=document.querySelector('.fgv'), cv=document.querySelector('.vf');
var ctx=cv.getContext('2d'), gH, gV, fbImg=document.querySelector('.fb');

function resize(){
  cv.width = cv.clientWidth; cv.height = cv.clientHeight;
  var w=cv.width, h=cv.height;
  gH = ctx.createLinearGradient(0,0,w,0);
  gH.addColorStop(0.000,'rgba(0,0,0,0)');
  gH.addColorStop(0.030,'rgba(0,0,0,.55)');
  gH.addColorStop(0.075,'rgba(0,0,0,1)');
  gH.addColorStop(1.000,'rgba(0,0,0,1)');
  gV = ctx.createLinearGradient(0,0,0,h);
  gV.addColorStop(0.000,'rgba(0,0,0,0)');
  gV.addColorStop(0.020,'rgba(0,0,0,.55)');
  gV.addColorStop(0.050,'rgba(0,0,0,1)');
  gV.addColorStop(0.900,'rgba(0,0,0,1)');
  gV.addColorStop(0.965,'rgba(0,0,0,.35)');
  gV.addColorStop(1.000,'rgba(0,0,0,0)');
}

function frame(){
  var src = (v.readyState>=2) ? v : (fbImg && fbImg.complete ? fbImg : null);
  if (src && cv.width) {
    ctx.globalCompositeOperation='source-over';
    ctx.clearRect(0,0,cv.width,cv.height);
    ctx.drawImage(src,0,0,cv.width,cv.height);
    ctx.globalCompositeOperation='destination-in';
    ctx.fillStyle=gH; ctx.fillRect(0,0,cv.width,cv.height);
    ctx.fillStyle=gV; ctx.fillRect(0,0,cv.width,cv.height);
  }
  requestAnimationFrame(frame);
}
```

- 两个渐变**依次** fill，`destination-in` 天然取交集，不依赖 `mask-composite`。
- 承载 canvas 的包裹层不要有 `transform`，否则 canvas 的 `mix-blend-mode` 失效（见 SKILL.md）。
- 视频源与静态兜底帧走**同一个** `drawImage` 分支，退化时遮罩行为完全一致。
- 隐藏原 video 用 `opacity:0;position:absolute`，**不要 `display:none`**（可能不再出新帧）。

## 3. autoplay 三重保险

```js
(function(){
  var vids=[].slice.call(document.querySelectorAll('video'));
  function kick(){ vids.forEach(function(v){
    try{ v.muted=true; var p=v.play(); if(p&&p.catch)p.catch(function(){}); }catch(e){}
  });}
  kick();
  ['click','touchstart','keydown'].forEach(function(ev){document.addEventListener(ev,kick);});
  setTimeout(kick,300); setTimeout(kick,1200); setTimeout(kick,2500);
  setInterval(function(){ vids.forEach(function(v){ if(v.paused) kick(); }); },1000);
})();
```

自证素材没坏：`file://` 直开，读 `{paused, readyState, currentTime, videoWidth, error}`。
`paused:false / readyState:4 / currentTime` 在推进 → iframe 策略问题，不是素材问题。

## 4. 素材处理：保完整画面 + 缩小贴边

```bash
# 保留完整画面（不 crop！），只做时长 / 速度处理
ffmpeg -y -ss 0.9 -t 6.1 -i src.mp4 \
  -filter:v "setpts=PTS/1.22,scale=1280:720" -an \
  -c:v libx264 -crf 28 -pix_fmt yuv420p preview.mp4
```

```css
/* 定位侧：贴边 + 缩高；两侧留白交给同源模糊背景 */
.vwrap{position:absolute;top:13.2%;right:0;height:74%;aspect-ratio:16/9}  /* 不要 transform */
.bgv{position:absolute;inset:0;width:100%;height:100%;object-fit:cover;
     filter:blur(78px) brightness(.86) saturate(1.32);transform:scale(1.55)}
```

体积换算：内联 base64 ≈ 文件字节 × 1.37。720p / CRF 28 的 5 s 片段约 0.8 MB，base64 后 ~1.1 MB。

**但内联只是为了聊天里的 `::preview`**。交付给 launcher 的版本要反过来——本地 `file://`
没有 CSP 限制，把视频与兜底帧抽成同目录独立文件（`<video src="bg.mp4">`、`<img src="fallback.jpg">`），
HTML 从 1.08 MB 掉到 12 KB：首帧不再等解析那 1 MB base64，视频也变成流式解码。

## 5. 挑关键帧：并排渲染再选

需要「神态最好」的那一帧（例如睁眼瞬间）时别猜时刻——把候选并排贴出来让视觉挑：

```bash
for t in 4.00 4.35 4.70; do
  ffmpeg -y -v error -ss $t -i preview.mp4 -frames:v 1 -vf "scale=430:-1" /tmp/eye_$t.png
done
ffmpeg -y -v error -i /tmp/eye_4.00.png -i /tmp/eye_4.35.png -i /tmp/eye_4.70.png \
  -filter_complex hstack=3 /tmp/eyes.png
```

再对 `/tmp/eyes.png` 提问「哪一帧神态最好，明确说左 / 中 / 右」。

## 6. 每轮验收清单

- [ ] 主体完整：头发、飘带 / 丝带、尾巴、发饰——逐项放大看，这些是最先被切掉的
- [ ] 四条边无直线边界（把矩形四个角放大看）
- [ ] 背景均匀：矩形内外采样亮度差 ≤5 阶
- [ ] 光效不被削：光环上缘是圆弧，不是平口（渐隐带压在主体上就会平口）
- [ ] 文字可读，且不依赖单侧压暗
- [ ] 兜底静态帧与视频路径的观感一致
