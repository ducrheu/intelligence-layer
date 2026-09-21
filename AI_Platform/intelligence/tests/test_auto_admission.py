from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from AI_Platform.intelligence.experimental.api.server import default_actors
from AI_Platform.intelligence.gateway.attestation import artifact_digest
from AI_Platform.intelligence.gateway.auto_admission import POLICY_VERSION, evaluate
from AI_Platform.intelligence.gateway.models import utc_now
from AI_Platform.intelligence.gateway.service import IntelligenceGateway

# Retrieval runs lexical-only in unit tests: fast, deterministic, no model server needed.
os.environ.setdefault("INTELLIGENCE_EMBED_DISABLE", "1")

TRUSTED = "local-hermes-writer"


def note(**overrides) -> dict:
    """A knowledge artifact shaped the way the write surface produces one."""
    now = utc_now()
    artifact = {
        "id": "auto-demo",
        "kind": "knowledge",
        "scope": "domain",
        "status": "candidate",
        "version": "1.0.0",
        "title": "Auto admission demo",
        "content": "body",
        "created_by": TRUSTED,
        "created_at": now,
        "updated_at": now,
        "source": [{"type": "session_evidence", "retrieved_at": now}],
        "provenance": [{"type": "mcp_write_surface", "created_at": now, "agent": TRUSTED}],
        "verified": False,
        "verified_by": None,
        "verified_at": None,
        "applies_to": ["hermes"],
        "compatibility": ["test"],
        "expires_at": None,
        "review_interval_days": 90,
        "tests": [],
        "evidence": [],
        "supersedes": None,
        "superseded_by": None,
        "metadata": {"audience": "hermes"},
    }
    artifact.update(overrides)
    return artifact


class PolicyVerdictTests(unittest.TestCase):
    """The rule set: what may be admitted without a human, and what may not."""

    def test_a_local_non_executable_artifact_from_a_trusted_producer_is_admittable(self) -> None:
        verdict = evaluate(note(), TRUSTED)
        self.assertTrue(verdict.auto_validate and verdict.auto_approve)
        self.assertEqual(verdict.tier, "T2")
        self.assertEqual(verdict.blocking, ())

    def test_the_verdict_is_deterministic(self) -> None:
        """No timestamps: an identical resubmission must produce an identical verdict."""
        self.assertEqual(evaluate(note(), TRUSTED).to_dict(), evaluate(note(), TRUSTED).to_dict())

    def test_shared_scope_needs_a_human(self) -> None:
        verdict = evaluate(note(scope="shared"), TRUSTED)
        self.assertFalse(verdict.auto_approve)
        self.assertIn("is shared", " ".join(verdict.blocking))

    def test_unknown_fields_fail_closed(self) -> None:
        verdict = evaluate(dict(note(), promoted_by="local-human"), TRUSTED)
        self.assertFalse(verdict.auto_validate)
        self.assertIn("unrecognised field", " ".join(verdict.blocking))

    def test_an_unknown_producer_needs_a_human(self) -> None:
        self.assertFalse(evaluate(note(), "some-new-agent").auto_validate)
        self.assertFalse(evaluate(note(created_by="atlas"), TRUSTED).auto_validate)

    def test_a_skill_without_re_checkable_evidence_is_not_admissible(self) -> None:
        """The gateway will not run the author's code itself; a skill needs evidence
        someone else produced and the gateway can re-check (see SkillEvidenceTests)."""
        verdict = evaluate(note(kind="skill", tests=[{"path": "x", "result": "pass"}]), TRUSTED, {})
        self.assertFalse(verdict.auto_validate)
        self.assertIn("skill is not verified", " ".join(verdict.blocking))

    def test_a_claim_of_authority_blocks_admission(self) -> None:
        verdict = evaluate(note(metadata={"permissions": ["read-only", "write:shared-kb"]}), TRUSTED)
        self.assertFalse(verdict.auto_approve)
        self.assertIn("claims authority", " ".join(verdict.blocking))

    def test_no_validity_horizon_blocks_admission(self) -> None:
        verdict = evaluate(note(review_interval_days=None), TRUSTED)
        self.assertFalse(verdict.auto_approve)
        self.assertIn("validity horizon", " ".join(verdict.blocking))

    def test_a_self_declared_verified_blocks_admission(self) -> None:
        verdict = evaluate(note(verified=True, verified_by="self", verified_at=utc_now()), TRUSTED)
        self.assertFalse(verdict.auto_approve)
        self.assertIn("verified=true", " ".join(verdict.blocking))

    def test_the_verdict_names_the_policy_version(self) -> None:
        self.assertEqual(evaluate(note(), TRUSTED).policy_version, POLICY_VERSION)

    # -- the substring trap: prose permissions that deny capability -------------

    def test_a_denied_capability_is_not_read_as_a_claim(self) -> None:
        """`read-only - it must never write candidates` is a denial, not a claim.

        A bare substring match on "write" gets this backwards - the same trap that
        once read `approve` inside `search_approved`.
        """
        for wording in ("read-only - it must never write candidates",
                        "forbidden: approve, write:candidate",
                        "no network access",
                        "must not execute anything"):
            with self.subTest(wording=wording):
                verdict = evaluate(note(metadata={"permissions": [wording]}), TRUSTED)
                self.assertNotIn("claims authority", " ".join(verdict.blocking))

    def test_a_granted_capability_is_a_claim(self) -> None:
        verdict = evaluate(note(metadata={"permissions": ["read-only", "write:runtime-mcp-config"]}), TRUSTED)
        self.assertIn("claims authority", " ".join(verdict.blocking))

    # -- scope vocabulary -------------------------------------------------------

    def test_project_scope_is_private(self) -> None:
        verdict = evaluate(note(scope="project"), TRUSTED)
        self.assertTrue(verdict.auto_approve, verdict.blocking)

    def test_shared_scope_is_named_as_the_reason(self) -> None:
        self.assertIn("is shared", " ".join(evaluate(note(scope="shared"), TRUSTED).blocking))

    def test_an_unknown_scope_is_not_assumed_private(self) -> None:
        verdict = evaluate(note(scope="whatever"), TRUSTED)
        self.assertFalse(verdict.auto_approve)
        self.assertIn("not a known private scope", " ".join(verdict.blocking))


