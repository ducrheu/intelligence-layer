from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from .attestation import verify_test_evidence

# Bump when the rules change: a decision must be attributable to the policy that
# made it, and rolling back the policy has to be possible.
POLICY_VERSION = "1.0.0"

# Fields the schema knows about. Anything else is a reason to stop: a policy that
# silently ignores unrecognised input is a policy that can be walked around.
KNOWN_FIELDS = frozenset({
    "id", "kind", "scope", "status", "version", "title", "content", "created_by",
    "created_at", "updated_at", "source", "provenance", "verified", "verified_by",
    "verified_at", "applies_to", "compatibility", "expires_at", "review_interval_days",
    "tests", "evidence", "supersedes", "superseded_by", "metadata",
})

# Who may produce an artifact that the policy considers admitting on its own.
# Everything else goes to a human, no matter how clean it looks.
TRUSTED_PRODUCERS = frozenset({"local-hermes-writer", "local-agent"})

# A skill that claims any of this is claiming authority; a human reads it.
PERMISSION_DENYLIST = re.compile(
    r"write|execute|exec|shell|sudo|admin|delete|remove|network|install|credential|secret|token",
    re.IGNORECASE,
)
# ...unless the entry is talking about what it must NOT do. Permission lists in the
# wild are prose ("read-only - it must never write candidates"), and a bare
# substring match on "write" reads a denial as a claim. That exact trap already
# burned this project once, when "approve" matched inside "search_approved".
DENIAL_PREFIX = re.compile(
    r"^\s*(?:read[- ]?only|never|no\b|not\b|forbidden|must not|must never|cannot|can't|denied|without|free of)\b",
    re.IGNORECASE,
)

# Kinds whose admission needs no code execution to verify.
NON_EXECUTABLE_KINDS = frozenset({"knowledge", "experience"})

# Scopes that stay on this machine, and the one that does not.
PRIVATE_SCOPES = frozenset({"domain", "local", "project"})
PUBLIC_SCOPES = frozenset({"shared"})

TIER_SHADOW = "T3"          # needs a human today
TIER_AUTO_VALIDATE = "T1"   # the policy may move candidate -> validated
TIER_AUTO_APPROVE = "T2"    # the policy may also move validated -> approved


@dataclass(frozen=True)
class AdmissionVerdict:
    """What the policy would decide, and why. Deterministic: no timestamps here,
    so an identical resubmission produces an identical verdict and stays
    idempotent. The "when" belongs to the event stream, not to the artifact."""

    policy_version: str
    tier: str
    auto_validate: bool
    auto_approve: bool
    reasons: tuple[str, ...] = ()
    blocking: tuple[str, ...] = field(default=())

    @property
    def automatable(self) -> bool:
        return self.auto_validate or self.auto_approve

    def to_dict(self) -> dict[str, Any]:
        return {
            "policy_version": self.policy_version,
            "tier": self.tier,
            "auto_validate": self.auto_validate,
            "auto_approve": self.auto_approve,
            "reasons": list(self.reasons),
            "blocking": list(self.blocking),
        }


def _blocked(blocking: list[str], reasons: list[str]) -> AdmissionVerdict:
    return AdmissionVerdict(POLICY_VERSION, TIER_SHADOW, False, False, tuple(reasons), tuple(blocking))


def evaluate(artifact: dict[str, Any], submitter: str | None,
             disk_hashes: dict[str, str] | None = None) -> AdmissionVerdict:
    """Decide what a policy identity may do with this artifact, fail-closed.

    The shape of the rule set comes from supply-chain practice: the producer must
    be known, the payload must not carry unrecognised fields, the evidence must be
    something the gateway can check without running the author's code, and
    anything that reaches beyond this machine or claims authority stops at a human.
    """
    blocking: list[str] = []
    reasons: list[str] = []

    unknown = sorted(set(artifact) - KNOWN_FIELDS)
    if unknown:
        blocking.append(f"unrecognised field(s) {unknown}: fail closed rather than ignore them")

    producer = artifact.get("created_by")
    if submitter not in TRUSTED_PRODUCERS:
        blocking.append(f"submitting identity {submitter!r} is not in the trusted producer list")
    if producer not in TRUSTED_PRODUCERS:
        blocking.append(f"created_by {producer!r} is not in the trusted producer list")

    scope = artifact.get("scope")
    if scope not in PRIVATE_SCOPES:
        if scope in PUBLIC_SCOPES:
            blocking.append(f"scope {scope!r} is shared; an artifact another party can read needs a human")
        else:
            blocking.append(f"scope {scope!r} is not a known private scope, so it is not assumed private")

    kind = artifact.get("kind")
    if kind in NON_EXECUTABLE_KINDS:
        reasons.append(f"{kind} carries no executable payload to verify")
    elif kind == "skill":
        # A skill is admissible when someone other than its author already ran its
        # tests and the gateway can re-check that the same bytes still pass for a
        # matching artifact. The gateway never executes the author's code itself.
        proven, detail = verify_test_evidence(artifact, artifact.get("evidence") or [], disk_hashes)
        if proven:
            reasons.append(detail)
        else:
            blocking.append(f"skill is not verified: {detail}")
    else:
        blocking.append(f"kind {kind!r} has no automated verification path")

    if not artifact.get("review_interval_days"):
        blocking.append("no review_interval_days: an admission without a validity horizon cannot be revisited")

    permissions = [str(item) for item in (artifact.get("metadata") or {}).get("permissions", [])]
    claims = sorted({item for item in permissions
                     if PERMISSION_DENYLIST.search(item) and not DENIAL_PREFIX.match(item)})
    if claims:
        blocking.append(f"metadata.permissions claims authority: {claims}")

    if artifact.get("verified"):
        blocking.append("the artifact claims verified=true; only an approval may set that")

    if blocking:
        return _blocked(blocking, reasons)

    reasons.insert(0, f"producer {producer!r} is trusted, scope {scope!r} is local, {kind} is non-executable")
    return AdmissionVerdict(
        policy_version=POLICY_VERSION,
        tier=TIER_AUTO_APPROVE,
        auto_validate=True,
        auto_approve=True,
        reasons=tuple(reasons),
    )
