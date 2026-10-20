# Updating the OpenClaw runtime (npm global install)

Measured on this box: install kind `package`, mode `npm`, root
`~/.npm-global/lib/node_modules/openclaw`, channel `stable` (default), service
`openclaw-gateway.service` whose `ExecStart` points straight at
`<root>/dist/index.js`. Config `~/.openclaw/openclaw.json` holds hand-edited
routing, channels and model declarations — back it up before touching anything.

## Procedure

1. `openclaw --version` and `openclaw update status` — channel, available
   version, install kind. `npm view openclaw dist-tags --json` shows the
   candidate tags (`latest`, `extended-stable`, `beta`) independently.
2. `cp ~/.openclaw/openclaw.json ~/.openclaw/openclaw.json.bak-before-update-$(date +%Y%m%d-%H%M%S)`.
3. `openclaw update --dry-run --yes` — prints the exact planned steps without
   writing (package manager target, plugin sync, completion refresh, service
   restart + doctor).
4. `openclaw update --yes` and then judge it by state, not by its exit output
   (see below).
5. `openclaw update repair --yes --json` if doctor/update reported abandoned
   handoff or post-update convergence warnings.
6. Verify (all four): `openclaw --version` = target; `systemctl --user is-active
   openclaw-gateway` = active; `openclaw channels status` shows each channel
   `running, connected`; `openclaw doctor` runs to completion.

## Traps, each one observed

- **A CLI `openclaw update` run from inside/next to the gateway returns
  `status: skipped`, `reason: managed-service-handoff-started` — that is not a
  failure.** The update is re-parented to a detached supervisor because the
  gateway cannot replace its own package and then kill itself. Real progress
  goes to `/tmp/openclaw-update-run-handoff-*/handoff.log`; the gateway is
  deliberately parked (`inactive`) mid-update and restarted at the end
  (`Restarted systemd service: openclaw-gateway.service`). Track it with the log
  plus `openclaw update status --json` → `lastRun.status: succeeded`,
  `lastRun.target.version`, `lastRun.after.version`, `availability.available`.
- **A stale `~/.openclaw/.upgrading` file (contents = a PID that no longer
  exists) poisons the next update.** Symptoms: `existing managed handoff lease is
  incompatible; retain diagnostics and run openclaw triage manually` and, from
  doctor, `Update executor was lost during native preparation`. Confirm the PID
  is gone (`ps -p <pid>`) and move the file aside — archive it, do not delete —
  then run `openclaw update repair --yes`.
- **Doctor and `update repair` fail with `SQLite source did not stabilize after
  10 read-only inspection attempts` when the gateway is hot** (it is writing its
  own state DB). Wait 1–2 minutes and re-run; do not conclude the DB is broken.
- **CLI-side doctor reports `channels.a2a.peers.hermes.token: env var
  "A2A_HERMES_TOKEN" … feature unavailable`.** False alarm from the CLI shell:
  the token lives in the systemd drop-in `EnvironmentFile`
  (`~/.config/systemd/user/openclaw-gateway.service.d/a2a-hermes.env`), which the
  gateway loads and the interactive CLI does not. `openclaw channels status`
  showing `A2A default: … connected` settles the question.
- **Plaintext-secret and `models[].route` doctor warnings are pre-existing
  config debt, not update fallout.** They appear identically before and after;
  do not treat the update as the cause and do not "fix" them mid-update.
- **Transcript-archive warnings during migration** (`Missing canonical
  transcript archive copy …` / `historical_transcript_deferred`) are historical:
  the SQLite blobs are retained and migration completes; they are only a problem
  if a conversation a human expects is actually missing.
- **Schedule the update inside the awake window (23:00–06:00 is a hard power
  cutoff on this box).** The restart is not instant and a cut mid-update leaves
  exactly the half-finished handoff described above.
