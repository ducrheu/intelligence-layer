# Testing

Run from the task root:

```powershell
python -m unittest discover -s AI_Platform/intelligence/tests -p "test_*.py" -v
```

The tests use only Python's standard library. They create temporary Git-like
repositories and do not mutate the legacy Freelance workspace, OpenClaw, PIT
project, Gateway, providers, cron, or production memory.

Coverage includes schema fields, lifecycle transitions, permissions,
candidate isolation, provenance, skill contracts, audit events, supersede
recovery, and bounded retrieval.
