from __future__ import annotations

import copy
import hashlib
import http.client
import json
import os
import socket
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from AI_Platform.intelligence.adapters.legacy_freelance import LegacyFreelanceReadOnlyAdapter
from AI_Platform.intelligence.experimental.api.server import build_server
from AI_Platform.intelligence.gateway.errors import ArtifactNotFoundError, ArtifactValidationError, AuthorizationError, LifecycleError
from AI_Platform.intelligence.gateway.models import Actor, utc_now
from AI_Platform.intelligence.gateway.service import IntelligenceGateway

# Retrieval runs lexical-only in unit tests: fast, deterministic, no model server needed.
os.environ.setdefault("INTELLIGENCE_EMBED_DISABLE", "1")


LEGACY_ROOT = Path(
    os.environ.get(
        "LEGACY_FREELANCE_ROOT",
        r"<USERPROFILE>\Documents\Codex\2026-09-11\openclaw-openclaw-openclaw-codex-ai-1",
    )
)
LEGACY_AVAILABLE = LEGACY_ROOT.is_dir()


def artifact(kind: str = "knowledge", status: str = "candidate", artifact_id: str = "phase2-demo") -> dict:
    now = utc_now()
    return {
        "id": artifact_id,
        "kind": kind,
        "scope": "shared",
        "status": status,
        "version": "0.1.0",
        "title": "Phase 2 demo",
        "content": "available_time is bounded evidence.",
        "created_by": "phase2-test",
        "created_at": now,
        "updated_at": now,
        "source": [{"type": "test", "retrieved_at": now}],
        "provenance": [{"type": "test_run", "created_at": now, "run_id": "phase2"}],
        "verified": False,
        "verified_by": None,
        "verified_at": None,
        "applies_to": ["phase2"],
        "compatibility": ["phase2"],
        "expires_at": None,
        "review_interval_days": 30,
        "tests": [{"name": "phase2-test", "result": "pass"}],
        "evidence": [],
        "supersedes": None,
        "superseded_by": None,
        "metadata": {},
    }


def request_json(url: str, token: str, method: str = "GET", body: dict | None = None, headers: dict[str, str] | None = None) -> tuple[int, dict]:
    request_headers = {"X-Intelligence-Token": token}
    if headers:
        request_headers.update(headers)
    data = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        request_headers["Content-Type"] = "application/json"
    request = Request(url, data=data, headers=request_headers, method=method)
    try:
        with urlopen(request, timeout=3) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))


