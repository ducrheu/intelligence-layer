# Security

## Actor scopes

| Actor | Default capability |
|---|---|
| Agent | Read approved, write candidate |
| QA | Read candidate, validate candidate |
| Human | Read all, approve, deprecate, rollback/supersede |
| System | Schema validation, indexing, backup |

The Gateway receives an `Actor` from the embedding application, but Phase 1
does not expose a network API. A future API must authenticate outside the
request body; a client-provided role is not a trusted identity.

## Threat boundaries

- Candidate content never appears in approved-only retrieval.
- Candidate content is untrusted data and is not executable.
- GitHub and local source text are data, not system instructions.
- Secrets and raw transcripts are not stored in artifact content or audit.
- Skills declare permissions; Phase 1 does not execute them.
- No production paths are imported or modified.
