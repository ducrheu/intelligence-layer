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

    horizon = artifact.get("review_interval_days")
    if horizon is None:  # older records carried it inside metadata
        horizon = (artifact.get("metadata") or {}).get("review_interval_days")
    if isinstance(horizon, int) and horizon > 0:
        age = days_since(artifact.get("verified_at") or artifact.get("created_at"), now)
        if age is not None and age > horizon:
            flags.append(REVIEW_DUE)
    return flags