class PolicyIdentityGuardTests(unittest.TestCase):
    """The scope is the door; the verdict is the lock."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.actors = default_actors()

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _gateway(self, mode: str) -> IntelligenceGateway:
        return IntelligenceGateway(self.root, auto_admission=mode)

    def _file(self, gateway: IntelligenceGateway, artifact: dict, actor: str = TRUSTED) -> None:
        gateway.submit_candidate(self.actors[actor], artifact)

    def test_shadow_mode_records_a_verdict_and_moves_nothing(self) -> None:
        gateway = self._gateway("shadow")
        self._file(gateway, note())
        stored = gateway.store.load("auto-demo", "knowledge", ("candidate",))
        self.assertEqual(stored["metadata"]["auto_admission"]["tier"], "T2")
        self.assertEqual(stored["status"], "candidate")
        with self.assertRaises(PermissionError) as caught:
            gateway.validate_candidate(self.actors["policy-auto"], "auto-demo", "knowledge")
        self.assertIn("shadow mode", str(caught.exception))
        self.assertEqual(gateway.store.load("auto-demo", "knowledge", ("candidate",))["status"], "candidate")

    def test_enforce_mode_lets_the_policy_act_on_an_admittable_artifact(self) -> None:
        gateway = self._gateway("enforce")
        self._file(gateway, note())
        validated = gateway.validate_candidate(self.actors["policy-auto"], "auto-demo", "knowledge")
        self.assertEqual(validated["status"], "validated")
        approved = gateway.approve(self.actors["policy-auto"], "auto-demo", "knowledge")
        self.assertEqual(approved["status"], "approved")
        self.assertTrue(approved["verified"])
        self.assertEqual(approved["verified_by"], "policy-auto")
        self.assertEqual(approved["metadata"]["auto_admission"]["policy_version"], POLICY_VERSION)

    def test_enforce_mode_still_refuses_what_the_policy_blocks(self) -> None:
        gateway = self._gateway("enforce")
        self._file(gateway, note(scope="shared"))
        with self.assertRaises(PermissionError) as caught:
            gateway.validate_candidate(self.actors["policy-auto"], "auto-demo", "knowledge")
        self.assertIn("policy may not validate", str(caught.exception))
        self.assertEqual(gateway.store.load("auto-demo", "knowledge", ("candidate",))["status"], "candidate")

    def test_the_human_can_still_approve_what_the_policy_refuses(self) -> None:
        gateway = self._gateway("enforce")
        self._file(gateway, note(scope="shared"))
        gateway.validate_candidate(self.actors["local-qa"], "auto-demo", "knowledge")
        approved = gateway.approve(self.actors["local-human"], "auto-demo", "knowledge")
        self.assertEqual(approved["status"], "approved")
        self.assertEqual(approved["verified_by"], "local-human")

    def test_a_denied_policy_action_is_audited(self) -> None:
        gateway = self._gateway("enforce")
        self._file(gateway, note(scope="shared"))
        with self.assertRaises(PermissionError):
            gateway.approve(self.actors["policy-auto"], "auto-demo", "knowledge")
        audit = (self.root / "qa" / "audit.jsonl").read_text(encoding="utf-8")
        self.assertIn('"result": "denied_by_policy"', audit)

    def test_an_identical_resubmission_is_still_idempotent(self) -> None:
        """The gateway's own metadata must not turn a resubmission into a conflict."""
        gateway = self._gateway("shadow")
        first = gateway.submit_candidate(self.actors[TRUSTED], note())
        self.assertFalse(first.get("_idempotent"))
        second = gateway.submit_candidate(self.actors[TRUSTED], note())
        self.assertTrue(second.get("_idempotent"))

    def test_resubmitting_the_stored_record_is_idempotent_too(self) -> None:
        gateway = self._gateway("shadow")
        gateway.submit_candidate(self.actors[TRUSTED], note())
        stored = gateway.store.load("auto-demo", "knowledge", ("candidate",))
        again = gateway.submit_candidate(self.actors[TRUSTED], stored)
        self.assertTrue(again.get("_idempotent"), "the gateway's own metadata keys are ignored when comparing")




