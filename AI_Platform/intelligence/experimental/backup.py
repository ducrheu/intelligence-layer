from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

BACKUP_VERSION = "1.0.0"
INCLUDE_DIRS = ("schemas", "knowledge", "experience", "skills", "sources", "qa", "gateway")
EXCLUDED_PARTS = {"__pycache__", ".pytest_cache", ".venv", "node_modules", "backups"}
SECRET_NAME = re.compile(r"(^|[._-])(secret|credential|password|passwd|token|api[_-]?key|private[_-]?key)([._-]|$)", re.IGNORECASE)
SECRET_CONTENT = re.compile(
    r"(api[_-]?key|access[_-]?token|password|private[_-]?key|authorization\s*:\s*bearer)\s*[:=]",
    re.IGNORECASE,
)


class BackupError(Exception):
    pass


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _is_secret(path: Path, data: bytes) -> bool:
    if any(SECRET_NAME.search(part) for part in path.parts):
        return True
    if len(data) <= 2_000_000:
        try:
            return bool(SECRET_CONTENT.search(data.decode("utf-8")))
        except UnicodeDecodeError:
            return False
    return False


def _iter_files(root: Path) -> list[Path]:
    files: list[Path] = []
    for directory in INCLUDE_DIRS:
        base = (root / directory).resolve()
        if not _is_within(base, root) or not base.exists():
            continue
        for path in base.rglob("*"):
            if not path.is_file():
                continue
            if any(part in EXCLUDED_PARTS for part in path.relative_to(root).parts):
                continue
            if path.is_symlink():
                raise BackupError(f"symlink is not allowed in backup source: {path}")
            files.append(path)
    return sorted(files)


def create_backup(source_root: Path, backup_path: Path) -> dict[str, Any]:
    source_root = source_root.resolve()
    backup_path = backup_path.resolve()
    if not source_root.is_dir():
        raise BackupError(f"source root does not exist: {source_root}")
    if _is_within(backup_path, source_root):
        raise BackupError("backup archive must not be inside source root")
    entries: list[dict[str, Any]] = []
    selected: list[tuple[Path, bytes]] = []
    for path in _iter_files(source_root):
        data = path.read_bytes()
        relative = path.relative_to(source_root).as_posix()
        if _is_secret(path, data):
            raise BackupError(f"refusing to back up possible secret-bearing file: {relative}")
        selected.append((path, data))
        entries.append({
            "path": relative,
            "size": len(data),
            "sha256": hashlib.sha256(data).hexdigest(),
        })
    manifest: dict[str, Any] = {
        "backup_version": BACKUP_VERSION,
        "created_at": utc_now(),
        "source_root": str(source_root),
        "file_count": len(entries),
        "total_bytes": sum(item["size"] for item in entries),
        "files": entries,
    }
    backup_path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=".intelligence-backup-", suffix=".tmp", dir=backup_path.parent)
    os.close(fd)
    try:
        with zipfile.ZipFile(temp_name, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("backup-manifest.json", json.dumps(manifest, indent=2, ensure_ascii=True) + "\n")
            for path, data in selected:
                archive.writestr(path.relative_to(source_root).as_posix(), data)
        os.replace(temp_name, backup_path)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)
    manifest["backup_path"] = str(backup_path)
    manifest["backup_sha256"] = sha256(backup_path)
    return manifest


def read_manifest(backup_path: Path) -> dict[str, Any]:
    with zipfile.ZipFile(backup_path, "r") as archive:
        try:
            manifest = json.loads(archive.read("backup-manifest.json").decode("utf-8"))
        except KeyError as exc:
            raise BackupError("backup manifest is missing") from exc
    if manifest.get("backup_version") != BACKUP_VERSION:
        raise BackupError("unsupported backup version")
    if manifest.get("file_count") != len(manifest.get("files", [])):
        raise BackupError("backup manifest file count mismatch")
    return manifest


def verify_backup(backup_path: Path) -> dict[str, Any]:
    manifest = read_manifest(backup_path)
    expected = {item["path"]: item for item in manifest["files"]}
    with zipfile.ZipFile(backup_path, "r") as archive:
        names = set(archive.namelist())
        actual = names - {"backup-manifest.json"}
        if actual != set(expected):
            raise BackupError("backup archive contents do not match manifest")
        for name, item in expected.items():
            data = archive.read(name)
            if len(data) != item["size"] or hashlib.sha256(data).hexdigest() != item["sha256"]:
                raise BackupError(f"backup integrity mismatch: {name}")
    return manifest


def restore_backup(backup_path: Path, destination_root: Path) -> dict[str, Any]:
    manifest = verify_backup(backup_path)
    destination_root = destination_root.resolve()
    destination_root.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(backup_path, "r") as archive:
        for item in manifest["files"]:
            relative = Path(item["path"])
            if relative.is_absolute() or ".." in relative.parts or any(part == "" for part in relative.parts):
                raise BackupError(f"unsafe archive path: {item['path']}")
            target = (destination_root / relative).resolve()
            if not _is_within(target, destination_root):
                raise BackupError(f"restore path escapes destination: {item['path']}")
            target.parent.mkdir(parents=True, exist_ok=True)
            data = archive.read(item["path"])
            fd, temp_name = tempfile.mkstemp(prefix=".restore-", suffix=".tmp", dir=target.parent)
            try:
                with os.fdopen(fd, "wb") as handle:
                    handle.write(data)
                os.replace(temp_name, target)
            finally:
                if os.path.exists(temp_name):
                    os.unlink(temp_name)
    restored = verify_tree(destination_root, manifest)
    return {"manifest": manifest, "restored": restored}


def verify_tree(root: Path, manifest: dict[str, Any]) -> dict[str, Any]:
    root = root.resolve()
    for item in manifest["files"]:
        path = (root / item["path"]).resolve()
        if not _is_within(path, root) or not path.is_file():
            raise BackupError(f"restored file missing: {item['path']}")
        if path.stat().st_size != item["size"] or sha256(path) != item["sha256"]:
            raise BackupError(f"restored file mismatch: {item['path']}")
    return {
        "file_count": manifest["file_count"],
        "total_bytes": manifest["total_bytes"],
        "byte_exact": True,
    }


def damage_copy(root: Path) -> None:
    candidates = sorted((root / "knowledge").rglob("*.json"))
    if not candidates:
        raise BackupError("no disposable knowledge artifact to damage")
    candidates[0].write_text("{corrupted", encoding="utf-8")
    source = root / "sources"
    if source.exists():
        shutil.rmtree(source)
