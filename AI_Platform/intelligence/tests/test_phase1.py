from __future__ import annotations

import os
import sys
from pathlib import Path

# Locate the checkout root by looking for the package itself instead of counting
# parent directories: a fixed depth breaks the moment the tree is laid out
# differently (a clone, a worktree, a CI checkout), and the failure looks like a
# missing package rather than a wrong path.
_ROOT = next(path for path in Path(__file__).resolve().parents if (path / "AI_Platform").is_dir())
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import os
import sys
from pathlib import Path


import json
import os
import tempfile
import unittest
from pathlib import Path

from AI_Platform.intelligence.gateway.errors import ArtifactValidationError, AuthorizationError, LifecycleError
from AI_Platform.intelligence.gateway.lifecycle import assert_transition
from AI_Platform.intelligence.gateway.models import Actor, utc_now
from AI_Platform.intelligence.gateway.schema import validate_artifact, validate_schema_files
from AI_Platform.intelligence.gateway.service import IntelligenceGateway

# Retrieval runs lexical-only in unit tests: fast, deterministic, no model server needed.
os.environ.setdefault("INTELLIGENCE_EMBED_DISABLE", "1")

def artifact(kind: str = "knowledge", status: str = "candidate", artifact_id: str = "demo") -> dict:
    return {
        "id": artifact_id,
        "kind": kind,
        "scope": "shared",
        "status": status,
        "version": "0.1.0",
        "title": "Demo artifact",
        "content": "available_time is an evidence boundary.",
        "created_by": "test-agent",
        "created_at": utc_now(),
        "updated_at": utc_now(),
        "source": [{"type": "test", "retrieved_at": utc_now()}],
        "provenance": [{"type": "test_run", "run_id": "run-1", "created_at": utc_now()}],
        "verified": False,
        "verified_by": None,
        "verified_at": None,
        "applies_to": ["test"],
        "compatibility": ["phase1"],
        "expires_at": None,
        "review_interval_days": 30,
        "tests": [{"name": "test-contract", "result": "pending"}],
        "evidence": [],
        "supersedes": None,
        "superseded_by": None,
        "metadata": {},
    }

