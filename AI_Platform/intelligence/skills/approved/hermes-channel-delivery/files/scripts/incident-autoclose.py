# Fold repeated cron failure alerts.
#
# Why this exists: cron groups failures into incidents keyed by (job, normalized error
# signature), and the per-run failure notice is withheld only once the incident reaches
# `closed` (= an operator acked it). Nothing acks on its own, so one broken job pushes one
# message per tick - measured: a single incident produced 12 pushes across nine hours. A
# changed error text mints a NEW incident, so a different fault still alerts.
#
# What it does:
#   1. fold: any incident already in `alerted` (the operator was told) whose first_seen_at is
#      older than the grace window -> `closed`.
#   2. escalate: an incident that has been folded but whose last_seen_at moved past its
#      closed_at is STILL FAILING - report it, at most once per incident per cooldown.
#
# Empty stdout sends no notification, and it always exits 0: a non-zero exit on a no_agent
# job is itself an alert, and an alert every 30 minutes is how a watchdog gets muted.
#
# Install: copy to ~/.hermes/scripts/ and schedule as a no_agent job, e.g.
#   hermes cron create "*/30 7-22 * * *" --name incident-autoclose \
#     --script incident-autoclose.py --no-agent --deliver <platform>
#
#     python3 incident-autoclose.py --dry-run    # report intent only
#     python3 incident-autoclose.py              # the scheduled run
#
# Touches only the `cron_incidents` table and only the transition `alerted -> closed`, which
# matches the scheduler's own semantics (`closed` is terminal; this script never resurrects one).
from __future__ import annotations

import argparse
import json
import pathlib
import sqlite3
import sys
from datetime import datetime, timedelta, timezone

HERMES = pathlib.Path.home() / ".hermes"
DB = HERMES / "cron" / "executions.db"
JOBS = HERMES / "cron" / "jobs.json"
STATE = HERMES / "cron" / "incident-autoclose-state.json"

GRACE_HOURS = 2          # how long after first sight an incident counts as "already told"
RENOTIFY_HOURS = 12      # cooldown between escalation reports for one incident
MAX_LINES = 3            # report at most this many escalations per run


def _parse(ts: str | None) -> datetime | None:
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return None


def _job_names() -> dict[str, str]:
    try:
        raw = json.loads(JOBS.read_text())
    except (OSError, ValueError):
        return {}
    jobs = raw.get("jobs", raw) if isinstance(raw, dict) else raw
    items = jobs.values() if isinstance(jobs, dict) else jobs
    return {str(j.get("id")): str(j.get("name") or j.get("id"))
            for j in items if isinstance(j, dict)}


def _load_state() -> dict:
    try:
        return json.loads(STATE.read_text())
    except (OSError, ValueError):
        return {"reported": {}}


def _save_state(state: dict) -> None:
    STATE.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATE.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2))
    tmp.replace(STATE)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    now = datetime.now(timezone.utc)
    names = _job_names()
    state = _load_state()
    reported: dict = state.setdefault("reported", {})

    try:
        db = sqlite3.connect(DB, timeout=10)
        db.row_factory = sqlite3.Row
        rows = db.execute(
            "SELECT id, job_id, state, first_seen_at, last_seen_at, closed_at, error, output_file "
            "FROM cron_incidents"
        ).fetchall()
    except sqlite3.Error as exc:
        # A watchdog that cannot read its ledger must still not look like a failure.
        print(f"\u26a0\ufe0f cannot read the cron incident ledger: {exc}")
        return 0

    folded, still_failing = [], []
    for r in rows:
        first = _parse(r["first_seen_at"])
        last = _parse(r["last_seen_at"])
        closed = _parse(r["closed_at"])
        if r["state"] == "alerted" and first and now - first >= timedelta(hours=GRACE_HOURS):
            folded.append(r["id"])
        if r["state"] == "closed" and closed and last and last > closed:
            prev = _parse(reported.get(r["id"]))
            if prev is None or now - prev >= timedelta(hours=RENOTIFY_HOURS):
                still_failing.append(r)

    lines: list[str] = []
    if folded:
        if not args.dry_run:
            with db:
                for iid in folded:
                    db.execute(
                        "UPDATE cron_incidents SET state='closed', closed_at=?, acked_at=? "
                        "WHERE id=? AND state='alerted'",
                        (now.isoformat(), now.isoformat(), iid),
                    )
        lines.append(f"\U0001f507 folded {len(folded)} repeated failure notice(s) "
                     "(same error alerts once; a changed error alerts again)")
    for r in still_failing[:MAX_LINES]:
        name = names.get(str(r["job_id"]), str(r["job_id"]))
        lines.append(
            f"\u26a0\ufe0f job '{name}' is still failing after being folded: last seen "
            f"{r['last_seen_at'][:19]}"
            f"\n   evidence: {r['output_file'] or '-'}"
        )
        if not args.dry_run:
            reported[r["id"]] = now.isoformat()
    if len(still_failing) > MAX_LINES:
        lines.append(f"   {len(still_failing) - MAX_LINES} more; see `hermes cron incidents`")

    if not args.dry_run:
        cutoff = now - timedelta(days=7)
        state["reported"] = {k: v for k, v in reported.items()
                             if (_parse(v) or now) >= cutoff}
        _save_state(state)

    if lines:
        print("\n".join(lines))
    if args.dry_run:
        print(f"[dry-run] would fold {folded}; would report {[r['id'] for r in still_failing]}",
              file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
