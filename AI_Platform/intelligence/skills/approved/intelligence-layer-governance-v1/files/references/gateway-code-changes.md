# Changing the gateway's own code safely, and shipping the tree

## Before the first edit

- **Check for version control; if there is none, take an archive first.** A governed gateway whose
  code is unversioned has no rollback, and a hand-made archive is then the only recovery path.
  Better: initialise the repository as part of the work, so the change itself has a rollback point.
- **Read the target's `__init__` before using `self.<attr>`.** The object that serves a request
  often reaches the store indirectly (`self.gateway.store.root`); assuming a direct `self.root`
  turns every request into a 500 instead of a clean error.
- **When inserting an attribute, assign it before anything that reads it.** A field used by a line
  above its own assignment raises at construction, so *every* request fails and the whole suite goes
  red in one shot — universal failure is the fingerprint of an ordering mistake, not of the feature.
  Keep the assignment next to its neighbours and put the resolver call first.
- **Respect the module's dependency posture.** A stdlib-only gateway stays stdlib-only; a call to a
  module you have not imported fails at request time, not at import time, and looks like a crash.

## Splicing source by string search

- **Anchor on complete lines including their indentation.** A substring anchor matches the first,
  *deeper-indented* occurrence: searching for `"    def _json"` lands inside `"        def _json"`,
  and the replacement then deletes the enclosing scope (a class header, a factory function)
  silently while the file still looks plausible at a glance.
- Prefer replacing a whole method between two unique anchors, or rewriting the file in full.
- **`ast.parse` immediately after every splice**, before restarting anything: a syntax error is
  invisible while the old module is still resident in memory and only detonates on the next restart.
  Treat the running service as a masking layer, not a safety net.
- **Diff against the pre-edit copy.** Scope deletions are exactly what the eye skips when you look
  only at the region you meant to change.

## Verify without guessing

- Reproduce **in-process** first: import the object, call the method, read the real traceback. An
  HTTP 500 body names the exception class but not the line, and guessing from it costs rounds.
- After restarting, drive the real path with requests and record status codes; then re-run the
  whole suite, the adapter discovery and the read-surface acceptance — the gateway is the read path
  too, so an auth edit is never only an auth change.
- A client's "sent/ok" is not delivery. For an external side effect, verify at the far end (a
  remote-issued id) or by the operator's own eyes.

## Moving runtime state out of the tree

Runtime state — the audit trail, the event stream, the telemetry aggregate, the embedding cache, the
identity token hashes — is what makes a store unpublishable, so give it one configurable home instead
of five hardcoded paths:

- Add a single resolver (a `state_dir(root)` helper) that reads one override (`INTELLIGENCE_STATE`)
  and otherwise defaults to the in-tree `qa/` directory, so single-machine development and the test
  suite stay unchanged.
- Point every writer **and every reader** at it: the service, the API's token-index loader, and any
  reporting tool that reads the event or telemetry file directly. One tool that still hardcodes
  `<store>/qa` keeps the old behaviour alive and silently recreates the files you just moved.
- Set the override in the service definition, then prove it took effect: after a restart the in-tree
  directory must stay free of state files *and* the live read path must still answer with a real
  token. Merge any state written while the switch was not yet in force back into the new home — the
  tail of an audit trail is evidence, not a stray file.
- Untrack and ignore the state paths, and keep the plaintext credential file outside the repository
  rather than merely ignored.

## Deploying a config change to the unit

- **A setting appended to the end of a unit file lands in whatever section comes last.** With an
  `[Install]` section present, an `Environment=` line after it is silently ignored: the service
  restarts, the old value is still in force, and the symptom is the path you moved still being used.
  Read the section layout first (`systemctl --user cat <unit>`), insert into `[Service]`, then
  `daemon-reload` and restart.
- Verify a config change by its observable effect, never by the file's contents.

## Shipping the tree as a repository

- **Prove a fresh clone runs the tests before pushing.** `git clone <local path>` into a scratch
  directory and run the suite there. A suite that locates its root by a fixed relative depth
  (`parents[3]`) and imports a package by name (`from <Pkg>.x import y`) requires the repository root
  to be the directory that makes that import valid; with the git root one level too deep, every
  clone fails to import while the working copy looks perfectly healthy. Move the root (or the
  bootstrap) and re-run the clone check — it is also the cheapest proof that the repository is
  complete.
