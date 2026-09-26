"""The exposure control: what a borrowed runtime may read, and what happens when the
control itself is broken.

Every case here exists because the failure mode is invisible from the outside. A denylist
that silently does not apply, a file that is missing and reads as "no restrictions", and a
by-id fetch that answers "denied" instead of "not found" all look like a working system
while leaking exactly what the control was added to protect. So each one gets a case that
must trip it - and, where a broader rule would break the owner's own reads, a case that
must *not* trip.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

_ROOT = next(path for path in Path(__file__).resolve().parents if (path / "AI_Platform").is_dir())
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

os.environ.setdefault("INTELLIGENCE_EMBED_DISABLE", "1")

from AI_Platform.intelligence.experimental.api.server import default_actors  # noqa: E402
from AI_Platform.intelligence.gateway.errors import ArtifactNotFoundError  # noqa: E402
from AI_Platform.intelligence.gateway.exposure import (  # noqa: E402
    DENYLIST_PATH, denied_ids, normalize,
)
from AI_Platform.intelligence.gateway.service import IntelligenceGateway  # noqa: E402

GUEST = "local-guest-friend"
OWNER = "local-hermes"
SECRET_ID = "the-shop-refund-postmortem"
PUBLIC_ID = "generic-excel-integrity"
SECRET_TITLE = "闲鱼小店第一笔成交被退款"
PUBLIC_TITLE = "Excel transformations require source integrity"


def artifact(artifact_id: str, title: str, content: str, **overrides) -> dict:
    now = datetime.now(timezone.utc).isoformat()
    body = {
        "id": artifact_id,
        "kind": "knowledge",
        "scope": "domain",
        "status": "approved",
        "version": "1.0.0",
        "title": title,
        "content": content,
        "created_by": "local-agent",
        "created_at": now,
        "updated_at": now,
        "source": [{"type": "test", "retrieved_at": now}],
        "provenance": [{"type": "test", "created_at": now}],
        "verified": True,
        "verified_by": "local-human",
        "verified_at": now,
        "tests": [],
        "evidence": [],
        "applies_to": ["test"],
        "compatibility": ["test"],
    }
    body.update(overrides)
    return body


class ExposureFixture(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name) / "store"
        self.root.mkdir()
        state = Path(self._tmp.name) / "state"
        state.mkdir()
        self._previous_state = os.environ.get("INTELLIGENCE_STATE")
        os.environ["INTELLIGENCE_STATE"] = str(state)
        self.gateway = IntelligenceGateway(self.root)
        self.actors = default_actors()
        self._put(SECRET_ID, SECRET_TITLE, "买家申请退款，金额 ¥2.90，这是小主人的店铺复盘")
        self._put(PUBLIC_ID, PUBLIC_TITLE, "never transform a spreadsheet without keeping the source")

    def tearDown(self) -> None:
        if self._previous_state is None:
            os.environ.pop("INTELLIGENCE_STATE", None)
        else:
            os.environ["INTELLIGENCE_STATE"] = self._previous_state
        self._tmp.cleanup()

    # ── helpers ────────────────────────────────────────────────────────────────────
    def _put(self, artifact_id: str, title: str, content: str, **overrides) -> None:
        """Write an approved artifact straight into the store layout.

        Going through submit -> validate -> approve would test the lifecycle instead of
        the read side, and the read side is what a denylist has to hold.
        """
        directory = self.gateway.store.root / self.gateway.store._kind_dir("knowledge") / "approved"
        directory.mkdir(parents=True, exist_ok=True)
        (directory / f"{artifact_id}.json").write_text(
            json.dumps(artifact(artifact_id, title, content, **overrides), ensure_ascii=False),
            encoding="utf-8")

    def deny(self, *ids: str, identity: str = GUEST) -> None:
        path = self.root / DENYLIST_PATH
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({identity: list(ids)}, ensure_ascii=False), encoding="utf-8")

    def search(self, query: str, actor: str = GUEST, **kwargs) -> list[dict]:
        return self.gateway.search(self.actors[actor], "knowledge", query,
                                   kwargs.get("scope"), 5, 20000, 2000)

    def ids(self, query: str, actor: str = GUEST, **kwargs) -> list[str]:
        return [item["id"] for item in self.search(query, actor, **kwargs)]

    def audit_results(self) -> list[str]:
        log = Path(os.environ["INTELLIGENCE_STATE"]) / "audit.jsonl"
        if not log.exists():
            return []
        return [json.loads(line)["result"]
                for line in log.read_text(encoding="utf-8").splitlines() if line.strip()]


class DeniedArtifactIsNotACandidateTest(ExposureFixture):
    """The predicate, not the response, is where the filtering has to happen."""

    def test_search_by_its_own_title_does_not_surface_a_denied_record(self) -> None:
        self.deny(SECRET_ID)
        # The query is the denied record's exact title: if the filter were applied after
        # retrieval (or not at all) this is the query that would find it.
        self.assertNotIn(SECRET_ID, self.ids(SECRET_TITLE))
        self.assertIn(PUBLIC_ID, self.ids(PUBLIC_TITLE))  # the same call still works

    def test_the_denied_record_is_gone_for_every_query_not_just_its_title(self) -> None:
        self.deny(SECRET_ID)
        for query in ("退款", "闲鱼", "小主人", "店铺复盘"):
            self.assertNotIn(SECRET_ID, self.ids(query), f"leaked for query {query!r}")

    def test_a_wider_scope_parameter_cannot_widen_what_the_identity_may_read(self) -> None:
        """OWASP API1:2023 (BOLA): the visible set must come from the identity, never from
        a parameter the caller controls."""
        self.deny(SECRET_ID)
        for scope in (None, "shared", "domain", "local", "project"):
            self.assertNotIn(SECRET_ID, self.ids(SECRET_TITLE, scope=scope),
                             f"scope={scope!r} widened access")

    def test_the_owner_still_reads_what_the_external_identity_may_not(self) -> None:
        self.deny(SECRET_ID)
        self.assertIn(SECRET_ID, self.ids(SECRET_TITLE, actor=OWNER))

    def test_a_kind_prefixed_entry_also_denies(self) -> None:
        """Hand-edited lists get written both ways; ignoring `kind/id` would under-deny."""
        self.deny(f"knowledge/{SECRET_ID}")
        self.assertNotIn(SECRET_ID, self.ids(SECRET_TITLE))


class DeniedFetchLooksLikeAMissTest(ExposureFixture):
    def test_by_id_fetch_is_refused(self) -> None:
        self.deny(SECRET_ID)
        with self.assertRaises(ArtifactNotFoundError):
            self.gateway.get_knowledge(self.actors[GUEST], SECRET_ID)

    def test_a_refusal_is_indistinguishable_from_a_missing_id(self) -> None:
        """Otherwise a caller maps the corpus by probing ids: one answer means "exists but
        denied", the other means "does not exist"."""
        self.deny(SECRET_ID)
        with self.assertRaises(ArtifactNotFoundError):
            self.gateway.get_knowledge(self.actors[GUEST], SECRET_ID)
        self.gateway.get_knowledge(self.actors[OWNER], PUBLIC_ID)
        with self.assertRaises(ArtifactNotFoundError):
            self.gateway.get_knowledge(self.actors[GUEST], "never-existed")
        self.assertEqual(self.audit_results().count("not_found"), 2)

    def test_the_owner_can_still_fetch_it_by_id(self) -> None:
        self.deny(SECRET_ID)
        self.assertEqual(SECRET_ID, self.gateway.get_knowledge(self.actors[OWNER], SECRET_ID)["id"])


