# SPDX-License-Identifier: Apache-2.0
"""Unit tests for the RAUC status predicates (no network, no target).

Checks 12 and 13 (ADR 0010; AoA section 7.7) reason about
``rauc status --detailed --output-format=json``: whether an update
moved the boot, whether the slot it moved away from was left alone,
and whether a refused install left every slot exactly as it was.
These samples are the RED/GREEN pair for those predicates.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from validate.rauc import (
    from_facts,
    is_refusal,
    moved,
    parse_status,
    to_facts,
    unchanged,
    untouched,
)


def _slot(
    name: str,
    bootname: str,
    state: str,
    sha256: str,
    installed_at: str,
    count: int,
    boot_status: str = "good",
) -> dict[str, Any]:
    return {
        name: {
            "class": name.split(".")[0],
            "device": f"/dev/disk/by-partlabel/{name}",
            "type": "raw",
            "bootname": bootname,
            "state": state,
            "parent": None,
            "mountpoint": None,
            "boot_status": boot_status,
            "slot_status": {
                "bundle": {"compatible": "lamadist-intel", "build": "20260906114101"},
                "checksum": {"sha256": sha256, "size": 1322541056},
                "installed": {"timestamp": installed_at, "count": count},
                "status": "ok",
            },
        }
    }


def _status(booted: str, primary: str, slots: list[dict[str, Any]]) -> str:
    return json.dumps(
        {
            "compatible": "lamadist-intel",
            "variant": "",
            "booted": booted,
            "boot_primary": primary,
            "slots": slots,
            "artifact-repositories": [],
        }
    )


SHA_A = "a" * 64
SHA_B = "b" * 64

# Before the update: booted a, b inactive.
BEFORE = _status(
    "a",
    "rootfs.0",
    [
        _slot("rootfs.0", "a", "booted", SHA_A, "2026-09-06T11:53:50Z", 3),
        _slot("rootfs.1", "b", "inactive", SHA_B, "2026-09-05T10:00:00Z", 2),
    ],
)

# After a clean update: booted b (freshly installed), a untouched.
AFTER = _status(
    "b",
    "rootfs.1",
    [
        _slot("rootfs.0", "a", "inactive", SHA_A, "2026-09-06T11:53:50Z", 3),
        _slot("rootfs.1", "b", "booted", SHA_B, "2026-09-06T20:35:11Z", 3),
    ],
)


def test_parse_reads_the_detailed_shape() -> None:
    status = parse_status(BEFORE)
    assert status.booted == "a"
    assert status.primary == "rootfs.0"
    assert set(status.slots) == {"rootfs.0", "rootfs.1"}
    slot = status.slots["rootfs.1"]
    assert (slot.bootname, slot.state, slot.boot_status) == ("b", "inactive", "good")
    assert slot.sha256 == SHA_B
    assert slot.installed_count == 2


def test_a_clean_update_moves_the_boot_and_leaves_the_old_slot_alone() -> None:
    before, after = parse_status(BEFORE), parse_status(AFTER)
    assert moved(before, after)
    assert untouched(before, after)


def test_untouched_rejects_a_rewritten_old_slot() -> None:
    tampered = json.loads(AFTER)
    tampered["slots"][0]["rootfs.0"]["slot_status"]["checksum"]["sha256"] = "c" * 64
    assert not untouched(parse_status(BEFORE), parse_status(json.dumps(tampered)))
    restamped = json.loads(AFTER)
    restamped["slots"][0]["rootfs.0"]["slot_status"]["installed"]["count"] = 4
    assert not untouched(parse_status(BEFORE), parse_status(json.dumps(restamped)))


def test_untouched_rejects_an_old_slot_marked_bad() -> None:
    bad = json.loads(AFTER)
    bad["slots"][0]["rootfs.0"]["boot_status"] = "bad"
    assert not untouched(parse_status(BEFORE), parse_status(json.dumps(bad)))


def test_moved_is_false_when_the_boot_did_not_move() -> None:
    before = parse_status(BEFORE)
    assert not moved(before, parse_status(BEFORE))


def test_unchanged_is_exact() -> None:
    before = parse_status(BEFORE)
    assert unchanged(before, parse_status(BEFORE))
    bumped = json.loads(BEFORE)
    bumped["slots"][1]["rootfs.1"]["slot_status"]["installed"]["count"] = 3
    assert not unchanged(before, parse_status(json.dumps(bumped)))
    repointed = json.loads(BEFORE)
    repointed["boot_primary"] = "rootfs.1"
    assert not unchanged(before, parse_status(json.dumps(repointed)))


def test_refusal_needs_a_failing_exit_and_a_signature_reason() -> None:
    assert is_refusal(1, "Failed to verify signature: certificate verify failed")
    assert is_refusal(1, "signature verification failed")
    assert not is_refusal(0, "Installing `/tmp/x.raucb` succeeded")
    assert not is_refusal(1, "Installing `/tmp/x.raucb` succeeded")
    assert not is_refusal(1, "No space left on device")
    # The real wording, and a refusal that came too late to count.
    assert is_refusal(
        1,
        " 10% Verifying signature\n 20% Verifying signature failed.\n"
        "LastError: signature verification failed: Verify error: self-signed certificate\n"
        "Installing `/tmp/wrong-ca.raucb` failed",
    )
    assert not is_refusal(
        1, " 43% Copying image to rootfs.0\nLastError: signature verification failed"
    )


def test_facts_round_trip_through_the_snapshot() -> None:
    status = parse_status(AFTER)
    facts = json.loads(json.dumps(to_facts(status)))
    assert from_facts(facts) == status


def test_parse_fails_loudly_on_shape_drift() -> None:
    with pytest.raises(ValueError):
        parse_status(json.dumps({"booted": "a"}))
    drifted = json.loads(BEFORE)
    del drifted["slots"][0]["rootfs.0"]["slot_status"]
    with pytest.raises(ValueError):
        parse_status(json.dumps(drifted))
