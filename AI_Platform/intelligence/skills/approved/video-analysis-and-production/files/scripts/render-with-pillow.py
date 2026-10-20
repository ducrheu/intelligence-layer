"""numpy + Pillow 逐帧渲染 → ffmpeg 管道 的骨架。

用法：改 CONFIG/绘制部分即可；20 核 CPU 上 1280x720 约 30-60ms/帧。
需要 numpy + Pillow 的环境：/home/huyi/hermes/venv/bin/python
"""
import subprocess
import numpy as np
from PIL import Image, ImageDraw, ImageFont

OUT = "/tmp/out.mp4"
W, H, FPS, DUR = 1280, 720, 30, 5
N = FPS * DUR
FONT = "/mnt/c/Windows/Fonts/simhei.ttf"  # 单文件中文字体最稳；ttc 可能失败

# 静态背景一次算好，别逐帧重算
GY = np.linspace(0, 1, H, dtype=np.float32)[:, None]
BG = np.zeros((H, W, 3), np.float32)
BG[..., 0] = 10 + 14 * GY
BG[..., 1] = 16 + 24 * GY
BG[..., 2] = 32 + 44 * GY

cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
       "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-",
       "-c:v", "libx264", "-preset", "medium", "-crf", "19", "-pix_fmt", "yuv420p",
       "-movflags", "+faststart", OUT]
# 不要给 ffmpeg 挂 stderr=PIPE：长任务会在 64KB 缓冲处死锁，重定向到文件或 DEVNULL
proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)

f_big = ImageFont.truetype(FONT, 40)
f_small = ImageFont.truetype(FONT, 20)

rng = np.random.default_rng(0)
series = np.cumsum(rng.normal(0, 1, N))

for i in range(N):
    img = Image.fromarray(BG.astype(np.uint8))
    d = ImageDraw.Draw(img)
    d.text((60, 60), "标题文字", font=f_big, fill=(255, 255, 255))
    d.text((60, 120), f"第 {i + 1}/{N} 帧", font=f_small, fill=(150, 175, 210))
    pts = [(60 + j * 10, 400 + series[j] * 3) for j in range(i + 1)]
    if len(pts) > 1:
        d.line(pts, fill=(78, 161, 255), width=3)
    proc.stdin.write(img.tobytes())

proc.stdin.close()
proc.wait()
print("OK ->", OUT)
