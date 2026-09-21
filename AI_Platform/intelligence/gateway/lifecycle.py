from __future__ import annotations

from .errors import LifecycleError

TRANSITIONS: dict[str, dict[str, set[str]]] = {
    "knowledge": {
        "candidate": {"validated", "archived"},
        "validated": {"approved", "candidate", "archived"},
        "approved": {"stale", "deprecated"},
        "stale": {"validated", "archived"},
        "deprecated": {"archived"},
        "archived": set(),
    },
    "experience": {
        "candidate": {"validated", "archived"},
        "validated": {"approved", "candidate", "archived"},
        "approved": {"archived"},
        "archived": set(),
    },
    "skill": {
        "candidate": {"experimental", "archived"},
        "experimental": {"validated", "candidate", "archived"},
        "validated": {"approved", "experimental", "archived"},
        "approved": {"deprecated"},
        "deprecated": {"archived"},
        "archived": set(),
    },
    "source": {
        "candidate": {"validated", "archived"},
        "validated": {"approved", "candidate", "archived"},
        "approved": {"stale", "deprecated"},
        "stale": {"validated", "archived"},
        "deprecated": {"archived"},
        "archived": set(),
    },
}


def assert_transition(kind: str, current: str, target: str) -> None:
    allowed = TRANSITIONS.get(kind, {}).get(current, set())
    if target not in allowed:
        raise LifecycleError(f"invalid {kind} transition: {current} -> {target}")
