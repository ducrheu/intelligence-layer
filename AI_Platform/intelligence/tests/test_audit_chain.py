"""The audit log's hash chain: does one rewritten line get noticed?

Admission tests prove an artifact was allowed in. These prove the *record of who did
what* cannot be quietly edited - which matters because ownership, the trust list and the
retraction rule are all read back out of that log, not out of the artifact.

The verifier is driven against deliberately broken fixtures. A checker that only ever
sees clean input is not evidence, so each way of breaking the chain gets a test that
asserts the checker notices.
"""
from __future__ import annotations

import json
import sys
import tempfile
import threading
import unittest
from pathlib import Path

# Locate the checkout root by looking for the package itself instead of counting parent
# directories: a fixed depth breaks on a clone, a worktree, or a CI checkout, and the
# failure then looks like a missing package rather than a wrong path.
_ROOT = next(path for path in Path(__file__).resolve().parents if (path / "AI_Platform").is_dir())
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import os  # noqa: E402

# Retrieval runs lexical-only in unit tests: fast, deterministic, and independent of
# whether a model server happens to be running on the machine.
os.environ.setdefault("INTELLIGENCE_EMBED_DISABLE", "1")

from AI_Platform.intelligence.experimental.api.server import default_actors  # noqa: E402
from AI_Platform.intelligence.gateway.audit_chain import (  # noqa: E402
    GENESIS, append_audit_record, chain_digest, previous_hash, verify,
)
from AI_Platform.intelligence.gateway.service import IntelligenceGateway  # noqa: E402


def record(index: int) -> dict:
    return {
        "timestamp": f"2026-09-23T00:00:{index:02d}Z",
        "actor": "local-agent",
        "role": "agent",
        "action": "submit_candidate",
        "artifact_id": f"artifact-{index}",
        "result": "success",
        "correlation_id": f"corr-{index}",
    }


class AuditChainTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.path = Path(self._tmp.name) / "audit.jsonl"

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def append(self, count: int) -> None:
        for index in range(count):
            append_audit_record(self.path, record(index))

    def lines(self) -> list[str]:
        return self.path.read_text(encoding="utf-8").splitlines()

    def rewrite(self, lines: list[str]) -> None:
        self.path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    # --- the property that has to hold ------------------------------------------

    def test_clean_log_verifies_and_links_every_record(self) -> None:
        self.append(3)
        records = [json.loads(line) for line in self.lines()]
        self.assertEqual(records[0]["prev_hash"], GENESIS)
        self.assertNotEqual(records[0]["hash"], GENESIS)
        for earlier, later in zip(records, records[1:]):
            self.assertEqual(later["prev_hash"], earlier["hash"])
        report = verify(self.path)
        self.assertTrue(report["ok"], report)
        self.assertEqual(report["chained"], 3)
        self.assertEqual(report["lines"], 3)

    def test_digest_covers_the_record_and_its_predecessor(self) -> None:
        first = append_audit_record(self.path, record(1))
        second = append_audit_record(self.path, record(2))
        self.assertEqual(chain_digest(second), second["hash"])
        tampered = dict(second, result="denied")
        self.assertNotEqual(chain_digest(tampered), second["hash"])
        # Swapping in a different predecessor must change the digest as well, which is
        # what makes a reorder detectable rather than merely suspicious.
        self.assertNotEqual(chain_digest(dict(second, prev_hash=first["hash"] + "x")), second["hash"])

    # --- the ways it gets broken ------------------------------------------------

    def test_edited_line_is_detected(self) -> None:
        self.append(4)
        lines = self.lines()
        edited = json.loads(lines[2])
        edited["result"] = "denied"  # flip a governance outcome, keep the old hash
        lines[2] = json.dumps(edited, ensure_ascii=True)
        self.rewrite(lines)
        report = verify(self.path)
        self.assertFalse(report["ok"], report)
        self.assertEqual(report["first_bad_line"], 3)

    def test_deleted_line_is_detected(self) -> None:
        self.append(4)
        lines = self.lines()
        del lines[1]
        self.rewrite(lines)
        report = verify(self.path)
        self.assertFalse(report["ok"], report)
        self.assertEqual(report["first_bad_line"], 2)

    def test_reordered_lines_are_detected(self) -> None:
        self.append(4)
        lines = self.lines()
        lines[1], lines[2] = lines[2], lines[1]
        self.rewrite(lines)
        report = verify(self.path)
        self.assertFalse(report["ok"], report)
        self.assertEqual(report["first_bad_line"], 2)

    def test_unparseable_line_is_detected(self) -> None:
        self.append(3)
        lines = self.lines()
        lines.insert(1, "{ this is not json")
        self.rewrite(lines)
        report = verify(self.path)
        self.assertFalse(report["ok"], report)
        self.assertEqual(report["first_bad_line"], 2)

    def test_empty_log_is_not_reported_as_verified(self) -> None:
        report = verify(self.path)
        self.assertFalse(report["ok"])
        self.assertIn("no audit log", report["reason"])

    # --- the log's own history is covered, not grandfathered in ------------------

    def test_pre_chain_prefix_is_anchored_and_editing_it_is_detected(self) -> None:
        """A log written before chaining existed must not become an unverifiable gap."""
        legacy = json.dumps({"timestamp": "old", "actor": "local-agent", "action": "submit_candidate"}, ensure_ascii=True)
        self.path.write_text(legacy + "\n", encoding="utf-8")
        first = append_audit_record(self.path, record(1))
        self.assertTrue(first["prev_hash"].startswith("sha256:"), first["prev_hash"])
        self.assertTrue(verify(self.path)["ok"])

        edited = json.dumps({"timestamp": "old", "actor": "local-human", "action": "approve"}, ensure_ascii=True)
        self.path.write_text(edited + "\n" + json.dumps(first, ensure_ascii=True) + "\n", encoding="utf-8")
        report = verify(self.path)
        self.assertFalse(report["ok"], report)
        # Reported at the anchor, not at the edited line: an untagged legacy line carries
        # no digest of its own, so the first thing that can speak about it is the record
        # that anchored it. The message has to name the anchor for that reason.
        self.assertEqual(report["first_bad_line"], 2)
        self.assertIn("history before it", report["reason"])

    def test_previous_hash_on_a_pure_legacy_log_is_a_digest_not_genesis(self) -> None:
        self.path.write_text('{"action": "x"}\n', encoding="utf-8")
        self.assertTrue(previous_hash(self.path).startswith("sha256:"))

    def test_truncated_tail_is_not_detectable_without_the_anchor(self) -> None:
        """Pinned limitation, not an oversight.

        A shorter chain is still a valid chain: nothing inside the file can say how long
        it used to be. The daily anchor job (qa/audit-anchor.json, committed) is the only
        thing that can. Do not "fix" verify() to reject this - it would reject a freshly
        created log too, and it cannot know without the anchor.
        """
        self.append(4)
        lines = self.lines()
        self.rewrite(lines[:-1])
        report = verify(self.path)
        self.assertTrue(report["ok"], report)
        self.assertEqual(report["chained"], 3)

    # --- the real writer, not a stand-in ----------------------------------------

    def test_gateway_audit_writes_a_chained_record(self) -> None:
        store = Path(self._tmp.name) / "store"
        store.mkdir()
        state = Path(self._tmp.name) / "state"
        state.mkdir()
        previous_state = os.environ.get("INTELLIGENCE_STATE")
        os.environ["INTELLIGENCE_STATE"] = str(state)
        try:
            gateway = IntelligenceGateway(store)
            gateway._audit(default_actors()["local-agent"], "search_knowledge", None, "success")
            gateway._audit(default_actors()["local-agent"], "get_knowledge", "artifact-1", "success", kind="knowledge")
        finally:
            if previous_state is None:
                os.environ.pop("INTELLIGENCE_STATE", None)
            else:
                os.environ["INTELLIGENCE_STATE"] = previous_state

        log = state / "audit.jsonl"
        records = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
        self.assertEqual(len(records), 2)
        self.assertEqual(records[0]["prev_hash"], GENESIS)
        self.assertEqual(records[1]["prev_hash"], records[0]["hash"])
        report = verify(log)
        self.assertTrue(report["ok"], report)

    def test_concurrent_writers_do_not_fork_the_chain(self) -> None:
        """The lock is load-bearing: read-tail-then-append is a race without it.

        Separate processes are the real case (the service plus the CLI tools that import
        the gateway); threads share a process but still open the log separately, which is
        enough to expose a missing lock.
        """
        errors: list[BaseException] = []

        def worker(offset: int) -> None:
            try:
                for index in range(5):
                    append_audit_record(self.path, record(offset * 100 + index))
            except BaseException as exc:  # noqa: BLE001 - reported through the assertion
                errors.append(exc)

        threads = [threading.Thread(target=worker, args=(n,)) for n in range(6)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertFalse(errors, errors)
        report = verify(self.path)
        self.assertTrue(report["ok"], report)
        self.assertEqual(report["chained"], 30)


if __name__ == "__main__":
    unittest.main(verbosity=2)
