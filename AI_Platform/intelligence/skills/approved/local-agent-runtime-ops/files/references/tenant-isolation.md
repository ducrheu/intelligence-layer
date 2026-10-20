# Isolating a second tenant on the same machine

Companion to §11. `references/remote-exposure.md` covers how a second party *reaches* a service;
this covers what stops them reading everything else once they are running on the box.

## Why a profile, and why the same user, are not isolation

- Hermes' own docs, on profiles: a profile is a separate Hermes *home*, and **"Profiles do not
  sandbox the agent … on the default local terminal backend the agent still has the same filesystem
  access as your user account. A profile does not stop it from accessing folders outside the profile
  directory."** The same page separately says **"SOUL.md can guide the model, but it does not enforce
  a workspace boundary."** Use these two sentences verbatim when writing the design up — they are the
  honest framing, and they come from the vendor rather than from you.
- The Linux kernel says the same about the OS: *"a single user is able to examine the memory and
  running state of any of their processes"* (Yama LSM docs). Consequence: **`chmod 600` on a secret is
  not protection from a sibling process owned by the same user**, and `/proc/<pid>/environ` is
  readable across processes of one user. File permissions only start meaning something across *users*.
- systemd's own manual calls environment variables **unsuitable for passing secrets** (exposed to
  unprivileged clients over D-Bus, propagated down the process tree including across setuid
  boundaries) and names `LoadCredential=` instead.
- systemd also gates a large block of hardening to system services only — `RootImageOptions=`,
  `RootEphemeral=`, `DynamicUser=`, capabilities, and assorted MAC/sandbox options are documented as
  **"only available for system services and is not supported for services running in per-user
  instances"**. A `systemd --user` unit therefore cannot be hardened properly, so "stay on the user
  manager" is a structural decision, not a config oversight. ArchWiki states it plainly: user units
  *"can not be hardened or sandboxed properly"*.

## The recipe

1. **A separate OS user for the tenant runtime.** Nothing else in this recipe matters without it.
2. **Its `HERMES_HOME` outside the owner's home**, owned by that user (`/var/lib/<tenant>/.hermes`).
   Moving the profile out is what lets you hide the owner's home wholesale.
