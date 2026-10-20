from __future__ import annotations

import hashlib
import json
import os
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .audit_chain import append_audit_record
from .errors import ArtifactNotFoundError, ArtifactValidationError
from .exposure import denied_ids, may_read, scrub_entries, scrub_references
from .attestation import GATEWAY_METADATA_KEYS, artifact_digest
from .auto_admission import POLICY_VERSION, evaluate
from .lifecycle import assert_transition
from .retrieval import EmbeddingCache, OllamaEmbedder, Retriever, build_reranker, rrf
from .models import Actor, utc_now
from .policy import can_read_approved, can_read_candidate, can_write_candidate, require
from .schema import validate_artifact
from .store import GitFileStore
from .telemetry import FRESH, freshness

MAX_EVENTS = 200
POLICY_IDENTITY = "policy-auto"
# A probe identity for the pre-admission duplicate check: it must see approved
# records only (a candidate that is not yet published is not a duplicate of
# itself), and it is never used to read for a caller.
DEDUP_ACTOR = Actor("dedup-probe", "system", frozenset({"read:approved"}))

# Cosine at or above this is the same thing said twice, not the same topic.
# Measured on the real corpus: the 16 distilled experience/knowledge pairs score
# 0.831-0.920 against each other, while genuinely different records on a shared
# topic stay <= 0.70. Rank position is NOT usable here - with ~40 documents every
# probe has *some* record at lexical rank 1, so a rank-based gate refuses new
# knowledge that shares nothing but vocabulary with the corpus.
DUPLICATE_COSINE = 0.82


