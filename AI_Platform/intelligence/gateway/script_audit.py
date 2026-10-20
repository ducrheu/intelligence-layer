"""Audit a skill's attached scripts before they are shared.

Why this is a gate and not a report: a skill's body is read, but its script is
run. Once the store is shared, "every agent on this machine can execute this"
is the actual claim being made, so the text that arrives with a skill has to be
read by something mechanical before a policy is allowed to approve it.

Two classes of finding, two outcomes:

- a credential (private key, provider token, password assignment) -> the skill
  is refused outright. Publishing a secret to a public git repo cannot be undone
  by a later review.
- a destructive or remote-execution pattern -> a human reads it. The pattern
  list is deliberately narrow: it names things that are always a decision
  (`rm -rf /`, `curl | sh`, writing /dev/sd*, `mkfs`) rather than everything that
  could be misused, because a gate that fires on ordinary code teaches everyone
  to click through it.

The audit result is bound to content by sha256, so an approval cannot be earned
by one payload and spent on another.
"""

from __future__ import annotations

import hashlib
import re
from typing import Any

SECRET_PATTERNS: dict[str, re.Pattern[str]] = {
    "private-key": re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    "github-token": re.compile(r"\bgh[pousr]_[A-Za-z0-9._-]{10,}"),
    "openai-style-key": re.compile(r"\bsk-[A-Za-z0-9_.-]{10,}"),
    "aws-key": re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    "slack-token": re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}"),
    "jwt": re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}"),
    "assigned-secret": re.compile(
        r"(?i)\b(api[_-]?key|appsecret|app_secret|secret[_-]?key|access[_-]?token|password)\b"
        r"\s*[:=]\s*[\"']?[A-Za-z0-9/+=_-]{8,}"),
}

# Documentation teaches with fake credentials: `ghp_xx...xxxx`, `sk-xxx`, `YOUR_API_KEY`,
# `password=password`. A gate that refuses those refuses the skills that explain how to
# configure anything, so a hit counts only when it does not look like a placeholder.
PLACEHOLDER = re.compile(
    r"(?i)(x{3,}|\.{3,}|<[^>]*>|your[_-]?|\bexample\b|placeholder|redacted|dummy|\bfake\b|"
    r"token[_-]?here|api[_-]?key[_-]?here|\*\*\*|changeme|replace[_-]?me)")


def _looks_like_key(value: str) -> bool:
    """A credential is a literal: no whitespace, no call syntax, mixed shape."""
    candidate = re.split(r"[:=]\s*", value, maxsplit=1)[-1].strip("\"' ")
    if len(candidate) < 16:
        return False
    if re.search(r"[(){}$\s<>]", candidate):
        return False  # get_valid_token(), $VAR, <placeholder>
    has_digit = bool(re.search(r"\d", candidate))
    has_alpha = bool(re.search(r"[A-Za-z]", candidate))
    if not (has_digit and has_alpha):
        return False
    return not (candidate.isalpha() and candidate.islower())


def _is_real_secret(value: str, kind: str = "assigned-secret") -> bool:
    """Judge the *value*, not the whole match: `password = password` is a variable."""
    candidate = re.split(r"[:=]\s*", value, maxsplit=1)[-1].strip("\"' ") or value
    if PLACEHOLDER.search(candidate) or PLACEHOLDER.search(value):
        return False
    if kind != "assigned-secret":
        # A known prefix (ghp_, sk-, xox, AKIA, eyJ) is itself the evidence. Real
        # values are long and base62-ish; `sk-body-color` from a CSS template is
        # neither, and matching it would flag every design reference in the store.
        return len(candidate) >= 20 and (bool(re.search(r"\d", candidate)) or len(candidate) >= 32)
    lowered = candidate.lower()
    if lowered in {"password", "passwd", "pwd", "token", "secret", "api_key", "apikey", "key"}:
        return False
    return _looks_like_key(candidate)

DANGEROUS_PATTERNS: dict[str, re.Pattern[str]] = {
    "recursive-delete-root": re.compile(r"rm\s+(-[a-zA-Z]*\s+)*-?[rf]{1,2}[a-zA-Z]*\s+/(\s|$|\*)"),
    "delete-home": re.compile(r"rm\s+-[a-zA-Z]*r[a-zA-Z]*f?\s+(~|\$HOME)(/|\s|$)"),
    "pipe-to-shell": re.compile(r"(curl|wget)[^\n|]*\|\s*(sudo\s+)?(ba|z|k)?sh\b"),
    "base64-exec": re.compile(r"(base64\s+(-d|--decode)|atob\()[^\n]{0,60}(sh\b|eval\b|exec\()"),
    "raw-disk-write": re.compile(r"\bdd\b[^\n]{0,80}of=/dev/(sd|nvme|hd)"),
    "mkfs": re.compile(r"\bmkfs(\.\w+)?\b"),
    "sudo": re.compile(r"(^|\s|;|&&|\|\|)sudo\s"),
    "ssh-key-write": re.compile(r">\s*~?/?\.ssh/authorized_keys"),
    "crontab-overwrite": re.compile(r"crontab\s+(-r|-e|[^\n]*\s-\s)"),
    "chmod-world-writable": re.compile(r"chmod\s+(-R\s+)?0?777\s+/"),
    "fork-bomb": re.compile(r":\(\)\s*\{\s*:\s*\|\s*:\s*&\s*\}\s*;\s*:"),
    "credential-exfil": re.compile(r"(curl|wget|nc|scp)[^\n]{0,120}(TOKEN|SECRET|PASSWORD|\.ssh/|id_rsa)"),
}


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def audit(files: list[dict[str, Any]]) -> dict[str, Any]:
    """Audit attached files. `files` items carry path/content/sha256."""
    secrets: list[dict[str, str]] = []
    dangers: list[dict[str, str]] = []
    mismatched: list[str] = []
    for item in files:
        path = str(item.get("path") or "?")
        content = item.get("content")
        if not isinstance(content, str):
            mismatched.append(f"{path}: no text content recorded")
            continue
        recorded = str(item.get("sha256") or "")
        if recorded and recorded != sha256_text(content):
            # The audit must describe the bytes that will be stored. A digest
            # that does not match its own payload means someone built the record
            # to pass review and the store to run.
            mismatched.append(f"{path}: sha256 does not match its content")
            continue
        for name, pattern in SECRET_PATTERNS.items():
            for match in pattern.finditer(content):
                if _is_real_secret(match.group(), name):
                    secrets.append({"path": path, "kind": name})
                    break
        # Destructive patterns only matter in something that can run. A reference
        # document that mentions `sudo` is explaining a concept, not doing one.
        if path.endswith((".py", ".sh", ".js", ".ts", ".cjs", ".mjs", ".bash", ".zsh")):
            for name, pattern in DANGEROUS_PATTERNS.items():
                if pattern.search(content):
                    dangers.append({"path": path, "kind": name})
    return {
        "clean": not secrets and not dangers and not mismatched,
        "secrets": secrets,
        "dangers": dangers,
        "mismatched": mismatched,
        "files": len(files),
        "digest": hashlib.sha256(
            "".join(sorted(f"{item.get('path')}:{item.get('sha256')}" for item in files)).encode()
        ).hexdigest(),
    }