class UseFailsClosedTest(ExposureFixture):
    """A control that cannot be evaluated must not read as "no restrictions"."""

    def test_absent_denylist_means_an_external_identity_reads_nothing(self) -> None:
        self.assertNotIn(SECRET_ID, self.ids(SECRET_TITLE))
        self.assertNotIn(PUBLIC_ID, self.ids(PUBLIC_TITLE))

    def test_absent_denylist_leaves_the_owner_unaffected(self) -> None:
        self.assertIn(PUBLIC_ID, self.ids(PUBLIC_TITLE, actor=OWNER))

    def test_malformed_denylist_means_an_external_identity_reads_nothing(self) -> None:
        path = self.root / DENYLIST_PATH
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{ this is not json", encoding="utf-8")
        self.assertEqual(denied_ids(self.root, self.actors[GUEST]), None)
        self.assertNotIn(PUBLIC_ID, self.ids(PUBLIC_TITLE))

    def test_an_external_identity_with_no_entry_reads_nothing(self) -> None:
        """No entry is not the same as "nothing denied" - guessing that way is the leak."""
        self.deny(SECRET_ID, identity="some-other-guest")
        self.assertEqual(denied_ids(self.root, self.actors[GUEST]), None)
        self.assertNotIn(PUBLIC_ID, self.ids(PUBLIC_TITLE))

    def test_a_denylist_entry_that_is_not_a_list_fails_closed(self) -> None:
        path = self.root / DENYLIST_PATH
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({GUEST: "not-a-list"}), encoding="utf-8")
        self.assertNotIn(PUBLIC_ID, self.ids(PUBLIC_TITLE))

    def test_a_malformed_denylist_cannot_lift_restrictions_for_the_owner(self) -> None:
        path = self.root / DENYLIST_PATH
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("garbage", encoding="utf-8")
        self.assertIn(PUBLIC_ID, self.ids(PUBLIC_TITLE, actor=OWNER))


