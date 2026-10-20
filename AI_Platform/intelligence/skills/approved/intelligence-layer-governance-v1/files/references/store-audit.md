# Auditing a running governed store

Order matters: **liveness first**, then supply, then duplication, then hygiene. A report that opens
with code debt buries the only finding that changes behaviour - a store can be technically healthy
and completely unused, and that is the finding the operator needs first.

Every number below must come from a command run in the session that reports it. Docs describe
intent; the store and the unit describe state.

## 0. Fix the state directory before reading anything

The runtime state (audit, events, usage counters, token hashes, embeddings) lives in
`$INTELLIGENCE_STATE`, not in `<root>/qa`. `<root>/qa` keeps a snapshot from whenever the split
happened - plausibly complete-looking and stale - so a report run without the variable prints a
real table built from the wrong days. Set the same value the service unit sets, and check it before
believing any count. `governance-config.json` is the exception: it is read from the store itself.

Symptom to recognise: a usage report whose "last read" dates all cluster on one old day, and a
`reads` column that is uniformly zero. That is a stale-state read, not an idle corpus.

## 1. Liveness: is anything actually being read?

- `events.jsonl`, `action == "used"`, grouped by day: the strong signal (whole record fetched).
- `audit.jsonl` action counts by day: `search_*` / `get_*` are reads, `submit_candidate` /
  `validate_candidate` / `approve` are intake.
- Compare intake against consumption. Writes continuing while reads sit at zero is a corpus that is
  fed and never consulted - a workflow gap, and no threshold change fixes it.
- Before calling a spike "usage", read what produced it: fifty searches inside thirty seconds is a
  benchmark, not a reader. Measurement traffic lands in the same files as real readers, so an
  evaluator pointed at the live store must be able to switch telemetry off — a flag checked at
  write time (`INTELLIGENCE_TELEMETRY_SUPPRESS` here) that gates the event and usage writes and
  never the audit chain. Without it one eval run inflates `reads` and, worse, clears the
  "nobody is reading this" threshold for days.
- Any alarm about consumption must count the action that *is* consumption. Counting `search_*` calls
  lets an evaluator, a duplicate screen or a plain miss clear the threshold; count `used` events,
  and compare timestamps as UTC-aware values — mixing a naive local `now()` with `Z`-stamped records
  shifts the window and hides a stall.

Calibration from a ~45-record store: 70% of all `used` events fell in the build week, the top record
held ~35% of the rest, and 18 days passed with zero - which the weekly report never mentioned.

## 2. Supply: what the corpus is made of

Count per kind and status, then per scope. Release counts, not file counts: a scanned `*.json` tree
includes archived records that no read surface serves.

Then name the **pipe** that fills each kind, and the class of knowledge that pipe cannot carry -
counting records answers "how much", not "why this and not that". A kind fed only by distillation of
another agent's experience contains only what that agent happened to do; a kind whose only gate
demands a declared contract plus a runnable test contains no method-shaped knowledge at all, however
valuable. Measured: every released record sat in one domain while the owner's current main line had
none, and the corpus was healthy by every count - the defect was a missing route, not missing
content. For each empty or thin kind, ask what would have had to happen for a record to appear, and
whether that thing is even possible on this side.

Read the harvester's cursor/watermark file in the same pass: its timestamp is where the next scan
starts, so a cursor pushed forward (by a test run, a clock change, a manual probe) makes the job
skip the real backlog, and its id list is the cheapest place to spot fixture pollution - test ids
like `layout-demo` sitting beside a real one. Check it after any suite run against live state.

Then the flags: `never-used` + `auto-admitted-unverified` together is the zombie signature - policy
admitted it, nobody ever read it. Measure the share of released records carrying it; above ~a third
is an admission-policy problem, not a content problem.

## 3. Duplication: cross-kind, or you will miss it

