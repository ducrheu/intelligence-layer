from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

from ...gateway.errors import ArtifactNotFoundError, ArtifactValidationError, AuthorizationError, LifecycleError
from ...gateway.models import Actor
from ...gateway.service import IntelligenceGateway

ALLOWED_KINDS = {"knowledge", "experience", "skill", "source"}
ARTIFACT_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
MAX_BODY_BYTES = 1_000_000


def default_actors() -> dict[str, Actor]:
    """Experimental identities only; these are not production credentials."""
    return {
        "local-agent": Actor("local-agent", "agent", frozenset({"read:approved", "write:candidate", "request:promotion", "withdraw"}), "experimental"),
        "local-hermes": Actor("local-hermes", "runtime", frozenset({"read:approved", "read:governance-metadata"}), "hermes"),
        # Hermes' learning identity: it may read candidates, propose new ones and
        # retract its own mistakes; it still cannot validate or approve anything.
        "local-hermes-writer": Actor(
            "local-hermes-writer",
            "runtime",
            frozenset({"read:approved", "read:candidate", "read:governance-metadata",
                       "write:candidate", "request:promotion", "withdraw"}),
            "hermes",
        ),
        "local-qa": Actor("local-qa", "qa", frozenset({"read:approved", "read:candidate", "validate:candidate", "request:promotion"}), "experimental"),
        "local-human": Actor("local-human", "human", frozenset({"read:approved", "read:candidate", "approve", "deprecate", "rollback", "request:promotion", "write:candidate", "withdraw", "withdraw:any"}), "experimental"),
        "local-system": Actor("local-system", "system", frozenset({"read:approved", "read:candidate", "validate:candidate", "request:promotion", "write:candidate"}), "experimental"),
        # The auto-admission identity. It holds the lifecycle scopes, but the
        # policy guard in the gateway decides whether it may use them on a given
        # artifact, and it may never act while the policy is in shadow mode.
        "policy-auto": Actor(
            "policy-auto",
            "policy",
            frozenset({"read:approved", "read:candidate", "read:governance-metadata",
                       "validate:candidate", "approve"}),
            "policy",
        ),
        # The borrowed runtime: an outside user's agent, reading on someone else's
        # behalf. Read-only, and only ever approved artifacts - no candidates, no
        # governance metadata, no event stream, so the reasoning behind moving records
        # stays inside. `external=True` is the flag that turns the exposure denylist on
        # and makes an unreadable denylist fail closed instead of reading as "no
        # restrictions" (gateway/exposure.py). Adding the identity grants nothing on its
        # own: without a minted token nobody can present it.
        "local-guest-friend": Actor(
            "local-guest-friend",
            "runtime",
            frozenset({"read:approved"}),
            "guest",
            True,
        ),
    }


class ExperimentalAPI:
    def __init__(self, root: Path, actors: dict[str, Actor] | None = None):
        self.gateway = IntelligenceGateway(root)
        self.actors = actors or default_actors()

    def actor_for_token(self, token: str | None) -> Actor:
        """Resolve a presented token to an identity.

        Tokens are minted per identity and stored as sha256 hashes (qa/identity_tokens.json);
        the plaintext lives outside the git-backed store, in the identity owner's own
        credential file. The previous scheme - the token *being* the identity name - made
        every identity claimable by anyone who could reach the port, which also made the
        human-only approve rule and the auto-admission trust checks unenforceable. Names are
        still accepted, but only while INTELLIGENCE_ALLOW_LEGACY_NAMES is not "0", so the
        migration can go identity by identity instead of all at once.
        """
        if not token:
            raise AuthorizationError("missing experimental identity")
        index = self._token_index()
        if index:
            digest = "sha256:" + hashlib.sha256(token.strip().encode("utf-8")).hexdigest()
            for actor_id, recorded in index.items():
                if hmac.compare_digest(recorded, digest):
                    return self.actors[actor_id]
        if os.environ.get("INTELLIGENCE_ALLOW_LEGACY_NAMES", "1") != "0" and token in self.actors:
            return self.actors[token]
        raise AuthorizationError("unknown experimental identity token")

    def _token_index(self) -> dict[str, str]:
        """Minted token hashes, loaded once per process."""
        cached = getattr(self, "_token_index_cache", None)
        if cached is not None:
            return cached
        index: dict[str, str] = {}
        path = self.gateway.state / "identity_tokens.json"
        if path.is_file():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                index = {k: str(v) for k, v in (data.get("tokens") or {}).items()}
            except (ValueError, OSError):
                index = {}
        self._token_index_cache = index
        return index


