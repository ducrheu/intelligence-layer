"""The ingestion gates: content-duplicate reporting, staleness demotion, near-dup scan.

Three checks that share one property worth testing hard: each of them has a way to be
quietly wrong. A duplicate report that never fires, a freshness rule that never fires, and
a scanner that reports nothing all look identical to a working system from the outside - so
each gate gets a fixture that must trip it, and a nearby case that must *not* trip it.
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

_ROOT = next(path for path in Path(__file__).resolve().parents if (path / "AI_Platform").is_dir())
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import os  # noqa: E402

os.environ.setdefault("INTELLIGENCE_EMBED_DISABLE", "1")

from AI_Platform.intelligence.experimental.api.server import default_actors  # noqa: E402
from AI_Platform.intelligence.gateway.errors import ArtifactValidationError  # noqa: E402
from AI_Platform.intelligence.gateway.near_duplicate import scan  # noqa: E402
from AI_Platform.intelligence.gateway.service import IntelligenceGateway  # noqa: E402
from AI_Platform.intelligence.gateway.telemetry import (  # noqa: E402
    EXPIRED, FRESH, REVIEW_DUE, freshness, review_flags,
)

WRITER = "local-agent"
READER = "local-hermes"


def artifact(artifact_id: str, content: str, **overrides) -> dict:
    now = datetime.now(timezone.utc).isoformat()
    body = {
        "id": artifact_id,
        "kind": "knowledge",
        "scope": "domain",
        "status": "candidate",
        "version": "1.0.0",
        "title": f"title for {artifact_id}",
        "content": content,
        "created_by": WRITER,
        "created_at": now,
        "updated_at": now,
        "source": [{"type": "test", "retrieved_at": now}],
        "provenance": [{"type": "test", "created_at": now}],
        "verified": False,
        "tests": [],
        "evidence": [],
        "applies_to": ["test"],
        "compatibility": ["test"],
    }
    body.update(overrides)
    return body


class GatewayFixture(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name) / "store"
        root.mkdir()
        state = Path(self._tmp.name) / "state"
        state.mkdir()
        self._previous_state = os.environ.get("INTELLIGENCE_STATE")
        os.environ["INTELLIGENCE_STATE"] = str(state)
        self.gateway = IntelligenceGateway(root)
        self.actors = default_actors()

    def tearDown(self) -> None:
        if self._previous_state is None:
            os.environ.pop("INTELLIGENCE_STATE", None)
        else:
            os.environ["INTELLIGENCE_STATE"] = self._previous_state
        self._tmp.cleanup()

    def submit(self, artifact_id: str, content: str, **overrides):
        return self.gateway.submit_candidate(
            self.actors[WRITER], artifact(artifact_id, content, **overrides))

    def audit_actions(self) -> list[str]:
        log = Path(os.environ["INTELLIGENCE_STATE"]) / "audit.jsonl"
        return [json.loads(line)["result"] for line in log.read_text(encoding="utf-8").splitlines() if line.strip()]


class ContentDuplicateReportTest(GatewayFixture):
    """Identical text under a second id is *reported*, and the id gate still refuses.

    Both halves are worth pinning: the report is the new behaviour, and the refusal that
    already existed must survive it.
    """

    def test_identical_text_under_a_second_id_is_reported_not_refused(self) -> None:
        self.submit("first-record", "The rule is: always verify the digest before use.")
        result = self.submit("second-record", "The rule is: always verify the digest before use.")
        # Filed (the id is the identity here, not the text) but flagged with the copy the
        # human should compare against.
        self.assertEqual(result["_content_duplicate_of"], "knowledge/first-record")
        self.assertIn("duplicate_content", self.audit_actions())
        self.assertEqual(self.audit_actions().count("success"), 2)

    def test_formatting_differences_do_not_hide_a_duplicate(self) -> None:
        self.submit("first-record", "The rule is: always verify the digest before use.")
        result = self.submit("second-record", "  The   rule is:\n always verify the DIGEST before use. ")
        self.assertEqual(result["_content_duplicate_of"], "knowledge/first-record")

    def test_different_content_carries_no_marker(self) -> None:
        self.submit("first-record", "The rule is: always verify the digest before use.")
        result = self.submit("second-record", "A different rule: name the failing artifact in the error.")
        self.assertNotIn("_content_duplicate_of", result)

    def test_the_same_text_in_another_kind_carries_no_marker(self) -> None:
        """Text is compared within a kind: the same sentence in a knowledge note and in an
        experience note is not a duplicate, and a cross-kind report would train the reader
        to ignore it."""
        self.submit("first-record", "Shared sentence that appears in two kinds.")
        result = self.submit("second-record", "Shared sentence that appears in two kinds.", kind="experience")
        self.assertNotIn("_content_duplicate_of", result)

    def test_the_same_id_with_different_text_is_still_refused(self) -> None:
        """The pre-existing hard gate must survive this change intact."""
        self.submit("first-record", "The original text.")
        with self.assertRaises(ArtifactValidationError):
            self.submit("first-record", "A different text under the same id.")
        self.assertIn("duplicate_conflict", self.audit_actions())


class FreshnessTest(unittest.TestCase):
    def test_expires_at_in_the_past_is_expired(self) -> None:
        past = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
        self.assertEqual(freshness({"expires_at": past}), EXPIRED)

    def test_review_interval_elapsed_is_review_due(self) -> None:
        old = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
        self.assertEqual(freshness({"verified_at": old, "review_interval_days": 7}), REVIEW_DUE)

    def test_interval_not_elapsed_is_fresh(self) -> None:
        recent = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
        self.assertEqual(freshness({"verified_at": recent, "review_interval_days": 7}), FRESH)

    def test_no_interval_means_fresh_not_unknown(self) -> None:
        """Absence of a review policy is not staleness; treating it as such would flag
        every record filed before the field existed."""
        self.assertEqual(freshness({"created_at": "2020-01-01T00:00:00Z"}), FRESH)

    def test_review_flags_reports_staleness(self) -> None:
        old = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
        record = artifact("stale-record", "body", status="approved",
                          verified_at=old, review_interval_days=7)
        self.assertIn(REVIEW_DUE, review_flags(record, {}, {}))

    def test_review_flags_ignores_unpublished_records(self) -> None:
        old = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
        record = artifact("draft-record", "body", verified_at=old, review_interval_days=7)
        self.assertEqual(review_flags(record, {}, {}), [])


class StalenessOrderingTest(GatewayFixture):
    def test_stale_records_move_behind_fresh_ones_without_being_dropped(self) -> None:
        past = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
        ranked = [{"key": "knowledge/stale", "score": 0.9, "why": {}},
                  {"key": "knowledge/fresh", "score": 0.5, "why": {}},
                  {"key": "knowledge/older", "score": 0.4, "why": {}}]
        documents = {
            "knowledge/stale": {"artifact": {"expires_at": past}},
            "knowledge/fresh": {"artifact": {}},
            "knowledge/older": {"artifact": {}},
        }
        ordered = self.gateway._stalest_last(ranked, documents)
        self.assertEqual(len(ordered), 3, "demotion must never drop a hit")
        self.assertEqual([item["key"] for item in ordered][-1], "knowledge/stale")
        self.assertEqual([item["key"] for item in ordered][:2],
                         ["knowledge/fresh", "knowledge/older"], "ranking decides among fresh ones")


class _StubRetriever:
    """Scripted *neighbour* ranks, plus the self-hit a real retriever always returns.

    Modelling the self-hit matters: without it the stub answers every query with the same
    list, so each artifact sees the other at the *other's* scripted rank and a pair gets
    whatever the last query said - which is how this stub's first version reported a pair
    that was below the bar.

    Ranks, not scores: the near-duplicate judgement reads `lexical_rank` / `vector_rank`
    out of the trace, because the fused score is an RRF value whose scale makes every
    cosine-style threshold meaningless.
    """

    def __init__(self, neighbours: dict[str, dict[str, tuple[int, int]]], vector: bool = True) -> None:
        self.neighbours = neighbours
        self.vector = vector

    def rank(self, query, documents, limit=4, embed_budget=8):
        own = next((key for key, value in documents.items()
                    if query.startswith(value["artifact"]["title"])), None)
        self_why = {"lexical_rank": 1}
        if self.vector:
            self_why["vector_rank"] = 1
        ranked = [{"key": own, "score": 0.11, "why": self_why}] if own else []
        for key, (lexical, vector) in self.neighbours.get(own or "", {}).items():
            if key not in documents:
                continue
            why = {"rrf": 0.05}
            if lexical:
                why["lexical_rank"] = lexical
            if vector and self.vector:
                why["vector_rank"] = vector
            ranked.append({"key": key, "score": 0.05, "why": why})
        return ranked[:limit], {}


class _StubGateway:
    def __init__(self, documents: dict, neighbours: dict[str, dict[str, tuple[int, int]]],
                 vector: bool = True) -> None:
        self._documents = documents
        self.retriever = _StubRetriever(neighbours, vector)

    def _search_documents(self, actor, kind, scope):
        return {key: value for key, value in self._documents.items() if key.startswith(f"{kind}/")}


class NearDuplicateScanTest(unittest.TestCase):
    def stub(self, neighbours: dict[str, dict[str, tuple[int, int]]], vector: bool = True) -> _StubGateway:
        documents = {
            "knowledge/alpha": {"artifact": {"id": "alpha", "title": "A", "content": "one"}},
            "knowledge/beta": {"artifact": {"id": "beta", "title": "B", "content": "two"}},
        }
        return _StubGateway(documents, neighbours, vector)

    def test_a_pair_both_retrievers_agree_on_is_reported_once(self) -> None:
        report = scan(self.stub({"knowledge/alpha": {"knowledge/beta": (2, 2)},
                                 "knowledge/beta": {"knowledge/alpha": (2, 2)}}),
                      default_actors()[READER], rank_limit=2)
        found = report["pairs"]
        # Both artifacts see each other; that is one relationship, not two findings.
        self.assertEqual(len(found), 1)
        self.assertEqual((found[0]["left"], found[0]["right"]), ("knowledge/alpha", "knowledge/beta"))
        self.assertEqual((found[0]["lexical_rank"], found[0]["vector_rank"]), (2, 2))
        self.assertTrue(report["vector_retriever_ran"])

    def test_a_single_retriever_match_is_not_reported(self) -> None:
        """Shared vocabulary is the false positive that would make this report ignorable."""
        report = scan(self.stub({"knowledge/alpha": {"knowledge/beta": (1, 0)},
                                 "knowledge/beta": {"knowledge/alpha": (0, 1)}}),
                      default_actors()[READER], rank_limit=2)
        self.assertEqual(report["pairs"], [])

    def test_a_screen_that_could_not_run_says_so(self) -> None:
        """With no vector half the criterion cannot be met at all, so an empty result would
        mean "not checked" while reading exactly like "checked and clean"."""
        report = scan(self.stub({"knowledge/alpha": {"knowledge/beta": (1, 1)},
                                 "knowledge/beta": {"knowledge/alpha": (1, 1)}}, vector=False),
                      default_actors()[READER], rank_limit=2)
        self.assertEqual(report["pairs"], [])
        self.assertFalse(report["vector_retriever_ran"])

    def test_a_distant_neighbour_is_not_reported(self) -> None:
        self.assertEqual(scan(self.stub({"knowledge/alpha": {"knowledge/beta": (9, 9)},
                                         "knowledge/beta": {"knowledge/alpha": (9, 9)}}),
                              default_actors()[READER], rank_limit=2)["pairs"], [])

    def test_an_artifact_never_matches_itself(self) -> None:
        self.assertEqual(scan(self.stub({"knowledge/alpha": {"knowledge/alpha": (1, 1)}}),
                              default_actors()[READER], rank_limit=2)["pairs"], [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