def skill(**overrides) -> dict:
    """A skill artifact shaped the way the backflow gate files one."""
    artifact = note(kind="skill", metadata={
        "name": "evidence-demo",
        "inputs": ["nothing"],
        "outputs": ["nothing"],
        "dependencies": ["python3"],
        "permissions": ["read-only"],
    })
    artifact["tests"] = [{"path": "skills/experimental/evidence-demo/tests/t.py", "result": "pass"}]
    artifact.update(overrides)
    return artifact


def test_run_evidence(artifact: dict, files: dict, recorder: str = "local-qa", **overrides) -> dict:
    record = {
        "type": "test_run",
        "command": "python3 tests/t.py",
        "exit_code": 0,
        "recorded_by": recorder,
        "recorded_at": "2026-09-20T00:00:00Z",
        "subject_digest": artifact_digest(artifact),
        "files": [{"path": path, "sha256": digest} for path, digest in files.items()],
    }
    record.update(overrides)
    return record


class SkillEvidenceTests(unittest.TestCase):
    """A skill is admissible only once someone re-checkable has run it."""

    FILES = {"skills/experimental/evidence-demo/tests/t.py": "sha256:aaaa"}
    META = {"name": "evidence-demo", "inputs": ["x"], "outputs": ["y"],
            "dependencies": ["python3"], "permissions": ["read-only"]}

    def _artifact(self, **overrides) -> dict:
        artifact = note(kind="skill", metadata=dict(self.META))
        artifact["tests"] = [{"path": "skills/experimental/evidence-demo/tests/t.py", "result": "pass"}]
        artifact.update(overrides)
        return artifact

    def test_a_skill_without_evidence_is_not_admissible(self) -> None:
        verdict = evaluate(self._artifact(), TRUSTED, {})
        self.assertFalse(verdict.auto_approve)
        self.assertIn("skill is not verified", " ".join(verdict.blocking))

    def test_evidence_recorded_by_the_author_does_not_count(self) -> None:
        artifact = self._artifact(evidence=[test_run_evidence(self._artifact(), self.FILES, recorder=TRUSTED)])
        verdict = evaluate(artifact, TRUSTED, self.FILES)
        self.assertFalse(verdict.auto_approve)
        self.assertIn("not a verifier identity", " ".join(verdict.blocking))

    def test_verified_evidence_makes_a_skill_admissible(self) -> None:
        artifact = self._artifact()
        artifact["evidence"] = [test_run_evidence(artifact, self.FILES)]
        verdict = evaluate(artifact, TRUSTED, self.FILES)
        self.assertTrue(verdict.auto_approve, verdict.blocking)
        self.assertIn("file hashes re-checked", " ".join(verdict.reasons))

    def test_evidence_does_not_survive_a_content_change(self) -> None:
        original = self._artifact()
        evidence = [test_run_evidence(original, self.FILES)]
        changed = self._artifact(title="Auto admission demo v2")
        changed["evidence"] = evidence
        verdict = evaluate(changed, TRUSTED, self.FILES)
        self.assertFalse(verdict.auto_approve)
        self.assertIn("subject_digest mismatch", " ".join(verdict.blocking))

    def test_evidence_does_not_survive_a_test_file_swap(self) -> None:
        artifact = self._artifact()
        artifact["evidence"] = [test_run_evidence(artifact, self.FILES)]
        swapped = {"skills/experimental/evidence-demo/tests/t.py": "sha256:bbbb"}
        verdict = evaluate(artifact, TRUSTED, swapped)
        self.assertFalse(verdict.auto_approve)
        self.assertIn("sha256 mismatch", " ".join(verdict.blocking))

    def test_a_failed_run_is_not_evidence(self) -> None:
        artifact = self._artifact()
        artifact["evidence"] = [test_run_evidence(artifact, self.FILES, exit_code=1)]
        verdict = evaluate(artifact, TRUSTED, self.FILES)
        self.assertFalse(verdict.auto_approve)
        self.assertIn("not a pass", " ".join(verdict.blocking))

    def test_the_digest_ignores_lifecycle_churn(self) -> None:
        """Status, timestamps, verification and evidence must not move the digest."""
        artifact = self._artifact()
        before = artifact_digest(artifact)
        churned = dict(artifact, status="validated", updated_at="2030-01-01T00:00:00Z",
                       verified=True, verified_by="local-human", verified_at="2030-01-01T00:00:00Z",
                       evidence=[{"type": "test_run", "exit_code": 0}])
        self.assertEqual(artifact_digest(churned), before)


