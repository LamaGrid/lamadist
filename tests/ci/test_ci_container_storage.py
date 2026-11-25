# SPDX-License-Identifier: Apache-2.0
"""Tests for the container storage setup of the CI build-container job.

The job image ships a storage drop-in that selects a FUSE mount program
and FUSE-only mount options, and the job container has no /dev/fuse.
The job must pin the image by digest so the drop-in cannot change
underneath it, and must override both settings with a later drop-in
instead of deleting the image's files.  The job runs as root, so the
rootful drop-in directory is the one the container tools read.

The tests scan the workflow text (no YAML parser), parse every drop-in
the step writes with tomllib, and prove each check by running it
against mutated copies of the workflow that it must reject.
"""

from __future__ import annotations

import re
import textwrap
import tomllib
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "ci.yml"
JOB = "build-container"
STEP = "Configure container storage"
IMAGE_DROP_IN = "20-image_build.conf"
ROOTFUL_DIR = "/etc/containers/storage.rootful.conf.d/"
STORAGE_CONF = "/etc/containers/storage.conf"
FUSE_MOUNT_PROGRAM = "/usr/bin/fuse-overlayfs"
GRAPH_OPTIONS_LINE = (
    "podman info --format '{{.Store.GraphDriverName}} {{.Store.GraphOptions}}'"
)
RUN_INDENT = " " * 10
DROP_IN = {
    "storage": {"options": {"overlay": {"mount_program": "", "mountopt": "nodev"}}}
}

HEREDOC_START = re.compile(r"cat > (/etc/containers/\S+) <<'(\w+)'")
SED_STRIP = re.compile(r"sed -i 's/\^ \*//' /etc/containers/\S+")
IMAGE_KEY = re.compile(r"^\s+image:\s*(\S+)(?:\s+#.*)?$")
DIGEST_PIN = re.compile(r"[^@\s]+@sha256:[0-9a-f]{64}")


@dataclass(frozen=True)
class Write:
    """One heredoc write: the target path and the text it writes."""

    path: str
    body: str


def _indent(line: str) -> int:
    return len(line) - len(line.lstrip(" "))


def _block(lines: list[str], start: int) -> list[str]:
    """Lines nested under the key at lines[start], up to the next sibling."""
    indent = _indent(lines[start])
    block: list[str] = []
    for line in lines[start + 1 :]:
        if line.strip() and _indent(line) <= indent:
            break
        block.append(line)
    return block


def _job_lines(text: str) -> list[str]:
    lines = text.splitlines()
    for number, line in enumerate(lines):
        if line == f"  {JOB}:":
            return _block(lines, number)
    raise AssertionError(f"no job named {JOB!r}")


def _script(text: str) -> list[str]:
    """The run text of the storage step, unindented, one entry per line."""
    job = _job_lines(text)
    for number, line in enumerate(job):
        if re.fullmatch(rf"\s+- name: {STEP}", line):
            step = _block(job, number)
            break
    else:
        raise AssertionError(f"no step named {STEP!r}")
    for number, line in enumerate(step):
        if re.fullmatch(r"\s+run: \|", line):
            body = textwrap.dedent("\n".join(_block(step, number)))
            return body.splitlines()
    raise AssertionError(f"step {STEP!r} has no run block")


def _split(script: list[str]) -> tuple[list[Write], list[str]]:
    """Split the run text into heredoc writes and the other code lines.

    Comment lines and blank lines are dropped from the code lines.  A
    heredoc keeps its start line among the code lines, so the order of
    writes and commands is preserved; its body and terminator are
    consumed with the write.
    """
    writes: list[Write] = []
    code: list[str] = []
    lines = iter(script)
    for line in lines:
        start = HEREDOC_START.fullmatch(line)
        if start:
            body: list[str] = []
            for body_line in lines:
                if body_line == start.group(2):
                    break
                body.append(body_line)
            else:
                raise AssertionError(f"heredoc {start.group(2)!r} is not closed")
            writes.append(Write(start.group(1), "\n".join(body) + "\n"))
            code.append(line)
        elif line.strip() and not line.lstrip().startswith("#"):
            code.append(line)
    return writes, code


def _drop_ins(text: str) -> list[tuple[str, dict[str, Any]]]:
    """Every heredoc write except the storage.conf write, parsed.

    Any other file the step writes is a drop-in or an image file that
    the step must not touch, so it is held to the drop-in rules.
    """
    writes, _ = _split(_script(text))
    return [
        (write.path, tomllib.loads(write.body))
        for write in writes
        if write.path != STORAGE_CONF
    ]


