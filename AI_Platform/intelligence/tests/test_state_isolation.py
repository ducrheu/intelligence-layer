"""The suite must not touch the live runtime's state directory.

Regression for a real incident: the gateway resolves its runtime state from
`INTELLIGENCE_STATE`, every cron wrapper exports it, and a test run started from
such a shell wrote **315 lifecycle events** for fixture artifacts (`layout-demo`,
`usage-demo`, `plain-note`, ...) into the production `events.jsonl`. The suite was
also red in that shell (5 of 13 files) because fixtures could not find their own
audit log - a failure that looked like a code bug and was really environment
inheritance.

Two properties are pinned here:

1. the suite drops the variable before any gateway is constructed;
2. a child test process started with the variable set still writes nothing to the
   directory it names.

The second is the one that would have caught the incident: it asserts on the
filesystem, not on the presence of a line of code.
"""
from __future__ import annotations

# Tests own their state directory. INTELLIGENCE_STATE is exported by every cron
# wrapper, and a suite that inherits it writes lifecycle events into the live
# store's event stream (measured: 315 test rows in the production log). Dropping
# it here makes the suite behave identically in a cron shell and in CI.
import os as _os

_os.environ.pop("INTELLIGENCE_STATE", None)

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

TESTS = Path(__file__).resolve().parent


class StateIsolationTests(unittest.TestCase):
    def test_the_suite_drops_the_cron_state_variable(self) -> None:
        self.assertNotIn("INTELLIGENCE_STATE", os.environ)

    def test_a_child_test_process_writes_nothing_to_the_inherited_state_dir(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            inherited = Path(tmp) / "inherited-state"
            inherited.mkdir()
            env = dict(os.environ)
            env["INTELLIGENCE_STATE"] = str(inherited)
            env["PYTHONPATH"] = str(TESTS.parents[2])  # AI_Platform package root
            result = subprocess.run(
                [sys.executable, "test_phase1.py"],
                cwd=str(TESTS), env=env, capture_output=True, text=True, timeout=180,
            )
            self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
            written = sorted(str(path.relative_to(inherited)) for path in inherited.rglob("*") if path.is_file())
            self.assertEqual(written, [], msg=f"a test process wrote into the inherited state dir: {written}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
