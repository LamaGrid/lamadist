# SPDX-License-Identifier: Apache-2.0
"""Tests for starting the build's local iceccd without root.

A fake iceccd records its arguments and HOME, so the tests check the
contract: the daemon runs as the caller with HOME set to the socket
directory, and every failure leaves the build compiling locally.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / ".mise" / "lib" / "start-iceccd.sh"


def _fake_iceccd(tmp_path: Path, rc: int = 0) -> Path:
    fake = tmp_path / "iceccd"
    fake.write_text(
        "#!/bin/sh\n"
        f'printf "%s\\n" "HOME=$HOME" "$@" > "{tmp_path}/called"\n'
        f"exit {rc}\n"
    )
    fake.chmod(0o755)
    return fake


def _sockdir(tmp_path: Path) -> Path:
    sockdir = tmp_path / "icecc"
    sockdir.mkdir()
    (sockdir / "iceccd.socket").symlink_to(".iceccd.socket")
    return sockdir


def _run(tmp_path: Path, sockdir: Path, fake: Path, **env: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(SCRIPT), "sched.example", str(tmp_path / "log")],
        env={
            **os.environ,
            "LAMADIST_ICECCD": str(fake),
            "LAMADIST_ICECC_SOCKDIR": str(sockdir),
            **env,
        },
        capture_output=True,
        text=True,
        check=False,
    )


def test_the_daemon_runs_as_the_caller_with_home_at_the_socket_dir(tmp_path: Path) -> None:
    sockdir, fake = _sockdir(tmp_path), _fake_iceccd(tmp_path)
    done = _run(tmp_path, sockdir, fake)
    assert done.returncode == 0, done.stderr
    called = (tmp_path / "called").read_text().splitlines()
    assert called[0] == f"HOME={sockdir}"
    assert "--no-remote" in called
    assert called[called.index("-s") + 1] == "sched.example"
    assert "-m" not in called


def test_the_local_slot_cap_is_passed_through(tmp_path: Path) -> None:
    sockdir, fake = _sockdir(tmp_path), _fake_iceccd(tmp_path)
    _run(tmp_path, sockdir, fake, LAMADIST_MAX_LOCAL_JOBS="6")
    called = (tmp_path / "called").read_text().splitlines()
    assert called[called.index("-m") + 1] == "6"


@pytest.mark.parametrize("breakage", ["missing", "no-link"])
def test_an_unusable_socket_dir_leaves_compiles_local(tmp_path: Path, breakage: str) -> None:
    fake = _fake_iceccd(tmp_path)
    sockdir = tmp_path / "icecc"
    if breakage == "no-link":
        sockdir.mkdir()
    done = _run(tmp_path, sockdir, fake)
    assert done.returncode == 0
    assert "compiles stay local" in done.stderr
    assert not (tmp_path / "called").exists()


def test_a_daemon_that_fails_to_start_leaves_compiles_local(tmp_path: Path) -> None:
    sockdir, fake = _sockdir(tmp_path), _fake_iceccd(tmp_path, rc=1)
    done = _run(tmp_path, sockdir, fake)
    assert done.returncode == 0
    assert "compiles stay local" in done.stderr
