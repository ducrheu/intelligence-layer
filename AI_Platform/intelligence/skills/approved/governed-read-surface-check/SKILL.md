---
name: governed-read-surface-check
description: Verify a governed KB read surface is still write-free.
version: 1.0.0
author: HUYI (operator), Hermes Agent
license: MIT
metadata:
  hermes:
    tags: [governance, intelligence-layer, acceptance-test, read-only, mcp]
    related_skills: [a2a-governed-read]
---

# Governed Read Surface Check Skill

Run one acceptance check that proves a governed knowledge-base read identity
still cannot write, cannot see unapproved bodies, and cannot escape its
retrieval bounds. It is the regression gate for the read side of the
Intelligence Layer: run it before and after any identity or scope change.

It checks an HTTP surface, not a document. It does not review content quality.

## When to Use

- Before and after touching the identity table, scopes, or MCP tool filters —
  the change that gives one identity write access must not widen the reader.
- When a new runtime (a second agent, a QA identity) is added and you need
  evidence that the reader still sees approved artifacts only.
- When an incident is suspected: a read identity returning unapproved bodies,
  unbounded result sets, or a successful write.

## Prerequisites

- The Intelligence Layer gateway reachable over loopback (default
  `http://127.0.0.1:8765`), or any server implementing the same experimental
  HTTP API.
- The token of the identity under test. Default `local-hermes`, overridable
  with `--token` or the `INTELLIGENCE_TOKEN` environment variable. Never pass a
  token on a command line that gets recorded, and never paste one into chat.
- Python 3 with the standard library only. No third-party dependency.

## Contract

- inputs: gateway base URL, the token of the read identity under test, and a list of probe queries
- outputs: one PASS/FAIL line per invariant plus `ACCEPTANCE: PASS|FAIL`, exit code 0 or 1
- dependencies: python3 standard library only (`urllib`, `http.server` in self-test mode)
- permissions: read-only - the only POST is a deliberately unpersistable probe that the gateway must reject; it can never create or change an artifact under any identity

## How to Run

```bash
# hermetic self-test: drives the checks against a local fake gateway that is
# deliberately correct and deliberately broken. No network, no real gateway.
python3 tests/read_surface.py

# live acceptance against the real gateway
python3 tests/read_surface.py --live --base-url http://127.0.0.1:8765 --token local-hermes

# choose the probe queries (defaults cover approved and pending-only terms)
python3 tests/read_surface.py --live --query collaboration --query pit
```

The live mode exits non-zero when any invariant breaks, so it is safe to use as
a pre-commit or post-deploy step.

## Quick Reference

| Invariant | What a failure means |
|---|---|
| `auth_required` | an unauthenticated caller reads the KB |
| `bogus_token_rejected` | an unknown token is treated as valid |
| `health_ok` | the surface is down or bound to a non-loopback address |
| `search_returns_approved_only` | a read identity sees unapproved bodies |
| `search_respects_max_items` | retrieval is unbounded |
| `search_respects_max_chars` | a single artifact body is returned past its cap |
| `metadata_warning_has_no_content` | the metadata-only warning leaks the body it warns about |
| `write_surface_closed` | the read identity can write candidates |
| `no_http_approve_endpoint` | approval became reachable over HTTP |
| `malformed_selector_rejected` | path-like artifact selectors are accepted |
| `approved_artifact_roundtrip` | an approved id cannot be fetched, or returns a non-approved record |

## Procedure

1. Confirm the gateway is the one you think it is: `health_ok` reports the bind
   address, which must be `127.0.0.1`.
2. Run the self-test first (`python3 tests/read_surface.py`). It proves the
   checker itself fails when it should — a checker that cannot fail is not
   evidence.
3. Run `--live` with the identity under test. Queries default to terms that
   match both approved and pending artifacts (`collaboration`, `pit`,
   `onboarding`, `governed`), so a visibility leak shows up rather than being
   masked by an empty result set.
4. Read the failures, not the score. Each failing line names the invariant and
   the observed status code. A `write_surface_closed` result of `400` instead of
   `403` is recorded as OK-with-note: authorization is open but the gateway's
   own schema guard still refused the write.
5. When the surface is shared, re-run it after every identity-table edit and
   keep the output as evidence for the artifact that describes the change.

## Pitfalls

- **A substring match on a tool name is not a tool.** A write-surface check that
  searches a tool list for the text `approve` matches `search_approved` and
  reports a false positive. Check the identity's scopes and the HTTP status of a
  real call instead of pattern-matching names.
- **An empty result set proves nothing.** Asserting "no unapproved item
  appeared" passes trivially when the query matched nothing. Always probe with
  terms that are known to match pending artifacts.
- **The probe must be unpersistable, not just unauthorized.** The probe payload
  carries `status: "approved"` and omits required records, so the gateway
  rejects it on the status check and again on schema validation. A probe that is
  merely unauthorized would create a real candidate the moment someone grants
  the identity write access.
- **Checking the MCP tool list is not checking the surface.** Tool visibility
  and authorization are separate layers; only a call proves the second.
- **Do not treat a green run as approval.** This checks that the reader cannot
  write. It says nothing about whether any candidate is worth approving.

## Verification

`python3 tests/read_surface.py` must print `SELF-TEST: PASS` and exit 0. Every
scenario in it asserts that a specific broken fake gateway produces a specific
failure, so a green run means the checks can actually fail. `--live` must print
`ACCEPTANCE: PASS` with all invariants listed; any `FAIL` line is the finding.
