from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

# Review flags. These drive attention, never deletion: a record that nobody has
# read is a question to answer ("is this wrong, or unfindable, or simply new?"),
# and the answer depends on why it is unused, which no counter can know.
NEVER_USED = "never-used"
SURFACED_ONLY = "surfaced-only"
REVIEW_DUE = "review-due"
UNVERIFIED = "auto-admitted-unverified"

# Freshness states. One definition, shared by the review flags and by retrieval
# ordering: a record must not be stale to the reporter and fresh to the ranker.
FRESH = "fresh"
EXPIRED = "expired"


def _parse(stamp: str | None) -> datetime | None:
    if not stamp:
        return None
    try:
        text = stamp.replace("Z", "+00:00")
        moment = datetime.fromisoformat(text)
    except ValueError:
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def days_since(stamp: str | None, now: datetime | None = None) -> float | None:
    moment = _parse(stamp)
    if moment is None:
        return None
    reference = now or datetime.now(timezone.utc)
    return round((reference - moment).total_seconds() / 86400.0, 1)


def review_flags(artifact: dict[str, Any], explicit: dict[str, Any], surfaced: dict[str, Any],
                 now: datetime | None = None) -> list[str]:
    """What a human should look at, given how the artifact has actually been used.

    Usage telemetry is the only signal that can falsify a knowledge base: an
    artifact nothing ever retrieves is either wrong, unfindable, or premature, and
    all three are worth knowing. Surfacing is tracked apart from retrieval because
    a search hit means the record was *findable*, not that it was read.
    """
    if artifact.get("status") not in ("approved", "validated"):
        return []

    key = f"{artifact.get('kind')}/{artifact.get('id')}"
    used = explicit.get(key) or {}
    seen = surfaced.get(key) or {}
    flags: list[str] = []

    if not used.get("count"):
        # A record auto-admitted by policy never passed a human, so "nobody has
        # read it yet" carries more weight there than for a hand-approved one.
        auto = (artifact.get("metadata") or {}).get("auto_admission") or {}
        flags.append(NEVER_USED if auto.get("auto_approve") else SURFACED_ONLY)
        if auto.get("auto_approve") and (auto.get("tier") or "").startswith("T2"):
            flags.append(UNVERIFIED)
    elif seen.get("count") and int(seen["count"]) > 10 * int(used["count"]):
        flags.append(SURFACED_ONLY)  # found constantly, read almost never

    if freshness(artifact, now) != FRESH:
        # Both halves count as review-due on purpose: the flag is "a human should look
        # at this record's currency", and inventing a second label would put a string in
        # the weekly report that every reader of it has to learn separately.
        flags.append(REVIEW_DUE)
    return flags


def review_horizon(artifact: dict[str, Any]) -> int | None:
    """The record's review interval in days, wherever it was written."""
    horizon = artifact.get("review_interval_days")
    if horizon is None:  # older records carried it inside metadata
        horizon = (artifact.get("metadata") or {}).get("review_interval_days")
    return horizon if isinstance(horizon, int) and horizon > 0 else None


def freshness(artifact: dict[str, Any], now: datetime | None = None) -> str:
    """``expired`` / ``review-due`` / ``fresh`` for one artifact.

    Two independent ways to be stale, checked in order of severity:

    - ``expires_at`` has passed - the record states it is no longer valid;
    - the review interval has elapsed since it was verified (or created, when nothing
      ever verified it).

    Deliberately *not* a boolean and deliberately not "hide it": an expired record is
    still the answer to "what did we say about X". Retrieval demotes these; only a human
    deprecates them.
    """
    reference = now or datetime.now(timezone.utc)
    expires = _parse(artifact.get("expires_at"))
    if expires is not None and expires <= reference:
        return EXPIRED
    horizon = review_horizon(artifact)
    if horizon is None:
        return FRESH
    age = days_since(artifact.get("verified_at") or artifact.get("created_at"), reference)
    return REVIEW_DUE if age is not None and age > horizon else FRESH
