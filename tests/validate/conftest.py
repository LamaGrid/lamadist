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

from steps import FACTS
from validate.target import SshTarget, TargetError, from_env

MARKERS: Final[tuple[str, ...]] = (
    *(f"P{n}: property {n} of the validation suite" for n in range(1, 19)),
    "G1: goal 1, the image works",
    "G2: goal 2, nothing breaks across an OTA update",
    "G3: goal 3, the security properties hold",
    "root: the check needs root on the target",
    "negative: negative control, runs without a target",
    "device_only: cannot run on the emulated target",
    "advisory: recorded, never gates",
    (
        "ota: compares against a snapshot from before an update "
        "(LAMADIST_VALIDATE_BASELINE); deselected without one, never skipped"
    ),
)
_ROOTHASH: Final[re.Pattern[str]] = re.compile(r"roothash=([0-9a-f]{64})")
_SKIP_FAIL_STATUS: Final[int] = 3

_outcomes: dict[str, str] = {}
_identity: dict[str, str] = {}


def pytest_configure(config: pytest.Config) -> None:
    for marker in MARKERS:
        config.addinivalue_line("markers", marker)


def pytest_collection_modifyitems(
    config: pytest.Config, items: list[pytest.Item]
) -> None:
    """Without a baseline the ``ota`` checks cannot compare anything, so
    they are deselected -- counted in the summary, never skipped (rule 2)."""
    if os.environ.get("LAMADIST_VALIDATE_BASELINE"):
        return
    dropped = [item for item in items if item.get_closest_marker("ota")]
    if dropped:
        config.hook.pytest_deselected(items=dropped)
        items[:] = [item for item in items if not item.get_closest_marker("ota")]


def _say(session: pytest.Session, text: str, *, red: bool = False) -> None:
    reporter = session.config.pluginmanager.get_plugin("terminalreporter")
    if reporter is not None:
        reporter.write_line(text, red=red)


def _compare_with_baseline(session: pytest.Session) -> dict[str, Any] | None:
    """Rule 2 across an update.  Every check the baseline ran must have
    run again in a full run, and any changed outcome is named.  A
    regression has already turned the run red; this makes it legible."""
    path = os.environ.get("LAMADIST_VALIDATE_BASELINE", "")
    if not path:
        return None
    try:
        before = json.loads(Path(path).read_text())
        old: dict[str, str] = dict(before["results"])
    except (OSError, KeyError, TypeError, ValueError) as err:
        _say(session, f"FAIL: unusable baseline snapshot {path}: {err!r}", red=True)
        session.exitstatus = 2
        return {"path": path, "error": repr(err)}
    selected = bool(session.config.option.keyword or session.config.option.markexpr)
    missing = sorted(set(old) - set(_outcomes))
    changed = {
        k: [old[k], _outcomes[k]]
        for k in sorted(set(old) & set(_outcomes))
        if old[k] != _outcomes[k]
    }
    if missing and not selected:
        _say(
            session,
            f"FAIL: {len(missing)} check(s) from the baseline did not run (rule 2)",
            red=True,
        )
        if session.exitstatus == 0:
            session.exitstatus = _SKIP_FAIL_STATUS
    if changed:
        _say(
            session,
            f"{len(changed)} check(s) changed outcome since the baseline: "
            + ", ".join(changed),
            red=True,
        )
    return {
        "path": path,
        "taken": before.get("taken"),
        "roothash_before": before.get("identity", {}).get("roothash"),
        "missing": missing,
        "changed": changed,
    }


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
    baseline = _compare_with_baseline(session)
    snapshot = os.environ.get("LAMADIST_VALIDATE_SNAPSHOT", "")
    if snapshot:
        Path(snapshot).write_text(
            json.dumps(
                {
                    "taken": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    "identity": _identity,
                    "exitstatus": int(session.exitstatus),
                    "skipped": skipped,
                    "facts": dict(FACTS),
                    "baseline": baseline,
                    "results": dict(sorted(_outcomes.items())),
                },
                indent=2,
            )
            + "\n"
        )