def check_image_is_pinned_by_digest(text: str) -> None:
    for line in _job_lines(text):
        match = IMAGE_KEY.match(line)
        if match:
            assert DIGEST_PIN.fullmatch(match.group(1)), line
            return
    raise AssertionError("the job has no container image line")


def check_every_drop_in_is_in_the_rootful_directory(text: str) -> None:
    drop_ins = _drop_ins(text)
    assert drop_ins, "the step writes no drop-in"
    for path, _ in drop_ins:
        assert path.startswith(ROOTFUL_DIR), path


def check_every_drop_in_sorts_after_the_image_drop_in(text: str) -> None:
    for path, _ in _drop_ins(text):
        name = path.rsplit("/", 1)[1]
        assert name.endswith(".conf"), path
        assert name > IMAGE_DROP_IN, path


def check_every_drop_in_clears_the_mount_program_and_fuse_options(text: str) -> None:
    for path, parsed in _drop_ins(text):
        assert parsed == DROP_IN, (path, parsed)


def check_step_prints_the_configured_graph_options(text: str) -> None:
    writes, code = _split(_script(text))
    assert writes, "the step writes nothing"
    assert code[-1] == GRAPH_OPTIONS_LINE, "print after the last write"


def check_step_runs_only_allowed_commands(text: str) -> None:
    _, code = _split(_script(text))
    for line in code:
        allowed = (
            line == GRAPH_OPTIONS_LINE
            or HEREDOC_START.fullmatch(line)
            or SED_STRIP.fullmatch(line)
        )
        assert allowed, f"command outside the allowlist: {line!r}"


CHECKS: list[Callable[[str], None]] = [
    check_image_is_pinned_by_digest,
    check_every_drop_in_is_in_the_rootful_directory,
    check_every_drop_in_sorts_after_the_image_drop_in,
    check_every_drop_in_clears_the_mount_program_and_fuse_options,
    check_step_prints_the_configured_graph_options,
    check_step_runs_only_allowed_commands,
]


@pytest.fixture(scope="module")
def workflow_text() -> str:
    return WORKFLOW.read_text()


@pytest.mark.parametrize(
    "check", [pytest.param(check, id=check.__name__) for check in CHECKS]
)
def test_workflow_passes_the_check(
    workflow_text: str, check: Callable[[str], None]
) -> None:
    check(workflow_text)


def _sub(old: str, new: str, after: str = "") -> Callable[[str], str]:
    """Replace the first occurrence of old that follows the text after."""

    def mutate(text: str) -> str:
        start = text.index(after) if after else 0
        position = text.find(old, start)
        assert position >= 0, f"mutation target not found: {old!r}"
        return text[:position] + new + text[position + len(old) :]

    return mutate


def _in_drop_in(old: str, new: str) -> Callable[[str], str]:
    return _sub(old, new, after="99-lamadist.conf <<")


def _yaml_lines(script: str) -> str:
    """Indent script lines the way the run block indents them in ci.yml."""
    return "".join(f"{RUN_INDENT}{line}" for line in script.splitlines(keepends=True))


def _lines_in_drop_in(old: str, new: str) -> Callable[[str], str]:
    """Replace whole script lines of the drop-in (old and new end in a newline)."""
    return _in_drop_in(_yaml_lines(old), _yaml_lines(new))


def _after_drop_in_table(extra: str) -> Callable[[str], str]:
    """Insert script lines after the drop-in's mountopt line."""
    mountopt = 'mountopt = "nodev"\n'
    return _lines_in_drop_in(mountopt, mountopt + extra)


def _before_graph_options(extra: str) -> Callable[[str], str]:
    """Insert script lines before the graph-options line."""
    line = f"{GRAPH_OPTIONS_LINE}\n"
    return _sub(_yaml_lines(line), _yaml_lines(f"{extra}\n{line}"))


def _after_graph_options(extra: str) -> Callable[[str], str]:
    """Insert script lines after the graph-options line."""
    line = f"{GRAPH_OPTIONS_LINE}\n"
    return _sub(_yaml_lines(line), _yaml_lines(f"{line}{extra}\n"))


