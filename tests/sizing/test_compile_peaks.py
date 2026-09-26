# SPDX-License-Identifier: Apache-2.0
"""Unit tests for the build memory table generator (compile_peaks.py)."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / ".mise" / "lib"))

import compile_peaks


def _task(run: Path, recipe: str, task: str, kib: int) -> None:
    path = run / recipe / task
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"Event: TaskSucceeded\nElapsed time: 1.0 seconds\nChild rusage ru_maxrss: {kib}\n"
    )


def test_table_name_keys_cross_recipes_by_target_arch() -> None:
    assert compile_peaks.table_name("gcc-cross-x86_64") == "gcc-cross-${TARGET_ARCH}"
    assert (
        compile_peaks.table_name("binutils-cross-aarch64")
        == "binutils-cross-${TARGET_ARCH}"
    )
    assert compile_peaks.table_name("gcc") == "gcc"
    assert compile_peaks.table_name("clang-native") == "clang-native"


def test_peaks_takes_the_max_over_runs_and_architectures(tmp_path: Path) -> None:
    run1, run2 = tmp_path / "run1", tmp_path / "run2"
    _task(run1, "llvm-native-22.1.8-r0", "do_compile", 2000 * 1024)
    _task(run2, "llvm-native-22.1.8-r0", "do_compile", 2336 * 1024)
    _task(run1, "gcc-cross-x86_64-15.2.0-r0", "do_compile", 1455 * 1024)
    _task(run2, "gcc-cross-aarch64-15.2.0-r0", "do_compile", 1500 * 1024)
    table, runs = compile_peaks.peaks(tmp_path)
    assert runs == 2
    assert table[("llvm-native", "do_compile")] == 2336
    assert table[("gcc-cross-${TARGET_ARCH}", "do_compile")] == 1500


def test_peaks_reads_ptest_and_install_only_where_the_build_happens(
    tmp_path: Path,
) -> None:
    run = tmp_path / "run"
    _task(run, "curl-8.17.0-r0", "do_compile_ptest_base", 1871 * 1024)
    _task(run, "rust-native-1.94.1-r0", "do_install", 1810 * 1024)
    _task(run, "busybox-1.37.0-r0", "do_install", 900 * 1024)
    table, _ = compile_peaks.peaks(tmp_path)
    assert table[("curl", "do_compile_ptest_base")] == 1871
    assert table[("rust-native", "do_install")] == 1810
    assert ("busybox", "do_install") not in table


def test_main_prints_rows_over_the_threshold_with_serial_flags(
    tmp_path: Path, capsys: object
) -> None:
    run = tmp_path / "run"
    _task(run, "linux-yocto-6.18.35+git-r0", "do_compile", 3723 * 1024)
    _task(run, "clang-native-22.1.8-r0", "do_compile", 2004 * 1024)
    _task(run, "zlib-1.3.2-r0", "do_compile", 90 * 1024)
    assert compile_peaks.main([str(tmp_path)]) == 0
    out = capsys.readouterr().out  # pyright: ignore[reportAttributeAccessIssue]
    rows = [line.split("\t") for line in out.splitlines() if not line.startswith("#")]
    assert rows == [
        ["linux-yocto", "do_compile", "3723", "1"],
        ["clang-native", "do_compile", "2004", "0"],
    ]
