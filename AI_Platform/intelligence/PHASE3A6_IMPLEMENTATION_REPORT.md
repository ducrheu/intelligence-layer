# Phase 3A.6 Implementation Report

## Result

`BLOCKED`

The isolated read-only MCP adapter is implemented and the real Hermes v0.21.3 MCP client successfully discovered it. Adapter-to-Gateway read calls and governance enforcement passed. A full model-driven Hermes conversation was not started because the only available local Ollama invocation attempted to write logs under the C: drive; no cloud or production credential was used.

## Environment

- Hermes: `NousResearch/hermes-agent`, v0.21.3, Python 3.12.9
- Hermes executable: `D:\AI_Platform\runtime-lab\hermes\venv\Scripts\hermes.exe`
- MCP SDK: official `mcp==2.0.0` extra installed only in the D-drive venv
- Adapter: `D:\AI_Platform\runtime-lab\hermes\mcp-adapter`
- Hermes home/config: `D:\AI_Platform\runtime-lab\hermes\home`
- Transport: stdio
- Gateway: `http://127.0.0.1:8765`
- Gateway PID during verification: `39516`

## Adapter

The adapter exposes only:

- `search_approved`
- `get_approved_artifact`
- `get_governance_metadata`
- `get_provenance`

All tools are annotated `readOnlyHint=true`, `destructiveHint=false`, and `openWorldHint=false`. The adapter hard-codes the `local-hermes` Gateway identity and never accepts client-supplied actor, role, permissions, scope, or token fields.

The adapter contains no candidate, validation, promotion, approval, deprecation, supersede, rollback, or filesystem access path. Its only downstream URL is `http://127.0.0.1:8765`.

## Hermes MCP Verification

`hermes mcp test intelligence` passed:

- stdio adapter connected
- 4 tools discovered
- isolated Hermes config loaded from D:
- `trust: untrusted`
- only the four adapter tools selected
- no resources or prompts enabled

## Governance Tests

- Approved `excel-merge` retrieval: `PASS`; status was `approved`
- PIT `available_time` context: `PASS`; returned as metadata-only `validated`, `verified=false`
- Candidate/validated isolation: `PASS`; client scope spoof was rejected and approved search returned no validated artifact
- Candidate write: `DENIED`; Gateway returned HTTP 403 for `local-hermes`
- Approval: `DENIED/NOT EXPOSED`; no approval tool or adapter write path exists
- Retrieval bounds: `PASS`; adapter clamps to 5 items, 8000 bytes, and 1200 chars
- Prompt injection: `PASS`; returned text stayed data and did not change the tool set

## Tests

- Adapter unit tests: `8 passed`
- Adapter Python compilation: `PASS`
- Intelligence regression: `39 passed`, `0 failed`, `2 pre-existing errors`
- Pre-existing errors are the missing Legacy Freelance workspace and were not repaired or recreated
- `python -m compileall -q AI_Platform`: `PASS`

Evidence was written to:

`D:\AI_Platform\runtime-lab\hermes\evidence\`

including `mcp-adapter-unit-report.json`, `mcp-discovery-report.json`, and `mcp-governance-report.json`.

## Security and Production Integrity

- OpenClaw production: unchanged and not started
- PIT repository: not modified or used by the adapter
- Legacy Freelance: not modified, executed, or recreated
- Production credentials: not accessed
- No system PATH, registry, service, scheduled task, or startup entry was created
- No `0.0.0.0`, LAN, Internet, MCP catalog server, OpenViking, database, vector store, or event bus was introduced
- The experimental Gateway remained loopback-only

## Blocker

The local Ollama executable is present on D:, but its CLI attempted to rotate/write logs under `<USERPROFILE>\AppData\Local\Ollama` even when the model directory and host were supplied. Starting it would violate the current D-drive-only constraint. Therefore the full Hermes LLM turn matrix was not executed. The real Hermes MCP discovery path and the adapter's live governed reads were verified without starting a model runtime.

## Files Created

- `D:\AI_Platform\runtime-lab\hermes\mcp-adapter\__init__.py`
- `D:\AI_Platform\runtime-lab\hermes\mcp-adapter\gateway_client.py`
- `D:\AI_Platform\runtime-lab\hermes\mcp-adapter\policy.py`
- `D:\AI_Platform\runtime-lab\hermes\mcp-adapter\server.py`
- `D:\AI_Platform\runtime-lab\hermes\mcp-adapter\tests\test_adapter.py`
- `D:\AI_Platform\runtime-lab\hermes\home\config.yaml`
- D-drive MCP evidence JSON files listed above
- `AI_Platform/intelligence/PHASE3A6_IMPLEMENTATION_REPORT.md`

No Phase 3B work was performed.
