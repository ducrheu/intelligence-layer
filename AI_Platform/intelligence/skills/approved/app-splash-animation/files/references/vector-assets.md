# 品牌矢量素材：获取与落地

## 1. 取官方路径

```bash
curl -sL -o brand.svg      "https://raw.githubusercontent.com/simple-icons/simple-icons/master/icons/<brand>.svg"
curl -sL -o brand-blue.svg "https://cdn.simpleicons.org/<brand>"   # 带品牌色 fill
```

- viewBox 通常是 `0 0 24 24`。SVG 与 GDI+ **都是 y 轴向下**，等比缩放即可，不需要翻转。
- 品牌色就是 cdn 版本 `<svg fill="#XXXXXX">` 里的值。
- 把 path 单独存一份备用：

```python
import re
s = open('brand.svg').read()
d = re.search(r'd="([^"]+)"', s).group(1)
open('brand.path','w').write(d)
```

## 2. 落盘前先统计命令集

这决定后续怎么解析，别先写解析器：

```python
import re; from collections import Counter
d = open('brand.path').read()
print(dict(Counter(re.findall(r'[A-Za-z]', d))))
```

实测：Simple Icons 的图形常含 **弧线命令 `a`（十几个）**，而 GDI+ `GraphicsPath` 没有端点式弧线 API。
两条路：

- **（省事，推荐）离线预处理**：Python 里按 SVG 规范 F.6（endpoint → center 参数化，每段 ≤ 90°，
  用 `t = 4/3·tan(Δθ/4)` 逼近）把弧线转成三次贝塞尔，输出纯 `M/L/C/Z` 的命令数组
  （如 `[type, x1,y1, x2,y2, x3,y3]` 定长分组），C# 端只读数组画图，不带解析器。
- **（自包含）运行时解析**：C# 写 tokenizer + 状态机（`M/m L/l H/h V/v C/c S/s Q/q T/t A/a Z/z`），
  含相对坐标、多于一组时的隐式重复（`M` 后的参数当 `L`）、以及同一套弧线转贝塞尔。

## 3. 先在 HTML 里排版，再移植到原生

把 path 内联进 `<svg>` 排版（大小、构图、辉光一起调），迭代速度比改原生代码快一个量级。
确认后把同一组参数（尺寸、颜色、渐变停止点）搬到原生绘制。

渐变填充直接拄品牌色：白 → 浅蓝 → 品牌蓝 的三段线性渐变，观感最好。

## 4. 画面构成（实测有效）

- 底：近黑深蓝（`#04060e`）+ 一层大面积径向辉光（品牌色、低 alpha）
- 主体：品牌矢量，居中偏上（约 44% 高度处）
- 衬：2–3 个同心细圆环 + 脉冲扩散环
- 点缀：4–5 个微粒（3 px 圆 + 品牌色阴影），缓慢上移淡出
- 文字：主体下方 ~76% 处，加双层 `text-shadow`（近距强 + 远距弱）才像发光
