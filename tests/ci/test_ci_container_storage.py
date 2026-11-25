# SPDX-License-Identifier: Apache-2.0
"""Golden-text test for the container storage step of the CI build job.

The test compares three things in .github/workflows/ci.yml with the
expected text kept in this file: the container image line of the
build-container job; the full text of its "Configure container storage"
step (the name and the whole run text, comments included); and the order
of that step and the "Build and push container image" step, storage
first.  It is a guard, not a proof: it is not a check of the rest of the
workflow, and an edit outside the three things may or may not make it
fail.

This test runs by hand.  No hook or workflow runs it.  An edit to the
image line, the storage step, or the build step's name line needs the
same edit here; so does renaming the job or its `container:` key.
"""

from __future__ import annotations

import textwrap
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Final

import pytest

ROOT: Final[Path] = Path(__file__).resolve().parents[2]
WORKFLOW: Final[Path] = ROOT / ".github" / "workflows" / "ci.yml"
JOB_HEADER: Final[str] = "  build-container:"
STEP_MARK: Final[str] = "      - name: "
STORAGE_STEP: Final[str] = "Configure container storage"
BUILD_STEP: Final[str] = "Build and push container image"

IMAGE_LINE: Final[str] = (
    "      image: quay.io/podman/stable:v6.2.0-immutable"
    "@sha256:e0da0a3aba6b332587c693dc206efa2dd2888dde286c280ef852cbad72c0e701"
)

# The step as it stands in the workflow, with its six leading spaces removed.
STORAGE_STEP_TEXT: Final[str] = """\
- name: Configure container storage
  run: |
    cat > /etc/containers/storage.conf << 'EOF'
    [storage]
    driver = "overlay"
    [storage.options.overlay]
    mount_program = ""
    EOF
    sed -i 's/^ *//' /etc/containers/storage.conf
    # The job image ships a storage drop-in that selects
    # fuse-overlayfs and a mount option only it accepts (fsync=0),
    # and a drop-in overrides storage.conf.  The job container has
    # no /dev/fuse, so a later drop-in clears the mount program
    # and the FUSE-only option.
    cat > /etc/containers/storage.rootful.conf.d/99-lamadist.conf << 'EOF'
    [storage.options.overlay]
    mount_program = ""
    mountopt = "nodev"
    EOF
    # Print the configured storage driver and graph options for the
    # log.  This is informational and checks nothing: || true keeps
    # a failure of podman info from failing the job.
    podman info --format '{{.Store.GraphDriverName}} {{.Store.GraphOptions}}' || true
"""


def _code(line: str) -> str:
    """The line less a trailing comment (a # after white space) and end white space."""
    for number, char in enumerate(line):
        if char == "#" and number and line[number - 1].isspace():
            return line[:number].rstrip()
    return line.rstrip()


def _index(lines: Sequence[str], wanted: str) -> int:
    """The index of the first line equal to `wanted` once `_code` has cleaned it.

    Raise AssertionError when there is none.
    """
    for number, line in enumerate(lines):
        if _code(line) == wanted:
            return number
    raise AssertionError(f"no line {wanted!r}")


def _job(text: str) -> str:
    """The build-container job: its header line up to the next job header.

    A job header is a two-space-indented line that ends in a colon, with no
    comment after it.  Without one, the job runs to the end of the text.
    """
    lines = text.splitlines(keepends=True)
    start = _index(lines, JOB_HEADER)
    rest = lines[start + 1 :]
    ends = [
        number
        for number, line in enumerate(rest)
        if line.startswith("  ") and line[2] not in " #" and line.endswith(":\n")
    ]
    return "".join(lines[start : start + 1 + (ends[0] if ends else len(rest))])


def _image_line(job: str) -> str:
    """The first image line after the job's `container:` key."""
    lines = job.splitlines()
    for line in lines[_index(lines, "    container:") + 1 :]:
        if line.startswith("      image:"):
            return line
    raise AssertionError("the container block has no image line")


def _steps(job: str) -> dict[str, str]:
    """Step text by name: the name line and the lines after it indented 8+ spaces.

    A step starts at a line `      - name: NAME` (six leading spaces).  Blank
    lines and comment lines indented under 8 spaces do not end the step: they
    count when a line indented 8+ spaces follows, and trailing ones do not.

    A second step whose line is `      - name: ` followed by the storage or the
    build step's name and nothing else makes this raise AssertionError.  A
    quoted name, a name with a comment on its line, and a name that is not the
    step's first key are not counted.
    """
    lines = job.splitlines(keepends=True)
    steps: dict[str, str] = {}
    seen: list[str] = []
    number = 0
    while number < len(lines):
        if not lines[number].startswith(STEP_MARK):
            number += 1
            continue
        end = number + 1
        scan = end
        while scan < len(lines):
            line = lines[scan]
            if line.strip() == "" or (
                line.lstrip().startswith("#") and not line.startswith(" " * 8)
            ):
                scan += 1
            elif line.startswith(" " * 8):
                scan += 1
                end = scan
            else:
                break
        name = lines[number].removeprefix(STEP_MARK).rstrip("\n")
        steps[name] = "".join(lines[number:end])
        seen.append(name)
        number = end
    repeated = [name for name in (STORAGE_STEP, BUILD_STEP) if seen.count(name) > 1]
    assert not repeated, f"repeated step names: {repeated}"
    return steps


