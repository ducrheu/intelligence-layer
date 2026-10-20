# OpenClaw runtime notes (agents, routing, credentials, cost)

Established by inspecting a live install. None of it is in always-loaded context,
and it decides what dispatch architectures are even possible.

## Layout

- Config: `~/.openclaw/openclaw.json`; per-file secrets under `~/.openclaw/env/`.
- Agent dirs: `~/.openclaw/agents/<id>/agent/` — each holds its **own**
  `openclaw-agent.sqlite`, which is both the session store and the provider-auth
  store. A freshly declared agent therefore has **no model credentials**, and every
  run fails with `missing-provider-auth` until it is granted some.
- Sessions and transcripts live **in that sqlite**, not in files:
  `transcript_events(session_id, seq, event_json, created_at)`, plus
  `conversation_deliveries` and FTS mirrors; the old `sessions/*.jsonl` are retired.
  To answer "was tool X ever actually called?", query the sqlite read-only
  (`sqlite3.connect('file:<db>?mode=ro', uri=True)`, filter
  `event_json LIKE '%<name>%'`, print `message.role` + a slice of the content) across
  `agents/*/agent/openclaw-agent.sqlite`. Grepping the tree finds nothing.
- Workspace: `/mnt/d/OpenClaw/workspace` — `skills/` is shared by every agent and
  the root `MEMORY.md` is shared, while per-agent memory lives under
  `workspace/agents/<id>/`. **Skills are shared; memory is per-agent.** The only
  cross-agent knowledge stream is the governed KB, and that is by design: an
  agent's private memory is unverified self-report and must not become another
  agent's fact.
- Gateway logs are **journald**, not a file: `journalctl --user -u
  openclaw-gateway.service --since "2 minutes ago"`. `[ws] ⇄ res ✓ <method>` lines
  are the method-level call record; `[node-connect] node command surface withheld
  node=… commands=…` names what a paired node can be asked to do.
- Local docs and source for behaviour questions: the unpacked release under
  `/mnt/d/OpenClaw/openclaw-source-<version>/docs` (e.g. `docs/tools/tts.md`,
  `docs/gateway/config-agents.md`, `docs/nodes/talk.md`) and the running install
  at `~/.npm-global/lib/node_modules/openclaw`. Never run a content search across
  the whole `/mnt/d/OpenClaw` tree — narrow to `docs/`, one package dir, or a
  single file first, or the probe times out and teaches nothing.

## Agent entries

`agents.entries.<id>` = `{name, workspace, agentDir, model{primary,fallbacks},
subagents{allowAgents}, skills[], tools{profile,allow,deny}}`, with
`agents.ownership: explicit` requiring every agent to be declared.

## Routing

- Top-level `bindings` = `[{type: "route", agentId, match:{channel, accountId},
  session:{dmScope}}]`. Bindings match **channel + account only** — the config's own
  comment says they do not match message text, so a target agent cannot be selected
  by message content.
- `channels.a2a` = `{enabled, exposeAgents[], peers{<name>:{url, token}}}` — no
  per-agent routing key. Practical consequence: **expose one entry point and let
  that agent fan out downward.**
- Downward fan-out is `<agent>.subagents.allowAgents`, empty by default: an agent
  cannot delegate until the targets are listed, even when the target agents exist.
- Confirm a dispatch actually reached a specialist in the journal — the lane is
  named `lane=session:agent:<id>:a2a:<peer>:<messageId>`. That is the only proof;
  a task state alone does not say which agent ran it.
- An inbound A2A task with no route binding for its channel fails **at agent
  selection** ("multiple agents are configured, but a2a account default routing has
  no explicit owner"). That is a routing gap, not an auth or transport error — read
  the returned message before debugging the token.
- A service that caches its credential at startup must be relaunched after any
  rotation, and a newly declared agent needs its own provider auth before it can
  run at all; both failures surface as task-level errors, not startup errors.

## Credentials

- Provider auth is per-agent and agentDir-scoped: `openclaw models auth
  paste-api-key --provider <p> --agent <id>`, with the value entered by the user and
  never typed into chat. "Copy the portable static auth profile from the main
  agentDir" only applies where such files exist — check the directory before
  promising that route; on this install the auth lives inside the per-agent sqlite,
  so that route does not exist and the CLI is the only path.
- Capability surfaces are plugins, and the startup log lists them (browser,
  duckduckgo, cua-computer for real computer control, memory-core, a2a, …). Read
  that line to know what a permission grant would actually enable.

## Model declarations drive cost

`models.providers.<provider>.models[*].contextWindow` / `maxTokens` are not
cosmetic: they set the threshold at which history is compacted. Declared far above
the model's real window (seen here: 1,000,000 context with a 384,000 output cap for
one provider whose siblings were declared 8,192), compaction never triggers and
every turn resends a huge history. Check these numbers first when a runtime "costs
more than it should", before touching any topology — an extra dispatch hop costs a
few hundred tokens, while an uncompacted context costs orders of magnitude more.

## Permission vocabulary

