# MCP access surface: one URL every agent can read

The store already answers a bounded HTTP API and a stdio MCP adapter. Neither is a
"read it from anywhere" surface: each runtime wires its own subprocess, token and tool
whitelist, so the third agent costs a third copy. The protocol's 2025-06-18 revision
defines **Streamable HTTP** — one endpoint path, POST carrying JSON-RPC, auth at the
transport layer — which is what makes "any client, one line of config" true.

## Deployed shape

All on `127.0.0.1:8765` (the gateway's own process; no second service to supervise).

| path | method | auth | behaviour |
|---|---|---|---|
| `/mcp` | POST | Bearer | `initialize` / `ping` / `tools/list` / `tools/call` / `resources/list` / `resources/read` / `prompts/list` |
| `/mcp` | GET | — | **405**. No server-initiated stream; the spec allows a basic server to decline it |
| `/.well-known/mcp.json` | GET | none | discovery: transport, url, auth shape, protocol version |
| `/healthz` | GET | none | one bit: the listener is up |

The implementation is `gateway/mcp_http.py` (pure dispatch, testable without a socket)
plus a branch in the experimental API handler. Keep dispatch a table keyed on method
name, not an if/elif ladder — MCP adds methods over time and each one should be a row.

## Tools and resources

| tool | note |
|---|---|
| `search_knowledge` | omit `kind` to search all four kinds; merge results by score |
| `get_artifact` | one record by kind + id, with provenance |
| `kb_index` | approved ids/titles/tags per kind — cheaper than a blind search when the caller does not know what exists |
| `deposit_candidate` | creates a **candidate** only; admission decides. A client must not be able to approve its own deposit |

Resources: `kb://index` and `kb://{kind}/{id}`. Mark read-only tools with
`annotations.readOnlyHint` — clients use it to decide what may run without a prompt,
and `trust: untrusted` then prompts only on the write tool, which is the free human gate.

`resources/list` enumerates the approved corpus, so cap or paginate it once the store
grows past a few hundred records; every record also appearing in `kb_index` is the
intended redundancy, not a bug.

## Auth and transport hardening

- Bearer token resolves to an `Actor`; what is readable follows the identity, never the URL.
  Accept `X-Intelligence-Token` as well so existing scripts keep working.
- **Validate `Origin`** when present, allowing only loopback hosts — the spec requires it
  specifically to stop DNS rebinding against a local server.
- Bind `127.0.0.1` only (already enforced by `build_server`).
- Notifications (`notifications/initialized`, `notifications/cancelled`) return **202 with no
  body**. Returning a JSON-RPC object makes strict clients treat the session as broken.
- Unknown method → `-32601`; unknown resource → `-32002` with the uri in `data`. Tool
  failures are *results* (`isError: true`), not protocol errors — a bad query must not
  tear down the session.

## Client configuration

```jsonc
// Hermes (~/.hermes/config.yaml, mcp_servers)
intelligence:
  url: http://127.0.0.1:8765/mcp
  headers: {Authorization: "Bearer <TOKEN>"}
  trust: untrusted
  tools: {include: [search_knowledge, get_artifact, kb_index]}

// mcporter (any MCP host)
{"mcpServers": {"kb": {"url": "http://127.0.0.1:8765/mcp",
  "headers": {"Authorization": "Bearer <TOKEN>"}}}}
```

`tools/kb_connect.py --check` runs the three probes that matter (endpoint alive, token
resolves, content readable) and `--print-config hermes|openclaw|mcporter` emits the block.
Prefer it to hand-editing config: it prints the token, so say out loud that the output
must not be committed.

**Keep the stdio adapter for runtimes already wired.** It resolves the identity from the
credential file and therefore never puts a plaintext token in a config file. The HTTP
endpoint is for the *next* agent, not a reason to re-plumb working ones.

## Verification: use a client you did not write

Own probe passing proves the envelope, not interoperability. Check all three:

1. **This agent's built-in MCP** — call the read tool from the running session; the result
   naming a record you filed minutes ago is the end-to-end proof.
2. **A third-party implementation** — `mcporter` (Node): `list <name> --schema`, `call
   <name>.search_knowledge query=...`, `resource <name> kb://index`. Three different code
   paths through the same server.
3. **The other local runtime** — `openclaw mcp probe` reports the tool count.

Then the negative cases in one pass: no token → 403, foreign `Origin` → 403, `GET /mcp` →
405, `/.well-known/mcp.json` without a token → 200. A surface that answers only the happy
path has not been tested.
