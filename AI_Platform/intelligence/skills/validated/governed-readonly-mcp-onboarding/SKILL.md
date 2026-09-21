# governed-readonly-mcp-onboarding

Onboard an agent runtime onto a **governed read-only** knowledge service: the
runtime gets search/read over approved artifacts and nothing else — no write
surface, no approval surface, no identity it can assert itself.

Derived from the approved experience artifact `governed-readonly-mcp-onboarding`
and from the live Hermes × OpenClaw integration (2026-09-19).

## Contract

A conforming onboarding satisfies all four points, and the change is not
"done" until the acceptance test below passes against the live stack:

1. Every client lists **exactly** the expected read-only tools.
2. Every client completes **one real end-to-end read** and gets a known
   approved artifact back.
3. Reverse test: **no token → 403**; an agent identity **cannot** reach the
   validation path → 403.
4. The MCP surface exposes **no write or approval tool at all**.

## Inputs

- Path to the stdio adapter (`server.py`) for the runtime to spawn.
- Gateway base URL (must be loopback).
- The identity token the runtime is allowed to present.
- The runtime's MCP client config file.

## Outputs

- Runtime config entry registering the adapter (read-only tool filter).
- A passing acceptance run (8/8) recorded as evidence.

## Steps

1. **Probe before configuring.** With no token, `GET /v1/search/<kind>` must
   return `403`. If it returns data, stop: the gateway is not enforcing identity.
2. **Register the adapter** with an explicit read-only tool allow-list. Do not
   rely on "the server has no write tools"; filter on the client too.
3. **Set the trust posture** to "untrusted" where the runtime supports it, so
   returned content is treated as data, never as instructions.
4. **List tools** and diff against the expected set. Extra tools = stop.
5. **Do one real read** through the runtime's own client (not `curl`).
6. **Run the reverse tests** (no token, wrong-scope identity).
7. **Record the run**: command, tool list, HTTP codes → artifact evidence.

## Failure modes (all three were hit for real)

| # | Symptom | Real cause | Fix |
|---|---|---|---|
| 1 | Read-only tool refused as "write-capable" under `trust: untrusted` | Client reads the pydantic **serialization alias** (`readOnlyHint`) off an object whose field is `read_only_hint` → always `None` | Read both spellings, keep fail-closed (`~/hermes/patches/apply-mcp-readonly-hint-patch.py`) |
| 2 | `requires the 'mcp' Python SDK, but it is not installed` | Minimal install omits the MCP extra by design | `uv pip install -e '.[mcp]'` |
| 3 | Connects, lists tools, then `403` on search | Identity problem, not connectivity | Adapter must send the agreed token header; unknown/missing token is refused |

## Dependencies

- Python 3 stdlib only on the adapter side (no third-party imports).
- A running gateway bound to `127.0.0.1`.
- The runtime's MCP client (Hermes ≥ 0.21.3, or OpenClaw `mcp add`).

## Permissions

- `read:approved` on the shared knowledge base.
- Write access to the runtime's own MCP config file.
- **Never** `approve` / `write:candidate` / `read:candidate`.

## Tests

`tests/test_onboarding.py` — live acceptance test, stdlib only:

```bash
python3 tests/test_onboarding.py      # exit 0 = 8/8 checks passed
```

It spawns the adapter over stdio (handshake + `tools/list` + real `tools/call`)
and exercises the gateway over HTTP for the reverse tests. Overridable via
`MCP_ADAPTER`, `GATEWAY_URL`, `READ_TOKEN`, `AGENT_TOKEN`.

## Stop condition

If any check fails, the onboarding is **not** complete — do not record success
and do not widen the tool filter to "make it work".
