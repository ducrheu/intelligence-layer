from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any


class LegacyFreelanceReadOnlyAdapter:
    """Read-only metadata bridge; never executes or writes the legacy workspace."""

    def __init__(self, root: Path):
        self.root = root.resolve()
        if not self.root.exists():
            raise FileNotFoundError(self.root)

    def _safe_file(self, relative: str) -> Path:
        path = (self.root / relative).resolve()
        if path != self.root and self.root not in path.parents:
            raise ValueError("legacy path escapes configured workspace")
        if not path.is_file():
            raise FileNotFoundError(path)
        return path

    def _read_json(self, relative: str) -> dict[str, Any]:
        return json.loads(self._safe_file(relative).read_text(encoding="utf-8"))

    @staticmethod
    def _sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    @staticmethod
    def _heading(text: str, fallback: str) -> str:
        match = re.search(r"^#\s+(.+)$", text, re.MULTILINE)
        return match.group(1).strip() if match else fallback

    def list_approved_skills(self) -> list[dict[str, Any]]:
        registry = self._read_json("skills/registry.json")
        results: list[dict[str, Any]] = []
        for item in registry.get("items", []):
            if item.get("status") != "approved":
                continue
            results.append(self._skill_metadata(item))
        return results

    def get_approved_skill(self, skill_name: str) -> dict[str, Any]:
        for item in self.list_approved_skills():
            if item["id"] == skill_name:
                return item
        raise KeyError(f"approved legacy skill not found: {skill_name}")

    def _skill_metadata(self, item: dict[str, Any]) -> dict[str, Any]:
        relative = item["path"]
        path = self._safe_file(relative)
        text = path.read_text(encoding="utf-8")
        approval = self._read_json("skills/approval_history.json")
        matching_events = [event for event in approval.get("events", []) if event.get("skill_id") == item.get("id")]
        return {
            "id": item["id"],
            "kind": "skill",
            "scope": "domain",
            "status": "approved",
            "version": item.get("version"),
            "title": item.get("description", item["id"]),
            "description": item.get("description"),
            "legacy_path": relative,
            "skill_markdown_title": self._heading(text, item["id"]),
            "source_jobs": item.get("source_jobs", []),
            "approval_history": matching_events,
            "regression_test": item.get("approval_basis", {}).get("regression_test"),
            "content_sha256": self._sha256(path),
            "execution_authority": "legacy-freelance-job-runner",
            "adapter_write": False,
        }

    def list_experience(self) -> list[dict[str, Any]]:
        registry_path = self._safe_file("experience/registry.json")
        registry = json.loads(registry_path.read_text(encoding="utf-8"))
        results: list[dict[str, Any]] = []
        known = {item["id"]: item for item in registry.get("items", [])}
        for directory, status in (("accepted", "approved"), ("pending", "candidate")):
            base = self.root / "experience" / directory
            if not base.exists():
                continue
            for path in sorted(base.glob("*.md")):
                relative = path.relative_to(self.root).as_posix()
                artifact_id = path.stem
                item = known.get(artifact_id, {})
                text = path.read_text(encoding="utf-8")
                results.append({
                    "id": artifact_id,
                    "kind": "experience",
                    "scope": "domain",
                    "status": status,
                    "title": item.get("title", self._heading(text, artifact_id)),
                    "legacy_path": relative,
                    "task_type": item.get("task_type", "unknown"),
                    "confidence": item.get("confidence"),
                    "source_jobs": item.get("source_jobs", []),
                    "content_sha256": self._sha256(path),
                    "execution_authority": "legacy-freelance-job-runner",
                    "adapter_write": False,
                })
        return results

    def get_experience(self, experience_id: str) -> dict[str, Any]:
        for item in self.list_experience():
            if item["id"] == experience_id:
                return item
        raise KeyError(f"legacy experience not found: {experience_id}")
