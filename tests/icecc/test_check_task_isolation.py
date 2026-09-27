# SPDX-License-Identifier: Apache-2.0
"""Tests for the CI check that BitBake can cut a task off the network.

BitBake's bb.utils.disable_network() gives up silently (a debug log)
when the kernel refuses an unprivileged user namespace, and the task
then runs with network access.  The check makes that loud.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / ".mise" / "lib" / "check-task-isolation.py"
BITBAKE_LIB = ROOT / "ext" / "bitbake" / "lib"


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True,
        text=True,
        check=False,
    )


def test_isolation_is_reported_where_the_kernel_allows_it() -> None:
    done = _run(str(BITBAKE_LIB))
    assert done.returncode == 0, done.stderr
    assert "task network isolation: ok" in done.stdout


def test_a_missing_bitbake_library_is_an_error() -> None:
    done = _run("/nonexistent/bitbake/lib")
    assert done.returncode == 2
    assert "bitbake" in done.stderr
