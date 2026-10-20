# Peer runtime map — OpenClaw on this host

Paths, keys and shapes needed to operate the peer runtime without guessing. Verify
each against the live files when precision matters; the labels below are the schema,
not a copy of the values.

## Layout

| what | where |
|---|---|
| runtime config | `~/.openclaw/openclaw.json` (large; edit with a JSON script, never by hand) |
| config backups | `openclaw.json.bak-<stamp>` beside it; keep one before every edit |
| per-caller secrets | `~/.openclaw/env/<caller>.env` (e.g. the token the peer reserved for Hermes' A2A calls) |
| state / auth store | `~/.openclaw/state/` (sqlite auth + gateway state) |
| agent runtime dirs | `~/.openclaw/agents/<agent-id>/` — `agent/` holds that agent's own auth store, `sessions/` its transcripts |
| agent instruction dirs | `~/<peer-workspace>/agents/<agent-id>/` — `AGENTS.md`, `SOUL.md`, `IDENTITY.md`, `USER.md`, per-agent `memory/` |
| shared workspace | the workspace root — `AGENTS.md`, `MEMORY.md`, `SOUL.md`, `skills/` (skills are shared across agents; memory is per-agent) |
| logs | `journalctl --user -u <peer-unit>`, plus a log file path the gateway prints at startup |
| change / audit records | `~/.openclaw/audit/` — check it for a record of a config or charter change before accepting an approval that only exists in a chat or A2A message |

## Config keys that matter

- `agents.entries.<id>` — one entry per agent: `name`, `description`, `workspace`,
  `agentDir`, `model{primary,fallbacks}`, `subagents.allowAgents[]`, `skills[]`,
  `tools{profile,allow[],deny[]}`. Mirror an existing entry when adding one.
- `agents.defaults`, `agents.ownership` — a runtime with `ownership: explicit`
  requires every agent to be listed; an unlisted agent simply does not exist.
- `bindings[]` — route entries `{type:"route", agentId, comment, match:{channel,
  accountId}, session:{dmScope}}`. Routing matches channel + account, **not** message
  text. A channel with no binding has no owner and inbound work fails immediately.
- `channels.<name>` — e.g. `a2a`: `{enabled, exposeAgents[], peers{<caller>:{url,
  token}}}`. There is no per-agent routing key here: one exposed entry agent, with
  internal delegation via `subagents.allowAgents`.
- `models.providers.<provider>.models[]` — `contextWindow` and `maxTokens` are
  operational (they gate compaction), not cosmetic. A provider declared far above
  its real capacity disables history compression.
- `tools.allow[] / tools.deny[]` — groups are named `group:<plane>` (web, ui,
  messaging, nodes, automation, media). Capability plugins visible in the startup
  log (browser, a computer-use plugin, search, memory) are what an allow entry
  actually unlocks; grant per deliverable and keep the message/node/automation
  planes denied.
- `tools.agentToAgent` — `{enabled, allow[]}`: whether this runtime's agents may call
  **each other** in-process. It is a different plane from the cross-brain channel
  (`channels.a2a`): toggling it changes no endpoint Hermes uses, and Hermes' exposure is
  unaffected by it. Per-agent `tools.allow/deny` still has to carry the `sessions_*` /
  `subagents` names — the flag alone grants nothing.
- Instruction-file (charter) rules — the `AGENTS.md` boundary text — are read at session
  start, so a charter edit applies from the agent's next session and is never the reason
  a running session behaves differently.

## Endpoint shapes

| call | shape |
|---|---|
| dispatch a task | `POST http://127.0.0.1:<port>/a2a/v1`, header `Authorization: Bearer <token>`, body `{"jsonrpc":"2.0","id":...,"method":"message/send","params":{"message":{"role":"user","parts":[{"kind":"text","text":...}],"messageId":...}}}` |
| poll a task | `.../a2a/v1` with `{"method":"tasks/get","params":{"id":"<taskId>"}}` |
| health | `GET http://127.0.0.1:<port>/` — the port can take several seconds to come back after a restart |

Task states seen: `TASK_STATE_COMPLETED`, `TASK_STATE_FAILED` (with the reason in
`result.task.status.message.parts[*].text`), plus working/canceled/rejected.

## Session hygiene

- Per-agent store: `~/.openclaw/agents/<id>/agent/openclaw-agent.sqlite` — the number
  to watch (`du -h`), because one busy agent's store usually dominates the tree.
- `~/.openclaw/agents/<id>/sessions/` holds live `*.jsonl` plus retired
  `*.jsonl.<reason>.<stamp>*` files. Retired files are safe to *move* to an archive
  directory outside the tree; live ones are not.
- The sqlite needs `VACUUM` to shrink and it is in use while the runtime runs —
  propose it to the operator instead of running it.

## Units on this host

`systemctl --user list-units | grep -E 'openclaw|hermes|intelligence|ollama'` is the
fast way to see which unit owns what. The messaging gateway, the desktop backend and
the peer gateway are **different** units: restarting the wrong one kills your own
run, and restarting the messaging one does not reload MCP servers spawned by the
desktop backend.