Deny/allow lists use `group:web`, `group:ui`, `group:messaging`, `group:nodes`,
`group:automation`, `group:media`, plus individual tool names (`read`, `exec`,
`process`, `write`, `edit`, `apply_patch`, `browser`, goal and memory tools).
Granting an execution capability means adding to `allow` **and** dropping the
matching item from `deny`, while leaving the messaging / node / automation groups
closed. Widen by deliverable, not in bulk: an agent that only teaches needs no
write tools, one that ships deliverables does. Per-agent name lists live under
`agents.entries.<id>.tools.allow`, so "who can do X" is answered by grepping the
raw config for the tool name across every entry — not by reading one agent.

## Windows companion (the tray app, which is also a node)

One GUI process does three jobs at once: it is the gateway's **node** (its handshake
prints the command surface, e.g. `commands=[… tts.speak, tts.status, stt.transcribe,
stt.listen, browser.proxy, system.run, canvas.*, screen.*, camera.* …]`), it renders
the chat the operator works in (its log's `[ChatTrace] chat.message role=… len=…`
lines are that window), and it owns local media engines. Anything it does locally is
invisible to the gateway.

Paths (Windows → WSL):

| What | Windows | From WSL |
| --- | --- | --- |
| Settings | `%APPDATA%\OpenClawTray\settings.json` | `/mnt/c/Users/<user>/AppData/Roaming/OpenClawTray/settings.json` |
| Gateway records | `%APPDATA%\OpenClawTray\gateways.json`, `gateways/<id>/` | same under `/mnt/c` |
| Log + diagnostics | `%LOCALAPPDATA%\OpenClawTray\openclaw-tray.log` (+`.old`), `Logs\diagnostics.jsonl`, `last-chat-state.json`, `tool-metadata.json` | same under `/mnt/c` |
| Model assets | `%APPDATA%\OpenClawTray\models\` — whisper `ggml-*.bin`, `piper/<voice>/` | same under `/mnt/c` |
| Binaries | `D:\OpenClaw\OpenClawTray\` (`OpenClaw.Tray.WinUI.exe`, `OpenClaw.Shared.dll`, sherpa-onnx/whisper DLLs) | `/mnt/d/OpenClaw/OpenClawTray/` |

Settings keys worth knowing: `EnableNodeMode`, `NodeTtsEnabled`, `VoiceTtsEnabled`,
`TtsProvider` (`piper|windows|elevenlabs|minimax`), `TtsPiperVoiceId`,
`TtsWindowsVoiceId`, `NodeSttEnabled`, `SttModelName`, `NodeBrowserProxyEnabled`,
`NodeSystemRunEnabled`, `SystemRun*`, `NodeCanvasEnabled`, `NotifyChatResponses`,
`VoiceAudioFeedback`, `ShowChatToolCalls`. The `Node*` keys decide which capabilities
the gateway may invoke; `VoiceTtsEnabled` is the chat window's own voice output, and
the window also has a composer speaker toggle and a per-message read-aloud action
(`ChatComposerSpeakerToggle`, `Chat_Assistant_Action_ReadAloud`).

Reading GUI wording/feature names out of the binaries: `strings -el <dll>` (UTF-16LE)
on `OpenClaw.Tray.WinUI.dll` / `OpenClaw.Shared.dll`; plain `strings` misses .NET
strings. Useful needles: `ReadAloud`, `Speaker`, `VoiceTtsEnabled`, `Node*Enabled`,
`Requires Node<X>Enabled` (each tool's doc string names its own gate), `tts.speak`.

Voice/TTS has four independent layers — check which one owns the behaviour instead of
reconfiguring all of them:

1. **Gateway TTS** — `tts.*` config (documented default: auto-TTS **off**; the `tts`
   agent tool is explicit-intent only) and `agents.entries.<id>.tts` for per-agent
   voice/auto mode. `openclaw config get tts` answering *"valid but unset — the
   runtime default applies"* is a positive finding, not a missing file.
2. **The `tts` agent tool** — present in every agent's `tools.allow` in the raw
   config; the agent calling it is an explicit act and does appear in the transcript.
3. **The Windows node's `tts.speak`** — gated by `NodeTtsEnabled`; a real invocation
   would show as a `node.invoke` request in the tray log and in the journal.
4. **Talk / realtime** — `talk.catalog` / `talk.session.create` / `talk.client.create`
   in the journal; needs a realtime provider credential, and a failure leaves a
   `[fetch-timeout] … /v1/realtime/client_secrets` line, so a talk attempt that never
   spoke is identifiable.

**A working client-side playback logs nothing.** The tray writes a line only on
failure (`TTS playback failed`, `TTS speak not available`, `Speaker mute change
failed`), and no `node.invoke` appears for local playback. Identification is by state
— provider + voice assets present (`models/piper/<voice>/`), the toggles true — and
should be reported as such. When the tray is the owner, hand the operator the in-app
toggle first, then the `settings.json` keys, and ask before restarting the app (it
closes their chat window).
