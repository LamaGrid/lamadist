# SPDX-License-Identifier: Apache-2.0
"""Tests for the guest script's N7A ROW line (.mise/lib/efivar_part_a.sh).

row() runs dd (or rm) and records the error in the err field.  The
field must hold the write's own error line: when open succeeds and
write fails, dd prints "dd: error writing ...: <errno>" first and its
record counts after, and the verdict reads the errno from err.  These
tests source the script, put stub dd, rm, chattr, and stat first on
PATH, and call row().  No guest runs.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / ".mise" / "lib" / "efivar_part_a.sh"
VAR = "/sys/firmware/efi/efivars/PK-8be4df61-93ca-11d2-aa0d-00e098032b8c"
STATS = "0+0 records in\n0+0 records out\n0 bytes copied, 0.00346111 s, 0.0 kB/s\n"


def _stub(path: Path, stderr: str, rc: int) -> None:
    """A command that prints `stderr` on stderr and exits with `rc`."""
    path.write_text("#!/bin/sh\ncat >&2 <<'EOF'\n" + stderr + f"EOF\nexit {rc}\n")
    path.chmod(0o755)


def _row(tmp_path: Path, tag: str, var: str, dd: str, rc: int, rm: str = "") -> str:
    """The N7A ROW line that row() prints against the stub commands."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _stub(bin_dir / "dd", dd, rc)
    _stub(bin_dir / "rm", rm, rc)
    _stub(bin_dir / "chattr", "", 0)
    (bin_dir / "stat").write_text("#!/bin/sh\necho 1\n")
    (bin_dir / "stat").chmod(0o755)
    done = subprocess.run(
        ["bash", "-c", 'source "$1"; row "$2" "$3"', "bash", str(SCRIPT), tag, var],
        capture_output=True,
        text=True,
        check=True,
        env={"PATH": f"{bin_dir}:/usr/bin:/bin"},
    )
    lines = done.stdout.splitlines()
    assert len(lines) == 1, done.stdout
    return lines[0]


def test_sourcing_the_script_prints_nothing_and_runs_no_case(tmp_path: Path) -> None:
    done = subprocess.run(
        ["bash", "-c", 'source "$1"; echo sourced', "bash", str(SCRIPT)],
        capture_output=True,
        text=True,
        check=True,
        env={"PATH": "/usr/bin:/bin"},
    )
    assert done.stdout == "sourced\n"


def test_a_write_time_error_keeps_the_errno_not_the_stats_line(
    tmp_path: Path,
) -> None:
    err = f"dd: error writing '{VAR}': Invalid argument\n" + STATS
    line = _row(tmp_path, "U-PK", "PK", err, 1)
    assert line == f"N7A ROW U-PK rc=1 err=dd: error writing '{VAR}': Invalid argument"


def test_an_open_time_error_still_reads_read_only_file_system(
    tmp_path: Path,
) -> None:
    err = f"dd: failed to open '{VAR}': Read-only file system\n"
    line = _row(tmp_path, "S-PK", "PK", err, 1)
    assert (
        line
        == f"N7A ROW S-PK rc=1 err=dd: failed to open '{VAR}': Read-only file system"
    )


def test_a_failed_remove_keeps_the_rm_line(tmp_path: Path) -> None:
    rm = f"rm: cannot remove '{VAR}': Invalid argument\n"
    line = _row(tmp_path, "X-PK", "PK", "", 1, rm)
    assert line == f"N7A ROW X-PK rc=1 err=rm: cannot remove '{VAR}': Invalid argument"


def test_a_failure_with_no_dd_or_rm_line_falls_back_to_the_last_line(
    tmp_path: Path,
) -> None:
    line = _row(tmp_path, "U-db", "db", STATS, 1)
    assert line == "N7A ROW U-db rc=1 err=0 bytes copied, 0.00346111 s, 0.0 kB/s"


@pytest.mark.parametrize("tag", ["U-PK", "S-db"])
def test_a_write_that_succeeds_prints_a_dash(tmp_path: Path, tag: str) -> None:
    line = _row(tmp_path, tag, "PK", STATS, 0)
    assert line == f"N7A ROW {tag} rc=0 err=-"