def _handler(api: ExperimentalAPI):
    class Handler(BaseHTTPRequestHandler):
        server_version = "IntelligencePhase2/0.1"

        def log_message(self, format: str, *args: Any) -> None:
            return

        def _json(self, status: int, value: Any) -> None:
            payload = json.dumps(value, ensure_ascii=True).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            try:
                self.wfile.write(payload)
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                return

        def _actor(self) -> Actor:
            return api.actor_for_token(self.headers.get("X-Intelligence-Token"))

        def _correlation_id(self) -> str | None:
            value = self.headers.get("X-Correlation-ID")
            return value[:128] if value else None

        def _path_parts(self) -> list[str]:
            path = urlparse(self.path).path
            parts = [unquote(part) for part in path.split("/") if part]
            if any(part in {".", ".."} or "\\" in part for part in parts):
                raise ValueError("invalid path")
            return parts

        def _kind_id(self, parts: list[str]) -> tuple[str, str]:
            if len(parts) != 4 or parts[0:2] != ["v1", "artifacts"]:
                raise ValueError("expected /v1/artifacts/{kind}/{id}")
            kind, artifact_id = parts[2], parts[3]
            if kind not in ALLOWED_KINDS or not ARTIFACT_ID.fullmatch(artifact_id):
                raise ValueError("invalid artifact selector")
            return kind, artifact_id

        def _read_body(self) -> dict[str, Any]:
            raw_length = self.headers.get("Content-Length")
            try:
                length = int(raw_length or "0")
            except ValueError as exc:
                raise ValueError("invalid content length") from exc
            if length < 1 or length > MAX_BODY_BYTES:
                raise ValueError("request body too large or empty")
            data = self.rfile.read(length)
            if len(data) != length:
                raise ValueError("incomplete request body")
            value = json.loads(data.decode("utf-8"))
            if not isinstance(value, dict):
                raise ValueError("request body must be an object")
            return value

        def _error(self, exc: Exception) -> None:
            if isinstance(exc, AuthorizationError):
                status = HTTPStatus.FORBIDDEN
            elif isinstance(exc, (ArtifactNotFoundError, KeyError)):
                status = HTTPStatus.NOT_FOUND
            elif isinstance(exc, (ArtifactValidationError, LifecycleError, ValueError, json.JSONDecodeError)):
                status = HTTPStatus.BAD_REQUEST
            elif isinstance(exc, PermissionError):
                status = HTTPStatus.FORBIDDEN
            else:
                status = HTTPStatus.INTERNAL_SERVER_ERROR
            self._json(status, {"error": type(exc).__name__, "message": str(exc)[:500]})

        def do_GET(self) -> None:
            try:
                actor = self._actor()
                parsed = urlparse(self.path)
                parts = self._path_parts()
                if parts == ["health"]:
                    self._json(HTTPStatus.OK, {"status": "ok", "bind": self.server.server_address[0]})
                    return
                if len(parts) == 3 and parts[:2] == ["v1", "search"] and parts[2] in ALLOWED_KINDS:
                    params = parse_qs(parsed.query, keep_blank_values=False)
                    query = params.get("query", [""])[0]
                    if not query:
                        raise ValueError("query is required")
                    scope = params.get("scope", [None])[0]
                    max_items = int(params.get("max_items", ["10"])[0])
                    max_bytes = int(params.get("max_bytes", ["20000"])[0])
                    max_chars = int(params.get("max_chars", ["12000"])[0])
                    result = self._gateway_search(actor, parts[2], query, scope, max_items, max_bytes, max_chars)
                    self._json(HTTPStatus.OK, {"items": result, "bounded": True})
                    return
                if len(parts) == 3 and parts[:2] == ["v1", "context"] and parts[2] in ALLOWED_KINDS:
                    result = self._context_packet(actor, parts[2], parsed.query)
                    self._json(HTTPStatus.OK, result)
                    return
                if parts == ["v1", "events"]:
                    params = parse_qs(parsed.query, keep_blank_values=False)
                    since = int(params.get("since", ["0"])[0])
                    max_items = int(params.get("max_items", ["20"])[0])
                    self._json(HTTPStatus.OK, api.gateway.read_events(actor, since, max_items))
                    return
                kind, artifact_id = self._kind_id(parts)
                if kind == "knowledge":
                    result = api.gateway.get_knowledge(actor, artifact_id)
                elif kind == "experience":
                    result = api.gateway.get_experience(actor, artifact_id)
                elif kind == "skill":
                    result = api.gateway.get_skill(actor, artifact_id)
                else:
                    result = api.gateway.get_source(actor, artifact_id)
                self._json(HTTPStatus.OK, result)
            except Exception as exc:
                self._error(exc)

        def _gateway_search(self, actor: Actor, kind: str, query: str, scope: str | None, max_items: int, max_bytes: int, max_chars: int) -> list[dict[str, Any]]:
            return api.gateway.search(actor, kind, query, scope, max_items, max_bytes, max_chars)

        def _context_packet(self, actor: Actor, kind: str, query_string: str) -> dict[str, Any]:
            if "read:approved" not in actor.scopes:
                raise AuthorizationError("context packets require approved read access")
            params = parse_qs(query_string, keep_blank_values=False)
            query = params.get("query", [""])[0]
            if not query:
                raise ValueError("query is required")
            max_items = int(params.get("max_items", ["5"])[0])
            max_bytes = int(params.get("max_bytes", ["8000"])[0])
            max_chars = int(params.get("max_chars", ["1200"])[0])
            approved = api.gateway.search(actor, kind, query, None, max_items, max_bytes, max_chars)
            warnings: list[dict[str, Any]] = []
            if "read:governance-metadata" in actor.scopes:
                metadata_actor = Actor(actor.actor_id, actor.role, frozenset({"read:approved", "read:candidate"}), actor.runtime, actor.external)
                for item in api.gateway.search(metadata_actor, kind, query, None, max_items, max_bytes, 1):
                    if item["status"] != "approved":
                        artifact = api.gateway.store.load(item["id"], kind, ("candidate", "experimental", "validated", "stale", "deprecated"))
                        warnings.append({
                            "id": artifact["id"],
                            "kind": artifact["kind"],
                            "status": artifact["status"],
                            "verified": artifact["verified"],
                            "title": artifact["title"],
                            "provenance": artifact.get("provenance", [])[:3],
                            "source": artifact.get("source", [])[:3],
                            "evidence": artifact.get("evidence", [])[:8],
                            "warning": "metadata_only_not_approved_knowledge",
                        })
            return {
                "query": query,
                "artifacts": approved,
                "provenance": [entry for artifact in approved for entry in artifact.get("provenance", [])],
                "retrieval_limits": {"max_items": max_items, "max_bytes": max_bytes, "max_chars": max_chars},
                "warnings": warnings,
            }

        def do_POST(self) -> None:
            try:
                actor = self._actor()
                parts = self._path_parts()
                correlation_id = self._correlation_id()
                if parts == ["v1", "candidates"]:
                    artifact = self._read_body()
                    if "role" in artifact or "actor" in artifact:
                        artifact.pop("role", None)
                        artifact.pop("actor", None)
                    result = api.gateway.submit_candidate(actor, artifact, correlation_id)
                    self._json(HTTPStatus.CREATED, result)
                    return
                if len(parts) == 4 and parts[:2] == ["v1", "validate"]:
                    kind, artifact_id = parts[2], parts[3]
                    if kind not in ALLOWED_KINDS or not ARTIFACT_ID.fullmatch(artifact_id):
                        raise ValueError("invalid artifact selector")
                    result = api.gateway.validate_candidate(actor, artifact_id, kind, correlation_id)
                    self._json(HTTPStatus.OK, result)
                    return
                if len(parts) == 4 and parts[:2] == ["v1", "promotion"]:
                    kind, artifact_id = parts[2], parts[3]
                    if kind not in ALLOWED_KINDS or not ARTIFACT_ID.fullmatch(artifact_id):
                        raise ValueError("invalid artifact selector")
                    result = api.gateway.request_promotion(actor, artifact_id, kind, correlation_id)
                    self._json(HTTPStatus.OK, result)
                    return
                if len(parts) == 4 and parts[:2] == ["v1", "evidence"]:
                    kind, artifact_id = parts[2], parts[3]
                    if kind not in ALLOWED_KINDS or not ARTIFACT_ID.fullmatch(artifact_id):
                        raise ValueError("invalid artifact selector")
                    body = self._read_body()
                    result = api.gateway.record_validation_evidence(
                        actor, artifact_id, kind, body.get("evidence"), correlation_id)
                    self._json(HTTPStatus.OK, result)
                    return
                if len(parts) == 4 and parts[:2] == ["v1", "withdraw"]:
                    kind, artifact_id = parts[2], parts[3]
                    if kind not in ALLOWED_KINDS or not ARTIFACT_ID.fullmatch(artifact_id):
                        raise ValueError("invalid artifact selector")
                    reason = None
                    if int(self.headers.get("Content-Length") or 0) > 0:
                        reason = str(self._read_body().get("reason") or "")
                    result = api.gateway.withdraw(actor, artifact_id, kind, reason, correlation_id)
                    self._json(HTTPStatus.OK, result)
                    return
                raise ValueError("unknown operation")
            except Exception as exc:
                self._error(exc)

    return Handler


def build_server(root: Path, host: str = "127.0.0.1", port: int = 0, actors: dict[str, Actor] | None = None) -> ThreadingHTTPServer:
    if host != "127.0.0.1":
        raise ValueError("Phase 2 experimental API must bind to 127.0.0.1")
    api = ExperimentalAPI(root, actors)
    server = ThreadingHTTPServer((host, port), _handler(api))
    server.daemon_threads = True
    return server
