# SPDX-License-Identifier: Apache-2.0
"""Step vocabulary for the validation features: regex to callable.

Every step is a declarative (command, matcher) pair over the target's
four operations, so the scenarios can later feed a job runner instead
of SSH.  No step passes on empty output (ADR 0010 rule 3), and no step
asserts on a score (rule 6).
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from typing import Any, Final

import pytest

Context = dict[str, Any]
Step = Callable[..., None]

STEPS: Final[list[tuple[re.Pattern[str], Step]]] = []


def step(pattern: str) -> Callable[[Step], Step]:
    """Register ``fn`` for step text fully matching ``pattern``."""

    def register(fn: Step) -> Step:
        STEPS.append((re.compile(pattern), fn))
        return fn

    return register


def _output(ctx: Context) -> str:
    out = ctx.get("output")
    if out is None:
        pytest.fail("no command has run in this scenario")
    if not out.strip():
        pytest.fail("empty output cannot satisfy a matcher (rule 3)")
    return out


@step(r'I run "(.+)"')
def _run(ctx: Context, cmd: str) -> None:
    ctx["output"] = ctx["target"].run(cmd).stdout


@step(r'I run "(.+)" as root')
def _run_root(ctx: Context, cmd: str) -> None:
    ctx["output"] = ctx["target"].run_root(cmd).stdout


@step(r'the output matches "(.+)"')
def _matches(ctx: Context, pattern: str) -> None:
    out = _output(ctx)
    assert re.search(pattern, out, re.MULTILINE), f"{pattern!r} not found in:\n{out}"


@step(r'the output does not match "(.+)"')
def _not_matches(ctx: Context, pattern: str) -> None:
    out = _output(ctx)
    assert not re.search(pattern, out, re.MULTILINE), f"{pattern!r} found in:\n{out}"


@step(r'the matcher "(.+)" rejects "(.+)"')
def _rejects(ctx: Context, pattern: str, sample: str) -> None:
    """Negative control: the same matcher must refuse a known-bad input."""
    assert not re.search(pattern, sample, re.MULTILINE), (
        f"negative control failed: {pattern!r} accepted {sample!r}"
    )


def _booted_slot_is_good(raw: str) -> bool:
    """Parse ``rauc status --output-format=json``; fail loudly on shape drift."""
    try:
        data = json.loads(raw)
        booted = data["booted"]
        for entry in data["slots"]:
            for slot in entry.values():
                if slot.get("bootname") == booted or slot.get("state") == "booted":
                    return slot["boot_status"] == "good"
    except (KeyError, TypeError, ValueError) as err:
        pytest.fail(f"unexpected rauc status shape ({err!r}):\n{raw}")
    pytest.fail(f"booted slot {booted!r} not found in rauc status:\n{raw}")


@step(r"the RAUC status reports the booted slot as good")
def _rauc_good(ctx: Context) -> None:
    assert _booted_slot_is_good(_output(ctx)), (
        f"booted slot is not good:\n{_output(ctx)}"
    )


@step(r'the RAUC status "(.+)" is not reported as good')
def _rauc_rejects(ctx: Context, sample: str) -> None:
    assert not _booted_slot_is_good(sample), (
        f"negative control failed: {sample!r} read as good"
    )


def _only(methods: list[str], wanted: str) -> bool:
    return methods == [wanted]


@step(r'the target offers only "(.+)" authentication')
def _auth_only(ctx: Context, wanted: str) -> None:
    methods = ctx["target"].auth_methods()
    assert _only(methods, wanted), f"sshd offers {methods}, not only {wanted!r}"


@step(r'the authentication list "(.+)" is not only "(.+)"')
def _auth_rejects(ctx: Context, sample: str, wanted: str) -> None:
    methods = [m.strip() for m in sample.split(",")]
    assert not _only(methods, wanted), (
        f"negative control failed: {sample!r} read as only {wanted!r}"
    )
