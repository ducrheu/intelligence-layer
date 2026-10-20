#!/usr/bin/env python3
"""把 PDF 逐页渲染成 PNG，供 vision 逐页检查。

用法:
    python render_pdf_pages.py <pdf> [输出目录] [dpi]
输出目录默认是 <pdf 所在目录>/preview，dpi 默认 110。

依赖: pymupdf   (uv pip install pymupdf)

为什么要这一步: 版面缺陷（中文乱码/方框、文字超框被裁、两端对齐拉出的
字距空洞、标题孤行落在页尾）在插图上完全看不出来，只有逐页渲染才暴露。
渲染完逐页喂给 vision，别凭代码里的样式定义判断「应该没问题」。
"""
import os
import sys

import pymupdf  # 注意: 不要 `import fitz`，那个别名已废弃，会打 deprecation warning


def main(argv):
    if len(argv) < 2:
        print(__doc__)
        return 1

    src = os.path.abspath(argv[1])
    if not os.path.isfile(src):
        print(f"找不到 PDF: {src}")
        return 1

    outdir = argv[2] if len(argv) > 2 else os.path.join(os.path.dirname(src), "preview")
    dpi = int(argv[3]) if len(argv) > 3 else 110
    os.makedirs(outdir, exist_ok=True)

    doc = pymupdf.open(src)
    for i, page in enumerate(doc, 1):
        pm = page.get_pixmap(dpi=dpi)
        path = os.path.join(outdir, f"page{i}.png")
        pm.save(path)
        print(f"saved {path} {pm.width}x{pm.height}")
    print("页数:", doc.page_count)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
