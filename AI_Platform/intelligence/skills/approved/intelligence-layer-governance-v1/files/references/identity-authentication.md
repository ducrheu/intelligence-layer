# Identity authentication, and the migration to it

## The failure mode to probe for

An auth layer that maps the presented token *straight to the identity* (`if token in self.actors`)
makes the literal identity name the credential. Every role boundary the design leans on —
human-only approve, author ≠ verifier, trusted producer — is then a request rather than an
enforcement, because anything that can reach the listener can claim any identity.

Probe it in one line before trusting any boundary: present the literal name as the token. A `200`
means names are still credentials, whatever the documentation says.

## Target state

- One random token per identity (`secrets.token_urlsafe(32)`), minted for **all** identities.
- The store keeps only `sha256:<hex>` (`qa/identity_tokens.json`). Hashes are not secrets and may
  travel with the artifacts.
- Plaintext lives **outside the versioned tree**, mode 0600, in the owner's credential area. The
  store is a git work tree that gets published; plaintext must never be committed.
- The gateway compares hashes with `hmac.compare_digest`, not `==`.
- Legacy acceptance (a name used as a token) is an explicit switch, defaulting to accepting during
  the migration and refusing once flipped.

## The migration, in order

1. **Mint for every identity before flipping anything.** A partial table locks out whoever is
   missing the moment names stop working.
2. **Teach the gateway hash-first while names still work.** Restart and prove all four paths before
   touching any other tool: minted token → 200, literal name → 200 (legacy on), unknown string →
   403, valid token without the scope → 403.
3. **Move each credential holder**, one at a time, re-checking after each: the read MCP entry, the
   write MCP entry, every CLI tool whose default actor is a name, and the peer-side tool that files
   artifacts. Each holds its own copy of the string; none of them reads the store's hash table.
4. **Flip the switch off**, restart, and re-run the read-surface acceptance plus the adapter suite.
   A name token must now be refused, and a refusal must be `403` — never `500`.
5. Keep the plaintext file 0600 and out of the repository, and rotate it if it may have leaked.

## Consequences to fix afterwards

- **Re-key trust lists.** A list that reads `created_by` from the artifact body is written by the
  submitter; enforcement has to come from the authenticated identity or from the audit log's record
  of who actually filed the artifact.
- **A `500` on every token is an edit bug, not an auth decision.** A missing stdlib import
  (`hmac`, `hashlib`, `os`) in the auth path turns clean refusals into server errors that look like
  a dead gateway. Fix the import and re-probe all four paths.
- **Expect query-string curl recipes to break at the flip.** Any snippet that passes the identity
  name as `X-Intelligence-Token` is a migration-era shortcut; read the actor's real token from its
  credential file instead of typing the name.
- **Two files share the name `identity_tokens.json`, and only one holds a usable token.** The copy in
  the store holds hashes; the plaintext lives in the credential file outside it. A smoke test that
  reads the store's copy and sends its value as the token gets `403` and makes a correct
  implementation look broken — check *which* file you read before debugging the auth code at all.
- **Settle a refusal arithmetically before suspecting the code.** Compute
  `sha256:<hex>` for the token you hold and compare it with the entry the index holds, in-process:
  equal digests plus a `403` means the transport or the token source is wrong, unequal digests mean
  the token was never the one that was minted. That one comparison replaces a round of guessing, and
  it also distinguishes "the index is empty" (a path or env-var problem) from "the index is right".
- **Report the state, not the intent.** Until the switch is off, say "names are still credentials"
  rather than describing the system as authenticated.
- **The credential file is a flat map `{identity: plaintext}` — a nested writer fails silently.**
  The client resolves with `json.loads(path).get(identity)`; a file written as
  `{"scheme": …, "tokens": {"<identity>": …}}` (or any wrapper) resolves to nothing, and the
  fallback is the identity *name*, so the only visible symptom is the gateway's `403 unknown
  identity token`. A mint script must therefore verify its own output **shape** — read the file back
  and assert `identity in json.loads(...)` — not just the hash round-trip; those are different
  assertions and only the second one catches this. And never fix it by re-minting: re-minting
  rotates the token you just verified, so reshape the existing plaintext in place (copy it aside
  first).
- **A harness that sets one identity's credential path for a whole process de-authenticates every
  other identity in it.** Exporting `INTELLIGENCE_TOKENS` once and resolving two identities from
  that single process makes the second one fall back to its name, so a perfectly working owner
  identity reports `403` and the run looks like a boundary breach that is not there. Resolve each
  identity's token from its own credential file, and print only `len(token)` plus a
  `token != identity_name` boolean — enough to catch the fallback without putting a secret in the
  transcript.
