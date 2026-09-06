# SPDX-License-Identifier: Apache-2.0
"""Step vocabulary for the validation features: regex to callable.

Every step is a declarative (command, matcher) pair over the target's
four operations, so the scenarios can later feed a job runner instead
of SSH.  No step passes on empty output (ADR 0010 rule 3), and no step
asserts on a score (rule 6).
"""

from __future__ import annotations

import json
import os
import re
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any, Final

import pytest
from validate.rauc import (
    Status,
    from_facts,
    is_refusal,
    moved,
    parse_status,
    to_facts,
    unchanged,
    untouched,
)
from validate.ssh_audit import Audit, parse

Context = dict[str, Any]
Step = Callable[..., None]

STEPS: Final[list[tuple[re.Pattern[str], Step]]] = []

# Facts a run records for the next run to compare against; conftest
# writes them into the snapshot beside the per-check outcomes.
FACTS: Final[dict[str, Any]] = {}

# Where the wrong-CA bundle lands on the target for check 13.  Root
# removes it: SELinux keeps the unprivileged user from unlinking a file
# the installer has opened.
_WRONG_CA_REMOTE: Final[str] = "/tmp/lamadist-validate-wrong-ca.raucb"

# Fixed ssh-audit reports for the negative controls: no network, no
# target.  "stock-image" is the shape ssh-audit returns for the
# current image (a broken SHA-1 MAC and an NSA-suspect ECDSA host key,
# both fail-rated; no Edwards-curve host key), so the same predicates
# the positive scenario runs must flag it.
_SAMPLE_REPORTS: Final[dict[str, dict[str, Any]]] = {
    "stock-image": {
        "kex": [
            {
                "algorithm": "curve25519-sha256",
                "notes": {
                    "warn": ["does not provide protection against post-quantum attacks"]
                },
            }
        ],
        "key": [
            {
                "algorithm": "ecdsa-sha2-nistp256",
                "notes": {"fail": ["suspected NSA-backdoored curve"]},
            }
        ],
        "mac": [
            {
                "algorithm": "hmac-sha1-etm@openssh.com",
                "notes": {"fail": ["using broken SHA-1 hash algorithm"]},
            }
        ],
        "fingerprints": [{"hostkey": "ecdsa-sha2-nistp256", "hash_alg": "SHA256"}],
    },
}


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


def _audit(ctx: Context) -> Audit:
    """One ssh-audit probe per scenario, cached in the context."""
    cached = ctx.get("audit")
    if cached is None:
        cached = ctx["target"].audit()
        ctx["audit"] = cached
    return cached


@step(r"the SSH server offers no algorithm rated fail by ssh-audit")
def _audit_no_fail(ctx: Context) -> None:
    audit = _audit(ctx)
    assert not audit.has_failures(), "ssh-audit rates as fail: " + "; ".join(
        f"{algo} ({', '.join(reasons)})" for algo, reasons in audit.failed.items()
    )


@step(r'the SSH server offers a "(.+)" host key')
def _audit_host_key(ctx: Context, algo: str) -> None:
    # The offered host-key algorithms come from the server's KEXINIT and
    # are read without completing the handshake.  ssh-audit's own client
    # cannot complete a post-quantum-only key exchange, so its host-key
    # fingerprint is empty against this image; the offered algorithm list
    # is the authoritative, handshake-independent source.
    audit = _audit(ctx)
    offered = audit.offered.get("key", ())
    assert algo in offered, (
        f"host key algorithms offered are {list(offered)}, missing {algo!r}"
    )


@step(r"the SSH server offers only post-quantum key exchange")
def _audit_pq_kex(ctx: Context) -> None:
    audit = _audit(ctx)
    assert audit.is_post_quantum_kex(), (
        "these key exchanges carry no post-quantum protection: "
        + ", ".join(audit.kex_not_pq)
    )


