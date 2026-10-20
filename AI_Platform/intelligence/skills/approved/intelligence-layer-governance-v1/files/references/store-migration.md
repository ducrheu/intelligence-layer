# Moving the governed store to another path

The store is referenced from more places than it looks, and the copy is exactly the kind of thing a
botched move leaves doubled. Move, repoint, verify, then freeze the original — in that order, and
never freeze before the new location is serving.

## 1. Find every reference first

Search code and config, not just prose, and search for a **fragment** of the path: a path split
across two adjacent string literals (a wrapped long line) does not match a single-line pattern, so a
whole-path search returns nothing while the dependency is right there.

```bash
rg -l --no-messages -g '!node_modules' -g '!*/source/*' '<path-fragment>' \
  <tool dir> <workspace dir> ~/.config/systemd ~/.hermes /mnt/c/Users/<user>/.codex
```

Expect: the systemd unit (`WorkingDirectory`, `ExecStart --root`, the `Documentation=` URL), every
tool that imports the package or posts to the gateway, prose docs, and **other applications' state
files** (an editor or agent CLI keeps a recent-projects list). Leave third-party state files alone —
report the stale entry instead of editing another tool's state.

The tools that matter here are beside the OpenClaw tree (`tools/intelligence-mcp/`,
`hermes-skill-backflow.py`, `intelligence-approve.py`, `intelligence-validate.py`,
`intelligence-repair-skill-layout.py`).

## 2. Back up, copy, prove the copy byte-for-byte

```bash
tar czf ~/store-backup-pre-move-$(date +%Y%m%d-%H%M%S).tar.gz -C <parent> <dir>
rsync -a --exclude '__pycache__' <src> <dest>/
( cd <src>  && find . -type f -not -path '*__pycache__*' | sort | xargs -d '\n' sha256sum > /tmp/c.sums )
( cd <dest> && find . -type f -not -path '*__pycache__*' | sort | xargs -d '\n' sha256sum > /tmp/d.sums )
diff /tmp/c.sums /tmp/d.sums
```

Exclude the one file a running service appends to (an audit log) from the comparison and say so —
otherwise its growth reads as a mismatch and hides a real one.

Keep whatever parent level the code depends on. If the package is imported as
`from <Platform>.intelligence...`, the copied tree must keep that level, and the suite must be run
with that parent on `sys.path` (`PYTHONPATH=<parent> python3 <Platform>/intelligence/tests/test_x.py`),
or every test breaks at import.

## 3. Repoint — configuration, not surgery

Turn hardcoded roots into env-overridable constants defaulting to the new path
(`INTELLIGENCE_ROOT`, `INTELLIGENCE_PLATFORM`, `INTELLIGENCE_GATEWAY`, plus a token var per
identity). The next move is then a config change. A tool that still hardcodes the root is a defect
to fix while you are in there, not a fact to work around.

Then, for a systemd user unit: edit, `systemctl --user daemon-reload`, restart, and prove where it
actually runs from instead of trusting the restart:

```bash
systemctl --user show -p MainPID --value <unit>
ls -l /proc/<pid>/cwd                              # must be the new root
curl -s -H 'X-Intelligence-Token: <read identity>' http://127.0.0.1:8765/health
```

Finish by running the store's own test suite from the new parent **and** the live acceptance check,
so "it serves" means "it serves correctly". A read-only surface check that passes is the cheapest
proof the move did not change visibility or bounds.

## 4. Freeze the original — and verify it from the Windows side

Rename the old directory (`<dir>.migrated-to-<dest>-<date>`) so a stale duplicate cannot be mistaken
for the live store, then delete it after a few days of clean running.

**On a drvfs mount (`/mnt/c`, `/mnt/d`), a freshly renamed directory can appear in WSL as
`d?????????` with `stat` reporting "No such file or directory", while the data is completely intact.**
That is an unrefreshed directory-entry cache, not data loss. Confirm from the Windows side — before
concluding anything, and especially before telling anyone a directory was destroyed:

```bash
/mnt/c/Windows/System32/cmd.exe /c dir /b "C:\path\to\parent"
/mnt/c/Windows/System32/cmd.exe /c dir /b /s "C:\path\to\renamed\dir"
```

A `dir` that lists the directory means the move succeeded; a WSL `ls` that cannot stat it is the
cache, and a WSL restart clears it. Quoting a path into `cmd.exe /c if exist "..."` is unreliable
from WSL — it answers "missing" for a directory that is there. Use `dir`, which fails loudly.

## Why the backup is not optional

A rename on drvfs can look like a deletion from inside WSL for as long as the cache is stale. The
tar backup taken before the copy is what makes that ambiguity survivable: with it, the worst case is
re-copying; without it, the only evidence is a directory entry you cannot stat.
