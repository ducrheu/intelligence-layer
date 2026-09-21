# Phase 2 Experimental Boundary

This directory contains a local-only HTTP experiment. It is not connected to
OpenClaw production, the production Gateway, PIT, Legacy Freelance, Hermes,
NanoBot, OpenViking, Dify, IMA, or MCP.

The server binds only to `127.0.0.1`. It exposes Gateway operations through
fixed server-side experimental identity tokens:

- `local-agent`
- `local-qa`
- `local-human`
- `local-system`

The request body cannot select a role. The API only accepts governed Artifact
IDs and never accepts filesystem paths.

Run:

```powershell
python -m AI_Platform.intelligence.experimental.api.run_server --root AI_Platform/intelligence --port 8765
```

This is a test boundary, not a production service.
