# The cross-runtime loop

How two agent runtimes on one machine exchange **work** (A2A dispatch) and **knowledge** (the governed
KB handoff). Every command below was run live; the failure modes are the ones that actually cost time.

Participants here: the learner/brain (`Hermes`, A2A inbound on `:9900`) and the executor pool (`OpenClaw`,
A2A on `:18789`, several agents in `agents.entries` of its config).

## 1. Dispatch: calling a peer agent over A2A

JSON-RPC 2.0 over HTTP, bearer-authenticated:

```bash
TOK=$(grep -oP '(?<=A2A_HERMES_TOKEN=).*' "$HOME/.openclaw/env/a2a-hermes.env" | tr -d '"'"'"' \r\n')
curl -s -X POST http://127.0.0.1:18789/a2a/v1 \
  -H "Content-Type: application/json" -H "Authorization: Bearer $TOK" \
  -d '{"jsonrpc":"2.0","id":"probe-1","method":"message/send","params":{"message":
       {"role":"user","parts":[{"kind":"text","text":"..."}],"messageId":"probe-1"}}}'
```

- The peer's token lives in **its** env file, not in yours. Its config references it by name
  (`channels.a2a.peers.<you>.token: "${A2A_HERMES_TOKEN}"`); read it into a shell variable, never print
  it, never paste it into chat or a config that gets committed. No bearer means 401 — that is the
  transport telling you which side owns the secret.
- **The peer needs an explicit route owner for the channel.** Its top-level `bindings[]` must carry a
  route for the peer channel, in the same shape as its other channels:
  `{"type":"route","agentId":"<agent>","match":{"channel":"a2a","accountId":"*"},"session":{"dmScope":"per-channel-peer"}}`.
  Without it, every dispatched task is created and immediately fails with the peer's own explanation
  ("multiple agents are configured, but … default routing has no explicit owner"). Back up the peer's
  config before editing it, keep the same key order and set of keys as its existing bindings, and
  restart its gateway afterwards.
- **Read the task state, not the status code alone.** `HTTP 200` + `result.task` is a real task; check
  `result.task.status.state`. `TASK_STATE_COMPLETED` is the proof the whole chain works;
  `TASK_STATE_FAILED` carrying a `status.message` still means auth + protocol succeeded — the message is
  the peer naming its own misconfiguration (routing, model, missing capability). Quote it verbatim as
  the finding.
- Right after a gateway restart the port refuses connections for a few seconds: an immediate `HTTP 000`
  is a restart artifact. Poll the port until it answers, then probe.
- Hermes' own inbound A2A and its **outbound** peer list are configured separately, and outbound is off
  by default.

## 2. Deposit: the executor records what it did

`tools/intelligence-deposit.py --what … --worked … --failed … --evidence … [--tags a,b] [--source …] --apply`

- Dry run by default; `--apply` files an `experience` candidate as the executor identity. It can only
  ever file a candidate — the executor never validates or approves, and must not be given the scope to.
- `--worked` / `--failed` / `--evidence` are the payload that makes a deposit reusable. Evidence must be
  a path, command or number; "it worked well" is not evidence, and a depositor that accepts vague input
  just files chat logs.
- `--source "a2a:<taskId>"` ties a deposit to the dispatch that produced it, using a field the audit
  trail already exposes. Traceability without touching the artifact schema.
- The executor's **skill** that triggers this lives in its own skills tree (for OpenClaw:
  `/mnt/d/OpenClaw/workspace/skills/<name>/SKILL.md`) using the same frontmatter convention as Hermes
  skills (`name`, `description` starting with the trigger, optional `metadata.openclaw.emoji`). Adding a
  skill directory is additive — no config edit — but a running worker may need a restart or a new
  session before it sees it.

## 3. Harvest: the learner finds other agents' work

`tools/intelligence-harvest.py [--json] [--all] [--commit]`

- Judgement comes from the **append-only audit log** (`$INTELLIGENCE_STATE/audit.jsonl`, action
  `submit_candidate`), never from `created_by`: that field is what the submitter wrote about itself.
- Identities belonging to the learner are skipped — the learner's own submissions are not "another
  agent's work".
- Cursor lives in `$INTELLIGENCE_STATE/harvest-cursor.json` and advances **only** on `--commit`, so a
  distillation that fails does not silently consume the deposit; the next run shows it again.
- Older audit rows carry no `kind`, and skills are stored as `<id>/manifest.json` while other kinds are
  `<id>.json` — a lookup that trusts one shape or one field reports records it cannot load. Search every
  kind and both layouts.
- **The kind name is not the directory name.** On disk a skill is `skills/<status>/<id>/manifest.json`
  and a source is `sources/<id>.json`, so a lookup at `STORE/<kind>` finds nothing for those two and
  every skill or source deposit digests as `status None / empty body` — indistinguishable from a test
  fixture, so the learner skips real work (measured: `excel-merge` sits in `skills/approved/` while the
  digest printed `[skill/None]`, no title, no body). Map `skill→skills`, `source→sources`.
