# SPDX-License-Identifier: Apache-2.0
"""RAUC slot facts as pure predicates (ADR 0010 checks 12 and 13).

``rauc status --detailed --output-format=json`` is reduced to one
``Status`` value: which slot is booted, which is the boot primary, and
for every slot its install identity (checksum, size, install stamp and
count) and boot status.  The predicates over two such values are the
whole of Goal 2's dynamic half:

- ``moved``: an update carried the boot to the other slot;
- ``untouched``: the slot the boot came from was left exactly as it
  was, still good;
- ``unchanged``: nothing about any slot differs, which is what a
  refused install must leave behind;
- ``is_refusal``: a failed install whose stated reason is signature
  trust, and never a success.

No network and no target: the steps feed this module strings, and
the unit tests feed it fixtures.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from typing import Any, Final


@dataclass(frozen=True, slots=True)
class Slot:
    name: str
    bootname: str
    state: str
    boot_status: str
    sha256: str
    size: int
    installed_at: str
    installed_count: int


@dataclass(frozen=True, slots=True)
class Status:
    booted: str
    primary: str
    slots: dict[str, Slot]


def parse_status(raw: str) -> Status:
    """Reduce the detailed JSON; raise ``ValueError`` on any shape drift."""
    try:
        data = json.loads(raw)
        slots: dict[str, Slot] = {}
        for entry in data["slots"]:
            for name, slot in entry.items():
                detail = slot["slot_status"]
                slots[name] = Slot(
                    name=name,
                    bootname=slot.get("bootname") or "",
                    state=slot["state"],
                    boot_status=slot.get("boot_status") or "",
                    sha256=detail["checksum"]["sha256"],
                    size=int(detail["checksum"]["size"]),
                    installed_at=detail["installed"]["timestamp"],
                    installed_count=int(detail["installed"]["count"]),
                )
        return Status(booted=data["booted"], primary=data["boot_primary"], slots=slots)
    except (AttributeError, KeyError, TypeError, ValueError) as err:
        raise ValueError(f"unexpected rauc status shape: {err!r}") from err


def booted_slot(status: Status) -> Slot:
    for slot in status.slots.values():
        if slot.state == "booted":
            return slot
    raise ValueError(f"no booted slot in rauc status (booted={status.booted!r})")


def moved(baseline: Status, now: Status) -> bool:
    """The boot sits on a different slot than it did in the baseline."""
    return booted_slot(now).name != booted_slot(baseline).name


def untouched(baseline: Status, now: Status) -> bool:
    """The slot booted in the baseline is now inactive, good, and the
    same install: same checksum, size, install stamp, and count."""
    old = booted_slot(baseline)
    cur = now.slots.get(old.name)
    if cur is None:
        return False
    same_install = (cur.sha256, cur.size, cur.installed_at, cur.installed_count) == (
        old.sha256,
        old.size,
        old.installed_at,
        old.installed_count,
    )
    return cur.state == "inactive" and cur.boot_status == "good" and same_install


def unchanged(before: Status, after: Status) -> bool:
    """Nothing about the boot primary or any slot differs."""
    return before == after


_REFUSED: Final[re.Pattern[str]] = re.compile(
    r"(?i)\b(signature|certificate|verif(?:y|ication|ied))\b"
)
_ACCEPTED: Final[re.Pattern[str]] = re.compile(r"(?i)\bsucceeded\b")
_WROTE: Final[re.Pattern[str]] = re.compile(r"Updating slots|Copying image")


def is_refusal(rc: int, text: str) -> bool:
    """A failed install whose stated reason is signature trust, that
    never reached the slot-writing phase, and that did not succeed."""
    return (
        rc != 0
        and bool(_REFUSED.search(text))
        and not _ACCEPTED.search(text)
        and not _WROTE.search(text)
    )


def to_facts(status: Status) -> dict[str, Any]:
    """JSON-ready form for the run snapshot (the next run's baseline)."""
    return {
        "booted": status.booted,
        "primary": status.primary,
        "slots": {name: asdict(slot) for name, slot in sorted(status.slots.items())},
    }


def from_facts(facts: Mapping[str, Any]) -> Status:
    try:
        return Status(
            booted=facts["booted"],
            primary=facts["primary"],
            slots={name: Slot(**slot) for name, slot in facts["slots"].items()},
        )
    except (AttributeError, KeyError, TypeError) as err:
        raise ValueError(f"unexpected snapshot facts shape: {err!r}") from err