class Phase1Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.gateway = IntelligenceGateway(self.root)
        self.agent = Actor("agent-1", "agent", frozenset({"read:approved", "write:candidate", "request:promotion"}), "test")
        self.qa = Actor("qa-1", "qa", frozenset({"read:approved", "read:candidate", "validate:candidate"}), "qa")
        self.human = Actor("human-1", "human", frozenset({"read:approved", "read:candidate", "approve", "deprecate", "rollback"}), None)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_schema_files_are_valid_json(self) -> None:
        schema_dir = Path("AI_Platform/intelligence/schemas")
        validate_schema_files(schema_dir)

    def test_create_knowledge_candidate(self) -> None:
        saved = self.gateway.submit_candidate(self.agent, artifact(artifact_id="knowledge-1"))
        self.assertEqual(saved["status"], "candidate")
        self.assertTrue(Path(saved["_path"]).exists())

    def test_create_experience_candidate(self) -> None:
        saved = self.gateway.submit_candidate(self.agent, artifact("experience", artifact_id="experience-1"))
        self.assertEqual(saved["kind"], "experience")

    def test_source_round_trip(self) -> None:
        value = artifact("source", artifact_id="source-1")
        value["status"] = "validated"
        value["source"] = [{"type": "github", "retrieved_at": utc_now(), "repository": "example/repo"}]
        self.gateway.store.save(value)
        loaded = self.gateway.get_source(self.human, "source-1")
        self.assertEqual(loaded["kind"], "source")

    def test_create_skill_candidate_requires_contract_and_test(self) -> None:
        value = artifact("skill", artifact_id="skill-1")
        value["metadata"] = {"name": "demo", "inputs": [], "outputs": [], "dependencies": [], "permissions": []}
        saved = self.gateway.submit_candidate(self.agent, value)
        self.assertEqual(saved["kind"], "skill")

    def test_invalid_artifact_rejected(self) -> None:
        value = artifact(artifact_id="invalid")
        value["version"] = "v1"
        with self.assertRaises(ArtifactValidationError):
            self.gateway.submit_candidate(self.agent, value)

    def test_missing_provenance_rejected(self) -> None:
        value = artifact(artifact_id="no-provenance")
        value["provenance"] = []
        with self.assertRaises(ArtifactValidationError):
            self.gateway.submit_candidate(self.agent, value)

    def test_missing_source_rejected(self) -> None:
        value = artifact(artifact_id="no-source")
        value["source"] = []
        with self.assertRaises(ArtifactValidationError):
            self.gateway.submit_candidate(self.agent, value)

    def test_agent_cannot_approve(self) -> None:
        self.gateway.submit_candidate(self.agent, artifact(artifact_id="security-1"))
        self.gateway.validate_candidate(self.qa, "security-1", "knowledge")
        with self.assertRaises(AuthorizationError):
            self.gateway.approve(self.agent, "security-1", "knowledge")

    def test_qa_cannot_approve(self) -> None:
        self.gateway.submit_candidate(self.agent, artifact(artifact_id="security-2"))
        self.gateway.validate_candidate(self.qa, "security-2", "knowledge")
        with self.assertRaises(AuthorizationError):
            self.gateway.approve(self.qa, "security-2", "knowledge")

    def test_human_can_approve_after_validation(self) -> None:
        self.gateway.submit_candidate(self.agent, artifact(artifact_id="approval-1"))
        self.gateway.validate_candidate(self.qa, "approval-1", "knowledge")
        approved = self.gateway.approve(self.human, "approval-1", "knowledge")
        self.assertEqual(approved["status"], "approved")
        self.assertTrue(approved["verified"])

    def test_candidate_is_hidden_from_approved_only_search(self) -> None:
        self.gateway.submit_candidate(self.agent, artifact(artifact_id="candidate-only"))
        self.assertEqual(self.gateway.search(self.agent, "knowledge", "available_time"), [])
        self.gateway.validate_candidate(self.qa, "candidate-only", "knowledge")
        self.gateway.approve(self.human, "candidate-only", "knowledge")
        results = self.gateway.search(self.agent, "knowledge", "available_time")
        self.assertEqual([item["id"] for item in results], ["candidate-only"])

    def test_invalid_lifecycle_transition_rejected(self) -> None:
        with self.assertRaises(LifecycleError):
            assert_transition("knowledge", "candidate", "approved")

    def test_request_promotion_is_not_approval(self) -> None:
        self.gateway.submit_candidate(self.agent, artifact(artifact_id="promotion-1"))
        self.gateway.validate_candidate(self.qa, "promotion-1", "knowledge")
        request = self.gateway.request_promotion(self.agent, "promotion-1", "knowledge")
        self.assertEqual(request["status"], "pending_human_approval")
        self.assertEqual(self.gateway.store.load("promotion-1", "knowledge", ("validated",))["status"], "validated")

    def test_supersede_keeps_old_artifact_recoverable(self) -> None:
        original = artifact("knowledge", "candidate", "old-1")
        # Supersede replaces a published artifact; an unpublished draft is withdrawn.
        original["status"] = "approved"
        original["verified"] = True
        original["verified_by"] = "local-human"
        original["verified_at"] = original["created_at"]
        self.gateway.store.save(original)
        replacement = artifact("knowledge", "candidate", "new-1")
        result = self.gateway.supersede(self.human, "old-1", replacement, "knowledge")
        self.assertEqual(result["status"], "candidate")
        old = self.gateway.store.load("old-1", "knowledge", ("deprecated",))
        self.assertEqual(old["superseded_by"], "new-1")

    def test_audit_events_are_written(self) -> None:
        self.gateway.submit_candidate(self.agent, artifact(artifact_id="audit-1"))
        lines = (self.root / "qa" / "audit.jsonl").read_text(encoding="utf-8").splitlines()
        event = json.loads(lines[-1])
        self.assertEqual(event["action"], "submit_candidate")
        self.assertEqual(event["artifact_id"], "audit-1")

if __name__ == "__main__":
    unittest.main()
