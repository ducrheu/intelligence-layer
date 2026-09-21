# Phase 2 Implementation Report

**Date:** September 17, 2026  
**Status:** COMPLETE  
**Scope:** Controlled integration experiment only  
**Production policy:** No production OpenClaw, PIT Repository, or Legacy Freelance file was modified.

## 1. Status

Phase 2 is complete for the agreed controlled experiment:

- PIT Repository was inspected read-only.
- PIT evidence was recorded in the Intelligence Layer.
- PIT candidates were advanced only to `validated`, never to `approved`.
- Legacy Freelance metadata was exposed through a read-only adapter.
- A minimal local-only HTTP boundary was implemented.
- Failure injection and security tests were added.
- Phase 1 and Phase 2 regression tests pass: **30 passed, 0 failed**.
- No OpenViking, Hermes, NanoBot, Dify, IMA, MCP server, OpenClaw production adapter, or production runtime integration was added.

## 2. Production Safety

| System | Result |
|---|---|
| Production OpenClaw | Unchanged |
| `openclaw.json` | Unchanged |
| OpenClaw Gateway | Unchanged |
| Provider configuration | Unchanged |
| Model routing | Unchanged |
| Fallback/retry | Unchanged |
| Cron | Unchanged |
| QQ Bot | Unchanged |
| Production Memory | Unchanged |
| Agent topology | Unchanged |
| PIT Repository `D:\quant-data-project` | Unchanged |
| Legacy Freelance workspace | Unchanged |
| Existing Freelance Job Runner | Unchanged |
| Existing Legacy `excel-merge` Skill | Unchanged |

The experiment lives under:

```text
<USERPROFILE>\Documents\Codex\2026-09-16\ai-platform-architecture-research-design-task\AI_Platform\intelligence
```

This is separate from:

```text
D:\OpenClaw\workspace
D:\quant-data-project
<USERPROFILE>\Documents\Codex\2026-09-11\openclaw-openclaw-openclaw-codex-ai-1
```

The local HTTP server is only created during tests or when explicitly run by
the developer. It binds to `127.0.0.1`, never `0.0.0.0`.

## 3. Files Changed

### Created

```text
AI_Platform/intelligence/adapters/legacy_freelance/__init__.py
AI_Platform/intelligence/adapters/legacy_freelance/reader.py

AI_Platform/intelligence/experimental/__init__.py
AI_Platform/intelligence/experimental/README.md
AI_Platform/intelligence/experimental/API.md
AI_Platform/intelligence/experimental/api/__init__.py
AI_Platform/intelligence/experimental/api/server.py
AI_Platform/intelligence/experimental/api/run_server.py

AI_Platform/intelligence/tests/test_phase2.py
AI_Platform/intelligence/sources/candidates/source-pit-repository-snapshot-20260916.json
work/phase2_record_pit_evidence.py
AI_Platform/intelligence/PHASE2_IMPLEMENTATION_REPORT.md
```

### Modified

```text
AI_Platform/intelligence/gateway/service.py
AI_Platform/intelligence/gateway/store.py
AI_Platform/intelligence/experimental/api/server.py
```

The Gateway changes are limited to:

- Idempotent duplicate Candidate submission.
- Idempotent repeated human approval.
- Validation evidence recording.
- Correct lifecycle file handling.
- Atomic-write recovery support.

The experimental API is a new local-only module. It does not import or modify
OpenClaw production code.

The following existing Phase 1 artifacts were updated through the Gateway:

```text
AI_Platform/intelligence/knowledge/candidates/pit-available-time-semantics.json
AI_Platform/intelligence/knowledge/candidates/pit-repository-revalidation.json
AI_Platform/intelligence/sources/candidates/source-pit-repository-snapshot-20260916.json
```

### Deleted

```text
Deleted: none
```

## 4. PIT Repository Verification

### Repository identity

