# SPDX-License-Identifier: Apache-2.0
"""The N7 RED map covers every verdict row, once, with a source line.

docs/validation/N7-WRITE-TEST.md records, for each row that the
verdict in .mise/lib/efivar_write_test.py prints, the GREEN result and
what the two RED runs do to it: R1 (edk2, AAVMF) and R2 (a U-Boot with
a writable run-time store, from an untracked overlay).  A row that
neither RED turns red must say "RED not shown".  So must a row that a
RED run turns red only by a refused write, and that set is pinned.
"""

from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[2]
LIB = ROOT / ".mise" / "lib"
DOC = ROOT / "docs" / "validation" / "N7-WRITE-TEST.md"
TAGS = ["U-PK", "U-KEK", "U-db", "W-db", "X-PK", "S-db", "S-KEK", "S-PK"]

# R2 is a U-Boot that answers run-time writes, but PRESEED still
# refuses every boot-time write (efi_variable.c:299-301), so R2 turns
# only Linux rows red.  This pins that finding.
R2_RED = {"A0.mount", "A1.remount", "A.post.PK"} | {f"A.{t}" for t in TAGS}

# No signed write took on any firmware, so these rows are red only by a
# refusal: they have not failed for the reason they test.
SIGNED = ["S-db", "S-KEK", "S-PK"]
REFUSED_ONLY = {f"A.{t}" for t in SIGNED} | {f"probe.{t}" for t in SIGNED}
REFUSED_ONLY |= {"probe.L1"}


def _load() -> ModuleType:
    sys.path.insert(0, str(LIB))
    spec = importlib.util.spec_from_file_location(
        "efivar_write_test", LIB / "efivar_write_test.py"
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["efivar_write_test"] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def table() -> dict[str, list[str]]:
    rows: dict[str, list[str]] = {}
    for line in DOC.read_text().splitlines():
        m = re.match(r"^\| `([\w.-]+)` \|(.*)\|$", line)
        if m:
            assert m.group(1) not in rows, f"{m.group(1)} twice"
            rows[m.group(1)] = [c.strip() for c in m.group(2).split("|")]
    return rows


def test_every_verdict_row_is_mapped(table: dict[str, list[str]]) -> None:
    wt = _load()
    assert sorted(table) == sorted(wt.row_names("u-boot", True))


def test_every_row_has_its_predictions_and_a_source(
    table: dict[str, list[str]],
) -> None:
    for row, cells in table.items():
        assert len(cells) == 4, row
        green, r1, r2, source = cells
        assert green and source, row
        for cell in (r1, r2):
            assert re.match(r"(red|pass|n/a)\b", cell), (row, cell)
        if not r1.startswith("red") and not r2.startswith("red"):
            assert "RED not shown" in source, row


def test_r2_turns_only_the_linux_rows_red(table: dict[str, list[str]]) -> None:
    red = {row for row, cells in table.items() if cells[2].startswith("red")}
    assert red == R2_RED


def test_r1_turns_every_probe_write_row_red(table: dict[str, list[str]]) -> None:
    for tag in TAGS:
        assert table[f"probe.{tag}"][1].startswith("red"), tag
    assert table["probe.L1"][1].startswith("red")


def test_rows_red_only_by_a_refused_write_say_red_not_shown(
    table: dict[str, list[str]],
) -> None:
    unshown_red = {
        row
        for row, (_green, r1, r2, source) in table.items()
        if "RED not shown" in source and "red" in (r1[:3], r2[:3])
    }
    assert unshown_red == REFUSED_ONLY
