# SPDX-License-Identifier: Apache-2.0
"""Regenerate the per-recipe build memory table from BitBake buildstats.

Every buildstats task record carries ``Child rusage ru_maxrss``: the
peak resident set of the largest single process the task spawned.  For
a compile that is the biggest compiler (or linker) process, which is
what one ``make -j`` slot costs at worst.  The build task's memory plan
(``_emit_memory_plan`` in ``.mise/tasks/_lib.sh``) reads the table this
script prints to cap ``-j`` for every recipe whose per-job peak exceeds
the long-tail budget, and to run the heaviest tasks one at a time.

Tasks harvested per recipe:

- ``do_compile`` for every recipe;
- ``do_compile_ptest_base``, the ptest build (ptest is in oe-core's
  default DISTRO_FEATURES);
- ``do_install`` only for recipes that build in do_install
  (``BUILDS_IN_INSTALL``: rust bootstraps the whole compiler there).

Cross-compiler recipes are keyed by ``${TARGET_ARCH}`` so one table
serves every machine (gcc-cross-x86_64 and gcc-cross-aarch64 become
gcc-cross-${TARGET_ARCH}, taking the larger peak); BitBake expands the
name when the plan's ``:pn-`` overrides are applied.

Usage::

    python3 .mise/lib/compile_peaks.py .cache/buildstats > .mise/lib/compile-peaks.tsv

The table keeps the MAX over all runs, so a recipe only gets cheaper
when its peak is re-measured from scratch (delete old runs first).
"""

from __future__ import annotations

import argparse
import datetime
import re
import sys
from pathlib import Path
from typing import Final

# Only rows above the long-tail per-job budget need an entry.
DEFAULT_MIN_MIB: Final[int] = 230

COMPILE_TASKS: Final[tuple[str, ...]] = ("do_compile", "do_compile_ptest_base")
BUILDS_IN_INSTALL: Final[frozenset[str]] = frozenset(
    {"rust-native", "rust", "nativesdk-rust"}
)

# Rows whose peak is one serial process (a final link, a single rustc,
# BTF generation, a ptest build with PTEST_PARALLEL_MAKE empty), not a
# function of -j.  Capping -j on them only slows the build; the heavy
# ones still run one at a time.
SERIAL_PEAK: Final[frozenset[str]] = frozenset(
    {
        "linux-yocto:do_compile",
        "cargo-native:do_compile",
        "libstd-rs:do_compile",
        "rpm-sequoia:do_compile",
        "rpm-sequoia-native:do_compile",
        "elfutils:do_compile_ptest_base",
    }
)

_RECIPE_DIR: Final[re.Pattern[str]] = re.compile(
    r"(?P<pn>.+)-(?P<pv>[^-]+)-(?P<pr>r\d+)$"
)
_CROSS: Final[re.Pattern[str]] = re.compile(r"-cross-[A-Za-z0-9_]+$")


def table_name(pn: str) -> str:
    """Key cross recipes by ${TARGET_ARCH} so one row covers every machine."""
    return _CROSS.sub("-cross-${TARGET_ARCH}", pn)


def _peak_mib(path: Path) -> int | None:
    for line in path.read_text(errors="replace").splitlines():
        key, sep, value = line.partition(":")
        if sep and key.strip() == "Child rusage ru_maxrss":
            try:
                return int(value.strip()) // 1024
            except ValueError:
                return None
    return None


def peaks(buildstats: Path) -> tuple[dict[tuple[str, str], int], int]:
    """Return {(recipe, task): peak MiB} over every run, and the run count."""
    result: dict[tuple[str, str], int] = {}
    runs = 0
    for run in sorted(p for p in buildstats.iterdir() if p.is_dir()):
        runs += 1
        for recipe_dir in run.iterdir():
            match = _RECIPE_DIR.match(recipe_dir.name)
            if not match:
                continue
            pn = match.group("pn")
            tasks = COMPILE_TASKS + (("do_install",) if pn in BUILDS_IN_INSTALL else ())
            for task in tasks:
                path = recipe_dir / task
                mib = _peak_mib(path) if path.is_file() else None
                if mib is not None:
                    key = (table_name(pn), task)
                    result[key] = max(result.get(key, 0), mib)
    return result, runs


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("buildstats", type=Path, help="BUILDSTATS_BASE directory")
    parser.add_argument("--min-mib", type=int, default=DEFAULT_MIN_MIB)
    args = parser.parse_args(argv)
    if not args.buildstats.is_dir():
        parser.error(f"{args.buildstats} is not a directory")
    table, runs = peaks(args.buildstats)
    today = datetime.datetime.now(datetime.UTC).date().isoformat()
    print("# Per-recipe build memory: peak RSS of the largest single process")
    print(f"# (MiB), max over {runs} buildstats runs, regenerated {today} by")
    print("# .mise/lib/compile_peaks.py.  serial=1: the peak is one process, so")
    print("# -j is left alone; heavy rows still run one at a time.")
    print("# recipe\ttask\tpeak_mib\tserial")
    rows = sorted(table.items(), key=lambda item: (-item[1], item[0]))
    for (pn, task), mib in rows:
        if mib >= args.min_mib:
            print(f"{pn}\t{task}\t{mib}\t{int(f'{pn}:{task}' in SERIAL_PEAK)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
