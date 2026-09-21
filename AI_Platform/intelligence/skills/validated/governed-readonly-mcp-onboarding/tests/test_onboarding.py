#!/usr/bin/env python3
"""Acceptance test — onboarding an agent runtime onto the governed read-only MCP.

This turns the four-point acceptance checklist of experience artifact
`governed-readonly-mcp-onboarding` into an executable test. It runs against
the LIVE stack (adapter over stdio + gateway on loopback), not a mock, because
the checklist is entirely about integration behaviour.

    python3 tests/test_onboarding.py

Environment overrides:
    MCP_ADAPTER   path to the stdio adapter (default /mnt/d/OpenClaw/tools/intelligence-mcp/server.py)
    GATEWAY_URL   gateway base url      (default http://127.0.0.1:8765)
    READ_TOKEN    read-only identity    (default local-hermes)
    AGENT_TOKEN   agent identity        (default local-agent)

Exit code 0 = every check passed. Any failure prints FAIL and exits 1.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from urllib.error import HTTPError
from urllib.request import Request, urlopen

MCP_ADAPTER = os.environ.get("MCP_ADAPTER", "/mnt/d/OpenClaw/tools/intelligence-mcp/server.py")
GATEWAY_URL = os.environ.get("GATEWAY_URL", "http://127.0.0.1:8765").rstrip("/")
READ_TOKEN = os.environ.get("READ_TOKEN", "local-hermes")
AGENT_TOKEN = os.environ.get("AGENT_TOKEN", "local-agent")

EXPECTED_TOOLS = {
    "search_approved",
    "get_approved_artifact",
    "get_governance_metadata",
    "get_provenance",
}
# Mutating verbs, matched as a *prefix* of the tool name. A substring match would
# false-positive on `search_approved`, which is a read tool.
MUTATING_VERBS = ("write", "approve", "deprecate", "promote", "validate", "delete", "publish", "rollback", "set", "create", "update")

results: list[tuple[str, bool, str]] = []


def check(name: str, condition: bool, detail: str) -> None:
    results.append((name, bool(condition), detail))
    print(f"{'PASS' if condition else 'FAIL'}  {name}  {detail}")


def http_status(path: str, method: str = "GET", token: str | None = None) -> tuple[int, str]:
    headers = {"X-Correlation-ID": "skill-acceptance-test"}
    if token:
        headers["X-Intelligence-Token"] = token
    request = Request(f"{GATEWAY_URL}{path}", headers=headers, method=method,
                      data=b"{}" if method == "POST" else None)
    try:
        with urlopen(request, timeout=5) as response:
            return response.status, response.read().decode("utf-8", "replace")
    except HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", "replace")


def mcp_session(calls: list[tuple[str, dict]]) -> list[dict]:
    """One stdio session: initialize, tools/list, then each call. Returns responses."""
    script = [{"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
              {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}]
    for index, (name, arguments) in enumerate(calls, start=10):
        script.append({"jsonrpc": "2.0", "id": index, "method": "tools/call",
                       "params": {"name": name, "arguments": arguments}})
    payload = "\n".join(json.dumps(item) for item in script) + "\n"
    process = subprocess.run([sys.executable, MCP_ADAPTER], input=payload, capture_output=True,
                             text=True, timeout=60)
    return [json.loads(line) for line in process.stdout.splitlines() if line.strip()]


def main() -> int:
    responses = {item.get("id"): item for item in mcp_session(
        [("search_approved", {"kind": "skill", "query": "excel-merge"}),
         ("get_provenance", {"kind": "skill", "artifact_id": "excel-merge"})]
    )}

    # 1. stdio handshake + exact read-only surface
    tools = [tool["name"] for tool in responses.get(2, {}).get("result", {}).get("tools", [])]
    check("mcp.tools_list", set(tools) == EXPECTED_TOOLS,
          f"tools={sorted(tools)}")
    check("mcp.no_write_surface",
          not any(tool.casefold().startswith(verb) for tool in tools for verb in MUTATING_VERBS),
          "no write/approve/promote tool name in the MCP surface")

    # 2. end-to-end read of a known approved artifact
    search_text = responses.get(10, {}).get("result", {}).get("content", [{}])[0].get("text", "{}")
    search = json.loads(search_text)
    items = search.get("items", [])
    check("e2e.approved_read", bool(items) and items[0].get("id") == "excel-merge",
          f"approved artifact returned: {items[0].get('id') if items else None}")

    provenance = responses.get(11, {}).get("result", {}).get("structuredContent", {})
    check("e2e.provenance_only", provenance.get("status") == "approved" and "content" not in provenance,
          "get_provenance returns lifecycle metadata, not the body")

    # 3. reverse test: unauthenticated access must be denied
    status, _ = http_status("/v1/search/skill?query=excel-merge")
    check("auth.missing_token_403", status == 403, f"unauthenticated search -> HTTP {status}")

    # 4. reverse test: an agent identity must not reach the validation path
    status, _ = http_status("/v1/validate/knowledge/pit-available-time-semantics", method="POST", token=AGENT_TOKEN)
    check("auth.agent_cannot_validate", status == 403, f"agent validate attempt -> HTTP {status}")

    # 5. approval gate: approval is not reachable over HTTP at all
    status, _ = http_status("/v1/approval/knowledge/pit-available-time-semantics", method="POST", token=READ_TOKEN)
    check("auth.no_http_approve_endpoint", status == 400, f"approval path -> HTTP {status} (no such operation)")

    # 6. invariant: every approved artifact is verified
    status, body = http_status("/v1/search/skill?query=excel-merge", token=READ_TOKEN)
    approved = json.loads(body).get("items", []) if status == 200 else []
    check("governance.approved_are_verified", status == 200 and bool(approved)
          and all(item.get("status") == "approved" for item in approved),
          f"read-only identity sees {len(approved)} approved skill artifact(s)")

    failed = [name for name, ok, _ in results if not ok]
    print()
    print(f"{len(results) - len(failed)}/{len(results)} checks passed")
    if failed:
        print("FAILED: " + ", ".join(failed))
        return 1
    print("ACCEPTANCE: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