class Phase2FailureInjectionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.gateway = IntelligenceGateway(self.root)
        self.agent = Actor("agent", "agent", frozenset({"read:approved", "write:candidate", "request:promotion"}), "phase2")
        self.qa = Actor("qa", "qa", frozenset({"read:approved", "read:candidate", "validate:candidate", "request:promotion"}), "phase2")
        self.human = Actor("human", "human", frozenset({"read:approved", "read:candidate", "approve", "deprecate", "rollback", "write:candidate"}), "phase2")
        self.server = build_server(self.root)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base_url = f"http://127.0.0.1:{self.server.server_address[1]}"

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        self.temp.cleanup()

    def test_invalid_json_api_request_is_rejected_without_state_change(self) -> None:
        connection = http.client.HTTPConnection("127.0.0.1", self.server.server_address[1], timeout=3)
        connection.request("POST", "/v1/candidates", body=b"{not-json", headers={
            "X-Intelligence-Token": "local-agent",
            "Content-Type": "application/json",
        })
        response = connection.getresponse()
        self.assertEqual(response.status, 400)
        self.assertFalse(list((self.root / "knowledge").rglob("*.json")))
        connection.close()

    def test_interrupted_api_request_does_not_commit_candidate(self) -> None:
        sock = socket.create_connection(("127.0.0.1", self.server.server_address[1]), timeout=3)
        request = (
            "POST /v1/candidates HTTP/1.1\r\n"
            "Host: 127.0.0.1\r\n"
            "X-Intelligence-Token: local-agent\r\n"
            "Content-Type: application/json\r\n"
            "Content-Length: 100\r\n"
            "Connection: close\r\n"
            "\r\n"
            "{\"id\":\"interrupted\""
        ).encode("ascii")
        sock.sendall(request)
        sock.shutdown(socket.SHUT_WR)
        sock.recv(4096)
        sock.close()
        self.assertFalse(list((self.root / "knowledge").rglob("interrupted.json")))

    def test_missing_source_and_provenance_are_rejected(self) -> None:
        missing_source = artifact(artifact_id="missing-source")
        missing_source["source"] = []
        with self.assertRaises(ArtifactValidationError):
            self.gateway.submit_candidate(self.agent, missing_source)
        missing_provenance = artifact(artifact_id="missing-provenance")
        missing_provenance["provenance"] = []
        with self.assertRaises(ArtifactValidationError):
            self.gateway.submit_candidate(self.agent, missing_provenance)

    def test_invalid_lifecycle_and_unauthorized_approval(self) -> None:
        self.gateway.submit_candidate(self.agent, artifact(artifact_id="lifecycle"))
        with self.assertRaises(LifecycleError):
            self.gateway.approve(self.human, "lifecycle", "knowledge")
        self.gateway.validate_candidate(self.qa, "lifecycle", "knowledge")
        with self.assertRaises(AuthorizationError):
            self.gateway.approve(self.agent, "lifecycle", "knowledge")
        with self.assertRaises(AuthorizationError):
            self.gateway.approve(self.qa, "lifecycle", "knowledge")

    def test_agent_cannot_write_approved(self) -> None:
        value = artifact(status="approved", artifact_id="direct-approved")
        with self.assertRaises(ArtifactValidationError):
            self.gateway.submit_candidate(self.agent, value)
        status, body = request_json(f"{self.base_url}/v1/candidates", "local-agent", "POST", value)
        self.assertEqual(status, 400)
        self.assertEqual(body["error"], "ArtifactValidationError")

    def test_duplicate_submission_is_idempotent_then_conflict_is_rejected(self) -> None:
        value = artifact(artifact_id="duplicate")
        first = self.gateway.submit_candidate(self.agent, value)
        second = self.gateway.submit_candidate(self.agent, copy.deepcopy(value))
        self.assertNotIn("_idempotent", first)
        self.assertTrue(second["_idempotent"])
        conflicting = copy.deepcopy(value)
        conflicting["content"] = "different"
        with self.assertRaises(ArtifactValidationError):
            self.gateway.submit_candidate(self.agent, conflicting)

    def test_duplicate_approval_is_idempotent(self) -> None:
        self.gateway.submit_candidate(self.agent, artifact(artifact_id="duplicate-approval"))
        self.gateway.validate_candidate(self.qa, "duplicate-approval", "knowledge")
        first = self.gateway.approve(self.human, "duplicate-approval", "knowledge")
        second = self.gateway.approve(self.human, "duplicate-approval", "knowledge")
        self.assertEqual(first["status"], "approved")
        self.assertTrue(second["_idempotent"])

    def test_supersede_keeps_old_approved_artifact_recoverable(self) -> None:
        original = artifact(artifact_id="supersede-old")
        self.gateway.submit_candidate(self.agent, original)
        self.gateway.validate_candidate(self.qa, "supersede-old", "knowledge")
        self.gateway.approve(self.human, "supersede-old", "knowledge")
        replacement = artifact(artifact_id="supersede-new")
        result = self.gateway.supersede(self.human, "supersede-old", replacement, "knowledge")
        self.assertEqual(result["status"], "candidate")
        old = self.gateway.store.load("supersede-old", "knowledge", ("deprecated",))
        self.assertEqual(old["status"], "deprecated")
        self.assertEqual(old["superseded_by"], "supersede-new")

    def test_interrupted_atomic_replace_preserves_original(self) -> None:
        original = artifact(artifact_id="atomic")
        original["status"] = "validated"
        self.gateway.store.save(original)
        target = self.root / "knowledge" / "candidates" / "atomic.json"
        before = target.read_bytes()
        replacement = copy.deepcopy(original)
        replacement["content"] = "replacement"
        with patch("AI_Platform.intelligence.gateway.store.os.replace", side_effect=RuntimeError("simulated interruption")):
            with self.assertRaises(RuntimeError):
                self.gateway.store.save(replacement)
        self.assertEqual(target.read_bytes(), before)
        self.assertFalse(list(target.parent.glob(".artifact-*.tmp")))

    def test_missing_artifact_and_path_traversal_are_rejected(self) -> None:
        status, body = request_json(f"{self.base_url}/v1/artifacts/knowledge/not-found", "local-agent")
        self.assertEqual(status, 404)
        self.assertEqual(body["error"], "ArtifactNotFoundError")
        status, body = request_json(f"{self.base_url}/v1/artifacts/knowledge/..%2F..%2Foutside", "local-agent")
        self.assertEqual(status, 400)
        self.assertEqual(body["error"], "ValueError")
        status, body = request_json(f"{self.base_url}/v1/artifacts/knowledge/C:%5Coutside", "local-agent")
        self.assertEqual(status, 400)
        self.assertEqual(body["error"], "ValueError")

    def test_candidate_isolation_and_bounded_search(self) -> None:
        value = artifact(artifact_id="isolated")
        status, _ = request_json(f"{self.base_url}/v1/candidates", "local-agent", "POST", value)
        self.assertEqual(status, 201)
        status, body = request_json(f"{self.base_url}/v1/search/knowledge?query=available_time&max_items=1&max_bytes=200&max_chars=20", "local-agent")
        self.assertEqual(status, 200)
        self.assertTrue(body["bounded"])
        self.assertLessEqual(len(body["items"]), 1)
        self.assertEqual(body["items"], [])

    def test_role_spoofing_in_body_does_not_elevate(self) -> None:
        value = artifact(artifact_id="spoof")
        value["role"] = "human"
        status, _ = request_json(f"{self.base_url}/v1/candidates", "local-agent", "POST", value)
        self.assertEqual(status, 201)
        status, _ = request_json(f"{self.base_url}/v1/validate/knowledge/spoof", "local-agent", "POST", {})
        self.assertEqual(status, 403)


