# 启动动画素材：矢量标记、官方片源、抽帧

## 1. 品牌矢量标记（首选）

Simple Icons 收录大量品牌的官方 path 数据：

```bash
# 带品牌色的 SVG（fill 已写好）
curl -sL -o brand.svg "https://cdn.simpleicons.org/<brand>"

# 原始 SVG（无 fill，方便自己上色/渐变）
curl -sL -o brand.svg \
  "https://raw.githubusercontent.com/simple-icons/simple-icons/master/icons/<brand>.svg"
```

把 `d=` 属性的 path 数据取出来即可：

```bash
python3 -c "
import re
d = open('brand.svg').read()
p = re.search(r'd=\"([^\"]+)\"', d).group(1)
open('brand.path','w').write(p)
print('path 长度:', len(p), '| viewBox:', re.search(r'viewBox=\"([^\"]+)\"', d).group(1))
from collections import Counter
print('命令分布:', dict(Counter(re.findall(r'[A-Za-z]', p))))
"
```

命令分布决定后续怎么画：只有 `M/L/C/Z` 且没有 `A/a` 时最好处理（GDI+ 的 `GraphicsPath`
直接支持）；出现 `a`（椭圆弧）就需要做 endpoint->center 参数化再分段转三次贝塞尔。

预览渲染验证：把 SVG 嵌进一个 HTML 用真浏览器截图看，**不要**用 PIL 之类的位图库猜。

## 2. 官方动效片源

想要的启动画面如果出自某个开源项目，**先把官方仓库 clone 下来再搜**，不要跟
搜索/抽取后端纠缠：

```bash
curl -s https://api.github.com/repos/<org>/<repo> | python3 -c "import json,sys;print(json.load(sys.stdin)['description'])"
timeout 240 git clone --depth 1 https://github.com/<org>/<repo>.git /tmp/proj
du -sh /tmp/proj                     # 先看体积，判断是不是全量源码
find /tmp/proj -not -path './.git/*' \( -iname '*.mp4' -o -iname '*.webm' -o -iname '*.mov' \) | head
```

- 仓库里没有 `media/` 不等于资源不存在：社区插件常把片源 **base64 内嵌在 JS 里**
  （为了绕开「包里文件清单漏写 / 安装副本过期 / 容器没做 faststart」这几类问题）。
  先看谁在用（npm 包 -> `package.json` 的 `repository.url`），再从插件仓库里找。
- 压缩版片源通常做过 CRF 20 重编码 + faststart 重排；**原始仓库里往往是未压缩的高码率版**，
  做 4K 铺满时优先用原始版。

先确认官方仓库里到底有没有那段画面：

```bash
grep -rl "<画面上的中文文案>" /tmp/proj --exclude-dir=.git | head
grep -rl "<画面上的英文文案>" /tmp/proj --exclude-dir=.git | head
```

全无命中就是第三方自制，没有源片可下，只能按参考图复刻。

## 3. 抽帧审查视频片源

每段视频抽 6 帧拼一张 contact sheet，一次看清它是什么内容、什么风格：

```bash
ffprobe -v error -select_streams v:0 \
  -show_entries stream=width,height,codec_name,r_frame_rate,nb_frames \
  -show_entries format=duration,bit_rate \
  -of default=noprint_wrappers=1 in.mp4

ffmpeg -y -v error -i in.mp4 -vf "fps=1/2.2,scale=440:-1,tile=3x2" -frames:v 1 sheet.png
```

然后用视觉工具看 `sheet.png`。挑单张高清帧当交付预览图时，用 `-ss` 定位再输出 PNG。
