"""Tamper-evident chaining for the append-only audit log.

The audit log is the root of trust for every governance decision in this layer: who
filed an artifact, who may retract it, which submissions a trust list may accept. An
append-only file with no chain cannot carry that weight - rewriting one line leaves no
trace - and in this deployment the log is a plain writable file next to the store. So
every record now carries two fields:

- ``prev_hash``: the previous record's ``hash`` (or the anchor described below).
- ``hash``: a digest of the record itself, with ``hash`` excluded.

Two properties are asserted by ``tests/test_audit_chain.py``, and both matter:

1. **The chain covers the log's past.** The first chained record points at a digest of
   everything written *before* the chain existed, so tampering with the pre-chain
   prefix is detectable too instead of being grandfathered in.
2. **A verifier that cannot fail is not evidence.** The test drives the verifier
   against deliberately broken fixtures - an edited line, a deleted line, reordered
   lines - and asserts it goes red for each.

What this does and does not buy:

- It makes tampering **detectable**, not impossible. Any process that can write the
  file can also recompute the whole chain; the log has no signature.
- A **truncated tail is not detectable by the chain alone** - a shorter chain is still
  a valid chain. That is why the daily anchor job commits the tail hash outside the
  file (see ``qa/audit-anchor.json``); the anchor is the only thing that can speak for
  "the log used to be longer". Do not "fix" the verifier to reject a short log: it
  cannot know without the anchor, and pretending otherwise would break the honest case
  of a freshly created log.
- The lock is not optional. The gateway service and the CLI tools that import the
  gateway directly (auto-admit, validate, approve) are separate processes appending to
  the same file, and an unguarded read-tail-then-append race produces two records
  claiming the same predecessor. The lock file lives beside the log, on a Linux
  filesystem: ``flock`` is not reliable on the Windows mounts this project also uses.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

try:  # POSIX only; imported so the module stays importable on a Windows checkout.
    import fcntl
except ImportError:  # pragma: no cover - exercised only off-Linux
    fcntl = None  # type: ignore[assignment]

GENESIS = "genesis"
# Records are read back from the tail of the file rather than the whole file: the log
# grows without bound, and this function runs on every audit write.
TAIL_WINDOW_BYTES = 65536


def chain_digest(record: dict) -> str:
    """Digest one record, excluding its own ``hash``.

    The canonical form is sorted keys and no whitespace so the digest cannot depend on
    dict ordering or on ``json.dumps`` defaults. ``prev_hash`` is inside the record, so
    the digest binds each line to its predecessor.
    """
    body = {key: value for key, value in record.items() if key != "hash"}
    blob = json.dumps(body, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return "sha256:" + hashlib.sha256(blob).hexdigest()


def _parse(line: bytes) -> dict | None:
    try:
        record = json.loads(line.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return None
    return record if isinstance(record, dict) else None


def previous_hash(path: Path, window: int = TAIL_WINDOW_BYTES) -> str:
    """The ``prev_hash`` for the next record.

    Three cases, and the middle one is the interesting one:

    - No log yet -> :data:`GENESIS`.
    - Log predates the chain (last record carries no ``hash``) -> a digest of the whole
      existing file, so the first chained record anchors the entire history.
    - Otherwise -> the last record's ``hash``.
    """
    if not path.is_file():
        return GENESIS
    size = path.stat().st_size
    if size == 0:
        return GENESIS
    with path.open("rb") as handle:
        handle.seek(max(0, size - window))
        blob = handle.read()
    last: dict | None = None
    for line in reversed(blob.splitlines()):
        if not line.strip():
            continue
        record = _parse(line)
        if record is not None:
            last = record
            break
    if last is None:
        return GENESIS
    if last.get("hash"):
        return str(last["hash"])
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def append_audit_record(path: Path, record: dict) -> dict:
    """Append one record, chained to the current tail, under an exclusive lock.

    Mutates and returns ``record`` so the caller can log the hash it produced.
    """
    lock_path = path.with_name(path.name + ".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+") as lock:
        if fcntl is not None:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        try:
            record["prev_hash"] = previous_hash(path)
            record["hash"] = chain_digest(record)
            with path.open("a", encoding="utf-8", newline="\n") as handle:
                handle.write(json.dumps(record, ensure_ascii=True) + "\n")
        finally:
            if fcntl is not None:
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
    return record


def verify(path: Path) -> dict:
    """Walk the log and report the first line that breaks the chain.

    Returns ``{"ok", "lines", "chained", "first_bad_line", "reason"}``. ``ok`` is True
    only when there is at least one chained record and every line passes:

    - every non-empty line parses as a JSON object (a partial trailing line is a
      failure: it means the writer was interrupted or the file was edited);
    - the first chained record's ``prev_hash`` equals a digest of the bytes before it;
    - every later record's ``prev_hash`` equals the previous record's ``hash``;
    - every chained record's ``hash`` equals its recomputed digest.
    """
    result = {"ok": False, "lines": 0, "chained": 0, "first_bad_line": None, "reason": ""}
    if not path.is_file():
        result["reason"] = "no audit log yet"
        return result

    with path.open("rb") as handle:
        raw_lines = [line for line in handle]
    records: list[dict | None] = []
    for index, raw in enumerate(raw_lines, start=1):
        result["lines"] = index
        if not raw.strip():
            records.append(None)
            continue
        record = _parse(raw)
        if record is None:
            result["reason"] = "line does not parse as a JSON object"
            result["first_bad_line"] = index
            return result
        records.append(record)

    anchored_at = next((i for i, rec in enumerate(records) if rec and rec.get("hash")), None)
    if anchored_at is None:
        result["reason"] = "log has no chained record yet"
        return result

    prefix = b"".join(raw_lines[:anchored_at])
    expected = GENESIS if not prefix else "sha256:" + hashlib.sha256(prefix).hexdigest()
    anchor = records[anchored_at]
    assert anchor is not None
    if anchor.get("prev_hash") != expected:
        result["reason"] = "the first chained record does not match the history before it"
        result["first_bad_line"] = anchored_at + 1
        return result

    previous: dict | None = None
    for index, record in enumerate(records):
        if record is None or not record.get("hash"):
            continue
        result["chained"] += 1
        if chain_digest(record) != record["hash"]:
            result["reason"] = "record digest does not match its contents"
            result["first_bad_line"] = index + 1
            return result
        if previous is not None and record.get("prev_hash") != previous.get("hash"):
            result["reason"] = "record does not link to the one before it"
            result["first_bad_line"] = index + 1
            return result
        previous = record

    result["ok"] = True
    result["reason"] = f"{result['chained']} chained records verified"
    return result


def main(argv: list[str] | None = None) -> int:
    """CLI so the daily job and a human can check the live log the same way.

    Run as a plain file (it imports nothing from the package)::

        python3 AI_Platform/intelligence/gateway/audit_chain.py --audit ~/.local/state/intelligence-layer/audit.jsonl
    """
    import argparse

    parser = argparse.ArgumentParser(description="Verify the audit log's hash chain.")
    parser.add_argument("--audit", required=True, help="path to audit.jsonl")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    report = verify(Path(args.audit).expanduser())
    if args.json:
        print(json.dumps(report, ensure_ascii=False))
    elif report["ok"]:
        print(f"审计链完好：{report['chained']} 条已链接记录 / 共 {report['lines']} 行")
    else:
        where = f"第 {report['first_bad_line']} 行" if report["first_bad_line"] else "（无定位）"
        print(f"审计链校验失败 {where}：{report['reason']}")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
