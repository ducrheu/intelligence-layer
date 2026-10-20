#!/usr/bin/env python3
"""Open Chaoxing login in the user's Chrome, capture the QR code image.

Prints: TARGET_ID, UUID, RECT, SAVED path
Reuses an existing passport2.chaoxing.com tab when present, so the uuid stays alive.
Pass 'reload' as argv[1] to force a fresh code.

Run with a python that has `websockets`. See ../SKILL.md.
"""
import base64
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cdp_cli import CDP, list_tabs, new_tab, ws_for  # noqa: E402

LOGIN = "https://passport2.chaoxing.com/login?fid=&refer="
FIND_QR = (
    '(() => {'
    ' const img = document.querySelector("#qrCode img, img[src*=createqr]");'
    ' if (!img) return "NOQR";'
    ' const r = img.getBoundingClientRect();'
    ' return JSON.stringify({src: img.src, x: r.x, y: r.y, w: r.width, h: r.height});'
    '})()'
)


def target_for_login():
    for t in list_tabs():
        if "passport2.chaoxing.com" in (t.get("url") or ""):
            return t["id"], False
    t = new_tab(LOGIN)
    return t["id"], True


def main():
    tid, created = target_for_login()
    print("TARGET_ID:", tid)
    print("CREATED:", created)

    d = CDP(ws_for(tid))
    try:
        d.cmd("Page.enable")
        if not created and len(sys.argv) > 1 and sys.argv[1] == "reload":
            d.cmd("Page.navigate", url=LOGIN)
            time.sleep(4)
        wait_until = time.time() + 20
        info = None
        while time.time() < wait_until:
            r = d.cmd("Runtime.evaluate", expression=FIND_QR, returnByValue=True)
            val = r.get("result", {}).get("value")
            if val and val != "NOQR":
                info = json.loads(val)
                break
            time.sleep(1)
        if not info:
            print("QR NOT FOUND")
            return
        uuid = info["src"].split("uuid=")[1].split("&")[0]
        print("UUID:", uuid)
        print("RECT:", info["x"], info["y"], info["w"], info["h"])
        out = os.path.join(os.environ.get("BH_AGENT_WORKSPACE", "/tmp"), "qr_live.png")
        r = d.cmd("Page.captureScreenshot", format="png",
                  clip={"x": info["x"], "y": info["y"], "width": info["w"],
                        "height": info["h"], "scale": 3})
        open(out, "wb").write(base64.b64decode(r["data"]))
        print("SAVED:", out)
    finally:
        d.close()


if __name__ == "__main__":
    main()
