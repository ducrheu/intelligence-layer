#!/usr/bin/env python3
"""登录态探针：验「这个调试 profile 到底登没登录」，只读、不碰凭证值。

用法：
  PY=<装了 websockets 的 python>
  $PY cdp_session_probe.py --port 9222 --domain ai-augmented.com
  $PY cdp_session_probe.py --port 9222 --domain ai-augmented.com \\
        --route https://whut.ai-augmented.com/app/jx-web/mycourse \\
        --expect WT-prd-access-token

做什么：
  1) Storage.getCookies（**整个浏览器**，不按 url 过滤）→ 只打印 domain / name / 值长度
     / expires / httpOnly。**值一律不读不打印**，也不落盘。
  2) 给了 --route 就新开一个标签导航过去，报告**最终落地 URL**：被弹到登录域 =
     登录态不可用；停在业务路由 = 可用。用完自动 close（--keep 可留）。
  3) 给了 --expect 就报该 cookie 名在不在（判定不用人眼数）。

为什么这么判（踩过的坑）：
  * 站点**首页**常常允许游客浏览，看着像进了；要拿**目标业务路由**判，它才会 302 到统一认证。
  * 所以别用 Network.getCookies(urls=[...]) 挑着查：只看业务域会漏掉挂在统一认证域 /
    父域上的 cookie，假阴性会让用户白重登一遍。
  * 用户说「我已经登好了」在这台机器上常见的不成立原因：他登在日常浏览器或手机 App 里 ——
    那两个入口我们结构上都接不上。

只读操作：不写不删 cookie，不动用户已有的标签页。端口默认取环境变量 CDP_PORT。
"""
import argparse
import json
import os
import sys
import time
import urllib.parse
import urllib.request

from websockets.sync.client import connect


class Browser:
    def __init__(self, port):
        self.base = f"http://127.0.0.1:{port}"

    def http(self, path, method="GET"):
        req = urllib.request.Request(self.base + path, method=method)
        with urllib.request.urlopen(req, timeout=20) as r:
            body = r.read().decode()
        return json.loads(body) if body.strip().startswith(("{", "[")) else body

    def pages(self):
        return [t for t in self.http("/json/list") if t.get("type") == "page"]

    def new_tab(self, url):
        # PUT 才生效；GET 会被现代 Chrome 拒
        return self.http("/json/new?" + urllib.parse.quote(url, safe=":/?&=#%"), method="PUT")


class CDP:
    def __init__(self, ws_url):
        self.ws = connect(ws_url, max_size=None, open_timeout=20)
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


def ensure_anchor(br):
    """拿一个页面 target 当锚点；一个都没有就开个 about:blank。"""
    pages = br.pages()
    if pages:
        return pages[0]
    br.new_tab("about:blank")
    time.sleep(1.0)
    pages = br.pages()
    if not pages:
        sys.exit("没有可用的 page target（浏览器没开调试端口？）")
    return pages[0]


def dump_cookies(cdp, domain_filter):
    r = cdp.cmd("Storage.getCookies")  # 不传参数 = 全浏览器
    allc = r.get("cookies", [])
    print(f"整个浏览器 cookie 数: {len(allc)}")
    hits = [c for c in allc if domain_filter in c.get("domain", "")]
    print(f"含 '{domain_filter}' 的: {len(hits)}")
    for c in hits:
        print(
            "  {:<34} {:<30} len={:<4} expires={:<12} httpOnly={}".format(
                c.get("domain", ""), c.get("name", ""),
                len(c.get("value", "")), c.get("expires", ""), c.get("httpOnly", ""),
            )
        )
    return hits


def probe_route(br, route, settle=6.0, keep=False):
    t = br.new_tab(route)
    tid = t.get("id")
    final = route
    deadline = time.time() + settle
    while time.time() < deadline:
        time.sleep(1.0)
        for p in br.pages():
            if p.get("id") == tid:
                final = p.get("url", final)
    print(f"路由探探: {route}")
    print(f"最终落地: {final}")
    bounced = final != route and any(
        k in final.lower() for k in ("login", "passport", "oauth", "auth", "cas")
    )
    print("判定: " + ("❌ 被弹回登录（该 profile 没有可用登录态）" if bounced
                    else ("✅ 停在该路由，登录态可用" if final == route
                          else "⚠️ 落到了别处，自己看一眼上面两个 URL")))
    if not keep and tid:
        try:
            br.http("/json/close/" + tid)
            print("已关闭该探针标签。")
        except Exception:
            pass
    return bounced, final


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", default=os.environ.get("CDP_PORT", "9222"))
    ap.add_argument("--domain", default="", help="域名子串，例如 ai-augmented.com")
    ap.add_argument("--route", default=None, help="目标业务路由（不是首页）")
    ap.add_argument("--expect", action="append", default=[],
                    help="期望存在的 cookie 名，可重复；用来免人眼判定")
    ap.add_argument("--keep", action="store_true", help="不关掉探针标签")
    a = ap.parse_args()

    br = Browser(a.port)
    anchor = ensure_anchor(br)
    cdp = CDP(anchor["webSocketDebuggerUrl"])
    try:
        cdp.cmd("Network.enable")
        hits = dump_cookies(cdp, a.domain)
        names = {c.get("name") for c in hits}
        for want in a.expect:
            print(("✅ 找到 " if want in names else "❌ 缺失 ") + want)
        if a.route:
            probe_route(br, a.route, keep=a.keep)
    finally:
        cdp.close()


if __name__ == "__main__":
    main()
