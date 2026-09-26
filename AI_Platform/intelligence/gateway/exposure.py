"""Who an *external* reader may not see.

The knowledge base is one library with one owner. A borrowed runtime - an outside
user's agent - reads the same approved corpus, but "everything approved" is not the
same set as "everything the owner would hand a stranger". This module holds that
difference in *data* (qa/guest-denylist.json) rather than in the external agent's
prompt, because the prompt is not a security control: OWASP LLM07 states plainly that
"the system prompt should not be considered a secret, nor should it be used as a
security control", and OWASP LLM06 requires authorization to live in the downstream
system rather than in a model's judgement.

Three properties matter more than the lookup itself:

1. **Deny by absence, not by remembering.** The denylist is consulted inside the
   pre-retrieval predicate (gateway/service.py::_search_documents) and in the by-id
   path (::_get), so a denied record is not merely filtered from the response - it is
   never a candidate. Nothing about it (count, score, ordering) can leak.
2. **A control that cannot be evaluated must fail closed.** If the denylist is
   missing or malformed for an external identity, that identity reads *nothing*.
   The alternative - treating an unreadable file as "no restrictions" - turns a
   broken/stale control into silent full exposure, which is the failure mode this
   whole mechanism exists to prevent.
3. **A refusal is indistinguishable from a miss.** Denied reads raise the same
   ArtifactNotFoundError and write the same audit action as an id that never existed,
   so probing by id cannot map the corpus.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from .models import Actor

DENYLIST_PATH = Path("qa") / "guest-denylist.json"

#: Returned when an external identity's control cannot be evaluated. Deliberately not
#: an empty set: empty means "nothing denied", which is the opposite verdict.
DENY_ALL: None = None

_warned = False


def _warn(reason: str, path: Path) -> None:
    """Say it once per process. A silent deny-all is a support nightmare, and a silent
    deny-none is a breach - either way somebody needs to see it in the journal."""
    global _warned
    if not _warned:
        _warned = True
        print(f"[exposure] {reason}: {path} - external identities will read nothing",
              file=sys.stderr, flush=True)


def normalize(raw: str) -> str:
    """Accept both `id` and `kind/id` in the file: hand-edited lists get written both
    ways, and silently ignoring the `kind/` form would under-deny."""
    text = str(raw).strip()
    return text.split("/", 1)[1] if "/" in text else text


def denied_ids(root: Path, actor: Actor) -> set[str] | None:
    """Ids `actor` must not read.

    Returns an empty set for the owner's own identities (the denylist is not their
    business), a set of ids for an external identity with a readable control file, and
    ``DENY_ALL`` (None) when an external identity's control cannot be evaluated.
    """
    if not actor.external:
        return set()
    path = Path(root) / DENYLIST_PATH
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        _warn("denylist missing", path)
        return DENY_ALL
    except (OSError, ValueError) as exc:
        _warn(f"denylist unreadable ({exc.__class__.__name__})", path)
        return DENY_ALL
    if not isinstance(payload, dict):
        _warn("denylist is not an object", path)
        return DENY_ALL
    # Accept {"deny": {...}} or a bare {identity: [...]} map.
    deny_block = payload.get("deny")
    entries: dict = deny_block if isinstance(deny_block, dict) else payload
    listed = entries.get(actor.actor_id)
    if listed is None:
        # An external identity with no entry has no defined exposure. Guessing "then
        # nothing is denied" is exactly the guess that leaks.
        _warn(f"no denylist entry for {actor.actor_id}", path)
        return DENY_ALL
    if not isinstance(listed, list):
        _warn(f"denylist entry for {actor.actor_id} is not a list", path)
        return DENY_ALL
    return {normalize(item) for item in listed if str(item).strip()}


def may_read(denied: set[str] | None, kind: str, artifact_id: str) -> bool:
    """True when this artifact survives the exposure control."""
    if denied is None:  # DENY_ALL
        return False
    return normalize(f"{kind}/{artifact_id}") not in denied


#: Fields that can name other records. A reference is an id in plain sight:
#: `experience:exp-wsl-huyi-quant-data-fabric-...` names both the record it points at and,
#: often, its subject - so an unscrubbed provenance/source list hands back the existence of
#: exactly what the denylist withheld. Found by scanning a *visible* record whose body was
#: clean but whose source entry referenced a denied one.
REFERENCE_FIELDS = ("source", "provenance", "evidence")


def _entry_visible(entry: Any, denied: set[str] | None) -> bool:
    if denied is None:
        return False
    if not isinstance(entry, dict):
        return True
    ref = str(entry.get("ref") or "").strip()
    if not ref:
        return True
    head, _, tail = ref.partition(":")
    ident = tail if tail else head          # `kind:id` or a bare id
    return normalize(ident) not in denied


def scrub_entries(entries: list[Any], denied: set[str] | None) -> list[Any]:
    return [entry for entry in entries if _entry_visible(entry, denied)]


def scrub_references(artifact: dict[str, Any], denied: set[str] | None) -> dict[str, Any]:
    """A copy of `artifact` with references to records this reader may not see removed.

    Silent on purpose: an explicit "one reference was withheld" marker would hand back the
    very fact the denylist exists to withhold, the same reason a denied id answers
    "not found" instead of "denied".
    """
    out = dict(artifact)
    for field in REFERENCE_FIELDS:
        entries = out.get(field)
        if isinstance(entries, list):
            out[field] = scrub_entries(entries, denied)
    return out