MUTATIONS: list[tuple[str, Callable[[str], str], Callable[[str], None]]] = [
    (
        "image tag instead of digest",
        lambda text: re.sub(
            r"(image: \S+?)@sha256:[0-9a-f]{64}", r"\1:latest", text, count=1
        ),
        check_image_is_pinned_by_digest,
    ),
    (
        "drop-in only in the rootless directory",
        _sub(ROOTFUL_DIR + "99", "/etc/containers/storage.rootless.conf.d/99"),
        check_every_drop_in_is_in_the_rootful_directory,
    ),
    (
        "drop-in in the generic directory selects the FUSE mount program",
        _before_graph_options(
            "mkdir -p /etc/containers/storage.conf.d\n"
            "cat > /etc/containers/storage.conf.d/99-zz.conf <<'EOF'\n"
            "[storage.options.overlay]\n"
            f'mount_program = "{FUSE_MOUNT_PROGRAM}"\n'
            "EOF"
        ),
        check_every_drop_in_is_in_the_rootful_directory,
    ),
    (
        "image file emptied with a heredoc",
        _before_graph_options("cat > /etc/containers/containers.conf <<'EOF'\nEOF"),
        check_every_drop_in_is_in_the_rootful_directory,
    ),
    (
        "drop-in sorts before the image drop-in",
        _sub("99-lamadist.conf", "10-lamadist.conf"),
        check_every_drop_in_sorts_after_the_image_drop_in,
    ),
    (
        "mount program left to the image",
        _in_drop_in('mount_program = ""', f'mount_program = "{FUSE_MOUNT_PROGRAM}"'),
        check_every_drop_in_clears_the_mount_program_and_fuse_options,
    ),
    (
        "mountopt line missing",
        _lines_in_drop_in('mountopt = "nodev"\n', ""),
        check_every_drop_in_clears_the_mount_program_and_fuse_options,
    ),
    (
        "mountopt keeps the FUSE-only option",
        _in_drop_in('mountopt = "nodev"', 'mountopt = "nodev,fsync=0"'),
        check_every_drop_in_clears_the_mount_program_and_fuse_options,
    ),
    (
        "the legacy mount_program key selects the FUSE mount program",
        _after_drop_in_table(
            f'[storage.options]\nmount_program = "{FUSE_MOUNT_PROGRAM}"\n'
        ),
        check_every_drop_in_clears_the_mount_program_and_fuse_options,
    ),
    (
        "a second rootful drop-in selects the FUSE mount program",
        _before_graph_options(
            f"cat > {ROOTFUL_DIR}99-zz.conf <<'EOF'\n"
            "[storage.options.overlay]\n"
            f'mount_program = "{FUSE_MOUNT_PROGRAM}"\n'
            "EOF"
        ),
        check_every_drop_in_clears_the_mount_program_and_fuse_options,
    ),
    (
        "graph-options line commented out",
        _sub(
            _yaml_lines(f"{GRAPH_OPTIONS_LINE}\n"),
            _yaml_lines(f"# {GRAPH_OPTIONS_LINE}\n"),
        ),
        check_step_prints_the_configured_graph_options,
    ),
    (
        "graph-options line printed before the last write",
        _after_graph_options(
            "cat > /etc/containers/storage.rootful.conf.d/98-extra.conf <<'EOF'\n"
            "[storage.options.overlay]\n"
            'mount_program = ""\n'
            'mountopt = "nodev"\n'
            "EOF"
        ),
        check_step_prints_the_configured_graph_options,
    ),
    (
        "graph status added to the printed line",
        _sub(
            "{{.Store.GraphOptions}}'",
            "{{.Store.GraphOptions}} {{.Store.GraphStatus}}'",
        ),
        check_step_prints_the_configured_graph_options,
    ),
    (
        "image drop-in deleted with find",
        _before_graph_options("find /etc/containers -name '20-*' -delete"),
        check_step_runs_only_allowed_commands,
    ),
    (
        "extra command chained on the graph-options line",
        _sub(GRAPH_OPTIONS_LINE, f"{GRAPH_OPTIONS_LINE} && rm -rf /var/lib/containers"),
        check_step_runs_only_allowed_commands,
    ),
]


@pytest.mark.parametrize(
    ("mutate", "check"),
    [pytest.param(mutate, check, id=name) for name, mutate, check in MUTATIONS],
)
def test_check_rejects_a_mutated_workflow(
    workflow_text: str, mutate: Callable[[str], str], check: Callable[[str], None]
) -> None:
    broken = mutate(workflow_text)
    assert broken != workflow_text
    with pytest.raises(AssertionError):
        check(broken)


def test_every_check_has_a_mutation_that_it_rejects() -> None:
    assert {check for _, _, check in MUTATIONS} == set(CHECKS)
