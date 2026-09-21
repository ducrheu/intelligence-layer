from __future__ import annotations

import json
from dataclasses import dataclass
from urllib.parse import urlencode
from urllib.request import Request, urlopen


@dataclass(frozen=True)
class HermesReadOnlyConsumer:
    """Runtime-neutral Hermes consumer contract; never touches the repository."""

    base_url: str
    token: str = "local-hermes"

    def _get(self, path: str, query: dict[str, str | int] | None = None) -> dict:
        suffix = f"?{urlencode(query)}" if query else ""
        request = Request(
            f"{self.base_url.rstrip('/')}{path}{suffix}",
            headers={"X-Intelligence-Token": self.token},
            method="GET",
        )
        with urlopen(request, timeout=3) as response:
            return json.loads(response.read().decode("utf-8"))

    def get_approved_skill(self, skill_id: str) -> dict:
        return self._get(f"/v1/artifacts/skill/{skill_id}")

    def search_approved(self, kind: str, query: str, *, max_items: int = 5, max_bytes: int = 8000, max_chars: int = 1200) -> list[dict]:
        response = self._get(
            f"/v1/search/{kind}",
            {"query": query, "max_items": max_items, "max_bytes": max_bytes, "max_chars": max_chars},
        )
        return response["items"]

    def get_context_packet(self, kind: str, query: str, *, max_items: int = 5, max_bytes: int = 8000, max_chars: int = 1200) -> dict:
        return self._get(
            f"/v1/context/{kind}",
            {"query": query, "max_items": max_items, "max_bytes": max_bytes, "max_chars": max_chars},
        )

    def request_write(self, path: str, payload: dict) -> tuple[int, dict]:
        request = Request(
            f"{self.base_url.rstrip('/')}{path}",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "X-Intelligence-Token": self.token,
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urlopen(request, timeout=3) as response:
                return response.status, json.loads(response.read().decode("utf-8"))
        except Exception as exc:
            if hasattr(exc, "code") and hasattr(exc, "read"):
                return exc.code, json.loads(exc.read().decode("utf-8"))
            raise
