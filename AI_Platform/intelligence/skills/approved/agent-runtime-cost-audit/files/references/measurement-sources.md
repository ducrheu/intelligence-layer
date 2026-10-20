# Where cost data actually lives

Open every store read-only: `sqlite3.connect(f'file:{path}?mode=ro', uri=True)`. An audit must
never hold a write lock on a store other agents are using.

## Hermes

- `~/.hermes/state.db`
  - `sessions`: per session `input_tokens`, `output_tokens`, `cache_read_tokens`,
    `reasoning_tokens`, `api_call_count`, `estimated_cost_usd`, `source`
    (desktop / qqbot / cron / a2a / tui), `tool_names`. `source` separates scheduled work from
    human conversation — always split by it.
  - `session_model_usage`: the same counts split by `model` AND `task`. The `task` column is
    where auxiliary spend surfaces: empty = main conversation, then `background_review`,
    `approval`, `compression`, `title_generation`. Group by model+task; the non-empty tasks
    are the line item most audits miss.
  - `messages`: `length(content)` per `role`; `tool` rows dominate. Group by `tool_name` to
    find which tool output bloats history (one-shot analysis tools and skill/prompt loaders
    are usually the worst per call).
  - `system_prompts`: `length(prompt)` is the fixed per-call system prompt (chars/4 ≈ tokens).
- `~/.hermes/cron/usage_audit.jsonl`: one JSON row per cron fire — `job_id`, `prompt_tokens`,
  `completion_tokens`, `duration_ms`, `error`. Per-fire cost of scheduled work, including the
  fires that ran for minutes.
- `~/.hermes/cron/jobs.json`: job definitions. `no_agent: true` with `"script": "x.sh|py"` is a
  deterministic job that never calls a model — audit every LLM job against that shape.
- `~/.hermes/sessions/request_dump_*.json`: `request.body.messages` and `request.body.tools` of
  a real request. Sum the tool schemas plus the system message for the FIXED per-call overhead
  (a full toolset's schema alone runs ~10K tokens, and it is paid on every call).
- Effective config: `hermes config get <key>`. Defaults live in code, so an absent key is not an
  absent behaviour — read the default before reporting on a setting.

## OpenClaw

- Per-agent store: `~/.openclaw/agents/<agent>/agent/openclaw-agent.sqlite`.
  - `trajectory_runtime_events.event_json` rows whose type is `model.completed` carry
    `data.usage` = `{input, output, cacheRead, reasoningTokens, total, cost:{total}}` plus
    `data.promptCache.lastCallUsage`. This is the only place per-turn token cost is recorded —
    there is no usage database and the log files carry no tokens.
  - **`usage` is cumulative for the RUN, not for one API call.** A single user prompt that
    loops over tools reports every call's tokens summed, so one run can legitimately show tens
    of millions of `cacheRead`. Never read it as context size.
  - `data.finalPromptText` (first ~60 chars) is enough to bucket runs — heartbeat poll, cron
    fire, chat turn — without loading the whole event; a LIKE filter on the JSON keeps the
    scan cheap even on a 500MB store.
  - `transcript_events.message` holds the actual messages; `session_windows` maps session →
    model, channel, workspace.
- Declared prices are local: `~/.openclaw/openclaw.json` → `models.providers.<p>.models[].cost`
  (`{input, output, cacheRead}`). Use those before any foreign price table.
- Fixed per-turn cost comes from the agent's context files: `ls -l <workspace>/*.md`
  (AGENTS.md / MEMORY.md / USER.md and any dream or scratch file the runtime injects).
- Cron jobs live in `state/openclaw.sqlite` → `cron_jobs` (`payload_kind`, `job_json`), one row
  per job per agent — the place to count how many scheduled jobs are LLM turns.

## Pricing the buckets

When the effective price vector is unknown, fit it instead of guessing: least-squares
`cost ≈ a·input + b·output + c·cacheRead` over a few hundred `model.completed` rows recovers
$/M per bucket to within a few percent of the declared prices. Disagreement between fit and
declaration is itself a finding (the runtime may be pricing at catalog rates the provider does
not charge). Rank levers by priced share, never by raw token count.

## The provider's own numbers

The remaining balance is usually one endpoint away, e.g. DeepSeek
`GET https://api.deepseek.com/user/balance` with `Authorization: Bearer $DEEPSEEK_API_KEY`.
Read it before and after a change: it is the only ground truth no runtime estimate can fake.
Credentials live in the runtime's secret file (`~/.hermes/.env`), and one key is usually shared
by every runtime on the machine — attribute spend accordingly instead of blaming one runtime.