class ReferencesDoNotLeakTest(ExposureFixture):
    """A reference is an id in plain sight.

    Found on the real corpus: a visible record's `source` entry referenced a withheld
    record by id (`experience:exp-wsl-huyi-quant-data-fabric-...`), so an unscrubbed
    reference list hands back the existence - and the subject - of what was withheld.
    """

    def setUp(self) -> None:
        super().setUp()
        # PUBLIC now cites SECRET: body is clean, the reference is not.
        self._put(PUBLIC_ID, PUBLIC_TITLE, "never transform a spreadsheet without keeping the source",
                  source=[{"type": "agent_artifact", "ref": f"knowledge:{SECRET_ID}",
                           "retrieved_at": "2026-09-01T00:00:00Z"}],
                  provenance=[{"type": "test", "created_at": "2026-09-01T00:00:00Z"},
                              {"type": "agent_artifact", "ref": f"experience:{SECRET_ID}",
                               "created_at": "2026-09-01T00:00:00Z"}])

    def test_search_result_carries_no_reference_to_a_withheld_record(self) -> None:
        self.deny(SECRET_ID)
        item = next(i for i in self.search(PUBLIC_TITLE, actor=GUEST) if i["id"] == PUBLIC_ID)
        self.assertNotIn(SECRET_ID, json.dumps(item, ensure_ascii=False))
        # The citing entry is gone; the plain provenance entry is not collateral damage.
        self.assertEqual(len(item["provenance"]), 1)
        self.assertEqual(item["provenance"][0]["type"], "test")

    def test_by_id_fetch_scrubs_both_source_and_provenance(self) -> None:
        self.deny(SECRET_ID)
        artifact = self.gateway.get_knowledge(self.actors[GUEST], PUBLIC_ID)
        self.assertEqual(artifact["source"], [])          # its only entry was the reference
        self.assertEqual(len(artifact["provenance"]), 1)  # reference dropped, plain entry kept
        self.assertNotIn(SECRET_ID, json.dumps(artifact, ensure_ascii=False))

    def test_the_owner_still_sees_the_references(self) -> None:
        self.deny(SECRET_ID)
        artifact = self.gateway.get_knowledge(self.actors[OWNER], PUBLIC_ID)
        self.assertEqual(len(artifact["source"]), 1)
        self.assertEqual(len(artifact["provenance"]), 2)

    def test_a_clean_reference_survives(self) -> None:
        """Scrubbing must not turn into removing provenance wholesale: with nothing
        matching the denylist, both entries stay."""
        self.deny("some-other-record")
        item = next(i for i in self.search(PUBLIC_TITLE, actor=GUEST) if i["id"] == PUBLIC_ID)
        self.assertEqual(len(item["provenance"]), 2)

    def test_bare_id_and_kind_prefixed_references_both_scrub(self) -> None:
        self._put(PUBLIC_ID, PUBLIC_TITLE, "body",
                  source=[{"ref": SECRET_ID}, {"ref": f"experience:{SECRET_ID}"}],
                  provenance=[])
        self.deny(SECRET_ID)
        artifact = self.gateway.get_knowledge(self.actors[GUEST], PUBLIC_ID)
        self.assertEqual(artifact["source"], [])

    def test_deny_all_also_strips_references(self) -> None:
        artifact = self.gateway.get_knowledge(self.actors[OWNER], PUBLIC_ID)
        self.assertEqual(len(artifact["source"]), 1)   # owner unaffected by deny-all
        with self.assertRaises(ArtifactNotFoundError):
            self.gateway.get_knowledge(self.actors[GUEST], PUBLIC_ID)


class WiringTest(ExposureFixture):
    def test_the_guest_identity_exists_and_is_read_only(self) -> None:
        guest = self.actors[GUEST]
        self.assertTrue(guest.external)
        self.assertEqual(guest.scopes, frozenset({"read:approved"}))
        for scope in ("write:candidate", "approve", "validate:candidate",
                      "read:candidate", "read:governance-metadata", "read:candidate"):
            self.assertNotIn(scope, guest.scopes)

    def test_only_the_guest_identity_is_marked_external(self) -> None:
        self.assertEqual({a.actor_id for a in self.actors.values() if a.external}, {GUEST})

    def test_normalize_accepts_both_shapes(self) -> None:
        self.assertEqual(normalize("knowledge/abc"), "abc")
        self.assertEqual(normalize(" abc "), "abc")


if __name__ == "__main__":
    unittest.main(verbosity=2)
