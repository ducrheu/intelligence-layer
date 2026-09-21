from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from .errors import ArtifactValidationError

SEMVER = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")
ISO_TIME = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$")
# The id becomes a path segment in the store (skills/<status>/<id>/manifest.json),
# so it must never carry a separator or a traversal segment. The HTTP API already
# enforces this for selectors; the artifact itself must be held to it too, or any
# write identity could place a file outside the store root.
ARTIFACT_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
KINDS = {"knowledge", "experience", "skill", "source"}
STATUSES = {"candidate", "experimental", "validated", "approved", "stale", "deprecated", "archived"}


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _require(value: dict[str, Any], key: str, expected: type | tuple[type, ...]) -> Any:
    if key not in value:
        raise ArtifactValidationError(f"missing required field: {key}")
    if not isinstance(value[key], expected):
        raise ArtifactValidationError(f"{key} must be {expected}")
    return value[key]


def _list_of_objects(value: Any, field: str) -> None:
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        raise ArtifactValidationError(f"{field} must be an array of objects")


def validate_artifact(value: dict[str, Any]) -> None:
    if not isinstance(value, dict):
        raise ArtifactValidationError("artifact must be an object")
    for key in (
        "id", "kind", "scope", "status", "version", "title", "content",
        "created_by", "created_at", "updated_at", "source", "provenance",
        "verified", "applies_to", "compatibility", "tests", "evidence",
    ):
        _require(value, key, (str, bool, list, type(None), int))
    if value["kind"] not in KINDS:
        raise ArtifactValidationError(f"invalid kind: {value['kind']}")
    if value["status"] not in STATUSES:
        raise ArtifactValidationError(f"invalid status: {value['status']}")
    if not SEMVER.fullmatch(value["version"]):
        raise ArtifactValidationError("version must be semantic version x.y.z")
    if not value["id"] or not value["title"] or not value["created_by"]:
        raise ArtifactValidationError("id, title and created_by must be non-empty")
    if not ARTIFACT_ID.fullmatch(value["id"]):
        raise ArtifactValidationError(
            "id must match [A-Za-z0-9][A-Za-z0-9._-]{0,127} - no path separators, no traversal"
        )
    for field in ("created_at", "updated_at"):
        if not isinstance(value[field], str) or not ISO_TIME.fullmatch(value[field]):
            raise ArtifactValidationError(f"{field} must be an ISO-8601 timestamp")
    for field in ("source", "provenance", "tests", "evidence"):
        _list_of_objects(value[field], field)
    if not value["source"]:
        raise ArtifactValidationError("durable artifacts require at least one source record")
    if not value["provenance"]:
        raise ArtifactValidationError("durable artifacts require at least one provenance record")
    if any("type" not in item or "retrieved_at" not in item for item in value["source"]):
        raise ArtifactValidationError("source records require type and retrieved_at")
    if any("type" not in item or "created_at" not in item for item in value["provenance"]):
        raise ArtifactValidationError("provenance records require type and created_at")
    for field in ("applies_to", "compatibility"):
        if not isinstance(value[field], list) or not all(isinstance(item, str) for item in value[field]):
            raise ArtifactValidationError(f"{field} must be an array of strings")
    if not isinstance(value["verified"], bool):
        raise ArtifactValidationError("verified must be boolean")
    if value["verified"] and (not value.get("verified_by") or not value.get("verified_at")):
        raise ArtifactValidationError("verified artifacts require verified_by and verified_at")
    if value["verified"] and value["status"] != "approved":
        raise ArtifactValidationError("only approved artifacts may be verified")
    if value["status"] == "approved" and not value["verified"]:
        raise ArtifactValidationError("approved artifacts must be verified")
    if value["kind"] == "skill":
        required_metadata = {"name", "inputs", "outputs", "dependencies", "permissions"}
        missing = required_metadata.difference(value.get("metadata", {}))
        if missing:
            raise ArtifactValidationError(f"skill metadata missing: {sorted(missing)}")
        if not value["tests"]:
            raise ArtifactValidationError("skills require at least one test")
    if value["kind"] == "source":
        for item in value["source"]:
            if "type" not in item or "retrieved_at" not in item:
                raise ArtifactValidationError("source artifacts require source type and retrieved_at")


def validate_schema_files(schema_dir: Path) -> None:
    for path in schema_dir.glob("*.schema.json"):
        parsed = load_json(path)
        if parsed.get("$schema") != "https://json-schema.org/draft/2020-12/schema":
            raise ArtifactValidationError(f"unsupported schema declaration: {path.name}")
