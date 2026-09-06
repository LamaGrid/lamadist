# SPDX-License-Identifier: Apache-2.0
"""Host-side SSH posture measurement via ssh-audit (ADR 0010, the
twelfth check; AoA section 7.6).

ssh-audit probes the target's SSH port from the host and adds nothing
to the image.  Its report grades algorithms, but ADR 0010 rule 6
forbids passing on a grade, so this module reduces the report to
concrete facts: which algorithms each class offers, which of them
ssh-audit tags ``fail``, and which host-key types are advertised.  The
step vocabulary asserts on those facts, never on the grade.

This lives beside ``target.py`` because it is SSH-specific: when a
job-runner transport replaces SSH (docs/PLAN.md Future Work), this
check retires with it.  ``parse`` is pure so it can be unit-tested
without a network or a live target.
"""

from __future__ import annotations

import json
import subprocess
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

_CLASSES: Final[tuple[str, ...]] = ("kex", "key", "enc", "mac")


class AuditError(RuntimeError):
    """ssh-audit could not be run or its output could not be read."""


@dataclass(frozen=True, slots=True)
class Audit:
    """The offered algorithms, ssh-audit's fail tags, and host keys."""

    offered: Mapping[str, tuple[str, ...]]
    failed: Mapping[str, tuple[str, ...]]  # algorithm -> fail reasons
    host_keys: tuple[str, ...]
    kex_not_pq: tuple[str, ...]  # key exchanges with no post-quantum protection

    def has_failures(self) -> bool:
        return bool(self.failed)

    def is_post_quantum_kex(self) -> bool:
        return not self.kex_not_pq


def parse(report: Mapping[str, Any]) -> Audit:
    """Reduce an ssh-audit JSON report to concrete facts."""
    offered: dict[str, tuple[str, ...]] = {}
    failed: dict[str, tuple[str, ...]] = {}
    kex_not_pq: list[str] = []
    for cls in _CLASSES:
        names: list[str] = []
        for entry in report.get(cls, ()):
            name = entry.get("algorithm")
            if not name:
                continue
            names.append(name)
            notes = entry.get("notes", {})
            reasons = notes.get("fail", ())
            if reasons:
                failed[name] = tuple(reasons)
            if cls == "kex" and any(
                "post-quantum" in warning for warning in notes.get("warn", ())
            ):
                kex_not_pq.append(name)
        offered[cls] = tuple(names)
    ordered: dict[str, None] = {}
    for fingerprint in report.get("fingerprints", ()):
        hostkey = fingerprint.get("hostkey")
        if hostkey:
            ordered.setdefault(hostkey, None)
    return Audit(
        offered=offered,
        failed=failed,
        host_keys=tuple(ordered),
        kex_not_pq=tuple(kex_not_pq),
    )


def run(
    host: str, port: int, *, executable: str | None = None, timeout: float = 60.0
) -> Audit:
    """Probe ``host:port`` with ssh-audit and return the parsed facts.

    The executable defaults to ssh-audit in the same directory as the
    running interpreter (the suite's venv installs both).
    """
    exe = executable or str(Path(sys.executable).with_name("ssh-audit"))
    argv = [exe, "-jj", "-p", str(port), host]
    try:
        done = subprocess.run(
            argv, capture_output=True, text=True, timeout=timeout, check=False
        )
    except FileNotFoundError as err:
        raise AuditError(f"ssh-audit not found at {exe!r}") from err
    except subprocess.TimeoutExpired as err:
        raise AuditError(f"ssh-audit timed out after {timeout:.0f}s") from err
    # ssh-audit exits non-zero when it finds fail-level issues, so the
    # report on stdout is authoritative; only an empty stdout is an
    # actual failure to probe.
    if not done.stdout.strip():
        raise AuditError(f"ssh-audit produced no report:\n{done.stderr.strip()}")
    try:
        report = json.loads(done.stdout)
    except json.JSONDecodeError as err:
        raise AuditError(f"ssh-audit output was not JSON: {err}") from err
    return parse(report)
