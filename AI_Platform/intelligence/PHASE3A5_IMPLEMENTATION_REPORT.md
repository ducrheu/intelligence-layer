# Phase 3A.5 Implementation Report

**Date:** September 19, 2026  
**Status:** BLOCKED  
**Scope:** Experimental Hermes runtime installation and real read-only consumer verification

## 1. Result

Phase 3A.5 runtime verification is **BLOCKED**. Hermes v0.21.3 was
successfully installed in the isolated D: drive venv, but a real agent turn
was not started because the available safe model/runtime boundary could not be
completed without weakening the experiment's controls.

The existing runtime-neutral consumer contract remains healthy, and the
Intelligence Layer boundary was exercised through the local HTTP API, but no
real Hermes process was started. Therefore this report does not claim a real
Hermes runtime PASS.

```text
Hermes source verification: PASS
Hermes isolated installation: PASS
Hermes executable verification: PASS
Local Intelligence API health: PASS
Ollama isolated runtime: NOT STARTED
Real Hermes runtime verification: NOT EXECUTED
```

## 2. Environment

| Component | Observed value |
|---|---|
| OS | Windows; WMI OS detail query was access-denied in the sandbox |
| PowerShell | 7.6.5 |
| Python | 3.12.9 |
| Node.js | v24.18.0 |
| npm | 11.16.0 |
| Git | 2.54.0.windows.1 |
| WSL | `wsl --status` access denied; not used |
| Ollama | `D:\Ollama\ollama.exe`; local models present; service not started by this phase |
| Hermes | `v0.21.3`, isolated under `D:\AI_Platform\runtime-lab\hermes` |

The verified release ZIP was extracted without entry/hash mismatches:

```text
source: D:\AI_Platform\runtime-lab\hermes\source\hermes-agent-2026.9.14
venv:   D:\AI_Platform\runtime-lab\hermes\venv
version: Hermes Agent v0.21.3 (2026.9.14)
```

## 3. Official Hermes Discovery

The official project identity used for discovery was:

```text
NousResearch/hermes-agent
```

The official Windows installer was inspected without executing it:

```text
https://hermes-agent.nousresearch.com/install.ps1
```

The installer supports explicit `-HermesHome` and `-InstallDir` parameters,
which could in principle place the checkout and runtime under an isolated
experiment directory. Its default installation uses a user-local Hermes home
under `%LOCALAPPDATA%\hermes`; it also contains separate stages for PATH
changes, configuration templates, dependencies, and interactive setup.

The installer was not executed. In particular, no PATH stage, configuration
stage, gateway stage, or setup wizard was run.

## 4. Installation and Runtime Blocker

The verified ZIP was extracted to D: and compared against the archive:

```text
ZIP files: 13,048
Extracted files: 13,048
Uncompressed size: 171,854,730 bytes
Extracted size: 171,854,730 bytes
File hash mismatches: 0
```

The project's ordinary wheel install intentionally failed with its own
packaging guard. The source documentation states that development/source
installation must use an editable install, so the following succeeded:

```text
D:\AI_Platform\runtime-lab\hermes\venv\Scripts\python.exe -m pip install -e .
```

No installer script, PATH modification, service, scheduled task, or global
Python installation was used.

The runtime turn remained blocked for two independent reasons:

1. Ollama was not running. `D:\Ollama` contains local models
   (`qwen2.5:7b`, `qwen2.5vl:7b`, and `nomic-embed-text`), but the existing
   launcher binds `0.0.0.0:11434`. It was not used because this phase permits
   loopback-only access.
2. Hermes does not ship a native tool binding for the existing
   Intelligence Gateway. Its normal agent startup performs plugin/MCP
   discovery, and using terminal/web tools as a substitute would grant more
   authority than the required `local-hermes` read-only boundary.

An exploratory invocation of the installed Ollama CLI attempted to reach its
existing Windows log location under `<USERPROFILE>\AppData\Local\Ollama` and
failed with access denied. No credentials were read and no Ollama process was
left running. This is recorded as a safety observation; the CLI was not
retried.

No API key, OpenClaw credential, production token, or other secret was copied
to Hermes.

## 5. Runtime and API Boundary

The existing experimental API was started temporarily with:

```powershell
python -m AI_Platform.intelligence.experimental.api.run_server `
  --root AI_Platform/intelligence `
  --port 8765
```

Health verification, using the server-side experimental identity header:

```text
GET http://127.0.0.1:8765/health
HTTP 200
{"status": "ok", "bind": "127.0.0.1"}
```

The API process was stopped after verification. No persistent service,
scheduled task, startup task, or background Hermes/Ollama process was left
running.

The intended Hermes identity remains:

```text
local-hermes
scopes:
  read:approved
  read:governance-metadata
```

No direct filesystem consumer was added. No MCP server, OpenViking adapter,
database, vector store, or production integration was added.

## 6. Real Hermes Test Matrix

The following tests were **not executed against a real Hermes process** because
the executable was unavailable:

