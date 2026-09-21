"""Usage telemetry: does anyone read what the knowledge base holds?

The point of these tests is that the knowledge base can be *falsified*. Admission
tests prove an artifact was allowed in; these prove we would notice if it turned
out to be useless.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

# Retrieval runs lexical-only in unit tests: fast, deterministic, and independent of
# whether a model server happens to be running on the machine.
os.environ.setdefault("INTELLIGENCE_EMBED_DISABLE", "1")

from AI_Platform.intelligence.experimental.api.server import default_actors  # noqa: E402
from AI_Platform.intelligence.gateway.service import IntelligenceGateway  # noqa: E402
from AI_Platform.intelligence.gateway.telemetry import (  # noqa: E402
    NEVER_USED, REVIEW_DUE, SURFACED_ONLY, UNVERIFIED, days_since, review_flags,
)

TRUSTED = "local-agent"
READER = "local-hermes"


def note(**overrides) -> dict:
    """A knowledge artifact shaped the way the write surface produces one."""
    now = datetime.now(timezone.utc).isoformat()
    artifact = {
        "id": "usage-demo",
        "kind": "knowledge",
        "scope": "domain",
        "status": "candidate",
        "version": "1.0.0",
        "title": "Usage telemetry demo",
        "content": "A record whose only job is to be measured.",
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
        "review_interval_days": 1,
        "tests": [],
        "evidence": [],
        "metadata": {"permissions": ["read-only"]},
    }
    artifact.update(overrides)
    return artifact


def released(**overrides) -> dict:
    """An artifact a reader can retrieve - the only kind a review looks at."""
    defaults = dict(status="approved", verified=True, verified_by="local-human",
                    verified_at=datetime.now(timezone.utc).isoformat())
    defaults.update(overrides)
    return note(**defaults)


class UsageRecordingTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.gateway = IntelligenceGateway(self.root, auto_admission="enforce")
        self.actors = default_actors()
        self.gateway.submit_candidate(self.actors[TRUSTED], note())
        # no direct candidate -> approved; the lifecycle has no fast lane
        self.gateway.validate_candidate(self.actors["local-qa"], "usage-demo", "knowledge")
        self.gateway.approve(self.actors["local-human"], "usage-demo", "knowledge")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _events(self) -> list[dict]:
        path = self.root / "qa" / "events.jsonl"
        if not path.is_file():
            return []
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]

    def test_retrieval_is_recorded_as_usage(self) -> None:
        self.gateway.get_knowledge(self.actors[READER], "usage-demo")
        used = [event for event in self._events() if event.get("action") == "used"]
        self.assertEqual(len(used), 1)
        self.assertEqual(used[0]["actor"], READER)
        self.assertEqual(used[0]["via"], "get")
        summary = self.gateway.usage_summary()
        self.assertEqual(summary["explicit"]["knowledge/usage-demo"]["count"], 1)
        self.assertEqual(summary["explicit"]["knowledge/usage-demo"]["by"], [READER])

    def test_usage_events_stay_metadata_only(self) -> None:
        """The event stream is forwarded to other agents; it must not carry records."""
        self.gateway.get_knowledge(self.actors[READER], "usage-demo")
        line = [line for line in (self.root / "qa" / "events.jsonl").read_text(encoding="utf-8").splitlines()
                if '"used"' in line][0]
        self.assertNotIn("content", line)
        self.assertNotIn("A record whose only job", line)

    def test_a_denied_read_records_no_usage(self) -> None:
        """An artifact nobody may read is not an artifact anybody used."""
        self.gateway.submit_candidate(self.actors[TRUSTED], note(id="still-a-candidate"))
        with self.assertRaises(Exception):
            self.gateway.get_knowledge(self.actors[READER], "still-a-candidate")
        self.assertEqual([event for event in self._events() if event.get("action") == "used"], [])

    def test_search_surfacing_is_counted_without_rewriting_records(self) -> None:
        """Counted, but a hit is not a read - and surfacing must not touch the store."""
        stored = next((self.root / "knowledge").rglob("usage-demo*.json"))
        before = stored.read_bytes()
        self.gateway.search(self.actors[READER], "knowledge", "usage-demo")
        usage = self.gateway.usage_summary()
        self.assertEqual(usage["surfaced"]["knowledge/usage-demo"]["count"], 1)
        self.assertEqual(usage["explicit"], {}, "surfacing is not retrieval")
        self.assertEqual(stored.read_bytes(), before, "a search must not rewrite what it finds")

    def test_repeated_retrieval_accumulates(self) -> None:
        for _ in range(3):
            self.gateway.get_knowledge(self.actors[READER], "usage-demo")
        entry = self.gateway.usage_summary()["explicit"]["knowledge/usage-demo"]
        self.assertEqual(entry["count"], 3)
        self.assertIsNotNone(entry["last_at"])


class ReviewFlagTests(unittest.TestCase):
    """Flags decide what a human looks at. They never delete anything."""

    def test_a_hand_approved_record_nobody_read_is_flagged(self) -> None:
        self.assertIn(SURFACED_ONLY, review_flags(released(), {}, {}))
        self.assertNotIn(NEVER_USED, review_flags(released(), {}, {}))

    def test_an_auto_admitted_record_nobody_read_is_flagged_harder(self) -> None:
        artifact = released(metadata={"permissions": ["read-only"],
                                      "auto_admission": {"auto_approve": True, "tier": "T2"}})
        flags = review_flags(artifact, {}, {})
        self.assertIn(NEVER_USED, flags)
        self.assertIn(UNVERIFIED, flags)

    def test_a_record_found_constantly_but_never_read_is_flagged(self) -> None:
        artifact = released()
        explicit = {"knowledge/usage-demo": {"count": 1, "last_at": "2026-09-19T00:00:00Z"}}
        surfaced = {"knowledge/usage-demo": {"count": 40, "last_surfaced_at": "2026-09-19T00:00:00Z"}}
        self.assertIn(SURFACED_ONLY, review_flags(artifact, explicit, surfaced))

    def test_a_used_record_inside_its_horizon_is_not_flagged(self) -> None:
        fresh = released()
        explicit = {"knowledge/usage-demo": {"count": 2, "last_at": "2026-09-19T00:00:00Z"}}
        self.assertEqual(review_flags(fresh, explicit, {}), [])

    def test_the_review_horizon_is_enforced(self) -> None:
        artifact = released(verified_at=(datetime.now(timezone.utc) - timedelta(days=10)).isoformat())
        explicit = {"knowledge/usage-demo": {"count": 1, "last_at": "2026-09-19T00:00:00Z"}}
        self.assertIn(REVIEW_DUE, review_flags(artifact, explicit, {}))

    def test_unreleased_artifacts_are_not_reviewed(self) -> None:
        self.assertEqual(review_flags(note(status="candidate"), {}, {}), [])
        self.assertEqual(review_flags(note(status="archived"), {}, {}), [])

    def test_days_since_handles_the_formats_we_write(self) -> None:
        now = datetime(2026, 9, 20, 12, 0, tzinfo=timezone.utc)
        self.assertEqual(days_since("2026-09-19T12:00:00Z", now), 1.0)
        self.assertEqual(days_since("2026-09-19T12:00:00+00:00", now), 1.0)
        self.assertIsNone(days_since(None, now))
        self.assertIsNone(days_since("not-a-timestamp", now))


if __name__ == "__main__":
    unittest.main(verbosity=2)
