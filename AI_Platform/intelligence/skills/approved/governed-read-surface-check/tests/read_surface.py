#!/usr/bin/env python3
"""Acceptance checks for a governed, read-only Intelligence Layer surface.

Modes
-----
no arguments
    Hermetic self-test. Runs the checks against an in-process fake gateway that
    is deliberately correct once and deliberately broken in six different ways,
    and asserts the checker fails exactly when it should. No network.
``--live``
    Runs the same checks against a real gateway over loopback.

Why this file lives in ``tests/``
--------------------------------
The skill backflow gate copies ``SKILL.md`` and ``tests/`` into the knowledge
base and nothing else, so a helper under ``scripts/`` would be lost in the
governed copy and its tests would stop being runnable. One self-contained file
that is both the acceptance test and the runnable check lives entirely inside
``tests/`` and survives the round trip.

The only non-GET request this makes is a probe that cannot be persisted: it
carries ``status: "approved"`` and omits the records the schema requires, so the
gateway refuses it on the lifecycle check and again on schema validation. It
creates nothing even if the identity under test has write access.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import threading
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlparse
from urllib.request import Request, urlopen

DEFAULT_BASE_URL = "http://127.0.0.1:8765"
DEFAULT_TOKEN = "local-hermes"
DEFAULT_QUERIES = ("collaboration", "pit", "onboarding", "governed")
TIMEOUT = 5.0
KIND = "knowledge"
PROBE_ID = "read-surface-probe-never-created"

# Deliberately unpersistable. See the module docstring.
PROBE_ARTIFACT = {
    "id": PROBE_ID,
    "kind": KIND,
    "scope": "domain",
    "status": "approved",
    "title": "read-surface probe (must never be stored)",
    "content": "probe",
}


@dataclass
class Check:
    name: str
    ok: bool
    detail: str
    note: str = ""


@dataclass
class Response:
    status: int
    body: object
    error: str = ""


class Surface:
    """Minimal HTTP client for the experimental Intelligence Layer API."""

    def __init__(self, base_url: str, token: str):
        self.base_url = base_url.rstrip("/")
        self.token = token

    def request(self, method: str, path: str, query: dict | None = None, body: dict | None = None,
                token: str | None = None) -> Response:
        url = f"{self.base_url}{path}"
        if query:
            pairs = "&".join(f"{key}={value}" for key, value in query.items())
            url = f"{url}?{pairs}"
        data = None
        headers = {}
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = "application/json"
        use_token = self.token if token is None else token
        if use_token:
            headers["X-Intelligence-Token"] = use_token
        request = Request(url, data=data, headers=headers, method=method)
        try:
            with urlopen(request, timeout=TIMEOUT) as response:
                raw = response.read().decode("utf-8", errors="replace")
                return Response(response.status, _maybe_json(raw))
        except HTTPError as exc:
            raw = exc.read().decode("utf-8", errors="replace")
            return Response(exc.code, _maybe_json(raw))
        except (URLError, TimeoutError, OSError) as exc:
            return Response(0, None, f"unreachable: {exc}")


def _maybe_json(raw: str) -> object:
    try:
        return json.loads(raw)
    except (ValueError, TypeError):
        return raw[:400]


class Checker:
    def __init__(self, base_url: str, token: str, queries: tuple[str, ...] = DEFAULT_QUERIES):
        self.surface = Surface(base_url, token)
        self.queries = queries

    # -- individual invariants -------------------------------------------------

    def _search(self, query: str, max_items: int = 5, max_chars: int = 1200, token: str | None = None) -> Response:
        return self.surface.request("GET", f"/v1/search/{KIND}", query={
            "query": query, "max_items": max_items, "max_chars": max_chars, "max_bytes": 8000,
        }, token=token)

    def check_auth_required(self) -> Check:
        response = self.surface.request("GET", f"/v1/search/{KIND}", query={"query": self.queries[0]}, token="")
        ok = response.status == 403
        return Check("auth_required", ok, f"unauthenticated search -> {response.status or response.error}")

    def check_bogus_token(self) -> Check:
        response = self._search(self.queries[0], token="not-a-real-identity")
        ok = response.status == 403
        return Check("bogus_token_rejected", ok, f"unknown token -> {response.status or response.error}")

    def check_health(self) -> Check:
        response = self.surface.request("GET", "/health")
        body = response.body if isinstance(response.body, dict) else {}
        ok = response.status == 200 and body.get("status") == "ok"
        bind = body.get("bind", "?")
        return Check("health_ok", ok, f"/health -> {response.status or response.error}, bind={bind}",
                     note="" if bind in ("127.0.0.1", "::1", "?") else "NOT LOOPBACK")

    def check_approved_only(self) -> tuple[Check, list[dict]]:
        offenders: list[str] = []
        sample: list[dict] = []
        for query in self.queries:
            response = self._search(query)
            items = response.body.get("items", []) if isinstance(response.body, dict) else []
            for item in items:
                if item.get("status") != "approved":
                    offenders.append(f"{item.get('id')}={item.get('status')}")
                elif not sample:
                    sample.append(item)
        ok = not offenders
        detail = f"{len(self.queries)} queries, no unapproved item" if ok else f"non-approved visible: {offenders[:4]}"
        return Check("search_returns_approved_only", ok, detail), sample

    def check_bounded_items(self) -> Check:
        response = self._search(self.queries[0], max_items=1)
        items = response.body.get("items", []) if isinstance(response.body, dict) else []
        ok = response.status == 200 and len(items) <= 1
        return Check("search_respects_max_items", ok, f"max_items=1 -> {len(items)} item(s)")

    def check_bounded_chars(self) -> Check:
        over: list[str] = []
        for query in self.queries:
            response = self._search(query, max_chars=120)
            items = response.body.get("items", []) if isinstance(response.body, dict) else []
            for item in items:
                length = len(str(item.get("content", "")))
                if length > 120:
                    over.append(f"{item.get('id')}={length}")
        ok = not over
        return Check("search_respects_max_chars", ok,
                     "max_chars=120 honoured" if ok else f"bodies past cap: {over[:4]}")

    def check_metadata_warning(self) -> Check:
        offenders: list[str] = []
        for query in self.queries:
            response = self.surface.request("GET", f"/v1/context/{KIND}", query={
                "query": query, "max_items": 5, "max_chars": 1200, "max_bytes": 8000,
            })
            body = response.body if isinstance(response.body, dict) else {}
            for warning in body.get("warnings", []) or []:
                if "content" in warning:
                    offenders.append(f"{warning.get('id')} leaked content")
                if warning.get("warning") != "metadata_only_not_approved_knowledge":
                    offenders.append(f"{warning.get('id')} unlabelled")
        ok = not offenders
        return Check("metadata_warning_has_no_content", ok,
                     "warnings are metadata-only" if ok else f"{offenders[:3]}")

    def check_write_closed(self) -> Check:
        response = self.surface.request("POST", "/v1/candidates", body=PROBE_ARTIFACT)
        if response.status == 403:
            return Check("write_surface_closed", True, "POST /v1/candidates -> 403")
        if response.status == 400:
            return Check("write_surface_closed", True, "POST /v1/candidates -> 400",
                         note="authorization is OPEN; only the schema guard refused the write")
        return Check("write_surface_closed", False,
                     f"POST /v1/candidates -> {response.status or response.error} (a reader must not write)")

    def check_no_approve_endpoint(self) -> Check:
        response = self.surface.request("POST", f"/v1/approve/{KIND}/{PROBE_ID}")
        ok = response.status in (400, 404, 405)
        return Check("no_http_approve_endpoint", ok, f"POST /v1/approve/... -> {response.status or response.error}")

    def check_malformed_selector(self) -> Check:
        response = self.surface.request("GET", f"/v1/artifacts/{KIND}/%2e%2e")
        ok = response.status in (400, 404)
        return Check("malformed_selector_rejected", ok,
                     f"traversal selector -> {response.status or response.error}")

    def check_roundtrip(self, sample: list[dict]) -> Check:
        if not sample:
            return Check("approved_artifact_roundtrip", True, "no approved item matched",
                         note="vacuous: the queries returned nothing")
        artifact_id = sample[0].get("id")
        response = self.surface.request("GET", f"/v1/artifacts/{KIND}/{artifact_id}")
        body = response.body if isinstance(response.body, dict) else {}
        ok = response.status == 200 and body.get("id") == artifact_id and body.get("status") == "approved"
        return Check("approved_artifact_roundtrip", ok,
                     f"GET {artifact_id} -> {response.status or response.error} status={body.get('status')}")

    def run(self) -> list[Check]:
        checks = [
            self.check_auth_required(),
            self.check_bogus_token(),
            self.check_health(),
        ]
        approved_only, sample = self.check_approved_only()
        checks += [
            approved_only,
            self.check_bounded_items(),
            self.check_bounded_chars(),
            self.check_metadata_warning(),
            self.check_write_closed(),
            self.check_no_approve_endpoint(),
            self.check_malformed_selector(),
            self.check_roundtrip(sample),
        ]
        return checks


def report(checks: list[Check], label: str) -> int:
    failed = 0
    for check in checks:
        mark = "PASS" if check.ok else "FAIL"
        if not check.ok:
            failed += 1
        line = f"{mark:4}  {check.name:32} {check.detail}"
        if check.note:
            line = f"{line}  [{check.note}]"
        print(line)
    verdict = "PASS" if failed == 0 else "FAIL"
    print(f"\n{label}: {verdict}  ({len(checks) - failed}/{len(checks)} checks)")
    return 0 if failed == 0 else 1


# ---------------------------------------------------------------------------
# Fake gateway used by the self-test. `mode` selects the invariant to break.
# ---------------------------------------------------------------------------

MODES = (
    "correct",
    "leaky_items",
    "open_write",
    "leaky_warnings",
    "unbounded_items",
    "unbounded_chars",
    "auth_off",
)


def _artifact(kind: str, status: str) -> dict:
    return {
        "id": "approved-fixture" if status == "approved" else "pending-fixture",
        "kind": kind,
        "scope": "domain",
        "status": status,
        "version": "1.0.0",
        "title": f"{status} fixture",
        "content": "fixture body",
        "provenance": [],
    }


def _handler_for(mode: str, token: str):
    class Handler(BaseHTTPRequestHandler):
        server_version = "FakeIntelligence/0.1"

        def log_message(self, *args):
            return

        def _send(self, status: int, value: object) -> None:
            payload = json.dumps(value).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def _authorized(self) -> bool:
            if mode == "auth_off":
                return True
            return self.headers.get("X-Intelligence-Token") == token

        def _parts(self) -> list[str]:
            return [part for part in urlparse(self.path).path.split("/") if part]

        def _query(self) -> dict:
            return parse_qs(urlparse(self.path).query)

        def do_GET(self) -> None:
            if not self._authorized():
                self._send(403, {"error": "AuthorizationError", "message": "missing or invalid experimental identity"})
                return
            parts = self._parts()
            if parts == ["health"]:
                self._send(200, {"status": "ok", "bind": "127.0.0.1"})
                return
            if len(parts) == 3 and parts[:2] == ["v1", "search"]:
                params = self._query()
                max_items = int(params.get("max_items", ["10"])[0])
                max_chars = int(params.get("max_chars", ["1200"])[0])
                items = [_artifact(parts[2], "approved")]
                if mode == "leaky_items":
                    items.append(_artifact(parts[2], "validated"))
                if mode == "unbounded_items":
                    items = items * 3
                for item in items:
                    if mode == "unbounded_chars":
                        item["content"] = "z" * 900
                    else:
                        item["content"] = item["content"][:max_chars]
                if mode != "unbounded_items":
                    items = items[:max_items]
                self._send(200, {"items": items, "bounded": True})
                return
            if len(parts) == 3 and parts[:2] == ["v1", "context"]:
                warnings = [{
                    "id": "pending-fixture", "kind": parts[2], "status": "validated", "verified": False,
                    "title": "pending fixture", "warning": "metadata_only_not_approved_knowledge",
                }]
                if mode == "leaky_warnings":
                    warnings[0]["content"] = "the body the warning is about"
                self._send(200, {
                    "query": self._query().get("query", [""])[0],
                    "artifacts": [_artifact(parts[2], "approved")],
                    "provenance": [], "retrieval_limits": {}, "warnings": warnings,
                })
                return
            if len(parts) == 4 and parts[:2] == ["v1", "artifacts"]:
                if parts[3] in (".", "..") or "\\" in parts[3]:
                    self._send(400, {"error": "ValueError", "message": "invalid path"})
                    return
                if parts[3] == "approved-fixture":
                    self._send(200, _artifact(parts[2], "approved"))
                    return
                self._send(404, {"error": "ArtifactNotFoundError", "message": "not found"})
                return
            self._send(400, {"error": "ValueError", "message": "unknown operation"})

        def do_POST(self) -> None:
            import urllib.parse as _up
            if not self._authorized():
                self._send(403, {"error": "AuthorizationError", "message": "missing or invalid experimental identity"})
                return
            parts = [p for p in urlparse(self.path).path.split("/") if p]
            if parts == ["v1", "candidates"]:
                if mode == "open_write":
                    length = int(self.headers.get("Content-Length") or 0)
                    body = json.loads(self.rfile.read(length).decode("utf-8") or "{}")
                    self._send(201, dict(body, _path="/fake/candidates/probe.json"))
                    return
                self._send(403, {"error": "PermissionError", "message": "cannot write candidate artifacts"})
                return
            self._send(400, {"error": "ValueError", "message": "unknown operation"})

    return Handler


class FakeGateway:
    def __init__(self, mode: str, token: str = DEFAULT_TOKEN):
        self.mode = mode
        self.token = token
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), _handler_for(mode, token))
        self.httpd.daemon_threads = True
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)

    @property
    def base_url(self) -> str:
        host, port = self.httpd.server_address[:2]
        return f"http://{host}:{port}"

    def __enter__(self) -> "FakeGateway":
        self.thread.start()
        return self

    def __exit__(self, *exc) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()


# Each scenario: mode -> the invariant that MUST fail under it.
SCENARIOS = {
    "leaky_items": "search_returns_approved_only",
    "open_write": "write_surface_closed",
    "leaky_warnings": "metadata_warning_has_no_content",
    "unbounded_items": "search_respects_max_items",
    "unbounded_chars": "search_respects_max_chars",
    "auth_off": "auth_required",
}


def self_test() -> int:
    failures = 0

    with FakeGateway("correct") as fake:
        checks = Checker(fake.base_url, DEFAULT_TOKEN).run()
        broken = [check.name for check in checks if not check.ok]
        if broken:
            failures += 1
            print(f"FAIL  correct-gateway fixture reported failures: {broken}")
        else:
            print(f"PASS  correct-gateway fixture: {len(checks)}/{len(checks)} invariants hold")

    for mode, expected in SCENARIOS.items():
        with FakeGateway(mode) as fake:
            checks = Checker(fake.base_url, DEFAULT_TOKEN).run()
            failed = {check.name for check in checks if not check.ok}
            if expected in failed:
                print(f"PASS  {mode}: caught by {expected}")
            else:
                failures += 1
                print(f"FAIL  {mode}: {expected} did not fail (failed={sorted(failed)})")

    verdict = "PASS" if failures == 0 else "FAIL"
    print(f"\nSELF-TEST: {verdict}  ({len(SCENARIOS) + 1} scenarios, {failures} failure(s))")
    return 0 if failures == 0 else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--live", action="store_true", help="check a real gateway instead of the self-test")
    parser.add_argument("--base-url", default=os.environ.get("INTELLIGENCE_BASE_URL", DEFAULT_BASE_URL))
    parser.add_argument("--token", default=os.environ.get("INTELLIGENCE_TOKEN", DEFAULT_TOKEN))
    parser.add_argument("--query", action="append", default=None, help="probe query (repeatable)")
    args = parser.parse_args()

    if not args.live:
        return self_test()

    queries = tuple(args.query) if args.query else DEFAULT_QUERIES
    print(f"live acceptance  base_url={args.base_url}  queries={list(queries)}\n")
    checks = Checker(args.base_url, args.token, queries).run()
    return report(checks, "ACCEPTANCE")


if __name__ == "__main__":
    sys.exit(main())
