from __future__ import annotations

from .errors import AuthorizationError
from .models import Actor


def require(actor: Actor, action: str) -> None:
    if action not in actor.scopes:
        raise AuthorizationError(f"{actor.actor_id} is not authorized for {action}")


def can_read_approved(actor: Actor) -> bool:
    return "read:approved" in actor.scopes or actor.role == "human"


def can_read_candidate(actor: Actor) -> bool:
    return "read:candidate" in actor.scopes or actor.role in {"qa", "human"}


def can_write_candidate(actor: Actor) -> bool:
    return "write:candidate" in actor.scopes or actor.role in {"agent", "qa", "system", "human"}