- **A digest line is an audit row, not proof of a deposit.** Confirm the id resolves in the store before
  treating it as new work: after one gap, 28 distinct `submit_candidate` rows resolved to 3 artifacts —
  25 were test-suite fixtures written into the *live* audit trail, and two of the three were pre-existing
  approved artifacts (`pit-available-time-semantics`, `excel-merge`, both `created_at 2026-09-16`) merely
  re-stamped by a fixture run. So read the loaded artifact's `created_at`/`created_by` before distilling
  what looks like fresh work by another actor, mark rows with no artifact in the digest ("no artifact in
  store"), commit the cursor past them since there is nothing to cite, and report the leak as a finding —
  never file a candidate about a fixture.

## 4. Distill: the learner files knowledge that cites its source

- The learner reads the digest and submits a `knowledge` (or `skill`) candidate whose `source[]` cites
  the deposited artifact — `{"type":"agent_artifact","ref":"<kind>:<id>","retrieved_at":…}` — with
  `provenance` recording the distillation. Cite the source; do not copy its body into the candidate.
- Body shape differs by transport: the HTTP endpoint takes the **bare artifact**, the MCP tool takes
  `{artifact: …}`. An envelope sent over HTTP fails the status guard ("must start as candidate or
  experimental") because the service never saw the artifact.
- **Ids are ASCII-only** (`[A-Za-z0-9][A-Za-z0-9._-]{0,127}`). Keep the Chinese in `title`/`content` and
  transliterate the id; a wholly non-Latin title still needs a fallback word plus a date so two
  sessions cannot collide.
- Scheduling: run the digest as a cron **monitor** (not `script`), so an empty unchanged digest
  suppresses the agent run entirely and an idle KB costs no model turn. Keep the digest deterministic
  when empty; expect one extra wake on the tick after a commit, when it goes from items back to empty.
- Nothing in this loop may validate or approve. Executor and learner both stop at `candidate`.

## 5. Client credentials once identity names are refused

After the legacy-name switch is off, a client that presents an identity *name* gets 403. Wire every
client the same way:

- **Configuration keeps the identity name; the client resolves it to a token at startup** through one
  shared resolver (`tools/intelligence_identity.py`: `token_for(identity, env_var)`), with plaintext
  tokens in the owner's credential file (mode 600, outside the repo) and only `sha256` in the store.
  One resolver means a missed client fails visibly instead of authenticating by name.
- **In-process callers want the identity, HTTP callers want the token.** A driver that imports the
  gateway module and calls it directly (`intelligence-auto-admit.py`) must keep the *name* — handing it
  a token fails at runtime with an unknown-actor error listing the known identities. Comment which is
  which so the next edit does not cross them.
- A code change inside an MCP adapter takes effect only when the host that spawned it restarts. Prove the
  new path by starting that server yourself over its own transport (stdio JSON-RPC: `initialize`,
  `tools/list`, then one real `tools/call`) rather than assuming a restart reached it.
- Before flipping the switch, confirm the switch itself reaches the process: environment lines placed
  after the last section header of a systemd unit are silently ignored, so the flip can look applied while
  names still succeed. See `governance-auth-hardening` for the full flip checklist.

## 6. Share a skill: one runtime's沉淀 becomes another runtime's capability

- **Inventory before claiming sharing.** Count `SKILL.md` under each runtime's own root and intersect
  by directory name. Measured here: 109 vs 20 skills, **0** names in common. "We already share skills"
  was simply false, and no retrieval tuning fixes a supply gap.
- `kb_skill_sync.py --scan` diffs both roots against the store (missing / content-changed / ships
  scripts / carry-scope). `--apply` submits `kind=skill` with `content` = the `SKILL.md` body verbatim,
  and `metadata` carrying `name description inputs outputs dependencies permissions`, `verification`,
  `origin_runtime` / `origin_path` / `sha256`, and `tags`.
- **Tags and scope are the parts that decide whether it is reachable.** The ranker weights
  `metadata.tags` at 2.0 and `applies_to` at 0, so an untagged skill is findable by body text only.
  Personal trees (`skills/local/**`) go in as `scope=local` so a borrowed identity cannot read them;
  everything else `domain`.
- Install back out with `--install <id> --to <skills dir>`: it writes `content` to `SKILL.md`. Verify
  the round trip **twice** — `diff -q` against the source for bytes, and the receiving runtime's own
  listing (`hermes skills list` showing `shared | enabled`) for "it actually loaded". Bytes matching
  is not the same claim as the runtime seeing it.
- **Known gaps — state them instead of implying full sharing.** `--apply` skips an id already in the
  store, so an edited skill does not flow back (needs an update/`supersedes` mode); and only
  `SKILL.md` is stored, so a skill that ships scripts installs incomplete because its attachments
  still live only in the source tree. Half a skill shared is not shared.
