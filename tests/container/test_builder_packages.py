# SPDX-License-Identifier: Apache-2.0
"""Tests for the builder image's explicit package list and its lock.

A text scan of container/packages.txt and container/packages.lock.  It
checks that tar is listed and pinned, that the set of listed names
equals the set of pinned names with a version on every pin, and that no
name is pinned twice.
"""

from __future__ import annotations

from pathlib import Path
from typing import Final

CONTAINER: Final = Path(__file__).resolve().parents[2] / "container"


def _listed() -> set[str]:
    lines = (CONTAINER / "packages.txt").read_text().splitlines()
    return {
        ln.strip() for ln in lines if ln.strip() and not ln.lstrip().startswith("#")
    }


def _pin_lines() -> list[str]:
    lines = (CONTAINER / "packages.lock").read_text().splitlines()
    return [ln for ln in lines if ln.strip() and not ln.lstrip().startswith("#")]


def _pins() -> dict[str, str]:
    pins: dict[str, str] = {}
    for line in _pin_lines():
        name, _, version = line.partition("=")
        pins[name] = version
    return pins


def test_tar_is_listed_explicitly() -> None:
    assert "tar" in _listed()


def test_lock_pins_a_tar_version() -> None:
    assert _pins().get("tar"), "packages.lock has no pinned version for tar"


def test_listed_and_pinned_sets_are_equal_and_every_pin_has_a_version() -> None:
    listed = _listed()
    pins = _pins()
    assert set(pins) == listed, (
        f"listed but not pinned: {sorted(listed - set(pins))}; "
        f"pinned but not listed: {sorted(set(pins) - listed)}"
    )
    unversioned = sorted(name for name, version in pins.items() if not version)
    assert not unversioned, f"pins without a version: {unversioned}"


def test_no_name_is_pinned_twice() -> None:
    names = [line.partition("=")[0] for line in _pin_lines()]
    duplicated = sorted({name for name in names if names.count(name) > 1})
    assert not duplicated, f"names pinned more than once: {duplicated}"
