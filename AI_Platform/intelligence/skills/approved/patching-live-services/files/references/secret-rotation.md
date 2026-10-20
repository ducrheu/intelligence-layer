# Rotating a shared secret a live service verifies

Rotation is not "generate a new value". It is a change to two sides that must agree,
verified from four directions, with a rollback path that exists before you start.

## Before

1. Back up **both** sides — the client's plaintext credential file and the service's
   verification registry — with 600 permissions, and say where the backups are. That
   backup is the only way back if the new value is not accepted.
2. **Read an existing entry's exact format before writing a new one.** Registries often
   store a scheme-prefixed or structured value (`sha256:<hex>`, a record with a
   `scheme` field) rather than a bare digest. A bare hash where a prefixed value is
   expected is silently rejected: the new credential is refused and the old one has
   already been overwritten, which locks you out of your own service. Copy the shape of
   a neighbouring untouched entry.
3. List anyone holding a **static** copy of the secret. If clients resolve a
   name → token at runtime, rotation needs no client-side change; if any hold a fixed
   value in config, they must be updated in the same pass.

## During

4. Write both sides in one operation: the client plaintext (what clients resolve) and
   the service registry (what the service compares). Update per-identity records too.
5. Restart the service — hash tables are typically loaded at startup.

## After — all four verifications

| check | expected |
|---|---|
| new credential authenticates | success (200 / protected action allowed) |
| old credential | refused (403) |
| capability probe on a non-existent target | 404 (permitted, nothing there) — **not** 403 |
| the service's acceptance suite | still green |

The capability probe is what distinguishes "the credential works but has no write scope"
from "the credential is unknown"; without it a permission regression looks like success.

## Then sweep for the old value

```bash
grep -rl "<old value>" <store tree>
git grep -l "<old value>" $(git rev-list --all) --     # history hits must be 0
```

A credential that was stamped into an artifact has to be scrubbed there as well, and the
scrub recorded (withdraw the artifact through the governed path first, then neutralise the
value, then re-scan to prove zero). Never print a credential value — report only its
length or a short prefix, and never put it on a command line you will paste anywhere.
