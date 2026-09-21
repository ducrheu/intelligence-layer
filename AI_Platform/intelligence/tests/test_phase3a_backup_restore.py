from __future__ import annotations

import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from AI_Platform.intelligence.experimental.backup import (
    BackupError,
    create_backup,
    damage_copy,
    restore_backup,
    verify_backup,
)


ROOT = Path("AI_Platform/intelligence")


class Phase3ABackupRestoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.work = Path(self.temp.name)
        self.source = self.work / "intelligence"
        self.source.mkdir()
        for directory in ("schemas", "knowledge/approved", "knowledge/candidates", "experience/approved", "skills/approved/demo", "sources/approved", "qa", "gateway"):
            (self.source / directory).mkdir(parents=True, exist_ok=True)
        (self.source / "schemas" / "artifact.schema.json").write_text('{"schema":"phase3a"}\n', encoding="utf-8")
        (self.source / "knowledge" / "approved" / "approved.json").write_text('{"status":"approved","verified":true}\n', encoding="utf-8")
        (self.source / "knowledge" / "candidates" / "candidate.json").write_text('{"status":"validated","verified":false}\n', encoding="utf-8")
        (self.source / "experience" / "approved" / "experience.json").write_text('{"status":"approved"}\n', encoding="utf-8")
        (self.source / "skills" / "approved" / "demo" / "manifest.json").write_text('{"status":"approved"}\n', encoding="utf-8")
        (self.source / "sources" / "approved" / "source.json").write_text('{"status":"approved"}\n', encoding="utf-8")
        (self.source / "qa" / "audit.jsonl").write_text('{"action":"read","artifact_id":"approved"}\n', encoding="utf-8")
        (self.source / "gateway" / "policy.txt").write_text("approved reads only\n", encoding="utf-8")

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_backup_manifest_integrity_and_restore(self) -> None:
        backup = self.work / "backup.zip"
        manifest = create_backup(self.source, backup)
        verified = verify_backup(backup)
        self.assertEqual(manifest["file_count"], 8)
        self.assertEqual(verified["file_count"], 8)
        destination = self.work / "restored"
        result = restore_backup(backup, destination)
        self.assertTrue(result["restored"]["byte_exact"])
        self.assertEqual(result["restored"]["file_count"], 8)
        self.assertEqual(
            (destination / "knowledge" / "approved" / "approved.json").read_bytes(),
            (self.source / "knowledge" / "approved" / "approved.json").read_bytes(),
        )

    def test_restore_drill_recovers_damage_in_disposable_copy(self) -> None:
        backup = self.work / "backup.zip"
        manifest = create_backup(self.source, backup)
        disposable = self.work / "disposable"
        restore_backup(backup, disposable)
        damage_copy(disposable)
        self.assertFalse((disposable / "sources").exists())
        result = restore_backup(backup, disposable)
        self.assertTrue(result["restored"]["byte_exact"])
        self.assertTrue((disposable / "sources" / "approved" / "source.json").exists())
        self.assertTrue((disposable / "knowledge" / "approved" / "approved.json").read_text(encoding="utf-8").startswith("{\"status\":\"approved\""))

    def test_backup_excludes_cache_and_rejects_secret_file(self) -> None:
        (self.source / "gateway" / "__pycache__").mkdir()
        (self.source / "gateway" / "__pycache__" / "x.pyc").write_bytes(b"cache")
        backup = self.work / "backup.zip"
        manifest = create_backup(self.source, backup)
        self.assertNotIn("gateway/__pycache__/x.pyc", {item["path"] for item in manifest["files"]})
        (self.source / "gateway" / "api_token.txt").write_text("TOKEN=secret\n", encoding="utf-8")
        with self.assertRaises(BackupError):
            create_backup(self.source, self.work / "secret.zip")

    def test_backup_manifest_rejects_tampering(self) -> None:
        backup = self.work / "backup.zip"
        create_backup(self.source, backup)
        tampered = self.work / "tampered.zip"
        with zipfile.ZipFile(backup, "r") as source, zipfile.ZipFile(tampered, "w") as target:
            for item in source.infolist():
                data = source.read(item.filename)
                if item.filename == "knowledge/approved/approved.json":
                    data = b'{"status":"changed"}\n'
                target.writestr(item, data)
        with self.assertRaises(BackupError):
            verify_backup(tampered)

    def test_backup_and_restore_boundaries_are_enforced(self) -> None:
        with self.assertRaises(BackupError):
            create_backup(self.source, self.source / "nested-backup.zip")
        backup = self.work / "backup.zip"
        create_backup(self.source, backup)
        with zipfile.ZipFile(backup, "a") as archive:
            archive.writestr("../outside.txt", b"escape")
        with self.assertRaises(BackupError):
            verify_backup(backup)


if __name__ == "__main__":
    unittest.main()