| Test | Result |
|---|---|
| Startup, version, PID | BLOCKED: runtime not started |
| Approved `excel-merge` retrieval | BLOCKED: no native HTTP consumer tool |
| Validated-but-not-approved PIT evidence | BLOCKED |
| PIT provenance retrieval | BLOCKED |
| Approved-only isolation | BLOCKED |
| Candidate write denial | BLOCKED |
| Approval denial | BLOCKED |
| Prompt-injection handling | BLOCKED |
| Bounded retrieval | BLOCKED |

The equivalent runtime-neutral consumer contract had already passed in Phase
3A through the same API boundary. That prior result is not relabeled as a real
Hermes runtime result.

Evidence files were written under:

```text
D:\AI_Platform\runtime-lab\hermes\evidence\
```

including `runtime-start-report.json`, `runtime-test-report.json`,
`filesystem-access-report.json`, `network-access-report.json`, and
`regression-report.json`.

## 7. Security and Safety

The following safety properties were preserved:

- No production OpenClaw process was started.
- No file was written under `D:\OpenClaw\workspace`.
- No production OpenClaw configuration, routing, Gateway, Cron, QQ Bot,
  Memory, topology, or Skill was modified.
- No PIT file or database was written.
- No Legacy Freelance file, registry, Skill, Experience, or Job Runner was
  modified.
- No production credential was copied or exposed.
- The experimental API remained bound to `127.0.0.1`.
- Hermes was installed but was not started, so it was not granted production
  filesystem access.
- No candidate-write or approval permission was granted to `local-hermes`.
- No global PATH or system environment variable was changed by this phase.
- No persistent Hermes/API service was created.

## 8. Regression

Command:

```powershell
python -m unittest discover -s AI_Platform/intelligence/tests -p "test_*.py"
```

Result from the installed environment:

```text
39 passed, 0 failed, 2 errors
```

Compilation check:

```powershell
python -m compileall -q AI_Platform
PASS
```

The two errors are pre-existing environment errors caused by the missing
Legacy Freelance workspace:

```text
<USERPROFILE>\Documents\Codex\2026-09-11\openclaw-openclaw-openclaw-codex-ai-1
```

No Legacy workspace was created or repaired. No existing test was deleted or
weakened. `compileall` passed.

## 9. Production Integrity

### OpenClaw

```text
Production path: D:\OpenClaw\workspace
Phase 3A.5 writes: none
Production process started: no
```

The production OpenClaw repository already had unrelated pre-existing dirty
state when inspected. This phase did not attempt to clean, repair, or attribute
those changes.

### PIT

```text
Path: D:\quant-data-project
Branch: master
HEAD: d9e00554195d7399dd92ce3ade2a77fbfced62f7
```

The working tree contained pre-existing changes in the inspected environment.
No Phase 3A.5 command wrote to the repository, and the HEAD remained unchanged.

### Legacy Freelance

The selected workspace was absent in this environment. No workspace was
created, no Job was executed, and the read-only adapter was not changed.

## 10. Files Created / Modified / Deleted

### Created

```text
AI_Platform/intelligence/PHASE3A5_IMPLEMENTATION_REPORT.md
```

An isolated staging directory was created during the failed repository
download attempt and removed during clean shutdown:

```text
runtime-lab/hermes/
```

It contained no Hermes source, executable, configuration, credentials, or
runtime data. The directory no longer exists.

### Modified

```text
Modified:

```text
AI_Platform/intelligence/PHASE3A5_IMPLEMENTATION_REPORT.md
```
```

### Deleted

```text
Deleted: none
```

No existing Phase 1, Phase 2, or Phase 3A implementation was redesigned.

## 11. Known Limitations

1. Hermes is installed but its real agent turn was not started.
2. Ollama local models exist, but the available launcher is not loopback-only
   and its CLI touched a C: AppData log path; it was not used for runtime.
3. Hermes has no native adapter for the existing Intelligence HTTP API.
4. Enabling terminal/web/MCP as a workaround would violate the required
   read-only authority boundary.
5. The eight requested real-runtime tests remain unexecuted.
6. No isolated model credential is configured.
7. No MCP, OpenViking, semantic retrieval, private Hermes memory, or
   production authentication was introduced.

## 12. Next Recommendation

Do not proceed to Phase 3B.

Before retrying the real runtime test, make one controlled decision:

1. Provide a loopback-only Ollama launch configuration whose model data and
   logs stay on D:, or provide another isolated local OpenAI-compatible model
   endpoint.
2. Define an approved, read-only Hermes-to-Intelligence HTTP tool boundary.
   This could be a future Hermes-side adapter, but it must not grant shell,
   MCP, arbitrary filesystem, candidate-write, or approval authority.
3. Preserve the explicit D: `HERMES_HOME`, workspace, cache, and log paths.
4. Run only the read-only consumer experiment first.

Until those conditions are available, the correct result remains:

```text
BLOCKED
```

No Candidate Write, QA integration, Human Approval integration, MCP work,
OpenViking work, or production OpenClaw integration should begin.
