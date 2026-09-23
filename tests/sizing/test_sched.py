# SPDX-License-Identifier: Apache-2.0
"""Unit tests for the lamadist-memory BitBake scheduler's hold-back rule."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
sys.path[0:0] = [
    str(_ROOT / "ext" / "bitbake" / "lib"),
    str(_ROOT / "meta-lamadist" / "lib"),
]

sched = pytest.importorskip("lamadist.sched", reason="needs the kas bitbake checkout")

LLVM = "virtual:native:/x/llvm_git.bb:do_compile"
CLANG = "virtual:native:/x/clang_git.bb:do_compile"
ZLIB = "/x/zlib_1.3.2.bb:do_compile"
HEAVY = frozenset({LLVM, CLANG})


def test_nothing_is_held_while_no_heavy_task_runs() -> None:
    assert sched.held_back({LLVM, CLANG, ZLIB}, {ZLIB}, HEAVY) == frozenset()


def test_the_first_heavy_task_may_start() -> None:
    assert sched.held_back({LLVM}, set(), HEAVY) == frozenset()


def test_a_second_heavy_task_waits_while_one_runs() -> None:
    assert sched.held_back({CLANG, ZLIB}, {LLVM}, HEAVY) == frozenset({CLANG})


def test_tail_tasks_are_never_held() -> None:
    assert ZLIB not in sched.held_back({CLANG, ZLIB}, {LLVM}, HEAVY)


def test_the_scheduler_is_selectable_by_name() -> None:
    assert sched.RunQueueSchedulerMemory.name == "lamadist-memory"


def test_a_failed_heavy_task_does_not_block_the_rest() -> None:
    assert sched.held_back({CLANG}, {LLVM}, HEAVY, failed={LLVM}) == frozenset()


def test_covered_heavy_tasks_are_skipped_not_held() -> None:
    assert sched.held_back({CLANG}, {LLVM}, HEAVY, covered={CLANG}) == frozenset()


def test_an_uncovered_heavy_task_is_still_held() -> None:
    assert sched.held_back({CLANG}, {LLVM}, HEAVY, covered={ZLIB}) == frozenset({CLANG})


def test_the_running_heavy_task_is_never_in_the_held_set() -> None:
    assert LLVM not in sched.held_back({LLVM, CLANG}, {LLVM}, HEAVY)
