# The evidence channel and auto-admission, as deployed here

Two surfaces decide whether an artifact needs a human: `POST /v1/evidence/{kind}/{id}`
proves a claim, and `gateway/auto_admission.py` decides who may move it. Driver:
`/mnt/d/OpenClaw/tools/intelligence-auto-admit.py` (`--apply` to act).

## Recording evidence

Scope `validate:candidate` (the `local-qa` identity; the write identity does not
have it). Payload is `{"evidence": [ ... ]}`, appended to the artifact's `evidence`:

```json
{"type": "test_run", "command": "python3 tests/t.py", "exit_code": 0,
 "files": [{"path": "skills/validated/<id>/tests/t.py", "sha256": "sha256:..."}]}
```

`intelligence-validate.py --apply` records this itself before validating, so the QA
hop produces the evidence it implies. Equivalent to the HTTP call above:

```bash
curl -s -X POST -H 'X-Intelligence-Token: local-qa' -H 'Content-Type: application/json' \
  -d "{\"evidence\":[{\"type\":\"test_run\",\"command\":\"python3 tests/t.py\",\"exit_code\":0,\"files\":[{\"path\":\"$REL\",\"sha256\":\"sha256:$(sha256sum $REL | cut -d' ' -f1)\"}]}]}" \
  http://127.0.0.1:8765/v1/evidence/skill/<id>
```

## Rules the gateway enforces (do not work around them)

- It overwrites `recorded_by`, `recorded_at` and `subject_digest` on every incoming
  record. Forging them is silently corrected, not rejected - verified live.
- `VERIFIER_IDENTITIES` = {local-qa, local-system, policy-auto, local-human}. The
  author is never in it, so an author's own passing run proves nothing.
- A record with no `recorded_by` was never stamped by the gateway. Those are
  author claims and are ignored in the verdict, even when a filing tool wrote them
  into `evidence` (the backflow gate does exactly that with its own `test_run`).
- At decision time it re-checks three things: `exit_code == 0`, `subject_digest`
  equal to the artifact's current digest, and every `files[].sha256` still matching
  the store. All three are re-computed then - never assume a filed record still
  holds.
- The digest covers id, kind, scope, version, title, content, metadata *minus*
  `GATEWAY_METADATA_KEYS` (`auto_admission`, `withdraw`, `approval_action`). Those
  keys exist because writing a verdict into `metadata` otherwise moved the digest
  and invalidated the evidence that had just been filed. Import that constant from
  `gateway/attestation.py`; never redefine it in a second module.

## What the policy admits here

`gateway/auto_admission.py` (version-stamped per verdict). Auto-admitted: kind
`knowledge`/`experience`, scope in {domain, local, project}, trusted producer,
`review_interval_days` set, no permission claims, no unknown fields, not
self-declared verified. Never auto: scope `shared`, unknown scopes (reported as
unknown, not as private), unknown kinds, permission claims, and any identity
change.

- The mode is store-scoped: `qa/governance-config.json` -> `{"auto_admission":
  "shadow"|"enforce"}`, read by the gateway and therefore by every caller. A
  process environment variable is only a fallback when the file is absent - never
  the authority, or the service and a tool will disagree about the same store.
- Ask the gateway for a verdict (`gateway.evaluate_admission(...)`), never the
  policy function directly: only the gateway supplies the file digests the
  evidence check re-verifies against, so a direct caller reports "sha256 mismatch"
  on artifacts the enforced policy approves.
- `kind: skill` is graded by **payload**, not gated on tests:

  | shape | gate | recorded as |
  |---|---|---|
  | no tests, no scripts | auto-admit (same tier as `knowledge`) | `metadata.verification: "static-review"` |
  | ships `.py/.sh/.js/.ts` attachments | human | `metadata.executable_attachments: true` |
  | has tests + another identity's evidence | auto-admit | the digest/evidence path above |

  Rationale: 119 of 129 real skills are prompt-shaped and have nothing to execute, so a test
  requirement is a rule-shape mismatch rather than a quality bar - it left the store with 2 skills
  while two runtimes held 129. A skill without tests that omits `verification: static-review` is
  refused by the schema on purpose; never add the flag as a shortcut for a skill that ships code.
- Skill lifecycle differs from the other kinds: `candidate -> experimental -> validated -> approved`,
  with `candidate -> validated` also allowed for the text-only shape above. A driver written for
  `knowledge` fails every skill with `invalid skill transition` - read `gateway/lifecycle.py`
  `TRANSITIONS` before automating a move.
- A skill candidate from the backflow path can still be blocked by the producer list
  (`created_by: atlas-backflow` / `atlas-main`, deliberately absent from `TRUSTED_PRODUCERS`). Adding
  them is the operator's decision - offer the one-line change, do not make it silently.

## Scheduled automation

| job | schedule | notes |
|---|---|---|
| `governance-feedback` | 3h | agent run gated by `~/.hermes/scripts/governance-event-count.py`; silent when the event count is unchanged |
| `auto-admission` | 15m | no_agent script `~/.hermes/scripts/auto-admit-candidates.sh`; zero LLM cost, prints nothing and exits 0 when there is nothing to admit |

Both are silent by construction. An idle tick must exit 0: a non-zero exit on a
no_agent job raises an alert, and an alert every 15 minutes is how the watchdog
gets muted. `deliver: local` means output is only written under
`~/.hermes/cron/output/<job>/`.
