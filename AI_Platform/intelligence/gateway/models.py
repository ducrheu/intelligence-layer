from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


@dataclass(frozen=True)
class Actor:
    actor_id: str
    role: str
    scopes: frozenset[str] = field(default_factory=frozenset)
    runtime: str | None = None


@dataclass
class Artifact:
    id: str
    kind: str
    scope: str
    status: str
    version: str
    title: str
    content: str
    created_by: str
    created_at: str
    updated_at: str
    source: list[dict[str, Any]]
    provenance: list[dict[str, Any]]
    verified: bool = False
    verified_by: str | None = None
    verified_at: str | None = None
    applies_to: list[str] = field(default_factory=list)
    compatibility: list[str] = field(default_factory=list)
    expires_at: str | None = None
    review_interval_days: int | None = None
    tests: list[dict[str, Any]] = field(default_factory=list)
    evidence: list[dict[str, Any]] = field(default_factory=list)
    supersedes: str | None = None
    superseded_by: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "scope": self.scope,
            "status": self.status,
            "version": self.version,
            "title": self.title,
            "content": self.content,
            "created_by": self.created_by,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "source": self.source,
            "provenance": self.provenance,
            "verified": self.verified,
            "verified_by": self.verified_by,
            "verified_at": self.verified_at,
            "applies_to": self.applies_to,
            "compatibility": self.compatibility,
            "expires_at": self.expires_at,
            "review_interval_days": self.review_interval_days,
            "tests": self.tests,
            "evidence": self.evidence,
            "supersedes": self.supersedes,
            "superseded_by": self.superseded_by,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "Artifact":
        return cls(**value)
