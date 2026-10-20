# Intelligence Layer — concrete topology

Established by live inspection of this host. Re-verify (units, ports, identity table) before
relying — paths and binds drift, and the governance source is the authority.

## Processes

| Piece | Unit | Bind | Notes |
|---|---|---|---|
| Intelligence gateway (governed artifact API) | `intelligence-gateway.service` | `127.0.0.1:8765` | python3, `PYTHONDONTWRITEBYTECODE=1`, read-only consumer of the source tree |
| Hermes backend / dashboard / gateway | `hermes-backend`, `hermes-dashboard`, `hermes-gateway` | `:9121`, `:9120`, `:9900` | `:9900` is the inbound A2A platform |
| OpenClaw gateway | `openclaw-gateway.service` | `127.0.0.1:18789` (+ `[::1]`) | node; also serves the Control UI and an A2A endpoint |
| Ollama | `ollama.service` | `127.0.0.1:11434` | GPU |

## Key paths

- Intelligence layer root: `/mnt/d/intelligence-layer/AI_Platform/intelligence` — moved off the
  C: Codex workspace, which is why the parent `AI_Platform` level must survive any future move
  (the package is imported as `AI_Platform.intelligence...`). The gateway unit's `ExecStart --root`
  and `WorkingDirectory` name it; both, and the tool scripts, read env overrides
  (`INTELLIGENCE_ROOT`, `INTELLIGENCE_PLATFORM`, `INTELLIGENCE_GATEWAY`) so relocation is config.
  Subdirs: `gateway/` (policy, service, store, schema, lifecycle, models),
  `experimental/api/server.py` (HTTP surface + identity table), `<kind>/approved/`,
  `<kind>/candidates/`, `skills/<status>/<id>/{manifest.json,SKILL.md,tests/}`.
- Runtime state lives OUTSIDE the tree, resolved through `INTELLIGENCE_STATE` (set in the gateway
  unit, default `~/.local/state/intelligence-layer`): the audit trail, the event stream, the
  telemetry aggregate, the embedding cache and the token hash table. Only
  `qa/governance-config.json` (the auto-admission mode) stays in the repository. Looking for
  `qa/audit.jsonl` inside the tree and not finding it is expected — read the unit's environment for
  the real location before concluding anything was lost.
- Read-only MCP adapter for Hermes: `tools/intelligence-mcp/` next to the OpenClaw tree
  (`server.py` hand-rolled JSON-RPC, `gateway_client.py` HTTP client with a hardcoded token default,
  `policy.py` input bounds, `tests/test_adapter.py`).
