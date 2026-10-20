# -*- coding: utf-8 -*-
"""起手骨架：中文图文 PDF（reportlab platypus）。

复制出来改 CONTENT 段即可。字体先转 TTF，见 SKILL.md 第 1 节：
    otf2ttf ~/.local/share/fonts/noto-cjk/NotoSansSC-Regular.otf -o fonts/NotoSansSC-Regular.ttf
    otf2ttf ~/.local/share/fonts/noto-cjk/NotoSansSC-Bold.otf    -o fonts/NotoSansSC-Bold.ttf

插图脚本（matplotlib）另写一个文件，输出到 figs/，本文件只负责装配。
"""
import os

from PIL import Image as PILImage
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import cm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.pdfmetrics import registerFontFamily
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (Image, KeepTogether, Paragraph,
                                SimpleDocTemplate, Spacer, Table, TableStyle)

FONT_REG = "fonts/NotoSansSC-Regular.ttf"
FONT_BOLD = "fonts/NotoSansSC-Bold.ttf"
OUT = "handout.pdf"
MARGIN = 2 * cm
CONTENT_WIDTH = A4[0] - 2 * MARGIN
INK = colors.HexColor("#1a2233")
GREY = colors.HexColor("#6b7280")
ACCENT = colors.HexColor("#c0392b")

pdfmetrics.registerFont(TTFont("CJK", FONT_REG))
pdfmetrics.registerFont(TTFont("CJK-B", FONT_BOLD))
# 不注册族的话 <b> 会被静默忽略（不报错，只是没效果）
registerFontFamily("CJK", normal="CJK", bold="CJK-B",
                   italic="CJK", boldItalic="CJK-B")

S = {
    "title": ParagraphStyle("title", fontName="CJK-B", fontSize=20, leading=28,
                            textColor=INK, spaceAfter=12),
    "h2": ParagraphStyle("h2", fontName="CJK-B", fontSize=14.5, leading=21,
                         textColor=INK, spaceBefore=14, spaceAfter=6),
    "body": ParagraphStyle("body", fontName="CJK", fontSize=11, leading=18,
                           textColor=colors.HexColor("#333a45"), spaceAfter=6),
    "cap": ParagraphStyle("cap", fontName="CJK", fontSize=9.5, leading=14,
                          textColor=GREY, alignment=1, spaceBefore=3),
    "quote": ParagraphStyle("quote", fontName="CJK", fontSize=11, leading=18,
                            textColor=INK, firstLineIndent=0),
}


def figure(path, width=None):
    """按原图宽高比算高度 —— 写死高度会把图压扁/拉长。"""
    w, h = PILImage.open(path).size
    width = width or CONTENT_WIDTH
    return Image(path, width=width, height=width * h / w)


def figure_block(path, caption):
    """图 + 图注绑在一起，防止跨页被拆散。"""
    return KeepTogether([figure(path), Paragraph(caption, S["cap"])])


def box(text, bg="#fff7e6", border="#e8a33d"):
    """高亮框：放题目原文或答案。"""
    t = Table([[Paragraph(text, S["quote"])]], colWidths=[CONTENT_WIDTH])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor(bg)),
        ("BOX", (0, 0), (-1, -1), 1.2, colors.HexColor(border)),
        ("LEFTPADDING", (0, 0), (-1, -1), 10),
        ("RIGHTPADDING", (0, 0), (-1, -1), 10),
        ("TOPPADDING", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
    ]))
    return t


def verdict_table(rows):
    """逐选项判决表：[(选项, 说法, 判决, 理由), ...]"""
    data = [[Paragraph(f"<b>{c}</b>", S["body"]) if i == 0
             else Paragraph(str(c), S["body"]) for c in r] for i, r in enumerate(rows)]
    w = CONTENT_WIDTH
    t = Table(data, colWidths=[w * 0.09, w * 0.38, w * 0.11, w * 0.42], repeatRows=1)
    t.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.6, colors.HexColor("#d6dae1")),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#eef3ff")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    return t


def build(story, out=OUT, title=""):
    doc = SimpleDocTemplate(
        out, pagesize=A4, leftMargin=MARGIN, rightMargin=MARGIN,
        topMargin=1.8 * cm, bottomMargin=1.8 * cm, title=title)
    doc.build(story)
    print("saved", out, os.path.getsize(out), "bytes")
    return out


if __name__ == "__main__":
    story = [
        Paragraph("文档标题", S["title"]),
        box("<b>答案：C</b>　一句话理由。"),
        Spacer(1, 8),
        Paragraph("一、先把题目看清楚", S["h2"]),
        box("（题目原文照抄放这里）"),
        Paragraph("二、第一个概念", S["h2"]),
        Paragraph("正文段落。", S["body"]),
        # figure_block("figs/fig1.png", "图 1　这张图在说什么"),
        verdict_table([("选项", "说法", "判决", "理由"),
                       ("A", "……", "✗", "……")]),
    ]
    build(story, title="文档标题")
