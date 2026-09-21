"""Identity is a token, not a name.

The previous scheme mapped the presented token straight to the identity *name*, so
anyone who could reach the listener could be `local-human` - which holds approve,
withdraw:any and rollback. These tests pin the replacement: minted tokens resolve,
unknown tokens are refused, and the name shortcut exists only while the migration
switch is on.
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

os.environ.setdefault("INTELLIGENCE_EMBED_DISABLE", "1")

from AI_Platform.intelligence.experimental.api.server import ExperimentalAPI, default_actors  # noqa: E402
from AI_Platform.intelligence.gateway.errors import AuthorizationError  # noqa: E402


class IdentityTokenTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        (self.root / "qa").mkdir(parents=True, exist_ok=True)
        self.token = "minted-secret-token-value"
        (self.root / "qa" / "identity_tokens.json").write_text(json.dumps({
            "scheme": "sha256-v1",
            "tokens": {"local-hermes": "sha256:" + hashlib.sha256(self.token.encode()).hexdigest()},
        }), encoding="utf-8")
        self.api = ExperimentalAPI(self.root)

    def tearDown(self) -> None:
        self._tmp.cleanup()
        os.environ.pop("INTELLIGENCE_ALLOW_LEGACY_NAMES", None)

    def test_a_minted_token_resolves_to_its_identity(self) -> None:
        self.assertEqual(self.api.actor_for_token(self.token).actor_id, "local-hermes")

    def test_an_unknown_token_is_refused(self) -> None:
        with self.assertRaises(AuthorizationError):
            self.api.actor_for_token("not-a-real-token")

    def test_a_missing_token_is_refused(self) -> None:
        with self.assertRaises(AuthorizationError):
            self.api.actor_for_token(None)

    def test_the_name_shortcut_only_exists_while_the_migration_switch_allows_it(self) -> None:
        """Flipping the switch is what ends the vulnerability; it must actually work."""
        os.environ["INTELLIGENCE_ALLOW_LEGACY_NAMES"] = "1"
        self.assertEqual(self.api.actor_for_token("local-human").actor_id, "local-human")
        os.environ["INTELLIGENCE_ALLOW_LEGACY_NAMES"] = "0"
        with self.assertRaises(AuthorizationError):
            self.api.actor_for_token("local-human")

    def test_a_name_that_is_not_an_identity_is_never_accepted(self) -> None:
        os.environ["INTELLIGENCE_ALLOW_LEGACY_NAMES"] = "1"
        with self.assertRaises(AuthorizationError):
            self.api.actor_for_token("admin")

    def test_every_identity_can_be_addressed_by_a_minted_token(self) -> None:
        """Minting must cover the whole table, or flipping the switch locks someone out."""
        tokens = {actor: f"token-for-{actor}" for actor in default_actors()}
        (self.root / "qa" / "identity_tokens.json").write_text(json.dumps({
            "scheme": "sha256-v1",
            "tokens": {actor: "sha256:" + hashlib.sha256(value.encode()).hexdigest()
                       for actor, value in tokens.items()},
        }), encoding="utf-8")
        api = ExperimentalAPI(self.root)  # fresh process, fresh token index
        for actor, value in tokens.items():
            self.assertEqual(api.actor_for_token(value).actor_id, actor)


if __name__ == "__main__":
    unittest.main(verbosity=2)
