from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

from AI_Platform.intelligence.experimental.api.server import default_actors
from AI_Platform.intelligence.gateway.errors import ArtifactNotFoundError, ArtifactValidationError, AuthorizationError
from AI_Platform.intelligence.gateway.models import utc_now
from AI_Platform.intelligence.gateway.service import MAX_EVENTS, IntelligenceGateway

# Retrieval runs lexical-only in unit tests: fast, deterministic, no model server needed.
os.environ.setdefault("INTELLIGENCE_EMBED_DISABLE", "1")

SKILL_FILES = {
    "SKILL.md": "---\nname: layout-demo\nversion: 1.0.0\n---\n\n# Layout Demo\n\nBody.\n",
    "tests/test_layout.py": "print('PASS')\n",
    "scripts/helper.py": "print('helper')\n",
}


def _dir(status: str) -> str:
    return {"candidate": "candidates", "experimental": "experimental", "validated": "validated",
            "approved": "approved"}.get(status, status)


def skill_artifact(artifact_id: str = "layout-demo", status: str = "experimental",
                   version: str = "1.0.0") -> dict:
    """A schema-valid skill artifact, at the status the backflow gate submits."""
    now = utc_now()
    return {
        "id": artifact_id,
        "kind": "skill",
        "scope": "domain",
        "status": status,
        "version": version,
        "title": f"{artifact_id} (lifecycle regression)",
        "content": "# Layout Demo\n\nBody.\n",
        "created_by": "lifecycle-test",
        "created_at": now,
        "updated_at": now,
        "source": [{"type": "hermes_skill", "path": "/tmp/SKILL.md", "retrieved_at": now}],
        "provenance": [{"type": "skill_backflow", "created_at": now, "runtime": "hermes"}],
        "verified": False,
        "verified_by": None,
        "verified_at": None,
        "applies_to": ["governance"],
        "compatibility": ["test"],
        "expires_at": None,
        "review_interval_days": 180,
        "tests": [{"path": f"skills/{_dir(status)}/{artifact_id}/tests/test_layout.py",
                   "result": "pass", "exit_code": 0}],
        "evidence": [{"type": "test_run", "command": "python3 tests/test_layout.py", "exit_code": 0}],
        "supersedes": None,
        "superseded_by": None,
        "metadata": {
            "name": artifact_id,
            "inputs": ["nothing"],
            "outputs": ["nothing"],
            "dependencies": ["python3"],
            "permissions": ["read-only"],
            "staged_files": sorted(SKILL_FILES),
        },
    }


def knowledge_artifact(artifact_id: str = "plain-note") -> dict:
    now = utc_now()
    return {
        "id": artifact_id, "kind": "knowledge", "scope": "shared", "status": "candidate",
        "version": "1.0.0", "title": "Plain note", "content": "body", "created_by": "lifecycle-test",
        "created_at": now, "updated_at": now,
        "source": [{"type": "test", "retrieved_at": now}],
        "provenance": [{"type": "test_run", "created_at": now}],
        "verified": False, "verified_by": None, "verified_at": None,
        "applies_to": [], "compatibility": [], "expires_at": None,
        "review_interval_days": None, "tests": [], "evidence": [],
        "supersedes": None, "superseded_by": None, "metadata": {},
    }


