"""MCP over Streamable HTTP: the surface every agent is supposed to read.

The point of these tests is not the JSON-RPC envelope. It is that one URL
answers discovery, tool calls and resource reads for any client, that the
transport refuses anonymous and cross-origin callers, and that the one write
tool deposits a *candidate* -- it never approves itself.
"""

from __future__ import annotations

# Tests own their state directory (see test_state_isolation.py).
import os as _os

_os.environ.pop("INTELLIGENCE_STATE", None)

import json
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

_ROOT = next(path for path in Path(__file__).resolve().parents if (path / "AI_Platform").is_dir())
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from AI_Platform.intelligence.experimental.api.server import build_server
from AI_Platform.intelligence.gateway.models import Actor, utc_now
from AI_Platform.intelligence.gateway.service import IntelligenceGateway

_os.environ.setdefault("INTELLIGENCE_EMBED_DISABLE", "1")
_os.environ["INTELLIGENCE_ALLOW_LEGACY_NAMES"] = "1"


def artifact(artifact_id: str, kind: str = "knowledge") -> dict:
    now = utc_now()
    value = {
        "id": artifact_id,
        "kind": kind,
        "scope": "domain",
        "status": "candidate",
        "version": "0.1.0",
        "title": "考纲原文才算数",
        "content": "卷面范围只认考纲原文，转述标注待核实。",
        "created_by": "mcp-test",
        "created_at": now,
        "updated_at": now,
        "source": [{"type": "test", "retrieved_at": now}],
        "provenance": [{"type": "test", "created_at": now}],
        "verified": False,
        "verified_by": None,
        "verified_at": None,
        "applies_to": ["mcp"],
        "compatibility": ["mcp"],
        "expires_at": None,
        "review_interval_days": 30,
        "tests": [{"name": "test"}],
        "evidence": [],
        "supersedes": None,
        "superseded_by": None,
        "metadata": {"tags": ["考纲", "核实"]},
    }
    return value


class McpHttpTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        gateway = IntelligenceGateway(self.root)
        writer = Actor("mcp-writer", "agent", frozenset({"read:approved", "write:candidate"}), "test")
        qa = Actor("mcp-qa", "qa", frozenset({"read:approved", "read:candidate", "validate:candidate"}), "test")
        human = Actor("mcp-human", "human", frozenset({"read:approved", "read:candidate", "approve"}), "test")
        gateway.submit_candidate(writer, artifact("mcp-approved"))
        gateway.validate_candidate(qa, "mcp-approved", "knowledge")
        gateway.approve(human, "mcp-approved", "knowledge")
        # A candidate must stay invisible to a reader: only approved is knowledge.
        gateway.submit_candidate(writer, artifact("mcp-pending"))

        actors = {
            "mcp-writer": writer,
            "mcp-qa": qa,
            "mcp-human": human,
            "mcp-reader": Actor("mcp-reader", "runtime", frozenset({"read:approved"}), "test"),
        }
        self.server = build_server(self.root, actors=actors)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.server.server_address[1]}"

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        self.temp.cleanup()

    def rpc(self, method: str, params: dict | None = None, token: str | None = "mcp-reader",
            origin: str | None = None, request_id: int = 1) -> tuple[int, dict]:
        body = json.dumps({"jsonrpc": "2.0", "id": request_id, "method": method,
                           "params": params or {}}).encode()
        headers = {"Content-Type": "application/json", "Content-Length": str(len(body))}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        if origin:
            headers["Origin"] = origin
        request = Request(f"{self.base}/mcp", data=body, headers=headers, method="POST")
        try:
            with urlopen(request, timeout=20) as response:
                return response.status, json.loads(response.read() or b"null")
        except HTTPError as exc:
            return exc.code, json.loads(exc.read() or b"{}")

    def call(self, name: str, arguments: dict, token: str = "mcp-reader") -> dict:
        status, body = self.rpc("tools/call", {"name": name, "arguments": arguments}, token=token)
        self.assertEqual(status, 200)
        return json.loads(body["result"]["content"][0]["text"])

    def test_initialize_advertises_tools_and_resources(self) -> None:
        status, body = self.rpc("initialize", {"protocolVersion": "2025-06-18",
                                               "capabilities": {}, "clientInfo": {"name": "t", "version": "1"}})
        self.assertEqual(status, 200)
        result = body["result"]
        self.assertGreaterEqual(result["protocolVersion"], "2025-06-18")
        self.assertIn("tools", result["capabilities"])
        self.assertIn("resources", result["capabilities"])

    def test_tool_list_is_stable_and_includes_the_write_tool(self) -> None:
        status, body = self.rpc("tools/list")
        self.assertEqual(status, 200)
        names = {tool["name"] for tool in body["result"]["tools"]}
        self.assertLessEqual({"search_knowledge", "get_artifact", "kb_index", "deposit_candidate"}, names)
        # Every tool must be callable without an argument it did not declare.
        for tool in body["result"]["tools"]:
            self.assertIn("inputSchema", tool)

    def test_search_returns_approved_and_never_a_candidate(self) -> None:
        result = self.call("search_knowledge", {"query": "考纲"})
        ids = {item["id"] for item in result["items"]}
        self.assertIn("mcp-approved", ids)
        self.assertNotIn("mcp-pending", ids)

    def test_kb_index_lists_only_approved(self) -> None:
        result = self.call("kb_index", {})
        ids = {entry["id"] for entry in result["kinds"]["knowledge"]}
        self.assertIn("mcp-approved", ids)
        self.assertNotIn("mcp-pending", ids)

    def test_resource_uri_reads_one_record(self) -> None:
        status, body = self.rpc("resources/read", {"uri": "kb://knowledge/mcp-approved"})
        self.assertEqual(status, 200)
        payload = json.loads(body["result"]["contents"][0]["text"])
        self.assertEqual(payload["status"], "approved")

    def test_unknown_resource_is_a_jsonrpc_error(self) -> None:
        status, body = self.rpc("resources/read", {"uri": "kb://knowledge/does-not-exist"})
        self.assertEqual(status, 200)
        self.assertEqual(body["error"]["code"], -32002)

    def test_anonymous_and_foreign_origin_are_refused(self) -> None:
        status, _ = self.rpc("tools/list", token=None)
        self.assertEqual(status, 403)
        status, _ = self.rpc("tools/list", origin="http://evil.example.com")
        self.assertEqual(status, 403)
        # localhost origins are allowed (a browser-based client on this host).
        status, _ = self.rpc("tools/list", origin="http://127.0.0.1:3000")
        self.assertEqual(status, 200)

    def test_deposit_creates_a_candidate_not_knowledge(self) -> None:
        body = artifact("mcp-deposited")
        body["id"] = "mcp-deposited"
        result = self.call("deposit_candidate", {"artifact": body}, token="mcp-writer")
        self.assertTrue(result["deposited"])
        self.assertEqual(result["status"], "candidate")
        # A reader cannot see it yet, and the depositor did not approve it.
        search = self.call("search_knowledge", {"query": "考纲"})
        self.assertNotIn("mcp-deposited", {item["id"] for item in search["items"]})

    def test_well_known_discovery_needs_no_token(self) -> None:
        with urlopen(f"{self.base}/.well-known/mcp.json", timeout=20) as response:
            payload = json.loads(response.read())
        self.assertEqual(payload["transport"], "streamable-http")
        self.assertTrue(payload["url"].endswith("/mcp"))

    def test_get_on_mcp_is_405_not_a_hang(self) -> None:
        try:
            urlopen(f"{self.base}/mcp", timeout=20)
        except HTTPError as exc:
            self.assertEqual(exc.code, 405)
        else:
            self.fail("GET /mcp should be refused")


if __name__ == "__main__":
    unittest.main()
