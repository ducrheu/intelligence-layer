# Intelligence Layer

Phase 1 is a small, runtime-neutral governance boundary for durable
Knowledge, Experience, Skills, Sources, QA evidence, and provenance.

It is intentionally independent of OpenClaw, Hermes, NanoBot, Codex, model
routing, schedulers, and private agent memory.

## Authority

Git is the canonical authority. JSON files and Markdown files are reviewable
artifacts. The Python Gateway writes atomically into the repository, but it is
not a database and does not replace Git history.

## What can write

- Agents: candidate artifacts only.
- QA: validation results and validated status only.
- Humans: approve, reject through archive, deprecate, supersede, and rollback.
- System: schema checks, indexing, backup; no implicit promotion authority.

## What is approved

An Approved artifact is verified, has provenance, and has passed the explicit
human approval operation. Existing legacy `excel-merge` evidence is carried
forward; the PIT seed is deliberately still a Candidate until repository
revalidation.

## Storage scopes

- `approved/`: shared, read-mostly artifacts.
- `candidates/`: unapproved proposals.
- `experimental/`: skill experiments.
- `private/` is intentionally absent in Phase 1.
- Session transcripts are not durable artifacts.

## Basic usage

```python
from pathlib import Path
from AI_Platform.intelligence.gateway.models import Actor
from AI_Platform.intelligence.gateway.service import IntelligenceGateway

root = Path("AI_Platform/intelligence")
gateway = IntelligenceGateway(root)
agent = Actor("hermes-research", "agent", frozenset({"read:approved", "write:candidate", "request:promotion"}), "hermes")
results = gateway.search(agent, "knowledge", "available_time", max_items=5, max_bytes=4000)
```

No production runtime imports this package in Phase 1.