```text
Path:   D:\quant-data-project
Branch: master
HEAD:   d9e00554195d7399dd92ce3ade2a77fbfced62f7
Remote: https://github.com/ducrheu/quant-data-fabric.git
Status: clean during read-only inspection
```

Git required a one-shot `-c safe.directory=...` option because the sandbox
identity differs from the repository owner. No global Git configuration was
changed.

No checkout, pull, reset, merge, rebase, commit, push, file write, or database
write was performed.

### Evidence table

| Claim | Evidence | Location | Status |
|---|---|---|---|
| `event_time` | Defined as report-period time, modeled as `datetime`, persisted, and used in PIT tests | `README.md:11`, `src/domain/financial.py:12`, `src/repositories/financial.py:31`, `tests/test_financal_repository.py:24` | `CONFIRMED` |
| `available_time` | Defined as first-known/announcement time, persisted, and used as the visibility gate | `README.md:12`, `src/domain/financial.py:14`, `src/repositories/financial.py:119` | `CONFIRMED` |
| `processing_time` | Defined in the domain model and database; Normalizer maps it from `raw.ingest_time` | `src/domain/financial.py:16`, `src/repositories/financial.py:39`, `src/normalizers/financial.py:29` | `CONFIRMED` |
| `revision_id` | Composite uniqueness includes it; implementation and tests use `revision_id=2` | `src/domain/financial.py:20`, `src/repositories/financial.py:56`, `tests/test_financal_repository.py:63` | `PARTIALLY_CONFIRMED` |
| Look-ahead protection | Query uses `available_time <= as_of_time`; future-unavailable test returns `None` | `README.md:15`, `src/repositories/financial.py:119`, `tests/test_financal_repository.py:188` | `CONFIRMED` |
| Release-time example | README and tests show a report becoming visible only after announcement/available time | `README.md:17`, `tests/test_financal_repository.py:193-206` | `CONFIRMED` |

### Important contradiction

The repository README says at `README.md:149` that `revision_id` is currently
always `1` and that the revision lifecycle is planned for V0.3. However:

- `FinancialRecord` exposes `revision_id`.
- The database uniqueness key includes `revision_id`.
- Repository tests create `revision_id=2`.
- PIT tests verify that a later revision becomes visible after its
  `available_time`.

This is recorded as `PARTIALLY_CONFIRMED`, not silently normalized. The
implementation/tests and README are inconsistent and should be reconciled by a
future human-approved PIT project change. Phase 2 did not modify the PIT
repository.

### PIT lifecycle result

```text
pit-available-time-semantics:      validated
pit-repository-revalidation:      validated
source-pit-repository-snapshot:   validated
```

All three remain `verified: false` and are not Approved. The evidence is
available for human review; no automatic approval occurred.

## 5. Legacy Freelance Verification

Read-only workspace:

```text
<USERPROFILE>\Documents\Codex\2026-09-11\openclaw-openclaw-openclaw-codex-ai-1
```

### `excel-merge`

Observed identity:

```text
name: excel-merge
version: 0.1.0
status: approved
description: Merge compatible Excel workbooks into CSV with source preservation and machine QA.
```

Evidence:

- `skills/approved/excel-merge/SKILL.md`
- `skills/registry.json`
- `skills/approval_history.json`
- Existing validated Jobs `job_20260911_002`, `job_20260911_003`, `job_20260911_004`
- Existing regression test reference:
  `skills/approved/excel-merge/tests/test_regression.py`
- Accepted Experience:
  - `exp_excel_source_integrity_001`
  - `exp_xlsx_string_storage_001`
- Pending Experience:
  - `exp_excel_named_data_sheet_001`
  - `exp_excel_sparse_cells_001`

The Legacy Skill remains the execution authority. The Intelligence Layer
contains metadata and governance representation only.

## 6. Read-only Adapter

Implementation:

```text
AI_Platform/intelligence/adapters/legacy_freelance/reader.py
```

Interface:

```python
list_approved_skills()
get_approved_skill(skill_name)
list_experience()
get_experience(experience_id)
```

