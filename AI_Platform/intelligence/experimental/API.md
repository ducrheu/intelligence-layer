# Experimental HTTP API

## Authentication and authorization

Send:

```text
X-Intelligence-Token: local-agent
```

The token is mapped by server-side configuration. A JSON field such as
`{"role":"human"}` is ignored and cannot elevate permissions.

## Endpoints

| Method | Endpoint | Agent | QA | Human | Purpose |
|---|---|---:|---:|---:|---|
| GET | `/health` | yes | yes | yes | Local health check |
| GET | `/v1/artifacts/{kind}/{id}` | approved | approved/candidate | all | Retrieve one governed artifact |
| GET | `/v1/search/{kind}?query=...` | approved | approved/candidate | all | Bounded search |
| GET | `/v1/context/{kind}?query=...` | approved + metadata warnings | no | no | Compact approved context packet for `local-hermes` |
| POST | `/v1/candidates` | yes | yes | yes | Submit candidate or experimental artifact |
| POST | `/v1/validate/{kind}/{id}` | no | yes | yes | Validate candidate |
| POST | `/v1/promotion/{kind}/{id}` | yes | yes | yes | Request human promotion |

`kind` is one of `knowledge`, `experience`, `skill`, or `source`. Artifact
selectors must be IDs matching `[A-Za-z0-9][A-Za-z0-9._-]{0,127}`. Paths,
drive letters, UNC paths, traversal segments, and symlink resolution are not
accepted by the API.

Search accepts bounded `max_items`, `max_bytes`, `max_chars`, and optional
`scope`. There is no unbounded `GET ALL`.

The `local-hermes` identity may request a context packet. The `artifacts` array
contains approved results only. Non-approved matches can appear only in the
`warnings` array as governance metadata with `metadata_only_not_approved_knowledge`.
The packet never exposes raw non-approved content.

There is intentionally no API endpoint for `approve`, `deprecate`, or
`supersede`. Those operations remain explicit Gateway operations available to
the human actor in the local experiment, not to agent or QA HTTP callers.

## Example

```powershell
curl.exe -H "X-Intelligence-Token: local-agent" `
  "http://127.0.0.1:8765/v1/search/knowledge?query=available_time&max_items=5&max_bytes=4000"
```