- Gate scripts (OpenClaw side), all dry-run by default with `--apply` to act: the skill backflow
  gate (requires a source under the Hermes skills dir, a `## Contract` section, and a runnable
  test; stages the whole payload by allowlist), `intelligence-validate.py` (QA identity; re-runs
  the artifact's recorded tests from the governed copy and refuses if they are missing or failing),
  `intelligence-approve.py` (human identity; imports the gateway directly because approve has no
  HTTP endpoint), and `intelligence-repair-skill-layout.py` (idempotent store-layout repair; plan
  first, then `--apply`).
- Hermes side: `~/.hermes/config.yaml` (`mcp_servers:`, `gateway.platforms.a2a`, `a2a_agents:` if
  set), `~/.hermes/skills/<category>/<name>/`, `~/.hermes/.env` for the token. Feedback-loop state:
  `~/.hermes/governance-events-cursor`, `~/.hermes/governance-feedback-log.md`, and the monitor
  script `~/.hermes/scripts/governance-event-count.py` (see `references/feedback-loop.md`).
- Two MCP entries: `intelligence` (read-only, five tools) and `intelligence-write` (the same five
  plus `submit_candidate`, `request_promotion`, `withdraw_candidate`; token `local-hermes-writer`,
  `trust: full` so unattended writes do not each need a click). In-session tool names map a server
  name's hyphens to underscores: `mcp__intelligence_write__*`.

## Store layout rules

- Non-skill kinds map to `<kind>/approved/<id>.json` when approved, and to `<kind>/candidates/`
  for **every** other status including validated and archived. Because several statuses share one
  directory, a lookup must confirm the file's own `status` before returning it — the path alone
  cannot identify a record's status.
- `kind: skill` maps to `skills/<status>/<id>/manifest.json`; skill directories also hold the body
  and tests beside the manifest.
- Writes are temp-file + atomic replace. No locks, no fsync discipline assumed.

## Status machine

`candidate → experimental → validated → approved → deprecated → archived`.
No candidate→approved shortcut. `approved` requires `verified: true` with `verified_by` and
`verified_at` populated — which only the human approval path sets.

A transition relocates the **whole artifact directory** - manifest, `SKILL.md`, tests and support
files - and rewrites recorded `tests[].path` entries whose prefix was the old status directory. A
transition that moves only the manifest leaves a directory holding files with no `manifest.json`
and a recorded path naming a location that no longer exists; `intelligence-repair-skill-layout.py`
repairs that shape (plan, then `--apply`, iterating to a fixed point) and should otherwise report
nothing to fix.

`verified` may only be true at `approved`, and `approved` requires it: a candidate cannot arrive
pre-verified, and `submit_candidate` refuses an id that already exists in a live status (`approved`
/ `stale` / `deprecated`), auditing the refusal as `id_already_published`. `archived` is excluded on
purpose — the record is inert — so a withdrawn id can be refiled. Updating a published artifact is
therefore a `supersede` (human-held `rollback` scope) or a new id, never a re-submit over the same
id. Withdrawing is the separate move for unpublished artifacts: the status becomes `archived`, the
reason lands in `metadata.withdraw`, the artifact leaves search results, and the check for who may
retract it reads the audit log's last successful submitter rather than `created_by`.

## Identities and scopes

| Identity | Role | Scopes |
|---|---|---|
| `local-agent` | agent | read:approved, write:candidate, request:promotion, withdraw |
| `local-hermes` | runtime | read:approved, read:governance-metadata |
| `local-hermes-writer` | runtime | read:approved, read:candidate, read:governance-metadata, write:candidate, request:promotion, withdraw |
| `local-qa` | qa | read:approved, read:candidate, validate:candidate, request:promotion |
| `local-human` | human | read:approved, read:candidate, approve, deprecate, rollback, request:promotion, write:candidate, withdraw, withdraw:any |
| `local-system` | system | read:approved, read:candidate, validate:candidate, request:promotion, write:candidate |
| `policy-auto` | automated | read:approved, read:candidate, read:governance-metadata, validate:candidate, approve |

Notes that decide most access questions:

- The candidate-write policy accepts **either** the `write:candidate` scope **or** a role in
  {agent, qa, system, human}. The `runtime` role is deliberately not in that set, so a runtime
  identity needs the scope spelled out — and adding a scope is the only change needed.
- The MCP adapter's token is a client-side default, not a server-side session: one token per MCP
  server process. Separate identities therefore mean separate `mcp_servers:` entries with their own
  `env:` token, not one entry used differently per call.
- Identity tokens are minted random values now, not labels: `sha256(token)` is kept in the state
  directory and the plaintext lives in the owner's credential file outside the repository. The
  literal identity name is still accepted as a token only while the migration switch
  (`INTELLIGENCE_ALLOW_LEGACY_NAMES`) is on — so until it is flipped, treat every scope in this
  table as claimable by anything that can reach the port, and say so rather than describing the
  system as authenticated. `policy-auto` holds `approve`, which is why the human-only rule is stated
  as "no HTTP endpoint for approval", not "no automated identity may approve".
- `withdraw` lets an identity retract what it filed; `withdraw:any` (human only) retracts anything.
  A runtime identity that must write gets `local-hermes-writer` rather than an enlarged
  `local-hermes`, so the read identity's "no write tools exist" promise stays literally checkable.

## HTTP surface

`GET /health`; `GET /v1/search/{kind}` (bounded search); `GET /v1/context/{kind}` (approved packet +
metadata-only warnings, requires the governance-metadata scope); `GET /v1/artifacts/{kind}/{id}`;
`POST /v1/candidates`; `POST /v1/validate/{kind}/{id}`; `POST /v1/promotion/{kind}/{id}`;
`POST /v1/withdraw/{kind}/{id}` (optional `{"reason": ...}` body); `GET /v1/events?since=<line-offset
cursor>&max_items=` — metadata-only lifecycle events, requiring the governance-metadata or
candidate-read scope.

No HTTP endpoint exists for approve / deprecate / supersede. That absence is the design.

## Repository and delivery channel

- The layer is a git repository whose root is `/mnt/d/intelligence-layer` — deliberately one level
  **above** `AI_Platform`, because the code imports `AI_Platform.intelligence...` and tests locate
  their root by a fixed relative depth. Re-initialising the repository inside `AI_Platform/` makes
  every fresh clone fail to import while the working copy looks healthy; prove the layout with a
  clone into a scratch directory and a suite run there.
- Runtime state is untracked and ignored (see the state note above), so the repository is
  publishable while the audit trail stays local. Publishing is a privacy decision and needs a
  redaction pass first: `references/gateway-code-changes.md`.
- Scheduled reports can reach the user through a messaging platform rather than only the cron output
  directory: the jobs are pointed at it with `deliver: <platform>` (a bare platform name resolves to
  that platform's home channel) and a one-off push is testable from the shell. Adaptor specifics,
  the delivery-receipt rule and the bot-authorisation boundary: `references/feedback-loop.md`.

## A2A

- Hermes inbound: agent card at `/.well-known/agent-card.json` on `:9900`, JSON-RPC at `/`, both
  `SendMessage` (task nested under `result.task`) and `message/send` (task fields flat) answer.
  The card advertises streaming and push notifications.
- OpenClaw peer: agent card at `/.well-known/agent-card.json` on `:18789` (publicly served), task
  endpoint `/a2a/v1`, which requires a bearer token whose peers are whitelisted in the OpenClaw
  config. Advertised capabilities differ from Hermes's — check the card rather than assuming
  symmetry.
- Hermes outbound A2A is a toolset that is disabled by default and needs peers registered in
  `config.yaml`; inbound being enabled does not enable outbound.
