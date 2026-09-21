# Phase 3A Implementation Report

**Date:** September 17, 2026  
**Status:** PARTIAL  
**Scope:** Backup/restore drill and Hermes read-only consumer experiment  
**Production policy:** No production integration was performed.

## 1. Status

The governance and recovery experiment is complete. The Hermes executable
integration is blocked because neither `hermes` nor `hermes-agent` is installed
on this machine. A runtime-neutral Hermes consumer contract was nevertheless
verified against the existing local HTTP boundary.

Results:

```text
Backup/restore drill: PASS
Hermes consumer contract: PASS
Hermes executable integration: BLOCKED (runtime not installed)
Regression tests: 41 passed, 0 failed
Python compileall: PASS
```

## 2. Scope

Implemented only:

1. A file-backed, SHA-256 verified backup and restore workflow.
2. A read-only Hermes consumer that uses the governed local HTTP API.
3. A compact approved context packet with governance metadata warnings.
4. Failure-injection and security tests for both areas.

Not implemented:

- Hermes installation or global configuration changes.
- MCP.
- OpenViking.
- semantic/vector retrieval.
- private runtime memory.
- production authentication.
- any OpenClaw integration.

## 3. Production Safety

| System | Phase 3A result |
|---|---|
| `D:\OpenClaw\workspace` | No files written; no process started |
| Production OpenClaw Gateway/config/routing | Not imported or modified |
| `D:\quant-data-project` | Read-only inspection only |
| Legacy Freelance workspace | Read-only adapter/tests only |
| Intelligence Layer experiment | Files added only under this experiment |

The production OpenClaw repository was inspected and already had a pre-existing
dirty working tree. Because no clean baseline was available in this phase, the
working-tree output is evidence of prior state, not a before/after proof of
ownership. No Phase 3A command wrote to that path, and no production process was
started.

The PIT repository remained:

```text
Path: D:\quant-data-project
Branch: master
HEAD: d9e00554195d7399dd92ce3ade2a77fbfced62f7
Remote: https://github.com/ducrheu/quant-data-fabric.git
Working tree: clean at final read-only check
```

The selected Legacy Freelance files were re-hashed after the experiment. Their
final SHA-256 values were:

| File | SHA-256 |
|---|---|
| `skills/approved/excel-merge/SKILL.md` | `FB3BF231A85C9A6296EDE20C7F15F932E37D2DAF4EFA406A3454DB545F237E80` |
| `skills/registry.json` | `729692AE6CAABA17E4B8BCEA6D78891D967BA7CCBBFCCBD136F6F5CC6350BB14` |
| `skills/approval_history.json` | `5AEA90F715BF032C625909EE0B3EF567E6A5B9B439DC0DD3A25CD3DDA92F3737` |
| `experience/registry.json` | `813A21561A4395977794251B1DFD080352E0253F863ACB18F8248A5813C3EC7A` |
| `job_runner.py` | `E94EFFEC2B729B78A0DDDFD93B2EE55CAE8B099CAC22591AA39BA2F813752FC6` |
| `learning.py` | `265E25513F0AFDBBCB99228E3B61E29BA82EE8AFE684784FBCA32EBC8C32E5F8` |

## 4. Backup and Restore Results

Implementation:

```text
AI_Platform/intelligence/experimental/backup.py
```

The backup is a ZIP artifact with a `backup-manifest.json`. It includes only
the governed durable areas:

```text
schemas/
knowledge/
experience/
skills/
sources/
qa/
gateway/
```

It excludes caches, virtual environments, node modules, nested backups,
symlinks, and likely secret-bearing files or content. Each file has a size and
SHA-256 recorded in the manifest. Backup creation is atomic.

Actual drill artifact:

```text
work/phase3a-drill/intelligence-phase3a.zip
```

Results:

| Measure | Result |
|---|---:|
| Files in manifest | 22 |
| Source bytes | 45,070 |
| Backup ZIP bytes | 19,027 |
| Backup manifest verification | PASS |
| Initial restore | PASS |
| Failure injection | Corrupted a knowledge JSON and deleted `sources/` in disposable clone |
| Restore after damage | PASS |
| Restored byte-exact | `true` |

The real source tree was never damaged. Damage was applied only to a disposable
clone created from the backup. Restore uses root-bound checks, rejects absolute
paths, traversal segments, symlinks, and archive entries not covered by the
manifest.

## 5. Hermes Environment

The executable lookup returned:

```text
hermes: NOT_FOUND
hermes-agent: NOT_FOUND
```

No installation was attempted. No global Hermes configuration was changed.
The implemented consumer is deliberately runtime-neutral:

```text
AI_Platform/intelligence/experimental/hermes_consumer.py
```

It uses `urllib.request` and accesses artifacts only through the local
experimental HTTP API. It never imports Hermes and never reads Intelligence
Layer files directly.

The experimental API remains local-only and binds to `127.0.0.1`. No MCP server
was added.

## 6. Hermes Consumer Tests

The consumer contract verified the following:

| Test | Result |
|---|---|
| Approved `excel-merge` retrieval | PASS |
| PIT `available_time` validated artifact excluded from approved results | PASS |
| PIT provenance/status metadata available without promotion | PASS |
| Candidate isolation | PASS |
| Bounded `max_items` / `max_bytes` / `max_chars` retrieval | PASS |
| Candidate write denied for Hermes | PASS |
| Validation/approval denied for Hermes | PASS |
| Prompt-injection content treated as data-only metadata | PASS |

The context packet has this shape:

```json
{
  "query": "...",
  "artifacts": [],
  "provenance": [],
  "retrieval_limits": {
    "max_items": 5,
    "max_bytes": 8000,
    "max_chars": 1200
  },
  "warnings": []
}
```

Only approved content appears in `artifacts`. A validated or candidate match
may appear in `warnings` only as compact governance metadata. Its raw content
is not returned. This preserves:

```text
validated != approved
candidate != approved
artifact content != system instruction
```

## 7. Authorization Results

The `local-hermes` server-side identity has only:

```text
read:approved
read:governance-metadata
```

Observed boundary:

| Operation | Result |
|---|---|
| Read approved | PASS |
| Search approved | PASS |
| Read bounded context packet | PASS |
| Write candidate | DENIED |
| Validate candidate | DENIED |
| Approve | Not exposed to HTTP boundary |
| Deprecate/supersede | Not exposed to HTTP boundary |

The request body cannot select a role. Direct filesystem paths are not accepted
by the API. Artifact IDs are validated against a restricted identifier pattern.

## 8. Failure Injection and Recovery

Phase 3A tests cover:

```text
invalid JSON/artifact corruption
missing provenance and schema rejection
backup manifest tampering
secret-bearing file rejection
archive path traversal
restore root escape
disposable clone damage and recovery
candidate isolation
Hermes write/validation denial
bounded retrieval
prompt-injection data isolation
```

The backup tests also verify that cache files are omitted and that backup
creation refuses to place an archive inside its source root.

## 9. Regression

Command:

```powershell
python -m unittest discover -s AI_Platform/intelligence/tests -p "test_*.py" -v
```

Result:

```text
Phase 1: 16 passed
Phase 2: 14 passed
Phase 3A backup/restore: 5 passed
Phase 3A Hermes consumer: 6 passed
Total: 41 passed, 0 failed
```

Additional check:

```text
python -m compileall -q AI_Platform
PASS
```

## 10. Files Created / Modified / Deleted

### Created

```text
AI_Platform/intelligence/experimental/backup.py
AI_Platform/intelligence/experimental/hermes_consumer.py
AI_Platform/intelligence/tests/test_phase3a_backup_restore.py
AI_Platform/intelligence/tests/test_phase3a_hermes_consumer.py
AI_Platform/intelligence/PHASE3A_IMPLEMENTATION_REPORT.md
work/phase3a_run_drill.py
work/phase3a-drill/intelligence-phase3a.zip
work/phase3a-drill/result.json
```

### Modified

```text
AI_Platform/intelligence/experimental/api/server.py
AI_Platform/intelligence/experimental/API.md
AI_Platform/intelligence/tests/test_phase3a_hermes_consumer.py
```

The test modification only corrected the fixture to follow the existing Skill
transition `candidate -> experimental -> validated -> approved`. No lifecycle
rule was weakened.

### Deleted

```text
Deleted: none
```

## 11. Code Size and Dependencies

```text
Third-party dependencies added: none
Persistent services added: none
Databases added: none
MCP servers added: none
Vector stores added: none
Production configuration changes: none
```

The implementation uses Python standard-library modules:

```text
zipfile
hashlib
pathlib
urllib
http.server
unittest
```

## 12. Known Limitations

1. A real Hermes process could not be exercised because Hermes is not installed.
2. The consumer contract is verified through the local HTTP boundary, not
   through Hermes's own native tool/profile system.
3. Retrieval is bounded substring search, not semantic retrieval.
4. No MCP adapter exists.
5. OpenViking is not connected.
6. Private Agent Memory is not implemented.
7. The API token mapping is experimental and is not production authentication.
8. The API remains local-only and is not suitable for LAN or Internet exposure.
9. The backup workflow is a tested utility, not a scheduled backup service.
10. The PIT `revision_id` README/implementation contradiction remains unchanged.
11. The existing production OpenClaw working tree was dirty before this phase,
    so no claim is made that Phase 3A explains or repairs those unrelated
    changes.

## 13. Recommendation for Phase 3B

Do not automatically proceed.

The smallest sensible next experiment would be a separately approved Hermes
candidate-write trial, but only after deciding:

1. Whether the runtime-neutral HTTP contract is sufficient or needs a later
   MCP adapter.
2. Whether candidate writes should require a correlation ID and explicit
   task/run provenance.
3. Whether QA evidence needs stronger structured checks before any human
   approval workflow is tested from a runtime.
4. Whether a clean production baseline should be captured before future
   safety claims.

Any Phase 3B work should preserve the same rule:

```text
Hermes may propose.
QA may validate.
Only a human may approve.
```