class ArtifactLifecycleTests(unittest.TestCase):
    """A status change carries the artifact's files, and ids cannot be shadowed."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.gateway = IntelligenceGateway(self.root)
        self.actors = default_actors()
        self.artifact_id = "layout-demo"

    def tearDown(self) -> None:
        self._tmp.cleanup()

    # -- helpers ---------------------------------------------------------------

    def _stage(self, status: str) -> None:
        """Write the payload the backflow gate stages next to the manifest."""
        base = self.root / "skills" / _dir(status) / self.artifact_id
        for relative, body in SKILL_FILES.items():
            path = base / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(body, encoding="utf-8")

    def _submit(self, artifact: dict | None = None) -> dict:
        submitted = self.gateway.submit_candidate(self.actors["local-agent"],
                                                 artifact or skill_artifact(self.artifact_id))
        self.assertTrue(submitted.get("_path"))
        self._stage((artifact or skill_artifact(self.artifact_id))["status"])
        return submitted

    def _manifest(self, status: str) -> dict:
        path = self.root / "skills" / _dir(status) / self.artifact_id / "manifest.json"
        return json.loads(path.read_text(encoding="utf-8"))

    # -- layout ----------------------------------------------------------------

    def test_validate_moves_the_whole_skill_directory(self) -> None:
        self._submit()
        self.gateway.validate_candidate(self.actors["local-qa"], self.artifact_id, "skill")

        validated = self.root / "skills" / "validated" / self.artifact_id
        for relative in SKILL_FILES:
            self.assertTrue((validated / relative).is_file(), f"{relative} did not move to validated/")
        self.assertFalse((self.root / "skills" / "experimental" / self.artifact_id).exists(),
                         "the old status directory must not be left behind")

        manifest = self._manifest("validated")
        self.assertEqual(manifest["status"], "validated")
        self.assertEqual(manifest["tests"][0]["path"],
                         f"skills/validated/{self.artifact_id}/tests/test_layout.py")
        self.assertTrue((self.root / manifest["tests"][0]["path"]).is_file(),
                        "the recorded test path must resolve inside the store")

    def test_approve_moves_the_whole_skill_directory(self) -> None:
        self._submit()
        self.gateway.validate_candidate(self.actors["local-qa"], self.artifact_id, "skill")
        self.gateway.approve(self.actors["local-human"], self.artifact_id, "skill")

        approved = self.root / "skills" / "approved" / self.artifact_id
        for relative in SKILL_FILES:
            self.assertTrue((approved / relative).is_file(), f"{relative} did not move to approved/")
        self.assertFalse((self.root / "skills" / "validated" / self.artifact_id).exists())

        manifest = self._manifest("approved")
        self.assertEqual(manifest["tests"][0]["path"],
                         f"skills/approved/{self.artifact_id}/tests/test_layout.py")
        self.assertTrue(manifest["verified"])
        self.assertEqual(manifest["verified_by"], "local-human")

    def test_promotion_out_of_an_orphaned_directory_still_resolves(self) -> None:
        """A store split by the old behaviour repairs itself on the next transition."""
        self._submit()
        manifest_path = self.root / "skills" / "experimental" / self.artifact_id / "manifest.json"
        self.assertTrue(manifest_path.is_file())
        # The old bug exactly: the manifest moves to the new status directory and
        # is removed from the old one, while the payload stays put.
        stranded = dict(self._manifest("experimental"))
        stranded["status"] = "validated"
        target = self.root / "skills" / "validated" / self.artifact_id
        target.mkdir(parents=True)
        (target / "manifest.json").write_text(json.dumps(stranded, indent=2) + "\n", encoding="utf-8")
        manifest_path.unlink()
        self.assertTrue((self.root / "skills" / "experimental" / self.artifact_id / "SKILL.md").is_file(),
                        "the payload is stranded in the old status directory")

        self.gateway.approve(self.actors["local-human"], self.artifact_id, "skill")

        approved = self.root / "skills" / "approved" / self.artifact_id
        self.assertTrue((approved / "tests" / "test_layout.py").is_file())
        self.assertTrue((approved / "scripts" / "helper.py").is_file())

    def test_non_skill_transition_is_unchanged(self) -> None:
        self.gateway.submit_candidate(self.actors["local-agent"], knowledge_artifact())
        self.gateway.validate_candidate(self.actors["local-qa"], "plain-note", "knowledge")
        self.assertTrue((self.root / "knowledge" / "candidates" / "plain-note.json").is_file(),
                        "non-skill artifacts stay in the candidates/ directory")

    def test_schema_still_refuses_a_skill_without_tests(self) -> None:
        broken = skill_artifact("no-tests")
        broken["tests"] = []
        with self.assertRaises(ArtifactValidationError):
            self.gateway.submit_candidate(self.actors["local-agent"], broken)

    # -- id integrity ----------------------------------------------------------

    def test_candidate_cannot_shadow_a_published_artifact(self) -> None:
        """A published id may not be re-submitted as a candidate: that would let a
        later approval overwrite the approved manifest without a supersede link."""
        self._submit()
        self.gateway.validate_candidate(self.actors["local-qa"], self.artifact_id, "skill")
        self.gateway.approve(self.actors["local-human"], self.artifact_id, "skill")

        with self.assertRaises(ArtifactValidationError) as caught:
            self.gateway.submit_candidate(self.actors["local-agent"],
                                          skill_artifact(self.artifact_id, version="1.1.0"))
        self.assertIn("already approved", str(caught.exception))
        self.assertEqual(self._manifest("approved")["version"], "1.0.0",
                         "the approved artifact must be untouched")

    def test_explicit_supersede_is_still_allowed(self) -> None:
        """Superseding is the sanctioned update path and keeps the lineage link."""
        self._submit()
        self.gateway.validate_candidate(self.actors["local-qa"], self.artifact_id, "skill")
        self.gateway.approve(self.actors["local-human"], self.artifact_id, "skill")

        replacement = skill_artifact(self.artifact_id, status="experimental", version="2.0.0")
        new = self.gateway.supersede(self.actors["local-human"], self.artifact_id, replacement, "skill")

        self.assertEqual(new["supersedes"], self.artifact_id)
        self.assertTrue((self.root / "skills" / "experimental" / self.artifact_id / "manifest.json").is_file(),
                        "the superseding artifact starts as a candidate")
        replaced = self._manifest("deprecated") if (self.root / "skills" / "deprecated" / self.artifact_id).is_dir() else None
        self.assertIsNotNone(replaced, "the superseded artifact moves to deprecated/")
        self.assertEqual(replaced["status"], "deprecated")
        self.assertEqual(replaced["superseded_by"], self.artifact_id)

    def test_shadowing_a_deprecated_id_is_also_refused(self) -> None:
        self._submit()
        self.gateway.validate_candidate(self.actors["local-qa"], self.artifact_id, "skill")
        self.gateway.approve(self.actors["local-human"], self.artifact_id, "skill")
        self.gateway.deprecate(self.actors["local-human"], self.artifact_id, "skill")

        with self.assertRaises(ArtifactValidationError):
            self.gateway.submit_candidate(self.actors["local-agent"], skill_artifact(self.artifact_id))

    def test_approved_artifact_requires_verified_true(self) -> None:
        """The approval step is the only thing that may set verified."""
        self._submit()
        self.gateway.validate_candidate(self.actors["local-qa"], self.artifact_id, "skill")
        with self.assertRaises(ArtifactValidationError):
            forged = skill_artifact(self.artifact_id, status="validated")
            forged["status"] = "candidate"
            forged["verified"] = True
            forged["verified_by"] = "layout-test"
            forged["verified_at"] = utc_now()
            self.gateway.submit_candidate(self.actors["local-agent"], forged)


class GovernanceEventStreamTests(unittest.TestCase):
    """The feedback channel: a metadata-only stream a consumer can catch up on."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.gateway = IntelligenceGateway(self.root)
        self.actors = default_actors()
        self.artifact_id = "layout-demo"

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _run_a_full_cycle(self) -> None:
        self.gateway.submit_candidate(self.actors["local-agent"], skill_artifact(self.artifact_id))
        base = self.root / "skills" / "experimental" / self.artifact_id
        (base / "tests").mkdir(parents=True, exist_ok=True)
        (base / "tests" / "test_layout.py").write_text("print('PASS')\n", encoding="utf-8")
        self.gateway.validate_candidate(self.actors["local-qa"], self.artifact_id, "skill")
        self.gateway.approve(self.actors["local-human"], self.artifact_id, "skill")

    def test_transitions_appear_in_order_with_statuses(self) -> None:
        self._run_a_full_cycle()
        result = self.gateway.read_events(self.actors["local-hermes"], 0, 20)
        self.assertEqual(
            [(event["action"], event["from_status"], event["to_status"]) for event in result["events"]],
            [("candidate_submitted", None, "experimental"),
             ("validated", "experimental", "validated"),
             ("approved", "validated", "approved")],
        )
        self.assertEqual(result["next_cursor"], 3)
        self.assertEqual(result["total"], 3)

    def test_events_are_metadata_only(self) -> None:
        self._run_a_full_cycle()
        for event in self.gateway.read_events(self.actors["local-hermes"], 0, 20)["events"]:
            self.assertEqual(event["artifact_id"], self.artifact_id)
            self.assertEqual(event["kind"], "skill")
            for absent in ("content", "title", "metadata", "evidence", "source"):
                self.assertNotIn(absent, event)

    def test_cursor_moves_forward_and_yields_nothing_twice(self) -> None:
        self._run_a_full_cycle()
        first = self.gateway.read_events(self.actors["local-hermes"], 0, 2)
        self.assertEqual(first["next_cursor"], 2)
        rest = self.gateway.read_events(self.actors["local-hermes"], first["next_cursor"], 20)
        self.assertEqual(len(rest["events"]), 1)
        self.assertEqual(rest["next_cursor"], 3)
        self.assertEqual(self.gateway.read_events(self.actors["local-hermes"], 3, 20)["events"], [])

    def test_promotion_request_is_an_event(self) -> None:
        self.gateway.submit_candidate(self.actors["local-agent"], knowledge_artifact())
        self.gateway.validate_candidate(self.actors["local-qa"], "plain-note", "knowledge")
        self.gateway.request_promotion(self.actors["local-hermes-writer"], "plain-note", "knowledge")
        actions = [event["action"] for event in self.gateway.read_events(self.actors["local-hermes-writer"], 0, 20)["events"]]
        self.assertEqual(actions, ["candidate_submitted", "validated", "promotion_requested"])

    def test_identities_without_metadata_scope_are_denied(self) -> None:
        with self.assertRaises(PermissionError):
            self.gateway.read_events(self.actors["local-agent"], 0, 5)

    def test_window_is_bounded(self) -> None:
        for since, max_items in ((-1, 5), (0, 0), (0, MAX_EVENTS + 1)):
            with self.subTest(since=since, max_items=max_items):
                with self.assertRaises(ValueError):
                    self.gateway.read_events(self.actors["local-hermes"], since, max_items)