A screen that iterates one kind at a time cannot see the duplicate that accumulates fastest -
`experience` (raw note) next to the `knowledge` distilled from it, both approved. Scan the union of
kinds in one pass.

Pair by provenance, not similarity: the finished record already cites its source
(`source[].ref = "experience:<id>"`), which is exact, explainable, and free of the false positives
that make a rank-based report ignorable. Use the ranker only to *find candidates*; use the citation
to *prove* the pair.

When a pair has no citation - two records written independently - the verdict is cosine, not rank
agreement: measured on this corpus the real pairs sat at 0.83–0.92 while the nearest unrelated
neighbour never cleared 0.70, whereas the rank window fired on unrelated notes because at a few
dozen documents every probe has something at rank 1. Put the threshold inside that measured gap,
and use the same number for the admission-time duplicate screen so "duplicate" means one thing to
the auditor and to the gate.

## 4. Hygiene

- `git status --porcelain` for `??` under `approved/`: auto-admission writes files and nothing
  commits them, so the canonical tree silently falls behind the store. Count them before claiming
  the repository is the authority.
- Count commit subjects. A daily automated anchor commit per day of history means the log is mostly
  noise and a real change is hard to find; that is a reporting cost, not a bug, but say which it is.
- Compare the unit's `Environment=` with the docs: a migration switch, a state path, a test count,
  or a "still open" limitation is usually stale in prose and current in the unit.
- Verify the verifiers. Run the read-surface acceptance live; if it reports a fistful of failures,
  check the credential before the surface - a checker that defaults to the identity *name* after a
  token migration produces seven failures about a healthy gateway. Expect the self-test and the live
  run to be separately green.
- The fix for Git drift belongs in the maintenance job that already runs daily, not in a new one:
  commit the store paths and the audit anchor together when anything is pending, and fall back to a
  weekly anchor-only commit when nothing is. Filter the owner's excluded paths explicitly in that
  script rather than a broad `git add -A` — a bulk add stages the very records you were told to
  leave out.
- A liveness route that sits behind the same credential as the data routes is not a liveness route:
  no watchdog holds an identity token. Keep the authenticated `/health` and add an unauthenticated
  one-bit `/healthz` that says nothing about the corpus.
- Re-check every finding against the tree before it enters the report. Two plausible claims in one
  review were both wrong: "test leftovers are sitting in `approved/`" (they were in `candidates/`,
  which is the correct layout for every non-approved status) and "the scheduled agent runs on empty
  input and burns model calls" (cron's monitor gate suppresses the agent when the monitored output
  hash is unchanged — `changed=False`, no run — so the job cost a shell script). A wrong finding
  costs more than a missing one, because the fix built on it is wasted work.

## 5. Small API facts that cost time

- `IntelligenceGateway(...)` takes a `Path`; a `str` raises `TypeError` at construction.
- `search()` returns a list; `usage_summary()["explicit"]` is derived from `events.jsonl`, while
  `usage.json` holds only `surfaced` and `misses`. That is why "reads" never appear in the usage
  file and why a report can look internally consistent while reading the wrong state.
- Per-kind getters are `get_knowledge` / `get_experience` / `get_skill` / `get_source`.

## 6. Demand, not only mechanism

A stalled read path has two candidate causes and they look identical in the counters: nothing
*triggers* a lookup, or there is nothing to look up. Before prescribing triggers, compare the
corpus's topics with what the user is working on now. A store full of last quarter's engineering
notes, next to a user whose current work is in another domain entirely, stays unread no matter how
many skill preambles open with "search the KB first". Say it plainly and make it a decision: feed
the current main line, or accept the store as a reference shelf for one class of task.

## 7. Shape of the report

1. One-sentence verdict (alive / used / decaying / stalled).
2. Liveness with the date of the last real read.
3. Supply and the zombie share.
4. Duplication with the exact pairs.
5. Defects, each with the line that manifests it, then a phased fix list.
6. What you changed, and how each change was verified - a fix without a probe is a claim.
