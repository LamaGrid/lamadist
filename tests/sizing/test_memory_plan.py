# SPDX-License-Identifier: Apache-2.0
"""Tests for the build task's memory plan (_emit_memory_plan in _lib.sh).

Run through bash with BASH_COMPAT=51 as well, because the CI builder
image ships bash 5.1, which expands associative-array subscripts again
inside arithmetic (the gcc-cross-${TARGET_ARCH} keys once broke it).
"""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
TAIL_MIB = 230
HEADROOM_MIB = 1024


def _plan(cpus: int, mem_gb: int, compat: str | None = None, root: Path = ROOT) -> str:
    env = {**os.environ, "MISE_CONFIG_ROOT": str(root)}
    if compat:
        env["BASH_COMPAT"] = compat
    script = (
        "set -o errexit -o nounset -o pipefail; "
        f"source '{ROOT}/.mise/tasks/_lib.sh'; "
        f'ov=$(mktemp); _emit_memory_plan "$ov" {cpus} {mem_gb}; cat "$ov"'
    )
    done = subprocess.run(
        ["bash", "-c", script], env=env, capture_output=True, text=True, check=False
    )
    assert done.returncode == 0, done.stderr
    return done.stdout


def _value(overlay: str, key: str) -> str:
    match = re.search(rf"^\s*{re.escape(key)} = '([^']*)'", overlay, re.MULTILINE)
    assert match, key
    return match.group(1)


@pytest.mark.parametrize("compat", [None, "51"])
def test_plan_at_the_ci_envelope(compat: str | None) -> None:
    overlay = _plan(6, 10, compat)
    assert _value(overlay, "do_compile[number_threads]") == "2"
    assert _value(overlay, "PARALLEL_MAKE") == "-j 8"
    assert _value(overlay, "PARALLEL_MAKE:pn-gcc-cross-${TARGET_ARCH}") == "-j 3"
    assert _value(overlay, "PARALLEL_MAKE:pn-llvm-native") == "-j 2"
    assert "llvm-native:do_compile" in _value(overlay, "LAMADIST_HEAVY_TASKS")
    assert "rust-native:do_install" in _value(overlay, "LAMADIST_HEAVY_TASKS")


@pytest.mark.parametrize("mem_gb", [9, 10, 12, 16])
def test_slots_never_fall_as_cpus_rise(mem_gb: int) -> None:
    slots = [
        int(_value(_plan(cpus, mem_gb), "do_compile[number_threads]"))
        for cpus in (4, 6, 8, 12, 16)
    ]
    assert slots == sorted(slots)


def test_a_bad_table_fails_closed(tmp_path: Path) -> None:
    (tmp_path / ".mise" / "lib").mkdir(parents=True)
    (tmp_path / ".mise" / "lib" / "compile-peaks.tsv").write_text("a\tdo_compile\n")
    with pytest.raises(AssertionError):
        _plan(6, 10, root=tmp_path)
