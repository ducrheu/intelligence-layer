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

import json
import tempfile
import unittest
from pathlib import Path

from AI_Platform.intelligence.experimental.api.server import default_actors
from AI_Platform.intelligence.gateway.models import utc_now
from AI_Platform.intelligence.gateway.service import IntelligenceGateway

# Retrieval runs lexical-only in unit tests: fast, deterministic, no model server needed.
os.environ.setdefault("INTELLIGENCE_EMBED_DISABLE", "1")

TRUSTED = "local-hermes-writer"

def note(artifact_id: str) -> dict:
    """A knowledge artifact shaped the way the write surface produces one."""
    now = utc_now()
    return {
        "id": artifact_id,
        "kind": "knowledge",
        "scope": "domain",
        "status": "candidate",
        "version": "1.0.0",
        "title": f"{artifact_id} (store layout regression)",
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


class FlatKindRelocationTests(unittest.TestCase):
    """A status change must move ONE artifact, never its neighbours.

    Flat kinds (knowledge / experience / source) keep every artifact of a status
    in a single directory, so the directory is not the artifact. Relocating by
    moving the directory dragged unrelated siblings into `approved/` and deleted
    the emptied directory - the files then sat at a path their own status does
    not map to, so `load(id, kind, ("validated",))` could no longer find them and
    validate / approve / withdraw failed with "not found".
    """

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.gateway = IntelligenceGateway(self.root, auto_admission="enforce")
        self.actors = default_actors()
        for artifact_id in ("layout-a", "layout-b"):
            self.gateway.submit_candidate(self.actors[TRUSTED], note(artifact_id))

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_approving_one_artifact_leaves_its_neighbour_in_place(self) -> None:
        self.gateway.validate_candidate(self.actors["policy-auto"], "layout-a", "knowledge")
        self.gateway.approve(self.actors["policy-auto"], "layout-a", "knowledge")

        self.assertTrue((self.root / "knowledge" / "approved" / "layout-a.json").is_file(),
                        "the approved artifact must be at the approved path")
        self.assertTrue((self.root / "knowledge" / "candidates" / "layout-b.json").is_file(),
                        "an unrelated candidate must not be swept into approved/")
        self.assertTrue((self.root / "knowledge" / "candidates").is_dir(),
                        "the candidates directory must survive an approval")

    def test_a_neighbour_stays_readable_at_its_own_status(self) -> None:
        self.gateway.validate_candidate(self.actors["policy-auto"], "layout-a", "knowledge")
        self.gateway.approve(self.actors["policy-auto"], "layout-a", "knowledge")

        neighbour = self.gateway.store.load("layout-b", "knowledge", ("candidate",))
        self.assertEqual(neighbour["status"], "candidate")

    def test_a_validated_artifact_is_readable_at_its_own_status(self) -> None:
        self.gateway.validate_candidate(self.actors["policy-auto"], "layout-a", "knowledge")

        stored = self.gateway.store.load("layout-a", "knowledge", ("validated",))
        self.assertEqual(stored["status"], "validated")
        self.assertTrue((self.root / "knowledge" / "candidates" / "layout-a.json").is_file(),
                        "candidate/validated share the candidates directory by design")


class CheckedInStoreLayoutTests(unittest.TestCase):
    """The repository's own store must satisfy the invariant its loader relies on.

    Every artifact file sits where `_path()` says its status belongs. A checker
    is the only thing that keeps a hand edit, a seed import or a future relocation
    bug from leaving a file at a path its status cannot be loaded from.
    """

    def test_every_artifact_file_sits_where_its_status_says(self) -> None:
        root = _ROOT / "AI_Platform" / "intelligence"
        gateway = IntelligenceGateway(root)
        files: list[Path] = sorted((root / "skills").glob("*/*/manifest.json"))
        for kind in ("knowledge", "experience", "sources"):
            if (root / kind).is_dir():
                files += sorted((root / kind).rglob("*.json"))
        self.assertTrue(files, "the store appears to be empty")

        misplaced = []
        for path in files:
            artifact = json.loads(path.read_text(encoding="utf-8"))
            if gateway.store._path(artifact) != path:
                misplaced.append(f"{path.relative_to(root)} (status={artifact.get('status')})")
        self.assertEqual(misplaced, [],
                         "these files are not at the path their own status maps to: "
                         f"{misplaced}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