class WithdrawTests(unittest.TestCase):
    """Retracting an unpublished artifact: self-service for the author, reason kept.

    The store holds current state; history lives in qa/audit.jsonl and
    qa/events.jsonl, which are append-only. So withdrawing a knowledge artifact
    rewrites its state file in place (as every other transition does), while a
    skill's directory moves to `archived/` beside its former status directory.
    """

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.gateway = IntelligenceGateway(self.root)
        self.actors = default_actors()

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _file_candidate(self, artifact_id: str = "plain-note") -> None:
        self.gateway.submit_candidate(self.actors["local-agent"], knowledge_artifact(artifact_id))

    def test_author_withdraws_own_candidate(self) -> None:
        self._file_candidate()
        result = self.gateway.withdraw(self.actors["local-agent"], "plain-note", "knowledge", reason="superseded by a corrected draft")
        self.assertEqual(result["status"], "archived")
        self.assertEqual(result["metadata"]["withdraw"]["by"], "local-agent")
        self.assertEqual(result["metadata"]["withdraw"]["from_status"], "candidate")
        self.assertEqual(result["metadata"]["withdraw"]["reason"], "superseded by a corrected draft")
        with self.assertRaises(ArtifactNotFoundError):
            self.gateway.store.load("plain-note", "knowledge", ("candidate", "experimental", "validated"))
        archived = self.gateway.store.load("plain-note", "knowledge", ("archived",))
        self.assertEqual(archived["status"], "archived")

    def test_reason_defaults_rather_than_being_dropped(self) -> None:
        self._file_candidate()
        result = self.gateway.withdraw(self.actors["local-agent"], "plain-note", "knowledge")
        self.assertEqual(result["metadata"]["withdraw"]["reason"], "no reason given")

    def test_an_identity_cannot_withdraw_someone_elses_artifact(self) -> None:
        self._file_candidate()
        with self.assertRaises(PermissionError) as caught:
            self.gateway.withdraw(self.actors["local-hermes-writer"], "plain-note", "knowledge")
        self.assertIn("may only withdraw artifacts it filed", str(caught.exception))
        self.assertEqual(
            self.gateway.store.load("plain-note", "knowledge", ("candidate",))["status"], "candidate",
            "the refused withdrawal must not change anything",
        )

    def test_ownership_falls_back_to_the_audit_log(self) -> None:
        """The backflow gate files as local-agent with created_by=atlas-backflow.

        A claimant-controlled field cannot decide who may retract something, so
        the identity that actually filed it (from the append-only audit log) can.
        """
        self.gateway.submit_candidate(self.actors["local-agent"],
                                     dict(knowledge_artifact(), created_by="atlas-backflow"))
        self.assertEqual(self.gateway._last_submitter("plain-note", "knowledge"), "local-agent")
        result = self.gateway.withdraw(self.actors["local-agent"], "plain-note", "knowledge", reason="wrong draft")
        self.assertEqual(result["status"], "archived")
        self.assertEqual(result["created_by"], "atlas-backflow", "provenance of authorship is preserved")

    def test_the_human_can_withdraw_anything(self) -> None:
        self._file_candidate()
        result = self.gateway.withdraw(self.actors["local-human"], "plain-note", "knowledge", reason="not wanted")
        self.assertEqual(result["status"], "archived")

    def test_a_published_artifact_cannot_be_withdrawn(self) -> None:
        self.gateway.submit_candidate(self.actors["local-agent"], knowledge_artifact())
        self.gateway.validate_candidate(self.actors["local-qa"], "plain-note", "knowledge")
        self.gateway.approve(self.actors["local-human"], "plain-note", "knowledge")
        with self.assertRaises(ArtifactNotFoundError):
            self.gateway.withdraw(self.actors["local-human"], "plain-note", "knowledge")
        self.assertTrue(self.gateway.store.load("plain-note", "knowledge", ("approved",))["verified"])

    def test_an_identity_without_the_scope_cannot_withdraw(self) -> None:
        self._file_candidate()
        with self.assertRaises(AuthorizationError):
            self.gateway.withdraw(self.actors["local-hermes"], "plain-note", "knowledge")

    def test_skill_withdrawal_moves_the_whole_directory(self) -> None:
        self.gateway.submit_candidate(self.actors["local-agent"], skill_artifact("withdraw-demo"))
        base = self.root / "skills" / "experimental" / "withdraw-demo"
        (base / "tests").mkdir(parents=True, exist_ok=True)
        (base / "tests" / "test_layout.py").write_text("print('PASS')\n", encoding="utf-8")
        self.gateway.withdraw(self.actors["local-agent"], "withdraw-demo", "skill", reason="wrong approach")

        archived = self.root / "skills" / "archived" / "withdraw-demo"
        for relative in ("manifest.json", "tests/test_layout.py"):
            self.assertTrue((archived / relative).is_file(), f"{relative} did not move to archived/")
        self.assertFalse(base.exists(), "the experimental directory must not be left behind")
        manifest = json.loads((archived / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["tests"][0]["path"], "skills/archived/withdraw-demo/tests/test_layout.py")

    def test_a_withdrawn_id_can_be_reused(self) -> None:
        """An archived record is inert, so it must not burn the id forever."""
        self._file_candidate()
        self.gateway.withdraw(self.actors["local-agent"], "plain-note", "knowledge", reason="drafting error")
        resubmitted = self.gateway.submit_candidate(self.actors["local-agent"], knowledge_artifact())
        self.assertEqual(resubmitted["status"], "candidate")
        self.assertFalse(resubmitted.get("_idempotent"))
        self.assertEqual(resubmitted["created_by"], "lifecycle-test")

    def test_a_withdrawn_artifact_leaves_the_reading_surface(self) -> None:
        self._file_candidate()
        self.assertEqual(len(self.gateway.search(self.actors["local-hermes-writer"], "knowledge", "plain-note")), 1)
        self.gateway.withdraw(self.actors["local-agent"], "plain-note", "knowledge", reason="drafting error")
        self.assertEqual(self.gateway.search(self.actors["local-hermes-writer"], "knowledge", "plain-note"), [],
                         "an archived artifact is history, not a search result")

    def test_withdrawal_is_recorded_in_the_event_stream(self) -> None:
        self._file_candidate()
        self.gateway.withdraw(self.actors["local-agent"], "plain-note", "knowledge", reason="drafting error")
        actions = [(event["action"], event["to_status"])
                   for event in self.gateway.read_events(self.actors["local-hermes"], 0, 20)["events"]]
        self.assertIn(("withdrawn", "archived"), actions)

    def test_audit_records_a_refused_withdrawal(self) -> None:
        self._file_candidate()
        with self.assertRaises(PermissionError):
            self.gateway.withdraw(self.actors["local-hermes-writer"], "plain-note", "knowledge")
        audit = (self.root / "qa" / "audit.jsonl").read_text(encoding="utf-8")
        self.assertIn('"action": "withdraw"', audit)
        self.assertIn('"result": "denied_not_author"', audit)


if __name__ == "__main__":
    unittest.main(verbosity=2)