# SPDX-License-Identifier: Apache-2.0
"""Lint GitHub workflows so secrets never reach code a contributor controls.

The repository is public and pull requests build on the project's own
runners.  The write credentials for the build caches live only in the
``yocto-publish`` environment, whose branch policy admits ``main``.  This
lint closes the ways around that policy:

- Only ``push`` (``main`` and tags), ``pull_request``, and
  ``workflow_dispatch`` may trigger a workflow.  ``pull_request_target``,
  ``workflow_run``, ``issue_comment`` and the like run with secrets for
  code an outside contributor controls.
- A job that names ``yocto-publish`` in a workflow reachable from
  ``pull_request`` must choose it by an expression that is empty unless
  the event is a ``push``.

Usage: workflow_lint.py WORKFLOW.yml...  (exit 1 on any problem)
"""

from __future__ import annotations

import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Final

import yaml

ALLOWED_TRIGGERS: Final = frozenset({"push", "pull_request", "workflow_dispatch"})
PUBLISH_ENVIRONMENT: Final = "yocto-publish"
PUSH_GUARD: Final = "github.event_name == 'push'"


def _triggers(doc: Mapping[object, object]) -> Mapping[str, object]:
    # YAML 1.1 reads a bare `on` key as the boolean True.
    raw = doc.get("on", doc.get(True))
    if isinstance(raw, str):
        return {raw: None}
    if isinstance(raw, list):
        return {str(t): None for t in raw}
    if isinstance(raw, Mapping):
        return {str(k): v for k, v in raw.items()}
    return {}


def _check_triggers(triggers: Mapping[str, object]) -> list[str]:
    problems = [
        f"trigger '{name}' is not allowed (only {', '.join(sorted(ALLOWED_TRIGGERS))})"
        for name in triggers
        if name not in ALLOWED_TRIGGERS
    ]
    push = triggers.get("push")
    if isinstance(push, Mapping):
        branches = push.get("branches") or []
        problems += [
            f"push runs on branch '{b}'; only main may push-trigger"
            for b in branches
            if b != "main"
        ]
        if "branches-ignore" in push:
            problems.append("push uses branches-ignore; list main explicitly")
    elif "push" in triggers:
        problems.append("push has no branch filter; list main explicitly")
    return problems


def _environment_name(job: Mapping[str, object]) -> str:
    env = job.get("environment")
    if isinstance(env, Mapping):
        env = env.get("name")
    return str(env) if env is not None else ""


def _check_jobs(jobs: Mapping[str, object], reachable_from_pr: bool) -> list[str]:
    problems: list[str] = []
    for job_id, job in jobs.items():
        if not isinstance(job, Mapping):
            continue
        name = _environment_name(job)
        if PUBLISH_ENVIRONMENT not in name or not reachable_from_pr:
            continue
        if "${{" not in name:
            problems.append(
                f"job '{job_id}' names '{PUBLISH_ENVIRONMENT}' outright and the workflow"
                " runs on pull_request"
            )
        elif PUSH_GUARD not in " ".join(name.split()):
            problems.append(
                f"job '{job_id}' selects '{PUBLISH_ENVIRONMENT}' without requiring"
                f" {PUSH_GUARD}"
            )
    return problems


def lint_file(path: Path) -> list[str]:
    """Return the problems in one workflow file (empty when it passes)."""
    doc = yaml.safe_load(path.read_text())
    if not isinstance(doc, Mapping):
        return [f"{path}: not a workflow mapping"]
    triggers = _triggers(doc)
    jobs = doc.get("jobs")
    problems = _check_triggers(triggers)
    if isinstance(jobs, Mapping):
        problems += _check_jobs(jobs, "pull_request" in triggers)
    return [f"{path}: {p}" for p in problems]


def main(argv: Sequence[str]) -> int:
    problems = [p for arg in argv for p in lint_file(Path(arg))]
    for problem in problems:
        print(problem, file=sys.stderr)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
