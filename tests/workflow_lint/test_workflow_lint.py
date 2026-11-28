# SPDX-License-Identifier: Apache-2.0
"""Tests for the workflow trigger lint (workflow_lint.py).

The lint keeps secrets away from code an outside contributor controls:
only push (main and tags), pull_request, and workflow_dispatch may
trigger a workflow, and a job that names the publishing environment
must stay out of pull_request runs.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = Path(__file__).resolve().parent / "fixtures"
sys.path.insert(0, str(ROOT / ".mise" / "lib"))

pytest.importorskip("yaml", reason="needs PyYAML (tests/validate/requirements.txt)")

import workflow_lint


def test_a_workflow_with_only_allowed_triggers_passes() -> None:
    assert workflow_lint.lint_file(FIXTURES / "good.yml") == []


@pytest.mark.parametrize(
    ("fixture", "expected"),
    [
        ("bad-workflow-run.yml", "workflow_run"),
        ("bad-pull-request-target.yml", "pull_request_target"),
        ("bad-push-branch.yml", "release/**"),
        ("bad-publish-on-pr.yml", "yocto-publish"),
        ("bad-publish-expression.yml", "yocto-publish"),
    ],
)
def test_each_negative_fixture_fails_for_its_own_reason(
    fixture: str, expected: str
) -> None:
    problems = workflow_lint.lint_file(FIXTURES / fixture)
    assert problems, fixture
    assert any(expected in p for p in problems), problems


@pytest.mark.parametrize(
    "workflow",
    sorted((ROOT / ".github" / "workflows").glob("*.yml")),
    ids=lambda p: p.name,
)
def test_the_repository_workflows_pass(workflow: Path) -> None:
    assert workflow_lint.lint_file(workflow) == []


def test_the_command_line_exits_nonzero_on_a_bad_workflow(
    capsys: pytest.CaptureFixture[str],
) -> None:
    rc = workflow_lint.main(
        [str(FIXTURES / "good.yml"), str(FIXTURES / "bad-workflow-run.yml")]
    )
    assert rc == 1
    assert "bad-workflow-run.yml" in capsys.readouterr().err
