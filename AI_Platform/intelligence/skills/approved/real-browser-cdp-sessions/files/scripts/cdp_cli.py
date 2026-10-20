#!/usr/bin/env python3
"""Minimal CDP CLI to drive an already-running Chrome over its DevTools port.

Usage:
  cdp_cli.py list
  cdp_cli.py new <url>                      # -> prints targetId
  cdp_cli.py eval <targetId> <js-expr>
  cdp_cli.py goto <targetId> <url>
  cdp_cli.py shot <targetId> <out.png> [x y w h scale]
  cdp_cli.py cookies <targetId> <url> [url2 ...]
  cdp_cli.py close <targetId>

Port from env CDP_PORT (default 9222). Run with a python that has `websockets`.
"""
import base64
import json
import os
import sys
import urllib.parse
import urllib.request

from websockets.sync.client import connect

PORT = os.environ.get("CDP_PORT", "9222")
BASE = f"http://127.0.0.1:{PORT}"


def _http(path, method="GET"):
    req = urllib.request.Request(BASE + path, method=method)
    with urllib.request.urlopen(req, timeout=15) as r:
        body = r.read().decode()
    return json.loads(body) if body.strip().startswith(("{", "[")) else body


def list_tabs():
    return [t for t in _http("/json/list") if t.get("type") == "page"]


def new_tab(url):
    return _http("/json/new?" + urllib.parse.quote(url, safe=":/?&=#%"), method="PUT")


class CDP:
    def __init__(self, ws_url):
        self.ws = connect(ws_url, max_size=None, open_timeout=15)
        self.i = 0

    def cmd(self, method, **params):
        self.i += 1
        mid = self.i
        self.ws.send(json.dumps({"id": mid, "method": method, "params": params}))
        while True:
            msg = json.loads(self.ws.recv(timeout=60))
            if msg.get("id") == mid:
                if "error" in msg:
                    raise RuntimeError(f"{method}: {msg['error']}")
                return msg.get("result", {})

    def close(self):
        try:
            self.ws.close()
        except Exception:
            pass


def ws_for(target_id):
    for t in list_tabs():
        if t.get("id") == target_id:
            return t["webSocketDebuggerUrl"]
    raise SystemExit(f"no page target {target_id}")


def main():
    a = sys.argv[1:]
    if not a:
        print(__doc__)
        return
    c = a[0]

    if c == "list":
        for t in list_tabs():
            print(t.get("id"), "|", t.get("title", "")[:40], "|", t.get("url", "")[:90])

    elif c == "new":
        t = new_tab(a[1])
        print(t.get("id"), "|", t.get("url", ""))

    elif c == "close":
        print(_http("/json/close/" + a[1]))

    elif c == "eval":
        d = CDP(ws_for(a[1]))
        try:
            r = d.cmd("Runtime.evaluate", expression=a[2], returnByValue=True,
                      awaitPromise=True, userGesture=True)
            print(json.dumps(r.get("result", {}), ensure_ascii=False))
        finally:
            d.close()

    elif c == "goto":
        d = CDP(ws_for(a[1]))
        try:
            d.cmd("Page.enable")
            d.cmd("Page.navigate", url=a[2])
            print("navigating")
        finally:
            d.close()

    elif c == "cookies":
        d = CDP(ws_for(a[1]))
        try:
            d.cmd("Network.enable")
            r = d.cmd("Network.getCookies", urls=a[2:])
            for ck in r.get("cookies", []):
                print(ck.get("domain"), ck.get("name"), "=", ck.get("value", "")[:24])
        finally:
            d.close()

    elif c == "shot":
        tid, out = a[1], a[2]
        d = CDP(ws_for(tid))
        try:
            kwargs = {"format": "png"}
            if len(a) >= 7:
                x, y, w, h = (float(v) for v in a[3:7])
                scale = float(a[7]) if len(a) >= 8 else 1
                kwargs["clip"] = {"x": x, "y": y, "width": w, "height": h, "scale": scale}
            r = d.cmd("Page.captureScreenshot", **kwargs)
            open(out, "wb").write(base64.b64decode(r["data"]))
            print("SAVED", out)
        finally:
            d.close()

    else:
        print(__doc__)


if __name__ == "__main__":
    main()