def _telemetry_suppressed() -> bool:
    """True when the caller is a measurement, not a reader.

    Retrieval evals and screens run against the live store; without this their
    probes land in the usage counters and in the lifecycle stream, where they are
    indistinguishable from real use. Measured once: a suite run wrote 315 test
    events into the production stream, and a 51-query eval in October kept the
    "nobody is reading the knowledge base" alarm silent for a week.

    Only usage telemetry is suppressed. The audit chain records *who did what*
    and is never optional.
    """
    return os.environ.get("INTELLIGENCE_TELEMETRY_SUPPRESS", "").strip().lower() in ("1", "true", "yes")
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

    def evaluate_admission(self, artifact: dict[str, Any], submitter: str | None = None,
                           probe_duplicates: bool = False) -> dict[str, Any]:
        """What the auto-admission policy says about this artifact right now.

        `probe_duplicates` is off by default on purpose: the duplicate probe is a
        full-corpus retrieval (two ranks over every record), while the verdict
        itself is a pure judgement on the record's own fields. Submitting computes
        the probe once and records the verdict; re-running the corpus for every
        verdict turned a sweep of 133 artifacts into a ten-minute job.
        """
        who = submitter or self._last_submitter(artifact["id"], artifact["kind"])
        duplicate = self._nearest_live_record(artifact) if probe_duplicates else None
        return evaluate(artifact, who, self._disk_hashes(artifact),
                        duplicate_of=duplicate).to_dict()

    def _nearest_live_record(self, artifact: dict[str, Any]) -> str | None:
        """The live record this submission is a near copy of, if any.

        Distillation already produced one full round of cross-kind duplicates
        (every `knowledge` record and the `experience` it summarised). The
        admission policy can only see structure, so it admitted both; the check
        has to ask the read path's own question before the second copy becomes
        another approved record.

        A duplicate is a *cosine* judgement, not a rank judgement: with ~40
        documents every probe has some record at lexical rank 1, so rank alone
        refused new knowledge that shared nothing but vocabulary. Measured on
        this corpus, the 16 distilled pairs score 0.831-0.920 while unrelated
        neighbours stay at or below 0.70.
        """
        probe = f"{artifact.get('title') or ''}\n{(artifact.get('content') or '')[:1500]}".strip()
        if not probe:
            return None
        own = f"{artifact.get('kind')}/{artifact.get('id')}"
        kind = artifact.get("kind")
        # Compare within the kind, plus the knowledge<->experience pair that
        # distillation actually duplicated. Scanning all four kinds for every
        # submission cost ~10s per skill against a corpus of 40; the pairs that
        # can be duplicates are already known, and a skill cannot duplicate a
        # conclusion.
        kinds = [kind] if kind in {"skill", "source"} else ["knowledge", "experience"]
        for name in kinds:
            documents = self._search_documents(DEDUP_ACTOR, name, None)
            if not documents:
                continue
            ranked, _ = self.retriever.rank(probe, documents, limit=3, embed_budget=1)
            for item in ranked:
                if item["key"] == own:
                    continue
                similarity = item.get("cosine")
                if isinstance(similarity, (int, float)) and similarity >= DUPLICATE_COSINE:
                    return item["key"]
        return None

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
                           self._disk_hashes(artifact),
                           duplicate_of=self._nearest_live_record(artifact))
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
        # Chained to the previous record and appended under an exclusive lock: the audit
        # log is the root of trust for ownership and trust decisions, so one rewritten
        # line has to be detectable. Why both parts are required, and what the chain
        # still cannot catch: gateway/audit_chain.py.
        append_audit_record(self.audit_path, event)

    def _submitter_index(self) -> dict[tuple[str, str], str]:
        """artifact -> submitter, parsed once and then incrementally.

        The audit log is append-only and grows by one line per lifecycle action.
        Re-reading and re-parsing all of it for every verdict made a sweep of 133
        artifacts take ten minutes; the log only ever gets longer, so the index
        remembers how far it read and parses the new tail next time.
        """
        cache = getattr(self, "_submitter_cache", None)
        if cache is None:
            cache = {}
            self._submitter_cache = cache
            self._submitter_offset = 0
        if not self.audit_path.exists():
            return cache
        with self.audit_path.open("rb") as handle:
            handle.seek(self._submitter_offset)
            chunk = handle.read()
        if not chunk:
            return cache
        # Only complete lines: a writer may be mid-append, and a half line parsed
        # now would be parsed wrong forever.
        cut = chunk.rfind(b"\n")
        if cut < 0:
            return cache
        complete = chunk[: cut + 1]
        for raw in complete.splitlines():
            if not raw.strip():
                continue
            try:
                event = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if (event.get("action") == "submit_candidate" and event.get("result") == "success"
                    and event.get("artifact_id") and event.get("kind")):
                cache[(event["artifact_id"], event["kind"])] = event.get("actor")
        self._submitter_offset += len(complete)
        return cache

    def _last_submitter(self, artifact_id: str, kind: str) -> str | None:
        """Who filed this artifact, taken from the append-only audit log.

        Ownership cannot be read off `created_by`: that field is whatever the
        submitter wrote (the backflow gate files as `local-agent` with
        `created_by: atlas-backflow`), so a claimant-controlled field cannot
        decide who may retract something. The audit log is written by the
        gateway, so it can.
        """
        return self._submitter_index().get((artifact_id, kind))

    def _bump_surfaced(self, items: list[dict[str, Any]]) -> None:
        """Count search surfacing in one aggregated write, not one per hit.

        A search hit is weak evidence - the record was found, not necessarily read
        - so it does not belong in the lifecycle event stream. It is not dropped
        either: without it, a record that is only ever found by search would look
        unused and get retired. Kept separately so a decision can weigh both.
        """
        if not items or _telemetry_suppressed():
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
        if _telemetry_suppressed():
            return
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
        if _telemetry_suppressed():
            return
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

    @staticmethod
    def content_fingerprint(artifact: dict[str, Any]) -> str:
        """A digest of the artifact's *text*, independent of its id.

        ``artifact_digest`` cannot serve here: it covers ``id`` by design, so it never
        collides across two ids and would miss exactly the duplicate this is looking for.
        Whitespace and case are normalised because two copies differing only in
        formatting are still one record.
        """
        body = " ".join((artifact.get("content") or "").split()).casefold()
        return "sha256:" + hashlib.sha256(body.encode("utf-8")).hexdigest()

    def _content_collision(self, artifact: dict[str, Any]) -> dict[str, Any] | None:
        """An existing *live* record whose text is identical to this one's, if any.

        This **reports; it does not refuse**, and that is a deliberate reversal of the
        first version of this gate. Refusing looked right - the industry pattern is
        "id/content-hash dedup, fail closed" - but three facts in this codebase say
        otherwise:

        1. The identity here is the `id`; text is not a key. Four existing test files file
           several records that legitimately share a body, and the withdrawal/re-file path
           expects content to survive under a new id.
        2. Text-level dedup "must be evaluated, not assumed correct" - the FineWeb corpus
           work measured global deduplication making the *retained* data worse. Turning
           that into a refusal would bake an unvalidated rule into the write path.
        3. A refusal costs a blocked submission; a report costs a line in the weekly
           review. For a same-text pair the human still has to decide which copy is the
           record of record, so the refusal only moved the decision earlier and made it
           mandatory.

        Live statuses only: an archived record is inert and its id is deliberately
        reusable, so re-filing withdrawn text stays possible.
        """
        fingerprint = self.content_fingerprint(artifact)
        for other in self.store.iter_all():
            if other.get("kind") != artifact.get("kind") or other.get("id") == artifact.get("id"):
                continue
            if other.get("status") not in ("candidate", "experimental", "validated", "approved"):
                continue
            if self.content_fingerprint(other) == fingerprint:
                return other
        return None

    def submit_candidate(self, actor: Actor, artifact: dict[str, Any], correlation_id: str | None = None) -> dict[str, Any]:
        if not can_write_candidate(actor):
            self._audit(actor, "submit_candidate", artifact.get("id"), "denied", correlation_id)
            raise PermissionError(f"{actor.actor_id} cannot write candidate artifacts")
        if artifact.get("status") not in {"candidate", "experimental"}:
            raise ArtifactValidationError("candidate submission must start as candidate or experimental")
        validate_artifact(artifact)
        # Record what a policy identity would be allowed to do with this. The
        # verdict is timestamp-free so an identical resubmission stays idempotent.
        # The duplicate probe is deliberately NOT run here: it costs a full-corpus
        # embedding pass (and a second model in memory) on every submission, while
        # the same question is already answered offline by near_duplicate.py in the
        # weekly review, where a human can act on the pair.
        artifact = dict(artifact)
        artifact["metadata"] = dict(artifact.get("metadata", {}))
        artifact["metadata"]["auto_admission"] = self.evaluate_admission(
            artifact, actor.actor_id, probe_duplicates=False)
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
        collision = self._content_collision(artifact)
        path = self.store.save(artifact)
        self._audit(actor, "submit_candidate", artifact["id"], "success", correlation_id, artifact["kind"])
        if collision is not None:
            # Reported, not refused - see _content_collision for why. The audit line is
            # what the weekly review reads; `_content_duplicate_of` is what the filing
            # tool can print back at the submitter, who is the one who can act on it.
            self._audit(actor, "submit_candidate", artifact["id"], "duplicate_content", correlation_id, artifact["kind"])
        self._event(actor, "candidate_submitted", artifact, None, artifact["status"], correlation_id)
        result = dict(artifact)
        result["_path"] = str(path)
        if collision is not None:
            result["_content_duplicate_of"] = f"{collision['kind']}/{collision['id']}"
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
        denied = denied_ids(self.root, actor)
        if not may_read(denied, kind, artifact_id):
            # Same exception, same audit action as an id that never existed. A distinct
            # "denied" answer would let a caller map the corpus by probing ids, which is
            # the leak the denylist exists to prevent.
            self._audit(actor, f"get_{kind}", artifact_id, "not_found")
            raise ArtifactNotFoundError(f"{kind}/{artifact_id} not found")
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
        # References are ids in plain sight, so they get the same treatment as the records
        # themselves: a source entry pointing at a withheld record would leak it.
        return scrub_references(artifact, denied)

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
            min_coverage=float(os.environ.get("INTELLIGENCE_MIN_MATCH_COVERAGE", "0.0")),
            common_df_ratio=float(os.environ.get("INTELLIGENCE_COMMON_DF_RATIO", "0.0")),
        )

    def _search_documents(self, actor: Actor, kind: str, scope: str | None) -> dict[str, dict[str, Any]]:
        """Everything this actor may read, shaped for ranking.

        Filtering happens here, before any ranking, so the retriever only ever
        sees what the caller is allowed to read: no ranking trace, no count and no
        score can then leak the existence of a candidate to a reader without
        candidate scope.
        """
        documents: dict[str, dict[str, Any]] = {}
        # Exposure control first, inside the predicate: a denied artifact must never be
        # a candidate, so no count, score or ranking trace can reveal that it exists.
        denied = denied_ids(self.root, actor)
        for artifact in self.store.iter_all():
            if artifact.get("kind") != kind:
                continue
            if not may_read(denied, kind, str(artifact.get("id", ""))):
                continue
            if artifact.get("status") == "archived":
                # Terminal state, kept for the audit trail rather than for reading.
                continue
            if artifact.get("superseded_by"):
                # A distilled source: the finished record cites it, so the raw
                # copy is evidence, not an answer. Keeping both in the read
                # surface made every search pay twice for the same content and
                # let the raw note compete with its own summary. It stays
                # readable by id (provenance) and stays approved (history).
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

    def _stalest_last(self, ranked: list[dict[str, Any]],
                      documents: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
        """Move stale records behind fresh ones, keeping the ranking otherwise intact.

        Ordering, *not* exclusion. An expired record is still the answer to "what did we
        say about X" - dropping it would turn a review flag into silent data
        loss, and the caller would have no way to tell the difference between "we never
        knew" and "we knew and it went stale". The sort is stable, so among equals the
        ranking decides, and `freshness` travels with each hit so the caller can see it.
        """
        if not ranked:
            return ranked
        now = datetime.now(timezone.utc)
        return sorted(ranked, key=lambda item: freshness(documents[item["key"]]["artifact"], now) != FRESH)

    def retrieve(self, actor: Actor, kind: str, query: str, scope: str | None = None,
                 max_items: int = 10, max_bytes: int = 20000, max_chars: int = 12000,
                 embed_budget: int = 24) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        """Ranked retrieval plus the trace explaining the ranking."""
        if not can_read_approved(actor) and not can_read_candidate(actor):
            raise PermissionError(f"{actor.actor_id} cannot search artifacts")
        if max_items < 1 or max_items > 100 or max_bytes < 1 or max_chars < 1:
            raise ValueError("invalid retrieval limits")
        documents = self._search_documents(actor, kind, scope)
        denied = denied_ids(self.root, actor)
        ranked, summary = self.retriever.rank(query, documents, limit=max_items, embed_budget=embed_budget)
        ranked = self._stalest_last(ranked, documents)
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
                "provenance": scrub_entries(artifact["provenance"], denied)[:3],
                "score": item["score"],
                "why": item["why"],
                "freshness": freshness(artifact),
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

    def record_attachments(self, actor: Actor, artifact_id: str, kind: str,
                           files: list[dict[str, Any]], audit: dict[str, Any],
                           correlation_id: str | None = None) -> dict[str, Any]:
        """Record a record's support files without touching its content or status.

        A skill's SKILL.md was admitted on its own; the references and scripts
        beside it are support material, and the record is incomplete without them.
        Adding them changes neither the claim, the version nor the verification, so
        it is a metadata operation -- audited, and only when the body is unchanged
        (a body change goes through the normal candidate path).
        """
        if not can_write_candidate(actor):
            raise PermissionError(f"{actor.actor_id} cannot write candidate artifacts")
        artifact = self.store.load(artifact_id, kind,
                                   ("approved", "validated", "candidate", "experimental"))
        metadata = dict(artifact.get("metadata") or {})
        metadata["files"] = files
        metadata["script_audit"] = audit
        metadata["executable_attachments"] = bool(audit.get("files") and any(
            str(item.get("path", "")).endswith((".py", ".sh", ".js", ".ts", ".cjs", ".mjs"))
            for item in files))
        artifact["metadata"] = metadata
        artifact["updated_at"] = utc_now()
        path = self.store.save(artifact)
        self._audit(actor, "attachments_recorded", artifact_id, "success", correlation_id, kind)
        self._event(actor, "attachments_recorded", artifact, artifact["status"], artifact["status"],
                    correlation_id)
        result = dict(artifact)
        result["_path"] = str(path)
        return result

    def refresh_candidate(self, actor: Actor, artifact: dict[str, Any],
                          correlation_id: str | None = None) -> dict[str, Any]:
        """Replace an unpublished candidate's content in place.

        `submit_candidate` refuses a different payload under the same id, and it
        is right to: a silent overwrite hides what changed, and a candidate may
        not shadow a published artifact. A sync job needs the other half of that
        rule -- the record is still unpublished, so its author may replace it,
        audited, with `created_at` preserved so the record keeps its history.
        """
        if not can_write_candidate(actor):
            self._audit(actor, "refresh_candidate", artifact.get("id"), "denied", correlation_id)
            raise PermissionError(f"{actor.actor_id} cannot write candidate artifacts")
        validate_artifact(artifact)
        existing = self.store.load(artifact["id"], artifact["kind"],
                                   ("candidate", "experimental", "validated"))
        artifact = dict(artifact)
        artifact["metadata"] = dict(artifact.get("metadata", {}))
        artifact["created_at"] = existing.get("created_at") or artifact.get("created_at")
        artifact["status"] = str(existing.get("status") or artifact.get("status") or "candidate")
        artifact["metadata"]["auto_admission"] = self.evaluate_admission(
            artifact, actor.actor_id, probe_duplicates=False)
        path = self.store.save(artifact)
        self._audit(actor, "refresh_candidate", artifact["id"], "success", correlation_id, artifact["kind"])
        self._event(actor, "candidate_refreshed", artifact, existing.get("status"),
                    artifact["status"], correlation_id)
        result = dict(artifact)
        result["_path"] = str(path)
        return result

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

    def retire_distilled(self, actor: Actor, old_id: str, new_id: str, kind: str = "experience",
                         correlation_id: str | None = None) -> dict[str, Any]:
        """Take a distilled source out of the read surface, without inventing a new record.

        Distillation writes a `knowledge` record whose `source` says
        `experience:<id>`, and the raw experience stayed approved next to it. Both
        copies then competed in search for the same query: the summary and the note
        it summarised. `supersede()` does not fit here - it requires a *new*
        artifact and deprecates the old one - because the finished record already
        exists. This marks the source, leaves its status alone (history keeps its
        place; by-id reads still resolve it for provenance), and lets the read
        surface skip it.
        """
        require(actor, "rollback")
        old = self.store.load(old_id, kind, ("approved", "validated", "stale"))
        if old.get("superseded_by"):
            return old
        old["superseded_by"] = new_id
        old["updated_at"] = utc_now()
        self.store.save(old)
        self._audit(actor, "retire_distilled", old_id, "success", correlation_id)
        self._event(actor, "superseded", old, str(old.get("status") or ""),
                    str(old.get("status") or ""), correlation_id)
        return old

    def demote_unread(self, actor: Actor, artifact_id: str, kind: str, reason: str,
                      correlation_id: str | None = None) -> dict[str, Any]:
        """Take a record out of the read surface because nobody ever read it.

        The owner's rule: an approved record that no one has retrieved for 60
        days is a demand question, not a fact. It goes to `experimental` - not
        deleted, not deprecated - so it stops competing in search while staying
        one transition away from coming back. The reason is recorded on the
        artifact because the interesting part of this decision is *why*, and it
        is the only thing a reader will not be able to reconstruct later.
        """
        require(actor, "rollback")
        artifact = self.store.load(artifact_id, kind, ("approved",))
        previous = dict(artifact)
        artifact["status"] = "experimental"
        artifact["updated_at"] = utc_now()
        metadata = artifact.setdefault("metadata", {})
        metadata["demotion"] = {"reason": reason, "at": artifact["updated_at"],
                                "by": actor.actor_id}
        self.store.relocate(previous, artifact)
        self._audit(actor, "demote_unread", artifact_id, "success", correlation_id)
        self._event(actor, "demoted", artifact, "approved", "experimental", correlation_id)
        return artifact