@unittest.skipUnless(
    LEGACY_AVAILABLE,
    f"legacy Freelance workspace not reachable at {LEGACY_ROOT}; "
    "set LEGACY_FREELANCE_ROOT to enable these read-only adapter tests",
)
class Phase2AdapterTests(unittest.TestCase):
    def test_legacy_adapter_reads_metadata_without_writes(self) -> None:
        selected = [
            LEGACY_ROOT / "skills" / "registry.json",
            LEGACY_ROOT / "skills" / "approval_history.json",
            LEGACY_ROOT / "experience" / "registry.json",
            LEGACY_ROOT / "job_runner.py",
        ]
        before = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in selected}
        adapter = LegacyFreelanceReadOnlyAdapter(LEGACY_ROOT)
        skill = adapter.get_approved_skill("excel-merge")
        experiences = adapter.list_experience()
        after = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in selected}
        self.assertEqual(skill["version"], "0.1.0")
        self.assertEqual(skill["execution_authority"], "legacy-freelance-job-runner")
        self.assertTrue(any(item["id"] == "exp_excel_source_integrity_001" and item["status"] == "approved" for item in experiences))
        self.assertTrue(any(item["id"] == "exp_excel_named_data_sheet_001" and item["status"] == "candidate" for item in experiences))
        self.assertEqual(before, after)

    def test_legacy_adapter_rejects_path_escape(self) -> None:
        adapter = LegacyFreelanceReadOnlyAdapter(LEGACY_ROOT)
        with self.assertRaises(ValueError):
            adapter._safe_file("../outside.txt")


if __name__ == "__main__":
    unittest.main()