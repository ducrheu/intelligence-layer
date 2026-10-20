可以，我按图里题意来讲。

## 19题
\[
\lim_{x\to 0}\frac{x-\arcsin x}{(\arcsin x)^3}
\]

用展开式：
\[
\arcsin x=x+\frac{x^3}{6}+o(x^3)
\]

所以
\[
x-\arcsin x=x-\left(x+\frac{x^3}{6}+o(x^3)\right)
=-\frac{x^3}{6}+o(x^3)
\]

而
\[
(\arcsin x)^3=x^3+o(x^3)
\]

因此
\[
\lim_{x\to 0}\frac{x-\arcsin x}{(\arcsin x)^3}
=
\lim_{x\to 0}\frac{-\frac{x^3}{6}+o(x^3)}{x^3+o(x^3)}
=-\frac16
\]

**答案：\(-\frac16\)**

---

## 20题
我按图中常见题意理解为：
\[
\lim_{x\to 0}\frac{\alpha x^\alpha}{\sqrt{1+x\arctan x}-\sqrt{\cos x}}=\frac83
\]

先看分母主项。

### 第一步：化简第一个根号
\[
\arctan x=x+o(x)
\]
所以
\[
x\arctan x=x^2+o(x^2)
\]
于是
\[
\sqrt{1+x\arctan x}
=1+\frac12x^2+o(x^2)
\]

### 第二步：化简第二个根号
\[
\cos x=1-\frac{x^2}{2}+o(x^2)
\]
所以
\[
\sqrt{\cos x}
=\sqrt{1-\frac{x^2}{2}+o(x^2)}
=1-\frac{x^2}{4}+o(x^2)
\]

### 第三步：相减
\[
\sqrt{1+x\arctan x}-\sqrt{\cos x}
=
\left(1+\frac12x^2\right)-\left(1-\frac14x^2\right)+o(x^2)
=
\frac34x^2+o(x^2)
\]

所以原式近似为
\[
\frac{\alpha x^\alpha}{\frac34x^2}
=\frac{4\alpha}{3}x^{\alpha-2}
\]

要使极限是非零常数 \(\frac83\)，必须有
\[
\alpha-2=0
\]
所以
\[
\alpha=2
\]

再代回去：
\[
\frac{4\alpha}{3}=\frac83
\Rightarrow \alpha=2
\]

**答案：\(\alpha=2\)**

---

## 这类题的方法总结
你可以记成一句话：

**先找主项，再比阶数。**

### 常用等价无穷小
- \(\arcsin x\sim x\)
- \(\arctan x\sim x\)
- \(\sin x\sim x\)
- \(1-\cos x\sim \frac{x^2}{2}\)
- \(\sqrt{1+u}\sim 1+\frac u2\)

### 做题步骤
1. 先把复杂函数换成主项  
2. 看分子分母谁是最低次幂  
3. 如果题里有参数，先用“极限非零有限”判断幂次  
4. 再代系数

---

## 类似题给你练
先自己做，做完发我，我给你批：

1. \[
\lim_{x\to0}\frac{\tan x-x}{x^3}
\]

2. \[
\lim_{x\to0}\frac{x-\sin x}{x^3}
\]

3. \[
\lim_{x\to0}\frac{1-\cos x-\frac{x^2}{2}}{x^4}
\]

4. \[
\lim_{x\to0}\frac{\sqrt{1+x\ln(1+x)}-\sqrt{1-\frac{x^2}{2}}}{x^2}
\]

5. 已知
\[
\lim_{x\to0}\frac{a x^a}{\sqrt{1+x\arctan x}-\sqrt{\cos x}}=4
\]
求 \(a\)。

如果你愿意，我下一条可以直接把这 5 道的答案也给你。
