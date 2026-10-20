# Whole-stack health audit — the layer sweep

The concrete reads behind SKILL.md §16. Run them in this order; each one is bounded, and the verdict
comes from comparing the layers (mechanical health vs. delivered value).

## 1. Services

```bash
systemctl --user list-units --type=service --all --no-pager
systemctl --user list-units --state=failed --no-pager
for u in <units>; do systemctl --user show $u \
  -p NRestarts -p ActiveState -p SubState -p ExecMainStartTimestamp -p MainPID; done
```

`NRestarts=0` on every unit plus an empty failed list **is** the stability answer. Do not infer
uptime from the units — see the `ExecMainStartTimestamp` pitfall in §16.

## 2. Ports

```bash
ss -ltnp
```

One read. Everything bound to `127.0.0.1` is the intended posture (§11); a non-loopback bind is a
finding, not a detail.

## 3. Logs — classify, never read raw

An `errors.log` in the thousands of lines is usually two or three repeating warnings. Normalize each
line and count:

```python
import re, collections
pat, sev, first, last = collections.Counter(), collections.Counter(), {}, {}
for line in open(path, errors="replace"):
    m = re.match(r'^(\d{4}-\d\d-\d\d[^ ]* [^ ]+) (\w+) (.*)', line)
    if not m: continue
    ts, level, rest = m.groups()
    key = re.sub(r'\d+', 'N', rest)[:110]   # drop ids/durations so classes collapse
    pat[key] += 1
    sev[level] += 1
    first.setdefault(key, ts); last[key] = ts
```

Report the top classes with counts and first/last seen. Two classes commonly account for the majority
(here: a credential-exchange degradation warning and the SQLite WAL-reset notice), and both are
usually removable at the source — which is worth more than the report.

Also check whether the file rotates: a sibling `agent.log.1` with none for `errors.log` means the
latter is a single growing file. Judge by the daily line rate before calling it a problem.

## 4. Scheduled jobs

```bash
hermes cron list
```

Then the executions DB (read-only):

```python
import sqlite3
c = sqlite3.connect("file:~/.hermes/cron/executions.db?mode=ro", uri=True)
c.execute("select count(*) from executions").fetchone()
c.execute("select status, count(*) from executions group by status").fetchall()
c.execute("select delivery_outcome, count(*) from executions group by delivery_outcome").fetchall()
c.execute("select job_id, status, count(*) from executions group by 1,2").fetchall()
```

Tables: `executions` (`status`, `delivery_outcome`, `error`, `scheduled_instant`, `started_at`,
`finished_at`) and `cron_incidents`. The row count is typically a rolling window, not the lifetime
total — `jobs.json` carries the true `repeat.completed` per job.

**A high `suppressed` / low `delivered` split is the monitor gating working.** Then read the job's own
output directory (`~/.hermes/cron/output/<job_id>/*.md`) and grep for `no_change` to get the real
ratio, and read one *non*-suppressed run end to end — that is the only evidence the work landed.

`jobs.json` also tells you what a job actually is: `no_agent: true` + `script:` means it costs no LLM
tokens, `monitor_script: <name>` means it only wakes the agent on output change.

## 5. Governed store

```python
import json, collections
base = "~/.local/state/intelligence-layer/audit.jsonl"   # honor INTELLIGENCE_STATE
rows = [json.loads(l) for l in open(base, errors="replace") if l.strip()]
collections.Counter(r["action"] for r in rows)
collections.Counter(r["actor"] for r in rows)
```

Group by day to see production vs. idleness. Read the admission mode from the **store's**
`<root>/qa/governance-config.json` (`auto_admission: shadow|enforce`), not from an env var — the store
file is what the gateway and every tool both honor.

Confirmed-write identity check (§6): the state dir's `identity_tokens.json` holds sha256 digests only;
a plaintext registry elsewhere is the client side. Confirm `INTELLIGENCE_STATE` matches the service
unit's value before trusting anything read from the state dir — a mismatch reads an *empty* audit log
and silently makes every producer look untrusted.

## 6. Cost

Both tables live in `~/.hermes/state.db` (read-only connect):

```python
c.execute("select sum(api_call_count), sum(input_tokens), sum(output_tokens), "
          "sum(cache_read_tokens), sum(estimated_cost_usd), sum(actual_cost_usd) "
          "from session_model_usage")
c.execute("select source, count(*), sum(input_tokens), sum(estimated_cost_usd) "
          "from sessions group by source")
```

Schema traps: `sessions` keys on **`id`** (not `session_id`); `session_model_usage` keys on
`session_id`; the token columns are `input_tokens` / `output_tokens` / `cache_read_tokens`, **not**
`prompt_tokens`. `cost_status` / `cost_source` say whether `estimated_cost_usd` is a real figure.

`cache_read_tokens` dwarfs the input total — a high cache-read share is *why* the bill is small, so
report it as the mechanism rather than as consumption. Per-source grouping answers "who spends"
(interactive desktop vs. cron vs. qbot).

## 7. Self-iteration

```bash
ls -t ~/.hermes/logs/curator/*/REPORT.md | head
find ~/.hermes/skills -name SKILL.md | wc -l
find ~/.hermes/skills -name SKILL.md -printf '%TY-%Tm-%Td %p\n' | sort -r | head
```

The REPORT.md header line carries the verdict: `Model: (not resolved)` and
`skipped (consolidation off)` mean the LLM consolidation pass never ran — only time-based staleness
marking did. The mtime list is the other half: recent mtimes with a flat total means skills are being
added, not reshaped.

`~/.hermes/state.db` `sessions`/`messages` counts, plus the `messages_fts*` tables, tell you whether
session history is being indexed for recall at all.

## 8. Cross-brain link (live probe)

A read-only `message/send` round trip is the one probe that proves the A2A link is up right now.
Credential mechanics and the wrong-token trap: `openclaw-agent-dispatch` §4.

## Reviewing posture

- Report facts with the numbers that carry them, and mark what is *not* a defect (unclean exit after a
power cut, suppressed cron output, an agent blocked from editing user-owned skills).
- Rank findings by blast radius, and put "stable but idle / written-but-never-read" above cosmetic log
noise — mechanical green is not the finding the operator needs.
- Hand the long-form report over per §10 (absolute path in the same message, plus `MEDIA:`), and keep it
out of a git-backed tree with a public remote.