def _same(what: str, actual: str, expected: str) -> None:
    """Assert equal text, and show the expected and the actual text on failure."""
    assert actual == expected, (
        f"{what} differs\n--- expected\n{expected}\n--- actual\n{actual}"
    )


def check_image(text: str) -> None:
    """The job's container image line equals the expected line."""
    _same("the image line", _image_line(_job(text)), IMAGE_LINE)


def check_step_text(text: str) -> None:
    """The storage step's text equals the expected text."""
    step = _steps(_job(text))[STORAGE_STEP]
    _same("the storage step", textwrap.dedent(step), STORAGE_STEP_TEXT)


def check_order(text: str) -> None:
    """The storage step's name line comes before the build step's name line."""
    names = list(_steps(_job(text)))
    assert names.index(STORAGE_STEP) < names.index(BUILD_STEP), names


@pytest.fixture(scope="module")
def workflow_text() -> str:
    """The text of the workflow file."""
    return WORKFLOW.read_text()


CHECKS: Final[tuple[Callable[[str], None], ...]] = (
    check_image,
    check_step_text,
    check_order,
)


@pytest.mark.parametrize("check", CHECKS)
def test_workflow_matches_the_golden_text(
    workflow_text: str, check: Callable[[str], None]
) -> None:
    check(workflow_text)


def test_a_one_character_change_fails(workflow_text: str) -> None:
    broken = workflow_text.replace('mountopt = "nodev"', 'mountopt = "nodex"', 1)
    assert broken != workflow_text
    with pytest.raises(AssertionError):
        check_step_text(broken)


def test_storage_step_moved_after_build_fails(workflow_text: str) -> None:
    steps = _steps(_job(workflow_text))
    storage, build = steps[STORAGE_STEP], steps[BUILD_STEP]
    broken = workflow_text.replace(storage, "", 1).replace(
        build, build + "\n" + storage, 1
    )
    assert broken != workflow_text
    with pytest.raises(AssertionError):
        check_order(broken)


def test_a_duplicated_storage_step_fails(workflow_text: str) -> None:
    job = _job(workflow_text)
    broken = workflow_text.replace(job, job + _steps(job)[STORAGE_STEP], 1)
    assert broken != workflow_text
    for check in (check_step_text, check_order):
        with pytest.raises(AssertionError):
            check(broken)


def _passes_every_check(text: str) -> None:
    for check in CHECKS:
        check(text)


def test_a_repeated_checkout_step_is_outside_the_test(workflow_text: str) -> None:
    job = _job(workflow_text)
    extra = f"{STEP_MARK}Checkout\n        uses: actions/checkout@v4\n\n"
    broken = workflow_text.replace(job, job + extra, 1)
    assert broken != workflow_text
    _passes_every_check(broken)


def test_a_comment_under_eight_spaces_above_the_next_step_is_outside_the_test(
    workflow_text: str,
) -> None:
    job = _job(workflow_text)
    marker = f"{STEP_MARK}Install mise\n"
    assert marker in job
    commented = job.replace(marker, f"      # Tools for the build task.\n{marker}", 1)
    broken = workflow_text.replace(job, commented, 1)
    assert broken != workflow_text
    _passes_every_check(broken)


def _storage_step_last_line() -> str:
    return "      " + STORAGE_STEP_TEXT.splitlines()[-1] + "\n"


def test_an_unnamed_step_after_the_storage_step_is_outside_the_test(
    workflow_text: str,
) -> None:
    last = _storage_step_last_line()
    broken = workflow_text.replace(
        last, last + "      - uses: actions/checkout@v4\n", 1
    )
    assert broken != workflow_text
    _passes_every_check(broken)


@pytest.mark.parametrize(
    "tail",
    [
        "          rm -f /etc/containers/storage.rootful.conf.d/99-lamadist.conf",
        "        if: false",
        "        shell: bash",
    ],
)
def test_text_after_a_blank_line_in_the_storage_step_fails(
    workflow_text: str, tail: str
) -> None:
    last = _storage_step_last_line()
    broken = workflow_text.replace(last, f"{last}\n{tail}\n", 1)
    assert broken != workflow_text
    with pytest.raises(AssertionError):
        check_step_text(broken)


@pytest.mark.parametrize(
    "tail",
    [
        ("      # note", "        if: false"),
        ("# note", "        if: false"),
        ("      # note", "        continue-on-error: true"),
        ("          # note",),
    ],
)
def test_text_after_a_comment_line_in_the_storage_step_fails(
    workflow_text: str, tail: tuple[str, ...]
) -> None:
    last = _storage_step_last_line()
    broken = workflow_text.replace(last, last + "".join(f"{x}\n" for x in tail), 1)
    assert broken != workflow_text
    with pytest.raises(AssertionError):
        check_step_text(broken)


def test_a_comment_on_the_job_or_container_line_is_outside_the_test(
    workflow_text: str,
) -> None:
    job = _job(workflow_text)
    commented = job.replace(JOB_HEADER + "\n", JOB_HEADER + "  # builds it\n", 1)
    commented = commented.replace("    container:\n", "    container:  # image\n", 1)
    broken = workflow_text.replace(job, commented, 1)
    assert "# builds it" in broken
    assert "# image" in broken
    _passes_every_check(broken)