The adapter:

- Reads the legacy registry and approval history.
- Reads accepted and pending Experience Markdown.
- Converts metadata to runtime-neutral dictionaries.
- Computes SHA-256 for read evidence.
- Enforces a configured workspace boundary.
- Rejects `../` and path escape attempts.
- Never executes a Skill.
- Never starts a Job.
- Never changes a registry.
- Never changes a Skill.
- Never approves a legacy Skill.

The Phase 2 adapter test confirmed that selected legacy file hashes are
unchanged before and after adapter reads.

No `excel-merge-v2`, copy, or replacement implementation was created.

## 7. Experimental HTTP API

The chosen boundary is Python standard-library HTTP. No third-party framework
or new dependency was installed.

Implementation:

```text
AI_Platform/intelligence/experimental/api/server.py
```

Run explicitly:

```powershell
python -m AI_Platform.intelligence.experimental.api.run_server `
  --root AI_Platform/intelligence `
  --port 8765
```

The server rejects any bind address other than `127.0.0.1`.

### Server-side identities

```text
local-agent
local-qa
local-human
local-system
```

The request body cannot select or elevate a role. A body field such as
`{"role":"human"}` is ignored and cannot authorize the request.

### Operations

| Method | Endpoint | Allowed purpose |
|---|---|---|
| `GET` | `/health` | Local health check |
| `GET` | `/v1/artifacts/{kind}/{id}` | Governed artifact retrieval |
| `GET` | `/v1/search/{kind}?query=...` | Bounded search |
| `POST` | `/v1/candidates` | Candidate/experimental submission |
| `POST` | `/v1/validate/{kind}/{id}` | Candidate validation |
| `POST` | `/v1/promotion/{kind}/{id}` | Promotion request only |

There is no HTTP `approve`, `deprecate`, or `supersede` endpoint. Human-only
operations remain explicit local Gateway operations and are not exposed to
agent/QA HTTP callers.

### Bounded retrieval

Search supports:

```text
max_items
max_bytes
max_chars
scope
kind
```

There is no unbounded `GET ALL` operation.

### Path security

The API accepts Artifact IDs only. It rejects:

- `../`
- `../../outside`
- Absolute Windows paths
- Drive-letter paths
- UNC paths
- Backslash path injection
- Arbitrary repository paths

## 8. Authorization Model

| Operation | Agent | QA | Human | System |
|---|---:|---:|---:|---:|
| Read approved | Yes | Yes | Yes | Yes |
| Search approved | Yes | Yes | Yes | Yes |
| Submit candidate | Yes | Yes | Yes | Yes |
| Validate | No | Yes | Yes | Yes |
| Request promotion | Yes | Yes | Yes | Yes |
| Approve | No | No | Yes | No |
| Deprecate | No | No | Yes | No |
| Supersede | No | No | Yes | No |

The following are enforced:

- Agent cannot directly write `approved`.
- Agent cannot approve.
- QA cannot approve.
- `candidate -> approved` is rejected.
- Promotion request does not change lifecycle state.
- Candidate retrieval is separate from approved-only search.

## 9. Failure Injection

Test file:

```text
AI_Platform/intelligence/tests/test_phase2.py
```

| Failure case | Result |
|---|---|
| Invalid Candidate JSON | Rejected; no Artifact written |
| Schema/version error | Rejected |
| Missing Provenance | Rejected |
| Missing Source | Rejected |
| Invalid lifecycle transition | Rejected |
| Agent attempts approval | Rejected |
| QA attempts approval | Rejected |
| Agent attempts approved write | Rejected |
| Duplicate Candidate submission | Idempotent for same content; conflict rejected |
| Duplicate approval | Idempotent |
| Supersede old Artifact | New Candidate created; old Approved remains recoverable/deprecated |
| Interrupted atomic write | Original file unchanged; temporary file cleaned |
| Interrupted API request | No Candidate committed |
| Missing Artifact | Explicit `ArtifactNotFoundError` / HTTP 404 |
| Candidate isolation | Candidate omitted from approved-only search |
| Role spoofing | Request body role ignored; server identity controls access |
| Adapter path escape | Rejected |