class EvidenceStampTests(unittest.TestCase):
    """The gateway writes attribution and subject; a caller cannot mint them."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.gateway = IntelligenceGateway(self.root, auto_admission="enforce")
        self.actors = default_actors()

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_recorded_by_and_subject_are_gateway_owned(self) -> None:
        artifact = note(id="stamp-demo", metadata={"permissions": ["read-only"]})
        self.gateway.submit_candidate(self.actors[TRUSTED], artifact)
        self.gateway.record_validation_evidence(self.actors["local-qa"], "stamp-demo", "knowledge", [{
            "type": "test_run", "exit_code": 0,
            "recorded_by": "local-human", "subject_digest": "sha256:forged",
        }])
        stored = self.gateway.store.load("stamp-demo", "knowledge", ("candidate",))
        record = stored["evidence"][-1]
        self.assertEqual(record["recorded_by"], "local-qa", "attribution is not caller-controlled")
        self.assertEqual(record["subject_digest"], artifact_digest(stored))
        self.assertEqual(record["recorded_at"], stored["updated_at"])

    def test_recording_evidence_is_audited_and_announced(self) -> None:
        self.gateway.submit_candidate(self.actors[TRUSTED], note(id="stamp-demo", metadata={"permissions": ["read-only"]}))
        self.gateway.record_validation_evidence(self.actors["local-qa"], "stamp-demo", "knowledge",
                                               [{"type": "command_output", "command": "x", "result": "y"}])
        audit = (self.root / "qa" / "audit.jsonl").read_text(encoding="utf-8")
        self.assertIn('"action": "record_validation_evidence"', audit)
        events = self.gateway.read_events(self.actors["local-hermes"], 0, 20)["events"]
        self.assertIn("evidence_recorded", [event["action"] for event in events])

    def test_an_identity_without_the_scope_cannot_record_evidence(self) -> None:
        self.gateway.submit_candidate(self.actors[TRUSTED], note(id="stamp-demo"))
        with self.assertRaises(Exception):
            self.gateway.record_validation_evidence(self.actors[TRUSTED], "stamp-demo", "knowledge",
                                                   [{"type": "command_output"}])


if __name__ == "__main__":
    unittest.main(verbosity=2)