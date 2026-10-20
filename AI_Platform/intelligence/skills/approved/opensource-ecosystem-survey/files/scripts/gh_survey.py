#!/usr/bin/env python3
"""GitHub ecosystem sweep: multi-keyword repo search + README digest. stdlib only.

  gh_survey.py search --out out.json "mock location" "虚拟定位" "topic:mock-location"
  gh_survey.py search --sort updated "pymobiledevice3"
  gh_survey.py readme ZCShou/GoGoGo --chars 1200

Env: GITHUB_TOKEN (optional, raises the 10 req/min unauthenticated search limit).
"""
import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

UA = "hermes-gh-survey/1.0"


def _headers():
    h = {"User-Agent": UA, "Accept": "application/vnd.github+json"}
    tok = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if tok:
        h["Authorization"] = "Bearer " + tok
    return h


def fetch(url, timeout=30, retry_403=True):
    req = urllib.request.Request(url, headers=_headers())
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read().decode("utf-8", "ignore")
    except urllib.error.HTTPError as e:
        if e.code == 403 and retry_403:
            reset = e.headers.get("X-RateLimit-Reset")
            wait = 60
            if reset:
                try:
                    wait = max(5, min(90, int(reset) - int(time.time()) + 2))
                except ValueError:
                    pass
            sys.stderr.write("[rate-limited] sleeping %ss\n" % wait)
            time.sleep(wait)
            return fetch(url, timeout=timeout, retry_403=False)
        raise


def search(queries, sort, per_page, sleep, out):
    repos = {}
    for q in queries:
        params = {"q": q, "sort": sort, "order": "desc", "per_page": per_page}
        url = "https://api.github.com/search/repositories?" + urllib.parse.urlencode(params)
        try:
            data = json.loads(fetch(url))
        except Exception as e:  # one bad query must not kill the sweep
            sys.stderr.write("[skip] %r -> %s\n" % (q, e))
            time.sleep(sleep)
            continue
        total = data.get("total_count", 0)
        items = data.get("items", [])
        sys.stderr.write("%-40s total=%-6s got=%d\n" % (q, total, len(items)))
        for it in items:
            key = it["full_name"]
            rec = repos.setdefault(
                key,
                {
                    "full_name": key,
                    "url": it["html_url"],
                    "stars": it.get("stargazers_count", 0),
                    "language": it.get("language"),
                    "pushed_at": (it.get("pushed_at") or "")[:10],
                    "created_at": (it.get("created_at") or "")[:10],
                    "archived": it.get("archived", False),
                    "description": it.get("description") or "",
                    "topics": it.get("topics") or [],
                    "kw": [],
                },
            )
            if q not in rec["kw"]:
                rec["kw"].append(q)
        time.sleep(sleep)

    ranked = sorted(repos.values(), key=lambda r: r["stars"], reverse=True)
    if out:
        with open(out, "w", encoding="utf-8") as f:
            json.dump(ranked, f, ensure_ascii=False, indent=1)
        sys.stderr.write("\n%d unique repos -> %s\n" % (len(ranked), out))
    print("%6s %-42s %-10s %-11s %-8s %s" % ("STARS", "REPO", "LANG", "PUSHED", "FLAGS", "DESC"))
    for r in ranked:
        flags = "archived" if r["archived"] else ""
        print("%6d %-42s %-10s %-11s %-8s %s" % (
            r["stars"], r["full_name"][:42], str(r["language"])[:10],
            r["pushed_at"], flags, re.sub(r"\s+", " ", r["description"])[:90]))
    return ranked


def readme(repos, chars):
    names = ["README.md", "readme.md", "README.MD", "README.rst", "README"]
    for rp in repos:
        text = None
        for br in ("main", "master"):
            for n in names:
                try:
                    text = fetch(
                        "https://raw.githubusercontent.com/%s/%s/%s" % (rp, br, n),
                        timeout=25, retry_403=False)
                    break
                except Exception:
                    continue
            if text:
                break
        print("=" * 90)
        print("REPO:", rp)
        if not text:
            print("  (README not found — check the default branch / look for docs/*.md)")
            continue
        body = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", text)   # drop images/badges
        body = re.sub(r"<[^>]+>", "", body)                 # drop html
        body = re.sub(r"\n{2,}", "\n", body).strip()
        print(body[:chars])


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("search", help="multi-keyword repo search, deduped and star-ranked")
    s.add_argument("queries", nargs="+")
    s.add_argument("--sort", default="stars", choices=["stars", "updated", "forks"])
    s.add_argument("--per-page", type=int, default=20)
    s.add_argument("--sleep", type=float, default=7.0, help="seconds between queries (10/min unauth)")
    s.add_argument("--out", default=None, help="write JSON snapshot here")

    r = sub.add_parser("readme", help="README digest with branch/filename fallback")
    r.add_argument("repos", nargs="+")
    r.add_argument("--chars", type=int, default=1200)

    a = ap.parse_args()
    if a.cmd == "search":
        search(a.queries, a.sort, a.per_page, a.sleep, a.out)
    else:
        readme(a.repos, a.chars)


if __name__ == "__main__":
    main()