@step(r'the sample ssh-audit report "(.+)" rates an algorithm as fail')
def _sample_has_fail(ctx: Context, name: str) -> None:
    """Negative control: the fail predicate must catch a stock report."""
    audit = parse(_SAMPLE_REPORTS[name])
    assert audit.has_failures(), (
        f"negative control failed: sample {name!r} has no fail-rated algorithm"
    )


@step(r'the sample ssh-audit report "(.+)" offers no "(.+)" host key')
def _sample_missing_host_key(ctx: Context, name: str, algo: str) -> None:
    """Negative control: the host-key predicate must catch its absence."""
    offered = parse(_SAMPLE_REPORTS[name]).offered.get("key", ())
    assert algo not in offered, (
        f"negative control failed: {algo!r} unexpectedly present in {name!r}"
    )


@step(r'the sample ssh-audit report "(.+)" offers a classical key exchange')
def _sample_classical_kex(ctx: Context, name: str) -> None:
    """Negative control: the post-quantum predicate must catch a classical kex."""
    audit = parse(_SAMPLE_REPORTS[name])
    assert not audit.is_post_quantum_kex(), (
        f"negative control failed: sample {name!r} has no classical key exchange"
    )


# --- Goal 2: slots across an update, and a refused install ------------


def _detailed(
    booted: str, primary: str, slots: Sequence[tuple[str, str, str, str, str, int]]
) -> str:
    """A minimal ``rauc status --detailed`` document for the negative controls."""
    entries = []
    for name, bootname, state, sha256, installed_at, count in slots:
        entries.append(
            {
                name: {
                    "bootname": bootname,
                    "state": state,
                    "boot_status": "good",
                    "slot_status": {
                        "checksum": {"sha256": sha256, "size": 1},
                        "installed": {"timestamp": installed_at, "count": count},
                    },
                }
            }
        )
    return json.dumps({"booted": booted, "boot_primary": primary, "slots": entries})


_A, _B, _C = "a" * 64, "b" * 64, "c" * 64
_T0, _T1 = "2026-09-06T11:53:50Z", "2026-09-06T20:35:11Z"
_BEFORE = _detailed(
    "a",
    "rootfs.0",
    [
        ("rootfs.0", "a", "booted", _A, _T0, 3),
        ("rootfs.1", "b", "inactive", _B, _T0, 2),
    ],
)

# (baseline, now) pairs that the predicates the positive scenarios run
# must reject: no update at all; an update that rewrote the slot it came
# from; and an install that changed a slot.
_SAMPLE_HISTORY: Final[dict[str, tuple[str, str]]] = {
    "boot-did-not-move": (_BEFORE, _BEFORE),
    "rewritten-old-slot": (
        _BEFORE,
        _detailed(
            "b",
            "rootfs.1",
            [
                ("rootfs.0", "a", "inactive", _C, _T1, 4),
                ("rootfs.1", "b", "booted", _B, _T1, 3),
            ],
        ),
    ),
    "install-bumped-a-slot": (
        _BEFORE,
        _detailed(
            "a",
            "rootfs.0",
            [
                ("rootfs.0", "a", "booted", _A, _T0, 3),
                ("rootfs.1", "b", "inactive", _B, _T1, 3),
            ],
        ),
    ),
}
_SAMPLE_INSTALLS: Final[dict[str, tuple[int, str]]] = {
    "accepted": (0, "100% Installing done.\nInstalling `/tmp/x.raucb` succeeded"),
}


def _status(ctx: Context) -> Status:
    try:
        return parse_status(_output(ctx))
    except ValueError as err:
        pytest.fail(f"{err}:\n{_output(ctx)}")


def _live_status(ctx: Context) -> Status:
    raw = ctx["target"].run("rauc status --detailed --output-format=json").stdout
    try:
        return parse_status(raw)
    except ValueError as err:
        pytest.fail(f"{err}:\n{raw}")


@step(r"the RAUC slot facts are recorded")
def _record_facts(ctx: Context) -> None:
    FACTS["rauc"] = to_facts(_status(ctx))


