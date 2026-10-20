# Troubleshooting

### Voice not working
1. Check `stt.enabled: true` in config.yaml
2. Verify provider: `pip install faster-whisper` or set API key
3. In gateway: `/restart`. In CLI: exit and relaunch.

### Tool not available
1. `hermes tools` — check if toolset is enabled for your platform
2. Some tools need env vars (check `.env`)
3. `/reset` after enabling tools

### Model/provider issues
1. `hermes doctor` — check config and dependencies
2. `hermes auth` — re-authenticate OAuth providers (or `hermes auth add <provider>`)
3. Check `.env` has the right API key
4. **Copilot 403**: `gh auth login` tokens do NOT work for Copilot API. You must use the Copilot-specific OAuth device code flow via `hermes model` → GitHub Copilot.

### Changes not taking effect
- **Tools/skills:** `/reset` starts a new session with updated toolset
- **Config changes:** In gateway: `/restart`. In CLI: exit and relaunch.
- **Code changes:** Restart the CLI or gateway process

### web_extract shows a stale page (result caching)
`web_search`/`web_extract` cache results for 20 minutes (PR #94618) — a
repeat fetch of the same URL within the TTL is served from cache, which
can look like "my website changes aren't showing up."

Automatic carveouts (always fetched live, never cached):
- localhost / 127.0.0.1 / `*.local` / `*.localhost` / single-label LAN
  hostnames / private + link-local IP ranges (dev servers, hot-reload
  builds, chat-GUI artifact previews)
- URLs matched by `security.website_blocklist`
- failed responses and keyless-rescue-served responses

Developing a site tested over the PUBLIC internet (Vercel/Netlify
preview, ngrok/cloudflared tunnel, staging domain)? Public DNS isn't
auto-carved-out — list the host in config.yaml:

```yaml
web:
  cache_exempt_hosts:      # always fetched live; effective immediately
    - mysite.vercel.app
    - "*.ngrok-free.app"
    - mysite.dev           # suffix match: also covers preview.mysite.dev
```

Blunt instruments: `web.cache_ttl_minutes: 1` (min) or
`web.cache_enabled: false` disables both caches entirely.

### Skills not showing
1. `hermes skills list` — verify installed
2. `hermes skills config` — check platform enablement
3. Load explicitly: `hermes -s name` (or the skill's own `/<name>` slash command)

### Gateway issues
Check logs first:
```bash
grep -i "failed to send\|error" ~/.hermes/logs/gateway.log | tail -20
```

Common gateway problems:
- **Gateway dies on SSH logout**: Enable linger: `sudo loginctl enable-linger $USER`
- **Gateway dies on WSL2 close**: WSL2 requires `systemd=true` in `/etc/wsl.conf` for systemd services to work. Without it, gateway falls back to `nohup` (dies when session closes).
- **Gateway crash loop**: Reset the failed state: `systemctl --user reset-failed hermes-gateway`

### Platform-specific issues
- **Discord bot silent**: Must enable **Message Content Intent** in Bot → Privileged Gateway Intents.
- **Slack bot only works in DMs**: Must subscribe to `message.channels` event. Without it, the bot ignores public channels.
- **Windows-specific issues** (`Alt+Enter` newline, WinError 10106, UTF-8 BOM config, line endings): see `references/windows-quirks.md`.

### Auxiliary models not working
If `auxiliary` tasks (vision, compression, session_search) fail silently, the `auto` provider can't find a backend. Either set `OPENROUTER_API_KEY` or `GOOGLE_API_KEY`, or explicitly configure each auxiliary task's provider:
```bash
hermes config set auxiliary.vision.provider <your_provider>
hermes config set auxiliary.vision.model <model_name>
```

### "Reset permissions" / auto-approving everything
See `references/security-privacy.md` — wipe the "Always allow" stores, don't touch yolo mode.

### Cron failure alerts arrive in English (and other hardcoded UI strings)
Hermes has **no locale/i18n setting**: cron alert wording is hardcoded English
literals in `app/cron/scheduler.py` (`_summarize_cron_failure_for_delivery()`,
`_failure_streak_nudge()`, `_fallback_chain_phrase()`, the watchdog/monitor
alerts) and `app/cron/scheduler_script.py` (the `Script exited with code N` /
`stderr:` / `stdout:` labels). A user who wants everything in another language
must have those literals rewritten locally.

Local-install patching convention (`~/hermes/patches/`, e.g.
`apply-cron-message-zh-patch.py`): a standalone script holding OLD→NEW pairs with
`--check` (idempotent status), `--revert` (rollback derived from the same pair
table, so a rotated backup cannot lose the way back) and a per-run timestamped
`.bak`. Verify by calling the patched function directly (import the module, build
a fake job dict, print the string) — do **not** prove it by making a real job
fail, which delivers a test message to the user's chat.

Two traps:
- **The cron ticker lives in the gateway process**, so `systemctl --user restart
  hermes-gateway.service` is what reloads patched cron code — while a desktop
  chat session runs in a separate `hermes serve` backend (or inside the desktop
  app), so that restart does not interrupt the conversation. Restarting
  `hermes-backend`/`hermes-dashboard` does.
- **Do not translate internal contract strings** that other code matches on
  (`Script timed out after {n}s: {path}` is matched by
  `lower.startswith("script timed out")` and asserted in
  `app/evals/cron_timeout_fork_race.py`) unless you update every matcher in the
  same patch. Translate the *delivery* text instead; the raw error text is not
  what the user reads.

A no-agent job that crashes with a traceback is also a spec violation, not just
a language problem: script stdout IS included in the failure notice, so printing
a one-line summary in the operator's language before exiting non-zero makes an
unavoidable English wrapper prefix the only English left.

## browser_exec times out (`_IPCResponseTimeout ... waiting for the daemon`)

Two different failures wear the same message; tell them apart before acting.

- **Daemon won't start at all** — `The local browser could not be started: Chrome exited early ...
  error while loading shared libraries: libnspr4.so`: the machine is missing Chromium's runtime libs.
  Fix is root-only, so hand the operator `sudo apt install -y libnspr4 libnss3` (those two cover
  libnspr4/libnss3/libnssutil3/libsmime3). Confirm what is missing with
  `ldd <chrome> | grep "not found"` rather than guessing a package list.
- **Daemon alive but the page is wedged** — `ensure_real_tab()` *succeeds* while `js('location.href')`
  still times out, or a single navigation hangs: the renderer/page is stuck (JS-heavy or bot-walled
  site), not the IPC layer. Do not chase the timeout value: the harness IPC response timeout is a
  hardcoded 5.0s (`DEFAULT_IPC_RESPONSE_TIMEOUT_SECONDS` in `browser_harness/helpers.py`); only
  `cdp()` accepts `_response_timeout`, and raising it to 60s still fails against a hung renderer.
  Recover by killing the daemon; the next `browser_exec` call spawns a fresh one:

  ```bash
  pgrep -af "browser_harness[.]daemon"          # path: ~/.cache/uv/archive-v0/*/bin/python -m browser_harness.daemon
  kill <daemon-pid>
  pkill -f "ms-playwright/chromium-12[4]3"      # bracket a digit: an un-bracketed pattern matches
                                               # this very command line and SIGTERMs your own shell
  ```

  State lives in `~/.config/browser-harness/runtime/bu-default.{pid,sock}`; stale files there are
  harmless once the daemon is gone. `hermes browser close-profile` is NOT this — it kills the
  operator's real browser profile and loses unsaved tabs.
- WSL note: `/dev/shm` is usually large enough (check `df -h /dev/shm`); a small one is the classic
  Chromium hang cause elsewhere, so rule it out before blaming the harness.

