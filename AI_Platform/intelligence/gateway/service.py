from __future__ import annotations

import json
import os
import re
import uuid
from pathlib import Path
from typing import Any

from .errors import ArtifactNotFoundError, ArtifactValidationError
from .attestation import GATEWAY_METADATA_KEYS, artifact_digest
from .auto_admission import POLICY_VERSION, evaluate
from .lifecycle import assert_transition
from .retrieval import EmbeddingCache, OllamaEmbedder, Retriever, build_reranker, rrf
from .models import Actor, utc_now
from .policy import can_read_approved, can_read_candidate, can_write_candidate, require
from .schema import validate_artifact
from .store import GitFileStore

MAX_EVENTS = 200
POLICY_IDENTITY = "policy-auto"
# Default is shadow: verdicts are recorded and reported, nothing moves by itself.
AUTO_ADMISSION_MODES = ("shadow", "enforce")


def state_dir(root: Path) -> Path:
    """Where runtime state lives (audit, events, usage, embeddings, token hashes).

    It is deliberately separable from the artifact tree: the repository is meant to
    be publishable, while the audit trail, the usage counters and the token hashes
    are operational records that name identities and behaviour. INTELLIGENCE_STATE
    points them somewhere outside the working tree; the default keeps single-machine
    development working unchanged.
    """
    override = os.environ.get("INTELLIGENCE_STATE")
    return Path(override) if override else root / "qa"