## 10. Recovery Results

### Atomic write

The store writes to a temporary file and uses atomic replacement. The test
injects a failure into `os.replace`; the original Artifact remains byte-for-byte
unchanged and the temporary file is removed.

### Lifecycle file handling

When a Skill changes lifecycle directory, the old path is removed after the new
Artifact is saved. For non-Skill artifacts whose candidate/validated physical
layout is intentionally shared, the same file is retained with the updated
status. This prevents duplicate current-state representations without
destroying Git history.

### Supersede

The old Artifact records `superseded_by`, becomes deprecated, and remains
recoverable through Git history. The replacement begins as Candidate.

## 11. Audit

All Gateway operations continue to write:

```text
AI_Platform/intelligence/qa/audit.jsonl
```

Required fields:

```json
{
  "timestamp": "...",
  "actor": "...",
  "role": "...",
  "action": "...",
  "artifact_id": "...",
  "result": "...",
  "correlation_id": "..."
}
```

The API forwards `X-Correlation-ID` to Gateway operations. Secrets, API keys,
passwords, raw transcripts, and full tool outputs are not logged.

## 12. Regression Results

Command:

```powershell
python -m unittest discover -s AI_Platform/intelligence/tests -p "test_*.py" -v
```

Result:

```text
Phase 1 tests: 16 passed
Phase 2 tests: 14 passed
Total:         30 passed, 0 failed
```

Additional checks:

```text
Python compileall: PASS
Schema JSON parsing: PASS
Durable Artifact validation: 6 PASS
```

## 13. Code Size and Dependencies

### Dependencies

```text
Dependencies added: none
New services added: none
New database added: none
OpenViking connected: no
MCP server added: no
```

The API uses:

- `http.server`
- `socketserver` through `ThreadingHTTPServer`
- `urllib`
- `json`
- `pathlib`
- `unittest`
- Other Python standard-library modules

### Approximate implementation size

```text
Legacy adapter reader:       115 lines
Experimental HTTP server:    186 lines
Server launcher:              25 lines
Phase 2 tests:               249 lines
PIT evidence helper:         187 lines
```

The implementation remains intentionally small and file-backed. No service
manager, database, message bus, vector store, or orchestration framework was
introduced.

## 14. Known Limitations

1. The HTTP identity tokens are experimental server-side mappings, not a
   production authentication system.
2. The API is local-only and not suitable for network exposure.
3. There is no MCP server yet.
4. There is no semantic retrieval or derived index.
5. Search remains bounded substring search.
6. There is no private Agent Memory.
7. There is no Skill execution sandbox in the API.
8. Human approval is available through the local Gateway, not through the HTTP
   API.
9. PIT repository code and README still contain a `revision_id` documentation/
   implementation contradiction.
10. PIT evidence has been validated but not human-approved.
11. Legacy workspace is not a Git repository, so read-only protection used
   selected file SHA-256 comparisons rather than Git status.
12. No automated backup/restore service was added.
13. No OpenClaw production path imports this package.
14. The current experiment does not prove 30-day operational reliability.

## 15. Phase 3 Recommendation

Do not automatically enter Phase 3.

The next decision should be made by a human after reviewing this report and
the validated PIT evidence. The smallest reasonable Phase 3 would be:

1. Human-review and, if appropriate, approve the PIT evidence artifacts.
2. Reconcile the PIT `revision_id` README contradiction in the PIT project
   through a separately approved PIT change.
3. Add a read-only consumer integration test for one experimental runtime,
   without production OpenClaw wiring.
4. Decide whether the local HTTP boundary should remain a test utility or be
   replaced by a deliberately scoped MCP adapter.
5. Add backup/restore verification before any shared runtime receives write
   access.

No Phase 3 implementation was performed in this task.
