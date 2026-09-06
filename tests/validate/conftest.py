# SPDX-License-Identifier: Apache-2.0
"""Fixtures and hooks that keep a green run honest (ADR 0010, rules 1-7).

- rule 1: the session identity guard compares the target's root hash
  with the artifact under test before any check runs;
- rule 2: markers are a fixed vocabulary registered here, and a full
  run with any skipped check fails the session;
- rule 7: no host, port, or address reaches a report; the target name
  replaces them in every captured section and traceback.
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
from collections.abc import Generator
from pathlib import Path
from typing import Any, Final

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / ".mise" / "lib"))

from validate.target import SshTarget, TargetError, from_env

MARKERS: Final[tuple[str, ...]] = (
    *(f"P{n}: property {n} of the validation suite" for n in range(1, 17)),
    "G1: goal 1, the image works",
    "G2: goal 2, nothing breaks across an OTA update",
    "G3: goal 3, the security properties hold",
    "root: the check needs root on the target",
    "negative: negative control, runs without a target",
    "device_only: cannot run on the emulated target",
    "advisory: recorded, never gates",
)
_ROOTHASH: Final[re.Pattern[str]] = re.compile(r"roothash=([0-9a-f]{64})")
_SKIP_FAIL_STATUS: Final[int] = 3

_outcomes: dict[str, str] = {}
_identity: dict[str, str] = {}


def pytest_configure(config: pytest.Config) -> None:
    for marker in MARKERS:
        config.addinivalue_line("markers", marker)


@pytest.fixture(scope="session")
def target() -> SshTarget:
    """The target under test, reachable and identified (rule 1)."""
    try:
        tgt = from_env()
        tgt.wait_ready(
            timeout=float(os.environ.get("LAMADIST_VALIDATE_READY_TIMEOUT", "300"))
        )
        cmdline = tgt.run("cat /proc/cmdline").stdout
        release = tgt.run("cat /etc/os-release").stdout
    except TargetError as err:
        pytest.exit(f"target unavailable: {err}", returncode=2)
    found = _ROOTHASH.search(cmdline)
    if found is None:
        pytest.exit("target kernel command line carries no roothash", returncode=2)
    expected = os.environ.get("LAMADIST_VALIDATE_EXPECT_ROOTHASH", "")
    if not expected:
        pytest.exit("LAMADIST_VALIDATE_EXPECT_ROOTHASH is not set", returncode=2)
    if found.group(1) != expected:
        pytest.exit(
            "target root hash does not match the artifact under test", returncode=2
        )
    _identity.update(
        {
            "target": tgt.name,
            "roothash": found.group(1),
            "os_release": release.strip(),
        }
    )
    return tgt


def _scrub(text: str, tgt_env: dict[str, str]) -> str:
    for key in ("LAMADIST_VALIDATE_HOST", "LAMADIST_VALIDATE_SUDO_PASSWORD"):
        value = tgt_env.get(key, "")
        if value:
            text = text.replace(
                value, tgt_env.get("LAMADIST_VALIDATE_TARGET", "target")
            )
    return text


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(
    item: pytest.Item, call: pytest.CallInfo[None]
) -> Generator[None, Any]:
    outcome = yield
    report: pytest.TestReport = outcome.get_result()
    env = dict(os.environ)
    report.sections = [
        (name, _scrub(content, env)) for name, content in report.sections
    ]
    if report.longrepr is not None:
        scrubbed = _scrub(str(report.longrepr), env)
        if scrubbed != str(report.longrepr):
            report.longrepr = scrubbed


def pytest_runtest_logreport(report: pytest.TestReport) -> None:
    if report.when == "call" or (report.when == "setup" and report.outcome != "passed"):
        _outcomes[report.nodeid] = report.outcome


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    config = session.config
    selected = bool(config.option.keyword or config.option.markexpr)
    reporter = config.pluginmanager.get_plugin("terminalreporter")
    skipped = len(reporter.stats.get("skipped", [])) if reporter is not None else 0
    if skipped and not selected:
        if reporter is not None:
            reporter.write_line(
                f"FAIL: {skipped} skipped check(s) in a full run (rule 2)", red=True
            )
        session.exitstatus = _SKIP_FAIL_STATUS
    snapshot = os.environ.get("LAMADIST_VALIDATE_SNAPSHOT", "")
    if snapshot:
        Path(snapshot).write_text(
            json.dumps(
                {
                    "taken": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    "identity": _identity,
                    "exitstatus": int(session.exitstatus),
                    "skipped": skipped,
                    "results": dict(sorted(_outcomes.items())),
                },
                indent=2,
            )
            + "\n"
        )