@step(r"the baseline snapshot from before the update")
def _baseline(ctx: Context) -> None:
    path = os.environ.get("LAMADIST_VALIDATE_BASELINE", "")
    if not path:
        pytest.fail(
            "LAMADIST_VALIDATE_BASELINE is not set; ota checks run only with --baseline"
        )
    try:
        facts = json.loads(Path(path).read_text())["facts"]["rauc"]
        ctx["baseline"] = from_facts(facts)
    except (OSError, KeyError, TypeError, ValueError) as err:
        pytest.fail(f"unusable baseline snapshot {path}: {err!r}")


@step(r"the update moved the boot to the other slot")
def _moved(ctx: Context) -> None:
    now = _status(ctx)
    assert moved(ctx["baseline"], now), (
        f"the boot did not move since the baseline (still on {now.booted!r})"
    )


@step(r"the slot booted in the baseline is inactive, good, and untouched")
def _untouched(ctx: Context) -> None:
    now = _status(ctx)
    assert untouched(ctx["baseline"], now), (
        f"the slot booted in the baseline was not left alone:\n{_output(ctx)}"
    )


@step(r"a bundle signed by a certificate authority the target does not trust")
def _wrong_ca_bundle(ctx: Context) -> None:
    path = os.environ.get("LAMADIST_VALIDATE_WRONG_CA_BUNDLE", "")
    if not path or not os.path.isfile(path):
        pytest.fail("LAMADIST_VALIDATE_WRONG_CA_BUNDLE does not name a file")
    ctx["target"].push(path, _WRONG_CA_REMOTE)
    ctx["slots_before"] = _live_status(ctx)


@step(r"I install that bundle as root")
def _install_bundle(ctx: Context) -> None:
    tgt = ctx["target"]
    try:
        res = tgt.run_root(f"rauc install {_WRONG_CA_REMOTE}")
        ctx["install"] = (res.rc, res.stdout + res.stderr)
        ctx["output"] = res.stdout + res.stderr
    finally:
        ctx["slots_after"] = _live_status(ctx)
        tgt.run_root(f"rm -f {_WRONG_CA_REMOTE}")


@step(r"the installation is refused for its signature")
def _refused(ctx: Context) -> None:
    rc, text = ctx["install"]
    assert is_refusal(rc, text), (
        f"the install was not refused for its signature (rc={rc}):\n{text}"
    )


@step(r"the RAUC slots are unchanged by the attempt")
def _slots_unchanged(ctx: Context) -> None:
    before, after = ctx["slots_before"], ctx["slots_after"]
    assert unchanged(before, after), "a refused install changed a slot:\n" + json.dumps(
        {"before": to_facts(before), "after": to_facts(after)}, indent=1
    )


@step(r'the sample slot history "(.+)" did not move the boot')
def _sample_not_moved(ctx: Context, name: str) -> None:
    before, after = (parse_status(s) for s in _SAMPLE_HISTORY[name])
    assert not moved(before, after), (
        f"negative control failed: {name} read as an update"
    )


@step(r'the sample slot history "(.+)" rewrote the old slot')
def _sample_rewrote(ctx: Context, name: str) -> None:
    before, after = (parse_status(s) for s in _SAMPLE_HISTORY[name])
    assert moved(before, after) and not untouched(before, after), (
        f"negative control failed: {name} read as untouched"
    )


@step(r'the sample slot history "(.+)" changed a slot')
def _sample_changed(ctx: Context, name: str) -> None:
    before, after = (parse_status(s) for s in _SAMPLE_HISTORY[name])
    assert not unchanged(before, after), (
        f"negative control failed: {name} read as unchanged"
    )


@step(r'the sample install "(.+)" is not a refusal')
def _sample_not_refusal(ctx: Context, name: str) -> None:
    rc, text = _SAMPLE_INSTALLS[name]
    assert not is_refusal(rc, text), (
        f"negative control failed: {name} read as a refusal"
    )