3. **Read-only access to the code, granted narrowly.** Two paths, not one: the app tree *and* the
   virtualenv (the `hermes` entry point is a script whose shebang names the venv's python). Grant
   with `setfacl` rather than loosening the directory mode.
4. **The credential as a root-owned file, injected by systemd:** `LoadCredential=<name>:/etc/<x>/…`
   (mode 600, root) plus `Environment=<READER>_TOKENS=%d/<name>` — `%d` expands to the unit's private
   credentials directory, so the *path* is in the environment and the *secret* never is. Verified
   workable when the credential reader honors a path-shaped override (here: `INTELLIGENCE_TOKENS`).
   To avoid depending on specifier expansion inside `Environment=` at all, the literal resolved path
   `/run/credentials/<unit>.service/<name>` is equivalent for a system unit. Note that the file under
   `/etc` stays root-only: the tenant reads the *injected copy*, so every reader must be pointed at the
   credentials directory — point a client at the `/etc` source and it fails to open a file it is not
   allowed to see.
5. **A model credential for the tenant runtime — it cannot inherit the owner's.** A second OS user with
   its own `HERMES_HOME` cannot read the owner's `.env` or `auth.json`, so a tenant profile seeded from
   the owner's env file may arrive with no provider key at all: the first turn answers `agent init
   failed: No usable credentials found for provider '<p>'` while `/api/status` still reports the
   provider as configured. Provision the key explicitly into the tenant profile's `.env`, then re-apply
   the unit so it is installed into the tenant's own home. Use a **dedicated key**, not a copy of yours:
   the tenant's agent can read its own `.env`, so a shared key is neither independently revocable nor
   separately visible in the provider's usage view. Hand the file over with a script the operator runs
   (SKILL.md §10) instead of an inline command.
6. **A system-level unit** (`/etc/systemd/system/…`, `User=`/`Group=`), not `--user`.

## A read-only code tree breaks everything that builds on demand

The tenant reads the app tree and can never write it — that is the point — but the app does not know
that: several paths **build into that tree on first use**. Each one turns a read-only code grant into
a broken feature whose message names neither the cause nor the tree.

- **The dashboard's chat page is the one that bites.** It embeds the real TUI over a PTY, and the
  launcher resolves the bundle in this order: (1) `HERMES_TUI_DIR` holding `dist/entry.js` → run it
  directly; (2) a bundle shipped inside the package (`hermes_cli/tui_dist/entry.js`) — absent in a git
  checkout; (3) otherwise `npm install` + esbuild and **rebuild `ui-tui` in place**. A tenant reaches
  (3), the build dies with `Failed to write to output file: open …/ui-tui/dist/entry.js: permission
  denied`, and the UI reports only *Chat unavailable*. The owner never sees it: run as the owner, (3)
  succeeds silently, so this only ever surfaces for the tenant.
- **Pin the prebuilt artifact in the unit** so the search cannot reach the build branch:
  `Environment=HERMES_TUI_DIR=<app>/ui-tui` (the existing `dist/entry.js` is inside the ACL grant, and
  node from the system prefix is world-executable). Confirm the branch by **calling the launcher**, not
  by reading it: set the variable, call `_make_tui_argv(<tui dir>, False)`, and require the returned
  argv to end in `dist/entry.js`.
- **Assert the read in `--verify`**, because "the file exists" and "the tenant can read it" differ:
  `runuser -u <tenant> -- head -c 1 <app>/ui-tui/dist/entry.js`. A bundle that is missing or
  unreadable silently re-arms the build path, and the failure reappears in the UI rather than in the
  verifier.
- **Generalize it after granting read-only code**: grep the runtime for other build-on-write steps
  (asset manifests, compiled style/theme or plugin caches) and either pre-build them as the owner or
  point the tenant at a prebuilt location through an env var. The signature of a missed one is
  `permission denied` on a path inside the app tree in the **tenant's journal** — never a message the
  UI explains.

## Installing it: you have no root, so the operator runs the script

The agent has no passwordless sudo and never asks for a password — that is a standing rule, not a
limitation to route around. There is no masked password prompt to reach for either; a command-approval
dialog authorises *what* runs and never carries the secret. Offer the two safe paths and recommend the
first: **the operator runs the script** (the password never leaves their keyboard), or the operator
puts it in their own agent env file — which is equivalent to granting the agent sudo and leaves a
plaintext secret on disk. Never accept a password in chat and never write one into a config file.

- **Make the script worth running unattended.** The operator runs it once and reports "done"; every
  failure they cannot see costs a full round-trip. Each rule below came from a silent abort:
  - **Preflight the tools before touching anything**, and name the missing one with its install
    command: `setfacl`/`getfacl` come from the `acl` package, which a minimal Ubuntu lacks, and a
    `set -euo pipefail` script dies on first use of it — *after* creating the user, before anything
    else, printing nothing. Print the dependency and the fix (`缺少依赖: setfacl → sudo apt install -y acl`,
    in the operator's language) and exit non-zero, before any write.
  - **Be idempotent.** `useradd` on an existing user aborts the whole script at step 1 on the second
    run, right when a half-applied state most needs re-running: `id -u <user> >/dev/null 2>&1 || useradd …`,
    `install -d`/`install -m` for placement, `systemctl reset-failed` before `enable --now`.
  - **Report state, never infer it.** The credential step must distinguish "staging file present",
    "already installed", and "nothing yet". A two-branch check that only looks for the staging file
    announces "no token yet" on a machine where the token is installed and working — so the next run
    prints mint instructions for a secret that exists, and a re-mint would invalidate the one already
    verified end to end.
- **Have them tee the log to a path you can read:** `sudo ./install.sh --apply 2>&1 | tee /tmp/x.log`.
  `tee` runs as the invoking user, so the log needs no root, and you verify from the log plus your own
  unprivileged reads (`systemctl is-enabled/is-active`, `ls -ld` on the credential directory, `getfacl`
  on the trees, `systemctl show <unit> -p NRestarts`). Do not chain the commands with `&&`: when
  `--apply` stops halfway, the verification output is the most useful thing you can get.
- **"Done" is a self-report; read the state back.** Before writing success down, check the markers
  yourself: unit present and `active`, credential file present (prove its mode from `ls -ld` on the
  directory — you cannot read the file and should not need to), staging file *gone* (which proves the
  script reached that step), restart counter not climbing. A partial install looks exactly like a
  complete one from the operator's side.

## The permission trade-off you must measure, not assume

Granting traversal of the owner's home so the tenant can read the code **re-exposes everything in
that home that is world-readable — at every depth, not just at the top**. `/home/<owner>` was `750`
and `~/.hermes` `700`, so a new user genuinely could not read the sessions, memories or credential
files; a top-level glance found "a dozen loose files" (backup tarballs, analyses, notes). One
`setfacl -m u:<tenant>:x` on the home turned that into a number worth taking: **274,660 readable
files**. Every `o+x` subdirectory — second-runtime trees, `.npm-global`, `.venvs`, the app checkout
itself — lets the tenant descend, and everything `o+r` underneath comes with it. Three orders of
magnitude past what the eye finds is the whole reason the count has to be taken with `find` as the
tenant instead of eyeballed.

**Order: strip world bits first, grant ACLs second.**

1. `chmod -R o-rwx /home/<owner>` — the owner's own access is unaffected (they are the owner), and the
   tenant loses nothing it is owed, because its access is about to be granted by ACL.
2. `setfacl -m u:<tenant>:x` on **every ancestor** of the two trees it must read (the home *and* the
   directory between the home and the app/venv), then `setfacl -R -m u:<tenant>:rX` on those trees and
   `d:u:<tenant>:rX` so files created later inherit the read.
3. Do the ACLs **after** the `chmod`: `chmod` rewrites the ACL mask, so grants applied first can be
   silently clipped — the tenant then fails to read code you just granted, and it looks like a
   traversal problem rather than an ordering one.

- The default is therefore `ProtectHome=no` + an explicit `InaccessiblePaths=` list of the sensitive
  directories and `ReadWritePaths=` for the tenant's own home. **Say out loud in the write-up that
  this list is enumeration-based**: any sensitive directory created elsewhere later must be added
  again, and the guard is a habit, not a mechanism.
- **`InaccessiblePaths=` requires every path it names to exist.** One entry that is absent (a `.ssh`
  never created) and the unit dies before `ExecStart` with
  `Failed to set up mount namespacing: … No such file or directory` and
  `Main process exited, code=exited, status=226/NAMESPACE` — a start failure that reads like a broken
  binary rather than a bad path list. Prefix each entry with `-`
  (`InaccessiblePaths=-/home/<owner>/.ssh …`) to mean "hide it if it exists", which is what the list
  was always meant to say. With `Restart=on-failure` the unit then loops forever, so `--apply` should
  run `systemctl reset-failed <unit>` before `enable --now`.
- The stronger shape (`ProtectHome=yes` + re-exposing the code with `BindReadOnlyPaths=`) is the one
  to reach for when the code can be moved out of `/home` — but systemd does not document a guaranteed
  ordering between `ProtectHome` and the bind options, so do not enable it on faith. If you use it,
  the verification below is what tells you whether the code is still reachable.
- Copying the app to `/opt` instead of binding it sidesteps the ordering question but duplicates a
  virtualenv, whose shebangs and `pyvenv.cfg` carry absolute paths from the original location.

## Verify by pretending to be the tenant, in both directions

Configuration that *looks* right is the failure mode this whole exercise exists to avoid, so the
installer ships a `--verify` mode that runs each probe **as the tenant user** and prints ✓/✗ against
the expected answer: cannot read the owner's session DB, memory directory, CLI token directory, or
the loose files in the home; can read its own home; can execute the runtime.

- **Enumerate; do not spot-check.** Named-path probes only test the paths you happened to think of —
  the leak above was found *by* one named probe failing while its neighbours looked fine, and a
  hand-rolled simulator of "what can another user read" will also miss things (it read mode bits and
  ignored the ACL that granted the traversal). Add a census to `--verify`: as the tenant,
  `find /home/<owner> -type f -readable -not -path '<app>/*' -not -path '<venv>/*' | wc -l` and require
  **0**, printing the first few offenders when it is not. "How many things can it read outside the two
  trees" is an answerable question; "is it blocked" is not.
- **`--verify` must require root.** `runuser` fails for an unprivileged caller, so every probe prints
  "refused" — byte-identical to a working boundary, having measured nothing. Check `id -u` and exit
  non-zero, in the same spirit as the missing-subject check below and the plan-mode rule above.

- **The verifier must refuse to run when its subject does not exist.** Otherwise "user not created"
  and "access denied" print the same word and the check reports a boundary that is not there. This
  is the general shape: *a check whose failure mode and whose not-applicable mode look identical is
  not evidence.*
- **A plan/dry-run mode must be runnable without root** — refusing to show the plan to a non-root
  caller removes the one moment where the change is still free to review.
- **State what the boundary still does not buy**, from the vendor's own wording: these controls
  *"do not sandbox a hostile or compromised agent"*, and the owner of the tenant's own machine is
  root there, so on *their* box the allow-list is self-restraint plus a ledger, not a boundary.

## Where the tenant's artifacts land, and who can open them

The tenant *will* produce files (charts, documents, converted media) — that is the point of giving it
execution. Three separate things decide whether the operator ever sees them, and each one is measured
rather than assumed.

- **The working directory is the unit's, not the profile's.** `terminal.cwd` in the tenant's config
  loses to the session's cwd record, which is the *process* cwd at spawn
  (`tools/code_execution_env.py::_resolve_child_cwd` resolves session record → registered override →
  `TERMINAL_CWD` → `os.getcwd()` → staging dir). Omit `WorkingDirectory=` and systemd supplies `/`:
  every terminal command and every code-kernel cell starts in `/`, `/` is not writable by the tenant,
  and the agent improvises into `$HOME` — the tell is a report sentence like "the shell's cwd is `/`,
  so I created it under `$HOME`". Fix in the unit (`WorkingDirectory=<home>/workspace`), assert with
  `systemctl show <unit> -p WorkingDirectory --value`, and put the chosen directory in the tenant's
  own instruction layer so it stops inventing one per session.
- **Whether an image can be *shown* is a property of the client, not of the agent.** The browser entry
  is the real TUI over a PTY, and the TUI platform hint documents that `MEDIA:<path>` is **not
  intercepted** there (it prints as literal text) and that a file is delivered by stating its absolute
  path — so "it just gives me paths" is the instructed behaviour. The desktop client sets
  `source: 'desktop'` on every session, which is what flips the hint and makes `MEDIA:` render; in
  remote mode the app then reads the file **from the tenant's machine** through `/api/fs/read-data-url`
  (the `/api/media` route is deliberately restricted to media roots and is not the path remote clients
  use). Conclusion to hand the operator: to get inline pictures, change the entry point; to stay on
  the browser, open the dashboard's Files pane (its root is the tenant's home and the path is
  editable) or reach the output directory from the OS.
- **The reverse-direction ACL is part of the handoff.** A 0700 tenant home blocks the owner too —
  from Windows, `\\wsl.localhost\<Distro>\var\lib\<tenant>` answers "you may not have permission to
  use this network resource" even though the owner owns the machine. Grant
  `setfacl -m u:<owner>:rx <tenant home>` and `setfacl -R -m u:<owner>:rX <tenant home>/workspace`:
  the boundary that must hold is "tenant cannot read owner", and this is the opposite direction, so it
  costs nothing. The tenant keeps the only write access; its 0600 files (`state.db`, `config.yaml`,
  `.env`) stay unreadable because the file's own mode outranks the traversal ACL.
- **Check the probe's identity, not just its wording.** These verifiers run their probes *as the
  tenant*, so an owner-side claim written with the same helper silently measures the tenant reading its
  own files and prints ✓. Write it as `runuser -u <owner> -- …` and pair it with the negative:
  owner lists the workspace, owner still cannot read `state.db`. A probe that cannot fail is not
  evidence.

## The census is only as wide as the region you named

The `find /home/<owner>` count reaching 0 says nothing about the rest of the filesystem, and the rest
of the filesystem on a workstation with a Windows drive mounted is the larger surface.

- **`ProtectSystem=strict` blocks *writes*, not reads — a drvfs/`/mnt/<letter>` mount is fully
  readable to the tenant.** Mount permissions come from the host OS (typically 777, with metadata off),
  so the tenant can read every KB checkout, note and credential file that lives on the Windows side,
  and hiding `/home/<owner>` changed none of it. Enumerate mounts before claiming a read boundary, and
  say which regions the census covered.
- **Do not reach for `InaccessiblePaths=` on that mount without costing the tenant's own dependencies**
  — the knowledge-base client in this setup lives on the same drive, so hiding the mount removes the KB
  as well. Present the real options (re-mount with a narrower expose, relocate the client, accept and
  document) instead of silently breaking a working feature.
- **A behavioural switch in the tenant's `.env` survives the config that shadows it.** With
  `terminal.backend: local` present in `config.yaml`, an old `TERMINAL_ENV=ssh` line in `.env` is
  invisible — but delete or reformat that one config key and the env value becomes the effective
  backend, i.e. a tenant that can no longer execute anything (or, in the other direction, one that
  executes somewhere you did not intend). Remove leftovers rather than leaving them shadowed, and
  remember the deploy script copies `.env` verbatim: a fix in the source profile is not live until the
  next `--apply` plus restart.

## Executing on a Windows guest machine

When the tenant's own machine is Windows, the server-side allow-list machinery does not exist:

- Microsoft documents **only a handful** of `sshd_config` directives for Windows OpenSSH
  (`AllowUsers`/`DenyUsers`/`AllowGroups`/`DenyGroups`, `AuthorizedKeysFile` caveats,
  `GSSAPIAuthentication`). `Match`, `ForceCommand` and `ChrootDirectory` get no Windows coverage, and
  `ChrootDirectory` is documented as **SFTP-only** — *"A remote session into cmd.exe doesn't honor
  ChrootDirectory."* Do not design around them on Windows.
- The mechanism that does exist is the **default shell**, set in the registry
  (`HKLM\SOFTWARE\OpenSSH` → `DefaultShell`): point it at your own entry program and put the
  allow-list inside that program.
- Use a **dedicated standard (non-administrator) local account**; an administrator account takes the
  `administrators_authorized_keys` branch, which requires its ACL to hold only `NT AUTHORITY\SYSTEM`
  and `BUILTIN\Administrators`.
- Auditing: process-creation events (4688) with the group policy that includes the command line.

## The allow-list itself (either platform)

- **Allow action names, never binary paths.** A permitted interpreter, archiver, pager, editor,
  VCS or transfer tool is arbitrary command execution with extra steps — sudo's manual concedes
  that restricting users to programs without shell escapes *"is often unworkable"*, and GTFOBins is
  the catalogue of those escapes. Validate with `shlex` into a fixed argv, `shell=False`, no string
  concatenation, and reject shell metacharacters and path escapes in arguments.
- **Quotas have no off-the-shelf SSH equivalent.** The closest hard counter is systemd's
  `StartLimitIntervalSec=`/`StartLimitBurst=` against a *fixed* unit name per action; anything else
  is a self-built ledger, and its read-decide-write cycle must be atomic (a lock or a single
  transaction) or concurrent requests double-spend. All of them are soft limits — the cloud vendors
  document their own quotas as targets, not ceilings — so present quota as self-restraint plus
  traceability, not as a defense.
- **Log the requested command yourself.** `sshd` records authentication and session events, not what
  the client asked to run; raising `LogLevel` to `DEBUG` for it is officially discouraged. The
  wrapper's own structured log plus the host's exec auditing plus a copy off the box is the trio —
  and the copy is the part that survives the tenant editing the local log.

## The loopback namespace is shared by every tenant on the box

A service bound to `127.0.0.1` is private only while there is *one* tenant. Once a second one runs
on the same machine, "localhost" is a shared namespace and every service whose design assumes
"loopback = only me" is a cross-tenant surface. Measured here before anything was fixed: a
**credential-free** `POST` to the owner's own agent A2A port returned a completed task and a real
reply, because the runtime documents that posture as *"No token ⇒ localhost only"* — true for one
tenant, false from the moment there are two. The filesystem work in this file buys nothing if the
tenant can simply call the owner's services over the network.

- **Audit it before believing any isolation claim:** enumerate the listening sockets (`ss -ltnp`)
  and send **one credential-free request to each**, recording the status. The ones that answer or
  execute are surfaces; the ones returning `401`/`403` prove their own gate and need nothing. A
  write-up that says "loopback-only" without this table is a guess.
- **Expect a zero-auth local daemon in the list** — a local model server answering `/api/tags` to
  anyone is the usual find. That is a resource/cost exposure rather than a data one; name it rather
  than leaving it unmentioned.
- **Fix per owned surface, or remove the premise.** Give an unprotected service a credential (for a
  peer runtime: a peer-token map plus a trusted-peers allow-list, with the token read out of the
  other runtime's own env file so it never enters the conversation). The structural fix is a
  **per-tenant loopback address**: bind the tenant's dependency on `127.0.0.2` and give the tenant's
  unit `IPAddressDeny=127.0.0.0/8` + `IPAddressAllow=127.0.0.2/32`, which removes every `127.0.0.1`
  service at once with no per-service credential to maintain. Its cost is real and worth stating: the
  tenant's own inbound listener must move off `.1` too, and `tailscale serve` proxies **only**
  `http://127.0.0.1`, so a loopback-address bridge (`systemd-socket-proxyd`) has to sit in front of
  the entry path.
- **Prove the fix in both directions from one probe:** no credential → `401`, and the peer's own
  credential → accepted/completed. Only the second answer shows you did not lock out the working
  integration. The runtime's audit log is the corroboration: the caller's identity string changes
  from `ip:<addr>` to the authenticated peer name, i.e. it is now *identified* rather than *assumed*.

## Quotas for the runtime's own tool calls

For a tenant that runs *as an agent*, the SSH-side quota story above is not the one that gets used —
its tool calls happen in-process. Ship the gate as a `pre_tool_call` shell hook declared in the
tenant profile's own config.

- **`fail_closed: true` is mandatory and not the default.** A shell hook that crashes, times out, or
  prints non-JSON is *fail-open*; that is right for observability and wrong for a gate. With it, even
  a deleted hook script becomes a refusal.
- **Give it three independent ceilings** (per day, per session, per rolling minute) — they catch
  different failures: cost, one runaway conversation, and a loop. Refused calls must not count.
- **A short-lived process doing read-modify-write needs a lock** (`O_CREAT|O_EXCL` plus stale-lock
  reclaim) or concurrent calls overwrite each other and the count silently under-reports. And **an
  unreadable state file must be treated as failure, never as "zero used today"** — a sentinel of
  "empty" is how a quota becomes decorative.
- **Keep the thresholds in an override file inside the tenant's home** so the operator can change
  them without editing code.
- **Narrow the tool surface as well, and say which layer is the boundary.** A borrowed runtime has no
  business with scheduled-job or desktop-control tools: they leave persistent state on the owner's
  machine or drive their desktop. Configure the toolsets off **and** keep the hook as a second layer
  that catches a later re-enable.
- **Verify the gate as the tenant, and verify the deployment separately.** Run the hook script *as
  the tenant user* with synthetic payloads for both answers (a banned tool → a block directive, a
  normal tool → no directive), then confirm the running service is newer than its config (`enable
  --now` on a live unit is a no-op — see `patching-live-services`). A green file-on-disk check is not
  evidence that the gate is in the request path.
