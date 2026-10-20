# Governance tiers: what may be admitted without a human

Use this when deciding whether a class of artifact can be admitted automatically,
or when explaining why a tier line sits where it does. The purpose of the table is
not to avoid oversight; it is to stop oversight from being spread so thin that it
stops working - a measured approval rate above nine prompts in ten is the failure
mode, and tightening the gate further makes it worse rather than better.

## Decide in this order

1. Does the action change the rules themselves - identities, scopes, the policy
   source, the audit or event logs? Never automated.
2. Can the claim be checked without executing author-supplied code? A knowledge or
   experience record can. An artifact carrying tests cannot be *run* to decide -
   its tests are code - so it is admissible only through a re-checkable evidence
   channel (next-but-one section), never by the store executing it.
3. Can anything beyond this machine's own runtimes read it? A shared scope is a
   human's call regardless of how clean the artifact looks.
4. Is the producer known, and is the claim falsifiable - a validity horizon, cited
   sources, no claimed authority? If not, a human.
5. Only then: admit automatically, with the verdict recorded on the artifact and a
   review obligation attached.

## Tiers

| tier | who acts | what it takes |
|---|---|---|
| shadow | nobody | verdict recorded on the artifact; nothing moves |
| auto | the policy identity | non-executable kind; private scope; submitter and author both trusted; review horizon set; no permission claims; no unknown fields; not self-declared verified. A code-bearing artifact joins this tier only with re-checkable passing evidence attached |
| human | a person, plus a QA step | everything else - notably shared scope, and code-bearing artifacts with no re-checkable evidence |
| never | nobody | editing identities, scopes or the policy; retiring something published; deleting history |

## Controls that make an automatic admission acceptable

- Separate identities: author, validator and approver differ, and the policy
  identity is never the author.
- Fail closed on unrecognised input instead of ignoring it.
- The verdict is deterministic and version-stamped, so later rule changes can be
  reconciled against what was already admitted.
- A review obligation and two revocation paths: the human retires, the author
  retracts.
- A per-run cap, so a burst of submissions cannot sweep itself in before anyone
  looks at a sample.
- The driver runs locally: if approval has no remote endpoint, automation cannot be
  triggered remotely either.

## Evidence a store can re-check

An artifact is admissible without a human only if the store can verify the claim
itself. Author-asserted evidence is a claim, never verification, and must not
satisfy a gate. What counts:

- **Produced by a verifier identity** - author != verifier, and the store stamps
  the recorder and timestamp onto the record instead of trusting fields the
  caller supplies (test it by sending a forged recorder and asserting the store
  overwrote it).
- **Bound to the artifact** - a digest over the *author's* claim (id, kind, scope,
  version, title, content, metadata minus the store-written keys), recomputed at
  decision time, so editing the artifact afterwards invalidates the evidence.
- **Bound to the bytes that ran** - sha256 per executed file, re-checked against
  the store when the decision is made, so swapping the test file invalidates the
  evidence rather than inheriting it.
- **Fail closed** - an unstamped record, a non-zero exit, or a missing file list
  means no evidence. Records the store never stamped are assertions by an
  interested party, including ones a filing tool wrote into `evidence` itself.

A producer trust list is a separate gate and stays a human's decision: a good
record from an unknown producer does not become admissible, and widening that list
is never a side effect of implementing a gate. Offer the exact one-line change and
let the operator make it.

## The failure mode that is not admission

Admission is the visible half; the quiet half is that a store nothing invokes can
only accumulate. Track which records are pulled and when each was last used, and
treat zero invocations as a retirement signal - without it there is no way to
falsify what the store claims, and no warning before retrieval starts failing on
volume (flat substring or embedding-only search degrades from tens of records up).

## Precedents each rule came from

- One approval gate for every change defeats the purpose, and formal external
  review shows no measurable drop in change-failure rate:
  https://dora.dev/capabilities/streamlining-change-approval
- Tiered gating (deterministic allowlist, then scoped edits, then a classifier),
  plus dropping blanket code-execution allow rules when entering an automated mode:
  https://www.anthropic.com/engineering/claude-code-auto-mode
- Approval fatigue is measured, and realized safety is an inverted U in escalation
  rate: same page, and https://arxiv.org/abs/2606.08919
- An honest false-negative rate for classifier approval, with the instruction not
  to treat it as a drop-in for high-stakes review:
  https://www.anthropic.com/engineering/claude-code-auto-mode
- Policy decisions decoupled from enforcement, with a decision log:
  https://www.openpolicyagent.org/docs/latest/
- One policy at three strengths (deny/warn/audit) before enforcing:
  https://kubernetes.io/docs/reference/access-authn-authz/validating-admission-policy/
- Warn vs enforce, opted in per namespace:
  https://docs.sigstore.dev/policy-controller/overview
- Time-boxed exemptions with an expiry and responsible-party fields:
  https://learn.microsoft.com/en-us/azure/governance/policy/concepts/exemption-structure
- Provenance only counts when verified; fail closed on unrecognised fields; bind
  attestations to artifacts rather than releases:
  https://slsa.dev/spec/v1.0/verifying-artifacts
- Same-model self-review carries a measurable self-preference bias:
  https://arxiv.org/abs/2404.13076
- Verification is the dominant multi-agent failure class, and "has a verifier" is
  not the same as verifying: https://arxiv.org/abs/2503.13657
