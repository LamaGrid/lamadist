# SPDX-License-Identifier: Apache-2.0
"""A BitBake scheduler that runs at most one memory-heavy task at a time.

BitBake bounds tasks (BB_NUMBER_THREADS) and tasks of one name
(``do_compile[number_threads]``), but nothing bounds how much memory the
running tasks hold together.  The build task's memory plan (``.mise/
tasks/_lib.sh``, ``_emit_memory_plan``) sizes compile concurrency for a
tight envelope and names the handful of tasks whose single compiler or
linker process needs a gigabyte or more in ``LAMADIST_HEAVY_TASKS``
(``<pn>:<task>`` pairs).  Those tasks are budgeted one at a time.

A shared ``[lockfiles]`` entry already serialises them, but a task
waiting on that lock has been started: it holds a BitBake slot and, for
``do_compile``, one of the few compile slots, while doing nothing.
This scheduler keeps a second heavy task buildable-but-unstarted while
one runs, so the slot goes to other work.  The lock stays as a backstop
for any path that bypasses the scheduler.

Selected by the memory plan with::

    BB_SCHEDULERS = "lamadist.sched.RunQueueSchedulerMemory"
    BB_SCHEDULER = "lamadist-memory"
"""

from __future__ import annotations

from collections.abc import Iterable
from collections.abc import Set as AbstractSet

import bb.runqueue  # pyright: ignore[reportMissingImports]


def held_back(
    buildable: AbstractSet[str],
    running: Iterable[str],
    heavy: AbstractSet[str],
    covered: AbstractSet[str] = frozenset(),
    failed: AbstractSet[str] = frozenset(),
) -> frozenset[str]:
    """Return the buildable heavy tasks to hold while a heavy task runs.

    Empty when no heavy task is running, so the first heavy task that
    becomes buildable always starts.  A failed task still sits in
    BitBake's running set (``bitbake -k``), so it does not count as
    running.  Covered tasks are restored from sstate and skipped at once
    without running anything, so they are never held; neither are tasks
    already running.
    """
    running = set(running)
    if not any(t in running and t not in failed for t in heavy):
        return frozenset()
    return frozenset((buildable & heavy) - covered - running)


class RunQueueSchedulerMemory(bb.runqueue.RunQueueSchedulerSpeed):
    """The speed scheduler, starting at most one heavy task at a time."""

    name = "lamadist-memory"

    def __init__(self, runqueue: object, rqdata: object) -> None:
        super().__init__(runqueue, rqdata)
        wanted = set((self.rq.cfgData.getVar("LAMADIST_HEAVY_TASKS") or "").split())
        self.heavy: frozenset[str] = frozenset()
        if not wanted:
            return
        heavy = set()
        for tid in self.rqdata.runtaskentries:
            mc, _fn, taskname, taskfn = bb.runqueue.split_tid_mcfn(tid)
            pn = self.rqdata.dataCaches[mc].pkg_fn[taskfn]
            if f"{pn}:{taskname}" in wanted:
                heavy.add(tid)
        self.heavy = frozenset(heavy)
        bb.note(
            f"lamadist-memory scheduler: {len(self.heavy)} heavy task(s) run one at a time"
        )

    def next_buildable_task(self) -> str | None:
        running = self.rq.runq_running.difference(self.rq.runq_complete)
        held = held_back(
            self.buildable,
            running,
            self.heavy,
            covered=self.rq.tasks_covered,
            failed=frozenset(self.rq.failed_tids),
        )
        if not held:
            return super().next_buildable_task()
        # The parent picks from self.buildable, so hide the held tasks for
        # this one decision and put them back whatever it returns.
        self.buildable.difference_update(held)
        try:
            return super().next_buildable_task()
        finally:
            self.buildable.update(held)
