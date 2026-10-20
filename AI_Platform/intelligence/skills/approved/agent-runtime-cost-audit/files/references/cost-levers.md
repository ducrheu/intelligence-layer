# Cost levers, by mechanism

Each row: the lever, the mechanism that makes it work, and where it lives in Hermes unless the
row says otherwise.

## Context carried per call

| Lever | Key | Mechanism |
|---|---|---|
| Absolute token cap | `compression.threshold_tokens` | Compaction fires at the LOWER of the ratio threshold and this count — the only trigger that works on a large window. |
| Ratio | `compression.threshold` (default 0.50; windows under 512K are floored at 0.75, raise-only) | Scales with the window, so it is a no-op on a 1M model. |
| Deterministic prune | `compression.proactive_prune_tokens` (0 = off) | Prunes stale tool results with NO model call. Each prune rewrites history and breaks the cache prefix, so keep it a threshold, not a per-turn action. |
| Tail size | `compression.tail_mode` (`lean` vs `legacy`) | `lean` keeps a clamped ~2.5%-of-window tail instead of 0.20×threshold verbatim. |
| Idle compaction | `agent.idle_compact_after_seconds` (0 = off) | Compacts a quiet session, so returning to it does not re-send the old tail. |
| Session hygiene | — | A new session per task is the cheapest lever of all; one long-lived session is what makes per-call context large. |

OpenClaw equivalent: `agents.defaults.compaction` (`mode`, `midTurnPrecheck`). Mid-turn precheck
rewrites the prefix inside a run, and the next call repays the whole context at cache-miss price.
An effective input cap is a separate knob from the native declaration: OpenClaw caps the input
budget with `models.providers.<p>.models[].contextTokens` while `contextWindow` keeps declaring
the native window, and its preflight thresholds derive from the cap.

## Session age and idle gaps — where the 50x bucket actually comes from

A provider KV cache lives minutes to hours. A long-lived session that went idle therefore opens
its next message by re-billing the ENTIRE history at cache-miss price: the most expensive thing
the runtime does, and invisible in a mean. The run-level tell is a `usage` row whose `input`
dwarfs `cacheRead` (hundreds of thousands of miss tokens against a few thousand hit) on a run
whose text is an ordinary chat message. Runtimes whose turns are seconds apart inside a tool loop
keep the prefix warm and show a small miss share; runtimes whose user messages are hours apart
spend most of their money there — same model, same key, opposite bucket shape.

Rotating to a fresh session costs one small prompt instead of that re-read, so automate it
rather than relying on discipline:

- OpenClaw: `session.reset` — `mode: none` (default) | `daily` (`atHour`, local) | `idle`
  (`idleMinutes`), plus `resetByType.{direct,group,thread}` and `resetByChannel.<channel>` so one
  noisy channel rotates hard while the operator's own surface stays conservative.
- Freshness is the last REAL user interaction; heartbeat, cron and exec events do not keep a
  session alive, which is exactly what makes an idle policy safe to enable.
- Reset starts a fresh history window and deletes nothing: earlier transcripts, trajectories and
  search rows remain, and the long-term memory files are untouched.
- Trade-off to state before applying: the model no longer sees the recent conversation inline and
  may ask what you were working on. Mitigate with a task-state file in the workspace that a
  fresh session reads first — deterministic, near-zero cost, and more reliable than searching
  400K of history.

## Output and reasoning

- Measure `reasoning_tokens / output_tokens` first: on a reasoning model it is often ~half of
  the output bucket, and it is the same expense as any other output token.
- Effort ladders are narrow per wire (DeepSeek V4 accepts only low/medium/high/max; some models
  cannot disable thinking at all). Set the level explicitly — unset means the server default,
  usually the high end — and clamp to the nearest supported level instead of inventing one.
- Pin effort per task: keep the main conversation's level where real reasoning happens, and
  drive auxiliary tasks down or off.
- Hermes: `agent.reasoning_effort` plus a per-model-name map. OpenClaw: `thinkingDefault`.

## Auxiliary per-turn calls

- `auxiliary.background_review` is ON by default with `max_input_tokens: 600000` — an automatic
  reviewer that forks the conversation each turn. Cap the input, drop its reasoning effort, or
  disable it; a fork capped at 30–40K costs a fraction of one that sees 600K.
- `auxiliary.approval` is the classifier behind `approvals.mode: smart` — one model call per
  flagged command. Pin it to a fast/cheap or local model, or go manual/allowlist for shells
  already trusted.
- `auxiliary.compression`, `auxiliary.title_generation`: same treatment. `provider: auto` with an
  empty `model` means "inherit the main model", which is how the expensive model ends up doing
  bookkeeping.
- Local models are the floor: a host already running Ollama for embeddings can serve
  classification, titles and review at zero marginal cost.

## Recurring jobs: script before prompt

Test every scheduled job with one question: could a script compute this output? Cursors,
dedupe, threshold alerts, state checks, report formatting, "nothing changed → say nothing" are
all deterministic. Hermes cron runs them as `no_agent: true` with `"script": "<name>.sh|py"`,
invoking a model only when the delta is material. This REMOVES calls instead of shrinking them,
so do it before tuning any prompt. Then check the other runtime for a duplicated duty — the same
governance/audit/review job scheduled in both runtimes on one shared API key doubles the bill,
and tuning inside one runtime will never reveal it.

## Fixed per-call overhead

Every call pays the system prompt and the entire tool schema whether the turn uses them or not.
Prune toolsets the machine never uses, and keep skill descriptions short: a loaded skill's full
text is re-sent on every later call of that session, so progressive disclosure — index in
SKILL.md, depth in reference files — is a cost feature, not a style preference. Keep bulky
memory or context files out of the per-turn injection.

## Verify, don't assume

Re-measure after every change: per-call context, the bucket table, the provider balance. A
config diff is not evidence. Give an expected monthly saving per lever with its assumption
stated, and label anything unmeasured as an estimate.
