from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any

from .errors import ArtifactNotFoundError


class GitFileStore:
    """Small file store; Git remains the authority outside this class."""

    # Flat kinds keep every status inside one of two directories.
    _STATUS_DIRS = ("approved", "candidates")

    def __init__(self, root: Path):
        self.root = root

    @staticmethod
    def _status_dir(status: str) -> str:
        return {
            "candidate": "candidates",
            "experimental": "experimental",
            "validated": "validated",
            "approved": "approved",
            "stale": "stale",
            "deprecated": "deprecated",
            "archived": "archived",
        }[status]

    @staticmethod
    def _kind_dir(kind: str) -> str:
        return "sources" if kind == "source" else kind

    def _path(self, artifact: dict[str, Any]) -> Path:
        kind = artifact["kind"]
        status = artifact["status"]
        if kind == "skill" and status == "approved":
            return self.root / "skills" / "approved" / artifact["id"] / "manifest.json"
        if kind == "skill":
            return self.root / "skills" / self._status_dir(status) / artifact["id"] / "manifest.json"
        return self.root / self._kind_dir(kind) / ("approved" if status == "approved" else "candidates") / f"{artifact['id']}.json"

    def save(self, artifact: dict[str, Any]) -> Path:
        path = self._path(artifact)
        # Drop the memo before the write: a reload must never serve the pre-write
        # copy, and the fingerprint check alone cannot tell a rewrite of equal
        # size within the same mtime tick.
        getattr(self, "_manifest_cache", {}).pop(str(path), None)
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, temp_name = tempfile.mkstemp(prefix=".artifact-", suffix=".tmp", dir=path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
                json.dump(artifact, handle, indent=2, ensure_ascii=True)
                handle.write("\n")
            os.replace(temp_name, path)
        finally:
            if os.path.exists(temp_name):
                os.unlink(temp_name)
        return path

    def load(self, artifact_id: str, kind: str, statuses: tuple[str, ...]) -> dict[str, Any]:
        for status in statuses:
            if kind == "skill" and status == "approved":
                path = self.root / "skills" / "approved" / artifact_id / "manifest.json"
            elif kind == "skill":
                path = self.root / "skills" / self._status_dir(status) / artifact_id / "manifest.json"
            else:
                path = self.root / self._kind_dir(kind) / ("approved" if status == "approved" else "candidates") / f"{artifact_id}.json"
            if path.exists():
                artifact = json.loads(path.read_text(encoding="utf-8"))
                # Several statuses share a directory for non-skill kinds, so the
                # file's own status is the authority, not the path it was found at.
                if artifact.get("status") in statuses:
                    return artifact
        raise ArtifactNotFoundError(f"{kind} artifact not found: {artifact_id}")

    def remove(self, artifact: dict[str, Any]) -> None:
        path = self._path(artifact)
        if path.exists():
            path.unlink()
        if artifact.get("kind") == "skill" and path.parent.exists() and not any(path.parent.iterdir()):
            path.parent.rmdir()

    def file_digests(self, paths: list[str]) -> dict[str, str]:
        """sha256 of store-relative files, for re-checking recorded evidence."""
        digests: dict[str, str] = {}
        for relative in paths:
            try:
                data = (self.root / relative).read_bytes()
            except OSError:
                continue
            digests[relative] = "sha256:" + hashlib.sha256(data).hexdigest()
        return digests

    def artifact_dir(self, artifact: dict[str, Any]) -> Path:
        """Directory holding this artifact's manifest and any co-located files."""
        return self._path(artifact).parent

    def _rewrite_recorded_paths(self, old_dir: Path, new_dir: Path, artifact: dict[str, Any]) -> None:
        """Repoint recorded test paths at the directory the artifact lives in now."""
        old_prefix = old_dir.relative_to(self.root).as_posix().rstrip("/") + "/"
        new_prefix = new_dir.relative_to(self.root).as_posix().rstrip("/") + "/"
        for item in artifact.get("tests", []) or []:
            recorded = item.get("path")
            if isinstance(recorded, str) and recorded.startswith(old_prefix):
                item["path"] = new_prefix + recorded[len(old_prefix):]

    def _stranded_dirs(self, artifact_id: str, keep: Path) -> list[Path]:
        """Siblings holding this artifact's payload with no manifest of their own.

        That shape is the fingerprint of a status change made by an older build
        (manifest moved, payload left behind), so relocating collects them.
        A sibling that still has its own manifest is a different artifact
        location and is never touched here.
        """
        found: list[Path] = []
        base = self.root / "skills"
        if not base.is_dir():
            return found
        for status_dir in sorted(path for path in base.iterdir() if path.is_dir()):
            candidate = status_dir / artifact_id
            if candidate == keep or not candidate.is_dir():
                continue
            if (candidate / "manifest.json").exists():
                continue
            if any(path.is_file() for path in candidate.rglob("*")):
                found.append(candidate)
        return found

    def relocate(self, old_artifact: dict[str, Any], new_artifact: dict[str, Any]) -> Path:
        """Move an artifact to its new status location, its files included.

        For a SKILL the status directory IS the artifact, so a status change moves
        the whole directory - manifest, SKILL.md, tests, and any support files -
        and recorded test paths are rewritten to point at where the files actually
        are. `save()` alone moves the manifest only.

        For a flat kind (knowledge / experience / source) the status directory is
        NOT the artifact: every artifact of that status lives in it side by side.
        Moving the directory there drags unrelated siblings along and deletes the
        emptied directory (measured: approving one knowledge artifact swept three
        others into `approved/`, leaving their status fields behind), which then
        makes them unreachable for `load(id, kind, ("validated",))`. Flat kinds
        therefore move the one file and nothing else.
        """
        old_dir = self.artifact_dir(old_artifact)
        new_dir = self.artifact_dir(new_artifact)
        if old_dir == new_dir:
            return self.save(new_artifact)
        if new_artifact.get("kind") != "skill":
            self._rewrite_recorded_paths(old_dir, new_dir, new_artifact)
            old_path = self._path(old_artifact)
            new_path = self._path(new_artifact)
            if old_path != new_path and old_path.exists():
                new_path.parent.mkdir(parents=True, exist_ok=True)
                os.replace(old_path, new_path)
            return self.save(new_artifact)
        self._rewrite_recorded_paths(old_dir, new_dir, new_artifact)
        for source in (old_dir, *self._stranded_dirs(new_artifact["id"], new_dir)):
            if not source.exists():
                continue
            for path in sorted(source.rglob("*")):
                if not path.is_file():
                    continue
                target = new_dir / path.relative_to(source)
                target.parent.mkdir(parents=True, exist_ok=True)
                os.replace(path, target)
            shutil.rmtree(source, ignore_errors=True)
        return self.save(new_artifact)

    def _load_cached(self, path: Path) -> dict[str, Any]:
        """Parse a manifest once per (mtime, size).

        The store lives on a Windows mount: every stat is milliseconds and every
        manifest is now a skill's whole directory index. Re-parsing all of them
        per query cost 3s before any ranking started.
        """
        cache = getattr(self, "_manifest_cache", None)
        if cache is None:
            cache = {}
            self._manifest_cache = cache
        key = str(path)
        try:
            stat = path.stat()
        except OSError:
            cache.pop(key, None)
            raise
        fingerprint = (stat.st_mtime_ns, stat.st_size)
        hit = cache.get(key)
        if hit is not None and hit[0] == fingerprint:
            return hit[1]
        value = json.loads(path.read_text(encoding="utf-8"))
        cache[key] = (fingerprint, value)
        return value

    def iter_kind(self, kind: str):
        """Artifacts of one kind, without touching the other three."""
        base = self.root / {"skill": "skills", "source": "sources"}.get(kind, kind)
        if not base.is_dir():
            return
        if kind == "skill":
            for status_dir in sorted(path for path in base.iterdir() if path.is_dir()):
                for entry in sorted(path for path in status_dir.iterdir() if path.is_dir()):
                    manifest = entry / "manifest.json"
                    if manifest.is_file():
                        yield self._load_cached(manifest)
        else:
            # Flat kinds write every non-approved status into candidates/, so these
            # two directories hold the whole kind.
            for folder_name in self._STATUS_DIRS:
                folder = base / folder_name
                if not folder.is_dir():
                    continue
                for path in sorted(folder.glob("*.json")):
                    yield self._load_cached(path)

    def iter_all(self) -> list[dict[str, Any]]:
        return [artifact for kind in ("knowledge", "experience", "skill", "source")
                for artifact in self.iter_kind(kind)]