- **Scan for plaintext secrets before the first commit**, and enforce it structurally: ignore
  caches, generated dashboards/snapshots and credential-file patterns, and keep the plaintext token
  file outside the repository rather than merely ignored.
- **Decide deliberately whether runtime state is tracked.** Tracking the audit log, event stream and
  telemetry aggregate gives writes tamper-evident history but makes the repository unpublishable;
  relocating them keeps the repository publishable and gives up that history. Choose per repository —
  and if both are wanted, the tamper-evident copy belongs in a second, private remote rather than in
  the public one. Either way the tree goes dirty as the service writes; that is not an error.
- **Never accept a credential in chat.** Have the operator authenticate the CLI themselves
  (`gh auth login`) and drive the push with the CLI. Verify by comparing the local HEAD with the
  remote SHA — not by the command's own success message. Signing in to the hosting site in a browser
  is *not* a CLI login: the CLI keeps reporting no authenticated host until it is authenticated
  itself. Take the commit identity from what the CLI reports for the account (`gh api user`) instead
  of hand-building a `…@users.noreply.github.com` address, which produces commits the account cannot
  claim.
- **Publication also means redacting the environment the tree was written in.** Scan every tracked
  text file for absolute home paths, `%USERPROFILE%`-shaped paths, hostnames and private project
  names; replace them with stable placeholders (`$HOME`, `<USERPROFILE>`, `<host>`); then re-scan the
  tracked set — reporting nothing is the completion condition, not the first pass.
- **Redaction can invalidate evidence.** The artifact digest covers the fields the author claims
  (`content`, `metadata`) but not `source`, `provenance` or `tests[]`, so redacting a path inside
  `source` is safe while redacting one inside `content`/`metadata` changes the digest and makes any
  evidence bound to it stale. Check which field the text lives in before replacing it; when it is a
  digested field, re-record the evidence or route the change through a new version — never edit the
  governed copy and call it cosmetic.
- **Publication is a privacy decision.** An audit log carries identity names, artifact content and
  timestamps. Default to private; to publish publicly, move the audit log, the telemetry aggregate
  and the token hash table out of the tree first.
- **CI is nearly free when tests need no external services.** Keep model-dependent tests behind a
  disable switch so the workflow runs with no network, no model server and no third-party packages,
  and write the workflow's paths relative to the repository root — the same root the import path
  requires.

## Committing into a tree that other processes write to

- **Commit path-scoped, never `git add -A` / `git commit -a`.** The store is mutated by services and
  by other agents while you work, so a blanket add sweeps someone else's in-flight change into your
  commit and attributes it to you. Name the paths you actually edited, and pass them to both
  `git add --` and `git commit --`.
- **Read a lifecycle move as a pair before touching it.** Moving an artifact from the candidates
  directory to a published one shows up as one deletion plus one untracked file, and half of it
  alone looks like a broken repository. Never "fix" that by staging the deletion.
- **Never `git checkout .` / `git reset --hard` here.** The pending changes are another party's
  in-flight work in a tree with no locking; discarding them destroys state with no recovery path.
  When in doubt, commit only your paths and say which ones you left alone.
- **An off-limits subtree is an instruction narrower than "don't commit".** Take it as: never stage
  it, never edit it, never repair it, and report which paths stay uncommitted so the operator
  decides what happens to them.
- **A commit is not a publication.** On a repository with a public remote, commit when asked and
  treat `push` as a separate action needing its own ask; report the local commit id rather than
  implying anything reached the remote.
- **Pass the commit identity per-commit (`-c user.name=… -c user.email=…`) instead of rewriting the
  repository config**, and take the address from the account itself (an account-linked
  `…@users.noreply.github.com`); a hand-built address produces commits the account cannot claim.
  The display name is the operator's choice and need not match the account handle.
- **Read the identity out of the repository's own history before trusting `git config`.** The two
  disagree in practice: local config held the operator's personal address while every existing
  commit used the account-linked noreply one, so a commit made from `git config` alone would have
  been unclaimable and would have broken attribution in a shared repository. Get the exact
  `name <email>` from `git log --format='%an <%ae>'` and reuse it — history is the source of truth
  *and* the thing your new commit has to stay consistent with.