class IntelligenceGateway:
    """Runtime-neutral governance boundary for Phase 1."""

    def __init__(self, root: Path, auto_admission: str | None = None):
        self.root = root
        self.store = GitFileStore(root)
        self.state = state_dir(root)
        self.state.mkdir(parents=True, exist_ok=True)
        self.audit_path = self.state / "audit.jsonl"
        self.events_path = self.state / "events.jsonl"
        self.usage_path = self.state / "usage.json"
        self.retriever = self._build_retriever(root)
        self.audit_path.parent.mkdir(parents=True, exist_ok=True)
        self.config_path = root / "qa" / "governance-config.json"
        self.auto_admission = self._load_mode(auto_admission)

    def _load_mode(self, override: str | None) -> str:
        """The mode lives in the store, not in a process environment.

        A process-local setting lets the service and a tool disagree about the
        same store, which is how a governance setting silently drifts. One file
        is read by everyone; the environment is only a fallback for drills and
        tests where no store config exists yet.
        """
        mode = override
        if mode is None and self.config_path.is_file():
            try:
                mode = str(json.loads(self.config_path.read_text(encoding="utf-8")).get("auto_admission") or "")
            except (ValueError, OSError):
                mode = None
        if not mode:
            mode = os.environ.get("INTELLIGENCE_AUTO_ADMISSION", "shadow")
        mode = str(mode).strip().lower()
        if mode not in AUTO_ADMISSION_MODES:
            raise ValueError(f"auto_admission must be one of: {', '.join(AUTO_ADMISSION_MODES)}, got {mode!r}")
        return mode

    @staticmethod
    def _comparable(artifact: dict[str, Any]) -> dict[str, Any]:
        """The artifact as submitted, without the metadata the gateway added."""
        comparable = dict(artifact)
        metadata = dict(comparable.get("metadata") or {})
        for key in GATEWAY_METADATA_KEYS:
            metadata.pop(key, None)
        comparable["metadata"] = metadata
        return comparable

    def _disk_hashes(self, artifact: dict[str, Any]) -> dict[str, str]:
        """Hash every file a recorded piece of evidence claims to have executed."""
        paths: list[str] = []
        for record in artifact.get("evidence") or []:
            if not isinstance(record, dict):
                continue
            for item in record.get("files") or []:
                if isinstance(item, dict) and isinstance(item.get("path"), str):
                    paths.append(item["path"])
        return self.store.file_digests(paths)

    def evaluate_admission(self, artifact: dict[str, Any], submitter: str | None = None) -> dict[str, Any]:
        """What the auto-admission policy says about this artifact right now."""
        who = submitter or self._last_submitter(artifact["id"], artifact["kind"])
        return evaluate(artifact, who, self._disk_hashes(artifact)).to_dict()

    def _assert_policy_may(self, actor: Actor, artifact: dict[str, Any], action: str) -> None:
        """A policy identity may only do what the policy permits, recomputed now.

        The scope on the identity says "this may validate/approve"; this guard says
        "and only for artifacts whose verdict allows it". Both are needed: the
        scope is the door, the verdict is the lock.
        """
        if actor.actor_id != POLICY_IDENTITY:
            return
        if self.auto_admission != "enforce":
            self._audit(actor, f"policy_{action}", artifact["id"], "denied_shadow_mode", None, artifact["kind"])
            raise PermissionError(
                f"auto-admission is in {self.auto_admission} mode: verdicts are recorded, nothing moves on its own"
            )
        verdict = evaluate(artifact, self._last_submitter(artifact["id"], artifact["kind"]),
                           self._disk_hashes(artifact))
        allowed = verdict.auto_approve if action == "approve" else verdict.auto_validate
        if not allowed:
            self._audit(actor, f"policy_{action}", artifact["id"], "denied_by_policy", None, artifact["kind"])
            raise PermissionError(
                f"policy may not {action} {artifact['id']}: "
                f"{'; '.join(verdict.blocking) or 'not automatable under policy ' + POLICY_VERSION}"
            )

    def _audit(self, actor: Actor, action: str, artifact_id: str | None, result: str,
               correlation_id: str | None = None, kind: str | None = None) -> None:
        event = {
            "timestamp": utc_now(),
            "actor": actor.actor_id,
            "role": actor.role,
            "action": action,
            "artifact_id": artifact_id,
            "result": result,
            "correlation_id": correlation_id or str(uuid.uuid4()),
        }
        if kind is not None:
            event["kind"] = kind
        with self.audit_path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(event, ensure_ascii=True) + "\n")

    def _last_submitter(self, artifact_id: str, kind: str) -> str | None:
        """Who filed this artifact, taken from the append-only audit log.

        Ownership cannot be read off `created_by`: that field is whatever the
        submitter wrote (the backflow gate files as `local-agent` with
        `created_by: atlas-backflow`), so a claimant-controlled field cannot
        decide who may retract something. The audit log is written by the
        gateway, so it can.
        """
        if not self.audit_path.exists():
            return None
        submitter: str | None = None
        for line in self.audit_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if (event.get("action") == "submit_candidate" and event.get("result") == "success"
                    and event.get("artifact_id") == artifact_id and event.get("kind") == kind):
                submitter = event.get("actor")
        return submitter

    def _bump_surfaced(self, items: list[dict[str, Any]]) -> None:
        """Count search surfacing in one aggregated write, not one per hit.

        A search hit is weak evidence - the record was found, not necessarily read
        - so it does not belong in the lifecycle event stream. It is not dropped
        either: without it, a record that is only ever found by search would look
        unused and get retired. Kept separately so a decision can weigh both.
        """
        if not items:
            return
        try:
            state = json.loads(self.usage_path.read_text(encoding="utf-8")) if self.usage_path.is_file() else {}
        except (ValueError, OSError):
            state = {}
        surfaced = dict(state.get("surfaced") or {})
        stamp = utc_now()
        for item in items:
            key = f"{item.get('kind')}/{item.get('id')}"
            entry = dict(surfaced.get(key) or {"count": 0})
            entry["count"] = int(entry.get("count", 0)) + 1
            entry["last_surfaced_at"] = stamp
            surfaced[key] = entry
        state["surfaced"] = surfaced
        state["updated_at"] = stamp
        temp = self.usage_path.with_suffix(".tmp")
        temp.write_text(json.dumps(state, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
        os.replace(temp, self.usage_path)

    def _note_miss(self, query: str, kind: str) -> None:
        """Record a query that returned nothing, so vocabulary gaps become visible."""
        try:
            state = json.loads(self.usage_path.read_text(encoding="utf-8")) if self.usage_path.is_file() else {}
        except (ValueError, OSError):
            state = {}
        misses = dict(state.get("misses") or {})
        key = f"{kind}:{query.strip()[:160]}"
        entry = dict(misses.get(key) or {"count": 0})
        entry["count"] = int(entry.get("count", 0)) + 1
        entry["last_at"] = utc_now()
        misses[key] = entry
        state["misses"] = misses
        state["updated_at"] = utc_now()
        temp = self.usage_path.with_suffix(".tmp")
        temp.write_text(json.dumps(state, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        os.replace(temp, self.usage_path)

    def usage_summary(self) -> dict[str, Any]:
        """Per-artifact usage: explicit retrievals from the event stream, and
        search surfacing from the aggregate. This is what a review decision reads."""
        explicit: dict[str, dict[str, Any]] = {}
        if self.events_path.is_file():
            for line in self.events_path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if event.get("action") != "used":
                    continue
                key = f"{event.get('kind')}/{event.get('artifact_id')}"
                entry = explicit.setdefault(key, {"count": 0, "last_at": None, "by": []})
                entry["count"] += 1
                entry["last_at"] = event.get("timestamp")
                if event.get("actor") not in entry["by"]:
                    entry["by"].append(event.get("actor"))
        surfaced: dict[str, Any] = {}
        if self.usage_path.is_file():
            try:
                surfaced = dict(json.loads(self.usage_path.read_text(encoding="utf-8")).get("surfaced") or {})
            except (ValueError, OSError):
                surfaced = {}
        misses: dict[str, Any] = {}
        if self.usage_path.is_file():
            try:
                misses = dict(json.loads(self.usage_path.read_text(encoding="utf-8")).get("misses") or {})
            except (ValueError, OSError):
                misses = {}
        return {"explicit": explicit, "surfaced": surfaced, "misses": misses}

    def _event(self, actor: Actor, action: str, artifact: dict[str, Any], from_status: str | None,
               to_status: str, correlation_id: str | None = None, via: str | None = None) -> None:
        """Append a lifecycle event for consumers that need to react to a change.

        Metadata only: id, kind, statuses and the actor - never content. A reader
        of the stream learns that something changed, not what it says. The cursor
        is the line offset, which is stable because the file is append-only.
        """
        event = {
            "timestamp": utc_now(),
            "action": action,
            "kind": artifact.get("kind"),
            "artifact_id": artifact.get("id"),
            "from_status": from_status,
            "to_status": to_status,
            "actor": actor.actor_id,
            "created_by": artifact.get("created_by"),
            "correlation_id": correlation_id or str(uuid.uuid4()),
        }
        if via is not None:
            event["via"] = via
        with self.events_path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(event, ensure_ascii=True) + "\n")

    def read_events(self, actor: Actor, since: int = 0, max_items: int = 20) -> dict[str, Any]:
        """Bounded read of the lifecycle event stream from a line-offset cursor."""
        if "read:governance-metadata" not in actor.scopes and not can_read_candidate(actor):
            self._audit(actor, "read_events", None, "denied")
            raise PermissionError(f"{actor.actor_id} cannot read governance events")
        if since < 0:
            raise ValueError("since must be zero or greater")
        if max_items < 1 or max_items > MAX_EVENTS:
            raise ValueError(f"max_items must be between 1 and {MAX_EVENTS}")
        lines: list[str] = []
        if self.events_path.exists():
            lines = [line for line in self.events_path.read_text(encoding="utf-8").splitlines() if line.strip()]
        window = lines[since:since + max_items]
        self._audit(actor, "read_events", None, "success")
        return {
            "events": [json.loads(line) for line in window],
            "since": since,
            "next_cursor": since + len(window),
            "total": len(lines),
        }

    def _published(self, artifact_id: str, kind: str) -> dict[str, Any] | None:
        """An existing artifact under this id that is still live, if any.

        `archived` is deliberately excluded: it is the end of the lifecycle and
        its record is inert, so an author who retracts a mistake may reuse the
        id. Approved/stale/deprecated stay protected - those are the ids that
        could be silently overwritten by a later approval.
        """
        try:
            return self.store.load(artifact_id, kind, ("approved", "stale", "deprecated"))
        except ArtifactNotFoundError:
            return None

    def withdraw(self, actor: Actor, artifact_id: str, kind: str, reason: str | None = None,
                 correlation_id: str | None = None) -> dict[str, Any]:
        """Retract an unpublished artifact: the author's own, or anyone by the human.

        Nothing is deleted - the status becomes `archived` and the reason is kept
        with it. That is the point: a withdrawn candidate still explains itself to
        whoever reads the audit trail later, and the candidate layer stays a set of
        things someone actually stands behind.
        """
        require(actor, "withdraw")
        artifact = self.store.load(artifact_id, kind, ("candidate", "experimental", "validated"))
        author = artifact.get("created_by")
        submitter = self._last_submitter(artifact_id, kind)
        if "withdraw:any" not in actor.scopes and actor.actor_id not in (author, submitter):
            self._audit(actor, "withdraw", artifact_id, "denied_not_author", correlation_id, kind)
            raise PermissionError(
                f"{actor.actor_id} may only withdraw artifacts it filed "
                f"(created_by={author}, last_submitter={submitter})"
            )
        previous_status = artifact["status"]
        assert_transition(kind.removesuffix("s"), previous_status, "archived")
        artifact["status"] = "archived"
        artifact["updated_at"] = utc_now()
        artifact["metadata"] = dict(artifact.get("metadata", {}))
        artifact["metadata"]["withdraw"] = {
            "by": actor.actor_id,
            "at": artifact["updated_at"],
            "from_status": previous_status,
            "reason": (reason or "").strip()[:500] or "no reason given",
        }
        old_artifact = dict(artifact)
        old_artifact["status"] = previous_status
        if self.store._path(old_artifact) != self.store._path(artifact):
            self.store.relocate(old_artifact, artifact)
        else:
            self.store.save(artifact)
        self._audit(actor, "withdraw", artifact_id, "success", correlation_id, kind)
        self._event(actor, "withdrawn", artifact, previous_status, "archived", correlation_id)
        return artifact

    def submit_candidate(self, actor: Actor, artifact: dict[str, Any], correlation_id: str | None = None) -> dict[str, Any]:
        if not can_write_candidate(actor):
            self._audit(actor, "submit_candidate", artifact.get("id"), "denied", correlation_id)
            raise PermissionError(f"{actor.actor_id} cannot write candidate artifacts")
        if artifact.get("status") not in {"candidate", "experimental"}:
            raise ArtifactValidationError("candidate submission must start as candidate or experimental")
        validate_artifact(artifact)
        # Record what a policy identity would be allowed to do with this. The
        # verdict is timestamp-free so an identical resubmission stays idempotent.
        artifact = dict(artifact)
        artifact["metadata"] = dict(artifact.get("metadata", {}))
        artifact["metadata"]["auto_admission"] = evaluate(artifact, actor.actor_id, {}).to_dict()
        try:
            existing = self.store.load(artifact["id"], artifact["kind"], ("candidate", "experimental", "validated"))
        except ArtifactNotFoundError:
            existing = None
        if existing is None:
            published = self._published(artifact["id"], artifact["kind"])
            if published is not None and artifact.get("supersedes") != artifact["id"]:
                self._audit(actor, "submit_candidate", artifact["id"], "id_already_published", correlation_id)
                raise ArtifactValidationError(
                    f"{artifact['kind']} {artifact['id']} is already {published['status']}; a candidate may not "
                    "shadow a published artifact - supersede it (rollback scope) or use a new id"
                )
        if existing is not None:
            if self._comparable(existing) == self._comparable(artifact):
                self._audit(actor, "submit_candidate", artifact["id"], "idempotent", correlation_id)
                result = dict(existing)
                result["_idempotent"] = True
                return result
            self._audit(actor, "submit_candidate", artifact["id"], "duplicate_conflict", correlation_id)
            raise ArtifactValidationError(f"candidate already exists with different content: {artifact['id']}")
        path = self.store.save(artifact)
        self._audit(actor, "submit_candidate", artifact["id"], "success", correlation_id, artifact["kind"])
        self._event(actor, "candidate_submitted", artifact, None, artifact["status"], correlation_id)
        result = dict(artifact)
        result["_path"] = str(path)
        return result

    def get_knowledge(self, actor: Actor, artifact_id: str) -> dict[str, Any]:
        return self._get(actor, "knowledge", artifact_id)

    def get_experience(self, actor: Actor, artifact_id: str) -> dict[str, Any]:
        return self._get(actor, "experience", artifact_id)

    def get_skill(self, actor: Actor, artifact_id: str) -> dict[str, Any]:
        return self._get(actor, "skill", artifact_id)

    def get_source(self, actor: Actor, artifact_id: str) -> dict[str, Any]:
        return self._get(actor, "source", artifact_id)

    def _get(self, actor: Actor, kind: str, artifact_id: str) -> dict[str, Any]:
        statuses = ("approved", "stale", "deprecated", "archived")
        if can_read_candidate(actor):
            statuses = ("candidate", "experimental", "validated") + statuses
        elif not can_read_approved(actor):
            raise PermissionError(f"{actor.actor_id} cannot read artifacts")
        try:
            artifact = self.store.load(artifact_id, kind, statuses)
        except ArtifactNotFoundError:
            self._audit(actor, f"get_{kind}", artifact_id, "not_found")
            raise
        self._audit(actor, f"get_{kind}", artifact_id, "success")
        # Retrieval is the strong usage signal: the whole record was read.
        self._event(actor, "used", artifact, artifact["status"], artifact["status"], None, via="get")
        return artifact

    def _build_retriever(self, root: Path) -> Retriever:
        """Hybrid retrieval, degrading to lexical when the embedder is unavailable.

        A knowledge base that stops answering because a model server restarted is
        worse than one that answers with lexical matches and says so.
        """
        if os.environ.get("INTELLIGENCE_EMBED_DISABLE") == "1":
            return Retriever(cache=None, embedder=None, reranker=None)
        # Defaults are measured, not guessed (intelligence-retrieval-eval.py):
        # bge-m3 over nomic-embed-text is decisive on a Chinese corpus (vector-only
        # recall@1 0.958 vs 0.312); k=10 with the vector half down-weighted to 0.25
        # was best on the embedder where configurations were still distinguishable
        # and cost nothing on the strong one. RRF's textbook k=60 pools thousands of
        # documents and flattens the fusion on a corpus this size.
        model = os.environ.get("INTELLIGENCE_EMBED_MODEL", "bge-m3")
        cache = EmbeddingCache(self.state / "embeddings.json", model)
        weights = [float(part) for part in os.environ["INTELLIGENCE_RRF_WEIGHTS"].split(",")] \
            if os.environ.get("INTELLIGENCE_RRF_WEIGHTS") else None
        return Retriever(
            cache=cache,
            embedder=OllamaEmbedder(model=model),
            reranker=build_reranker(),
            rrf_k=int(os.environ.get("INTELLIGENCE_RRF_K", "10")),
            weights=weights if weights is not None else [1.0, 0.25],
            lexical=os.environ.get("INTELLIGENCE_LEXICAL_DISABLE") != "1",
            min_cosine=float(os.environ.get("INTELLIGENCE_MIN_COSINE", "0.50")),
            passage_chars=int(os.environ.get("INTELLIGENCE_PASSAGE_CHARS", "600")),
            chunk=os.environ.get("INTELLIGENCE_CHUNK", "1") != "0",
            idf_ratio=float(os.environ.get("INTELLIGENCE_MIN_IDF_RATIO", "0.6")),
        )

    def _search_documents(self, actor: Actor, kind: str, scope: str | None) -> dict[str, dict[str, Any]]:
        """Everything this actor may read, shaped for ranking.

        Filtering happens here, before any ranking, so the retriever only ever
        sees what the caller is allowed to read: no ranking trace, no count and no
        score can then leak the existence of a candidate to a reader without
        candidate scope.
        """
        documents: dict[str, dict[str, Any]] = {}
        for artifact in self.store.iter_all():
            if artifact.get("kind") != kind:
                continue
            if artifact.get("status") == "archived":
                # Terminal state, kept for the audit trail rather than for reading.
                continue
            if artifact.get("status") != "approved" and not can_read_candidate(actor):
                continue
            if scope and artifact.get("scope") != scope:
                continue
            metadata = artifact.get("metadata") or {}
            content = f"{artifact.get('title', '')}\n{artifact.get('content', '')}"
            documents[f"{kind}/{artifact['id']}"] = {
                "artifact": artifact,
                "digest": artifact_digest(artifact),
                "fields": [
                    (artifact.get("id", ""), 3.0),
                    (artifact.get("title", ""), 2.0),
                    (str(metadata.get("name") or ""), 2.0),
                    (" ".join(str(tag) for tag in (metadata.get("tags") or [])), 2.0),
                    (artifact.get("content", ""), 1.0),
                ],
                "embed_text": content,
                "rerank_text": content,
            }
        return documents

    def retrieve(self, actor: Actor, kind: str, query: str, scope: str | None = None,
                 max_items: int = 10, max_bytes: int = 20000, max_chars: int = 12000,
                 embed_budget: int = 24) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        """Ranked retrieval plus the trace explaining the ranking."""
        if not can_read_approved(actor) and not can_read_candidate(actor):
            raise PermissionError(f"{actor.actor_id} cannot search artifacts")
        if max_items < 1 or max_items > 100 or max_bytes < 1 or max_chars < 1:
            raise ValueError("invalid retrieval limits")
        documents = self._search_documents(actor, kind, scope)
        ranked, summary = self.retriever.rank(query, documents, limit=max_items, embed_budget=embed_budget)
        if self.retriever.cache is not None:
            self.retriever.cache.prune({document["digest"] for document in documents.values()})
            self.retriever.cache.save()
        matches: list[dict[str, Any]] = []
        for item in ranked:
            artifact = documents[item["key"]]["artifact"]
            compact = {
                "id": artifact["id"],
                "kind": artifact["kind"],
                "status": artifact["status"],
                "version": artifact["version"],
                "title": artifact["title"],
                "content": artifact["content"][:max_chars],
                "provenance": artifact["provenance"][:3],
                "score": item["score"],
                "why": item["why"],
            }
            encoded = json.dumps(compact, ensure_ascii=False)
            if len(json.dumps(matches, ensure_ascii=False)) + len(encoded) > max_bytes:
                break
            matches.append(compact)
        summary["returned"] = len(matches)
        summary["candidates"] = len(documents)
        return matches, summary

    def search(self, actor: Actor, kind: str, query: str, scope: str | None = None,
               max_items: int = 10, max_bytes: int = 20000, max_chars: int = 12000) -> list[dict[str, Any]]:
        matches, summary = self.retrieve(actor, kind, query, scope, max_items, max_bytes, max_chars)
        self._audit(actor, f"search_{kind}", None, "success")
        self._bump_surfaced(matches)
        if not matches and summary.get("candidates"):
            # A query that found nothing while the corpus had candidates is the
            # single most actionable signal this knowledge base can produce.
            self._note_miss(query, kind)
        return matches

    def validate_candidate(self, actor: Actor, artifact_id: str, kind: str, correlation_id: str | None = None) -> dict[str, Any]:
        require(actor, "validate:candidate")
        artifact = self.store.load(artifact_id, kind, ("candidate", "experimental", "validated"))
        validate_artifact(artifact)
        self._assert_policy_may(actor, artifact, "validate")
        target = "validated"
        assert_transition(kind.removesuffix("s"), artifact["status"], target)
        old_status = artifact["status"]
        artifact["status"] = target
        artifact["updated_at"] = utc_now()
        artifact.setdefault("evidence", []).append({"type": "qa", "actor": actor.actor_id, "validated_at": artifact["updated_at"]})
        old_artifact = dict(artifact)
        old_artifact["status"] = old_status
        if self.store._path(old_artifact) != self.store._path(artifact):
            self.store.relocate(old_artifact, artifact)
        else:
            self.store.save(artifact)
        self._audit(actor, "validate_candidate", artifact_id, "success", correlation_id)
        self._event(actor, "validated", artifact, old_status, target, correlation_id)
        return artifact

    def record_validation_evidence(
        self,
        actor: Actor,
        artifact_id: str,
        kind: str,
        evidence: list[dict[str, Any]],
        correlation_id: str | None = None,
    ) -> dict[str, Any]:
        require(actor, "validate:candidate")
        if not evidence or not all(isinstance(item, dict) for item in evidence):
            raise ArtifactValidationError("validation evidence must be a non-empty array of objects")
        artifact = self.store.load(artifact_id, kind, ("candidate", "experimental", "validated"))
        # Attribution, clock and subject are the gateway's to write. A caller that
        # could set recorded_by or subject_digest could mint its own verification.
        stamped: list[dict[str, Any]] = []
        for record in evidence:
            entry = dict(record)
            entry["recorded_by"] = actor.actor_id
            entry["recorded_at"] = utc_now()
            entry["subject_digest"] = artifact_digest(artifact)
            stamped.append(entry)
        artifact.setdefault("evidence", []).extend(stamped)
        artifact["updated_at"] = utc_now()
        artifact["metadata"] = dict(artifact.get("metadata", {}))
        artifact["metadata"]["auto_admission"] = self.evaluate_admission(artifact)
        validate_artifact(artifact)
        self.store.save(artifact)
        self._audit(actor, "record_validation_evidence", artifact_id, "success", correlation_id)
        self._event(actor, "evidence_recorded", artifact, artifact["status"], artifact["status"], correlation_id)
        return artifact

    def request_promotion(self, actor: Actor, artifact_id: str, kind: str, correlation_id: str | None = None) -> dict[str, Any]:
        require(actor, "request:promotion")
        artifact = self.store.load(artifact_id, kind, ("validated",))
        self._audit(actor, "request_promotion", artifact_id, "pending_human_approval", correlation_id)
        self._event(actor, "promotion_requested", artifact, artifact["status"], artifact["status"], correlation_id)
        return {"artifact_id": artifact_id, "kind": kind, "status": "pending_human_approval", "current_status": artifact["status"]}

    def approve(self, actor: Actor, artifact_id: str, kind: str, correlation_id: str | None = None) -> dict[str, Any]:
        require(actor, "approve")
        try:
            # Load every unpublished status, not just `validated`: approving a
            # candidate should say "that transition is not allowed", not "not found".
            artifact = self.store.load(artifact_id, kind, ("validated", "candidate", "experimental"))
        except ArtifactNotFoundError:
            existing = self.store.load(artifact_id, kind, ("approved",))
            if existing.get("verified") and existing.get("metadata", {}).get("approval_action") == "human_approval":
                self._audit(actor, "approve", artifact_id, "idempotent", correlation_id)
                result = dict(existing)
                result["_idempotent"] = True
                return result
            raise
        self._assert_policy_may(actor, artifact, "approve")
        previous_status = artifact["status"]
        assert_transition(kind.removesuffix("s"), previous_status, "approved")
        artifact["status"] = "approved"
        artifact["verified"] = True
        artifact["verified_by"] = actor.actor_id
        artifact["verified_at"] = utc_now()
        artifact["updated_at"] = artifact["verified_at"]
        artifact["metadata"] = dict(artifact.get("metadata", {}))
        artifact["metadata"]["approval_action"] = "human_approval"
        old_artifact = dict(artifact)
        old_artifact["status"] = previous_status
        if self.store._path(old_artifact) != self.store._path(artifact):
            path = self.store.relocate(old_artifact, artifact)
        else:
            path = self.store.save(artifact)
        self._audit(actor, "approve", artifact_id, "success", correlation_id)
        self._event(actor, "approved", artifact, previous_status, "approved", correlation_id)
        result = dict(artifact)
        result["_path"] = str(path)
        return result

    def deprecate(self, actor: Actor, artifact_id: str, kind: str, correlation_id: str | None = None) -> dict[str, Any]:
        require(actor, "deprecate")
        artifact = self.store.load(artifact_id, kind, ("approved", "stale"))
        previous_status = artifact["status"]
        assert_transition(kind.removesuffix("s"), previous_status, "deprecated")
        artifact["status"] = "deprecated"
        artifact["updated_at"] = utc_now()
        old_artifact = dict(artifact)
        old_artifact["status"] = previous_status
        if self.store._path(old_artifact) != self.store._path(artifact):
            self.store.relocate(old_artifact, artifact)
        else:
            self.store.save(artifact)
        self._audit(actor, "deprecate", artifact_id, "success", correlation_id)
        self._event(actor, "deprecated", artifact, previous_status, "deprecated", correlation_id)
        return artifact

    def supersede(self, actor: Actor, old_id: str, new_artifact: dict[str, Any], kind: str, correlation_id: str | None = None) -> dict[str, Any]:
        require(actor, "rollback")
        old = self.store.load(old_id, kind, ("approved", "stale", "deprecated"))
        previous_status = old["status"]
        new_artifact["supersedes"] = old_id
        new = self.submit_candidate(actor, new_artifact, correlation_id)
        old["superseded_by"] = new_artifact["id"]
        old["status"] = "deprecated"
        old["updated_at"] = utc_now()
        old_previous = dict(old)
        old_previous["status"] = previous_status
        if self.store._path(old_previous) != self.store._path(old):
            self.store.relocate(old_previous, old)
        else:
            self.store.save(old)
        self._audit(actor, "supersede", old_id, "success", correlation_id)
        self._event(actor, "superseded", old, previous_status, "deprecated", correlation_id)
        return new
