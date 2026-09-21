from __future__ import annotations

import hashlib
import json
from typing import Any

# Evidence the gateway can re-check by itself. Anything softer than this is a
# claim by a party with an interest in the outcome.
MACHINE_EVIDENCE_TYPE = "test_run"

# Who may produce evidence that counts. The author is never in this list: evidence
# a party records about its own work is a claim, not verification, and the whole
# point of the split is that the same context cannot judge itself.
VERIFIER_IDENTITIES = frozenset({"local-qa", "local-system", "policy-auto", "local-human"})

# What the digest covers. Status, timestamps, verification flags and evidence are
# excluded so a lifecycle transition does not invalidate evidence that was earned
# before it; changing the *content* does invalidate it.
DIGEST_FIELDS = ("id", "kind", "scope", "version", "title", "content", "metadata")

# Metadata the gateway writes itself. Excluded from the digest for the same reason
# it is excluded from the duplicate comparison: recording a verdict must not change
# the subject that evidence was recorded against, or every piece of evidence would
# invalidate itself the moment it was filed.
GATEWAY_METADATA_KEYS = ("auto_admission", "withdraw", "approval_action")


def artifact_digest(artifact: dict[str, Any]) -> str:
    """A stable fingerprint of what the artifact claims."""
    payload = {field: artifact.get(field) for field in DIGEST_FIELDS}
    metadata = dict(payload.get("metadata") or {})
    for key in GATEWAY_METADATA_KEYS:
        metadata.pop(key, None)
    payload["metadata"] = metadata
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def verify_test_evidence(artifact: dict[str, Any], evidence: list[Any],
                         disk_hashes: dict[str, str] | None = None) -> tuple[bool, str]:
    """Is there evidence that *this* artifact's tests ran and passed?

    Three things have to line up, and all three are re-checked at decision time
    rather than trusted from the record:

    1. the recorder is a verifier identity, not the author;
    2. the artifact has not changed since (its digest is the recorded subject);
    3. the files that were executed still have the recorded hashes on disk.

    Point 3 is what makes this different from "the author says the tests pass":
    the bytes that were run are pinned, so swapping a test file after the fact
    invalidates the evidence instead of inheriting it.
    """
    digest = artifact_digest(artifact)
    rejection: list[str] = []
    unstamped: list[str] = []
    for record in evidence or []:
        if not isinstance(record, dict) or record.get("type") != MACHINE_EVIDENCE_TYPE:
            continue
        recorder = record.get("recorded_by")
        if recorder is None:
            # Never stamped by the gateway, so it is an author-supplied claim.
            unstamped.append(record.get("type") or "unnamed")
            continue
        if recorder not in VERIFIER_IDENTITIES:
            rejection.append(f"recorded_by {recorder!r} is not a verifier identity")
            continue
        if record.get("exit_code") != 0:
            rejection.append(f"exit_code {record.get('exit_code')!r} is not a pass")
            continue
        if record.get("subject_digest") != digest:
            rejection.append("the artifact changed after the evidence was recorded (subject_digest mismatch)")
            continue
        files = record.get("files")
        if not isinstance(files, list) or not files:
            rejection.append("the evidence names no executed files, so nothing can be re-checked")
            continue
        hashes = disk_hashes or {}
        stale = [item.get("path") for item in files
                 if not isinstance(item, dict) or hashes.get(item.get("path")) != item.get("sha256")]
        if stale:
            rejection.append(f"the executed files changed since (sha256 mismatch): {stale}")
            continue
        return True, (f"test_run by {recorder} on {len(files)} file(s); "
                      f"subject {digest[7:19]}…, file hashes re-checked")
    if unstamped:
        rejection.append(f"{len(unstamped)} gateway-unstamped record(s) ignored as author claims")
    return False, "; ".join(rejection) or "no machine-checkable test_run evidence"
