# SPDX-License-Identifier: Apache-2.0
"""Golden test for the CI job that pushes the builder image.

The test parses .github/workflows/ci.yml with PyYAML, a YAML 1.1 parser.
GitHub's own parser may read some forms differently, and the test cannot
check that.  It fails when the file holds U+0085, U+2028, or U+2029, which
YAML 1.1 reads as line breaks and YAML 1.2 reads as text, when it holds
more than one YAML document or a mapping with a duplicate key, and when
the file has no `build-container` job whose steps are a list of mappings.
It then compares three things with the expected values kept in this file:
the names of the job's steps, in order (a step with no name is listed by
its sorted key names); the checkout step, as a whole mapping; and the
push step, as a whole mapping.  Comments and key order are not compared.

It does not compare the storage step, the job's other keys, or the rest
of the workflow.  It is a guard for the three things it compares.

The test needs PyYAML, which tests/ci/requirements.txt declares.  It runs
by hand.  No hook or workflow runs it.  A change to a step name, the
checkout step, or the push step needs the same change here.
"""

from __future__ import annotations

import shlex
import subprocess
from collections.abc import Callable, Hashable, Mapping
from pathlib import Path
from pprint import pformat
from typing import Any, Final

import pytest
import yaml

ROOT: Final[Path] = Path(__file__).resolve().parents[2]
WORKFLOW: Final[Path] = ROOT / ".github" / "workflows" / "ci.yml"
JOB: Final[str] = "build-container"

# YAML 1.1, which PyYAML reads, breaks a line at each of these characters.
# YAML 1.2 reads them as text, so a form that mixes them with a multi-line
# quoted scalar can give the two readers different step lists.
LINE_SEPARATORS: Final[str] = "\u0085\u2028\u2029"

# The expected values.  This is the one place that writes them down.
CHECKOUT_NAME: Final[str] = "Checkout"
STORAGE_NAME: Final[str] = "Configure container storage"
PUSH_NAME: Final[str] = "Build and push container image"

STEP_NAMES: Final[tuple[str, ...]] = (CHECKOUT_NAME, STORAGE_NAME, PUSH_NAME)

CHECKOUT_STEP: Final[Mapping[str, object]] = {
    "name": CHECKOUT_NAME,
    "uses": "actions/checkout@11d5960a326750d5838078e36cf38b85af677262",
    "with": {"persist-credentials": False},
}

PUSH_STEP: Final[Mapping[str, object]] = {
    "name": PUSH_NAME,
    "shell": "/usr/bin/bash --noprofile --norc -p -eo pipefail {0}",
    "run": "exec /usr/bin/bash -p .mise/lib/builder-ci.sh",
    "env": {
        "LAMADIST_REGISTRY": "${{ secrets.LAMADIST_REGISTRY }}",
        "LAMADIST_REGISTRY_USER": "${{ secrets.LAMADIST_REGISTRY_USER }}",
        "LAMADIST_REGISTRY_PASSWORD": "${{ secrets.LAMADIST_REGISTRY_PASSWORD }}",
        "LAMADIST_REGISTRY_TLS_VERIFY": "${{ vars.LAMADIST_REGISTRY_TLS_VERIFY }}",
    },
}


class _UniqueKeyLoader(yaml.SafeLoader):
    """A safe loader that raises on a mapping with a duplicate key."""

    def construct_mapping(
        self, node: yaml.MappingNode, deep: bool = False
    ) -> dict[Hashable, Any]:
        mapping = super().construct_mapping(node, deep=deep)
        if len(mapping) != len(node.value):
            raise yaml.constructor.ConstructorError(
                None, None, "found a duplicate key", node.start_mark
            )
        return mapping


def _build_container_steps(text: str) -> list[Mapping[str, object]]:
    """The build-container job's steps, parsed from the workflow text.

    Fails on U+0085, U+2028, or U+2029, a parse error, a duplicate key, more
    than one document, a missing job, or steps that are not a list of
    mappings.
    """
    found = sorted({f"U+{ord(c):04X}" for c in text if c in LINE_SEPARATORS})
    assert not found, (
        f"the workflow holds a line-separator character ({', '.join(found)}): "
        "YAML 1.1 reads it as a line break and YAML 1.2 as text"
    )
    try:
        documents = list(yaml.load_all(text, Loader=_UniqueKeyLoader))
    except yaml.YAMLError as err:
        raise AssertionError(f"the workflow does not parse: {err}") from err
    assert len(documents) == 1, f"{len(documents)} YAML documents, want 1"
    jobs = documents[0].get("jobs") if isinstance(documents[0], dict) else None
    assert isinstance(jobs, dict), "no mapping `jobs`"
    job = jobs.get(JOB)
    assert isinstance(job, dict), f"no mapping job {JOB!r}"
    steps = job.get("steps")
    assert isinstance(steps, list), "the job's steps are not a list"
    assert all(isinstance(step, dict) for step in steps), "a step is not a mapping"
    return steps


def _label(step: Mapping[str, object]) -> object:
    """A step's name, or its sorted key names when it has no name."""
    return step["name"] if "name" in step else tuple(sorted(map(str, step)))


def _step(text: str, name: str) -> Mapping[str, object]:
    """The one step with this name."""
    found = [s for s in _build_container_steps(text) if s.get("name") == name]
    assert len(found) == 1, f"{len(found)} steps named {name!r}"
    return found[0]


def _same(what: str, actual: object, expected: object) -> None:
    """Assert equal values, and show the expected and the actual on failure."""
    assert actual == expected, (
        f"{what} differs\n--- expected\n{pformat(expected)}\n"
        f"--- actual\n{pformat(actual)}"
    )


def check_names(text: str) -> None:
    """The job's step names, in order, equal the expected names."""
    names = tuple(_label(step) for step in _build_container_steps(text))
    assert names == STEP_NAMES, names


def check_checkout_step(text: str) -> None:
    """The checkout step, as a mapping, equals the expected mapping."""
    _same("the checkout step", _step(text, CHECKOUT_NAME), CHECKOUT_STEP)


def check_push_step(text: str) -> None:
    """The push step, as a mapping, equals the expected mapping."""
    _same("the push step", _step(text, PUSH_NAME), PUSH_STEP)


CHECKS: Final[tuple[Callable[[str], None], ...]] = (
    check_names,
    check_checkout_step,
    check_push_step,
)


def check_all(text: str) -> None:
    """Run the three checks.  The first that fails raises."""
    for check in CHECKS:
        check(text)


@pytest.fixture(scope="module")
def workflow_text() -> str:
    """The text of the workflow file."""
    return WORKFLOW.read_text()


# Anchors in the workflow text, for the edits below.
JOB_HEADER: Final[str] = f"  {JOB}:\n"
NEXT_JOB: Final[str] = "\n  build-x86-64:\n"
STORAGE_MARK: Final[str] = f"      - name: {STORAGE_NAME}\n"
PUSH_MARK: Final[str] = f"      - name: {PUSH_NAME}\n"
EXTRA_STEP: Final[str] = "      - run: mise install\n"

Edit = Callable[[str], str]


def _edit(text: str, old: str, new: str) -> str:
    """The text with its one `old` replaced by `new`.

    A missing anchor raises LookupError, not AssertionError, so a case that
    expects an AssertionError from a check cannot pass on a drifted anchor.
    """
    if text.count(old) != 1:
        raise LookupError(f"{text.count(old)} of {old!r}, want 1")
    return text.replace(old, new, 1)


def _job_text(text: str) -> str:
    """The build-container job's text, from its header to the next job."""
    start = text.index(JOB_HEADER)
    return text[start : text.index(NEXT_JOB, start) + 1]


def _push_text(text: str) -> str:
    """The push step's text, to the end of the job."""
    return text[text.index(PUSH_MARK) : text.index(NEXT_JOB) + 1]


def _before_push(step: str) -> Edit:
    return lambda text: _edit(text, PUSH_MARK, step + PUSH_MARK)


def _after_job(tail: str) -> Edit:
    """Put `tail` right after the job's last line."""
    return lambda text: _edit(text, NEXT_JOB, tail + NEXT_JOB)


def _swap_storage_and_push(text: str) -> str:
    storage = text.index(STORAGE_MARK)
    push = text.index(PUSH_MARK)
    end = text.index(NEXT_JOB) + 1
    return text[:storage] + text[push:end] + text[storage:push] + text[end:]


def _duplicate_push(text: str) -> str:
    return _after_job(_push_text(text))(text)


def _one_character_change(text: str) -> str:
    return _edit(text, "-p .mise/lib/", "-x .mise/lib/")


# Edits that make check_names fail.
NAMES_FAIL: Final[dict[str, Edit]] = {
    "unnamed-uses-step-before-push": _before_push("      - uses: jdx/mise-action@v2\n"),
    "unnamed-run-step-before-push": _before_push(EXTRA_STEP),
    "named-step-before-push": _before_push(
        "      - name: Install mise\n        uses: jdx/mise-action@v2\n"
    ),
    "step-after-push": _after_job(EXTRA_STEP),
    "named-step-after-push": _after_job("      - name: More\n        run: true\n"),
    "moved-step": _swap_storage_and_push,
    "duplicated-push-step": _duplicate_push,
}

# Edits that make check_push_step fail.
PUSH_FAIL: Final[dict[str, Edit]] = {
    "one-character-change": _one_character_change,
    "key-after-a-blank-line": _after_job("\n        working-directory: /tmp\n"),
    "env-key-after-two-blank-lines": _after_job(
        "\n\n          LD_PRELOAD: /tmp/x.so\n"
    ),
    "key-after-a-comment": _after_job("      # note\n        if: false\n"),
    "key-after-a-comment-at-column-0": _after_job(
        "# note\n        continue-on-error: true\n"
    ),
    "duplicated-push-step": _duplicate_push,
}


def _other_header(header: str, decoy: bool) -> Edit:
    """The real job gets another header and an added step, and with a decoy
    the end of the file gets a verbatim copy of the golden job in a block
    scalar, which YAML reads as a string."""

    def edit(text: str) -> str:
        job = _job_text(text)
        edited = _edit(
            _edit(job, JOB_HEADER, header), PUSH_MARK, EXTRA_STEP + PUSH_MARK
        )
        broken = _edit(text, job, edited)
        return broken.rstrip("\n") + "\ndecoy: |-\n" + job if decoy else broken

    return edit


def _second_document(marker: str, renamed: bool) -> Edit:
    """A second YAML document with `jobs:` and a copy of the job.

    When `renamed`, the first document's job is renamed and gets an added
    step, and the copy is the golden job.  Otherwise the first document is
    unchanged and the copy gets the added step.
    """

    def edit(text: str) -> str:
        job = _job_text(text)
        if renamed:
            first = _edit(
                _edit(text, JOB_HEADER, "  build-image:\n"),
                PUSH_MARK,
                EXTRA_STEP + PUSH_MARK,
            )
            copy = job
        else:
            first = text
            copy = _edit(job, PUSH_MARK, EXTRA_STEP + PUSH_MARK)
        return first.rstrip("\n") + "\n" + marker + "jobs:\n" + copy

    return edit


def _swallowing_scalar(text: str) -> str:
    """The storage step's `run:` opens a double-quoted scalar that swallows a
    copy of the push step.  A line of four spaces and a quote closes it, and
    a step added after that line is a real step."""
    start = text.index(STORAGE_MARK) + len(STORAGE_MARK)
    swallowed = text[:start] + '        run: "true\n' + text[text.index(PUSH_MARK) :]
    tail = '    "\n      - name: Real push\n        run: mise install\n'
    return _after_job(tail)(swallowed)


def _line_separator(separator: str, rest: str) -> Edit:
    """A comment above the push step holds a line-separator character."""
    return _before_push(f"      # note{separator}{rest}\n")


def _swallowing_comments(separator: str) -> Edit:
    """The push step is replaced by a form whose two readings differ.

    A comment line holds a line-separator character, then a
    `working-directory` key opens a double-quoted scalar.  PyYAML reads the
    character as a line break, so the scalar swallows an added step, a
    comment line closes it, and the golden push step follows: the parsed
    step list is the golden one.  A YAML 1.2 reader keeps the character as
    text in a comment, and reads the added step as a real step.
    """

    def edit(text: str) -> str:
        push = _push_text(text)
        added = (
            f'      # c{separator}        working-directory: "/tmp\n'
            "      - name: Evil push\n"
            "        run: mise run container:builder:build --ci\n"
            "        env:\n"
            "          LAMADIST_REGISTRY_PASSWORD: "
            "${{ secrets.LAMADIST_REGISTRY_PASSWORD }}\n"
            f'      # c{separator}    "{separator}'
        )
        return _edit(text, push, added + push.replace("\n", separator))

    return edit


# Edits that make a check fail, by the form of the edit.
FORMS_FAIL: Final[dict[str, Edit]] = {
    "bare-dash-step": _before_push("      -\n        run: mise install\n"),
    "bare-dash-then-spaces": _before_push("      -  \n        run: mise install\n"),
    "dash-and-comment-step": _before_push(
        "      - # note\n        run: mise install\n"
    ),
    "flow-mapping-step": _before_push("      - {run: mise install}\n"),
    "step-with-an-anchor": _before_push("      - &anchor\n        run: mise install\n"),
    "step-with-a-tag": _before_push("      - !!map\n        run: mise install\n"),
    "step-with-an-unknown-tag": _before_push("      - !x\n        run: mise install\n"),
    "step-at-indent-4": _before_push("    - run: mise install\n"),
    "step-at-indent-7": _before_push("       - run: mise install\n"),
    "step-at-indent-8": _before_push("        - run: mise install\n"),
    "quoted-job-header": _other_header('  "build-container":\n', decoy=False),
    "quoted-job-header-and-decoy": _other_header('  "build-container":\n', decoy=True),
    "single-quoted-job-header": _other_header("  'build-container':\n", decoy=False),
    "job-header-with-trailing-spaces": _other_header("  build-container:  \n", False),
    "job-header-with-trailing-spaces-and-decoy": _other_header(
        "  build-container:  \n", decoy=True
    ),
    "job-header-with-a-space-before-the-colon": _other_header(
        "  build-container :\n", decoy=False
    ),
    "escaped-quote-header": _other_header('  "build\\x2dcontainer":\n', decoy=False),
    "escaped-quote-header-and-decoy": _other_header(
        '  "build\\x2dcontainer":\n', decoy=True
    ),
    "explicit-key-header": _other_header("  ? build-container\n  :\n", decoy=False),
    "explicit-key-header-and-decoy": _other_header(
        "  ? build-container\n  :\n", decoy=True
    ),
    "second-document": _second_document("---\n", renamed=False),
    "second-document-after-an-end-marker": _second_document(
        "...\n---\n", renamed=False
    ),
    "renamed-job-and-second-document": _second_document("---\n", renamed=True),
    "renamed-job-and-second-document-after-an-end-marker": _second_document(
        "...\n---\n", renamed=True
    ),
    "duplicate-steps-key": _after_job("    steps:\n      - run: mise install\n"),
    "duplicate-job-key": _after_job(
        "  build-container:\n    runs-on: x\n    steps:\n      - run: true\n"
    ),
    "multi-line-quoted-scalar-swallows-the-push-step": _swallowing_scalar,
    # PyYAML reads U+0085, U+2028, and U+2029 as line breaks, and a YAML
    # 1.2 reader does not, so the test fails on the characters themselves.
    "u2028-in-a-comment-then-a-step": _line_separator(
        "\u2028", "      - run: mise install"
    ),
    "u0085-in-a-comment-then-a-step": _line_separator(
        "\u0085", "      - run: mise install"
    ),
    "u2028-in-a-comment-then-a-comment": _line_separator("\u2028", "      # more"),
    "u2028-with-a-swallowing-scalar": _swallowing_comments("\u2028"),
    "u0085-with-a-swallowing-scalar": _swallowing_comments("\u0085"),
    "u2029-with-a-swallowing-scalar": _swallowing_comments("\u2029"),
    # PyYAML refuses U+000B as a character that YAML does not allow.
    "u000b-in-a-comment": _line_separator("\u000b", ""),
}


def _decoy_only(text: str) -> str:
    """A verbatim copy of the job in a top-level block scalar.  YAML reads it
    as a string, so the real job is unchanged."""
    return text.rstrip("\n") + "\ndecoy: |-\n" + _job_text(text)


def _storage_step_edit(text: str) -> str:
    line = "          sed -i 's/^ *//' /etc/containers/storage.conf\n"
    return _edit(text, line, line + "          mise install\n")


# Edits that change no compared value: every check passes.  Comments are
# not compared, and neither is the storage step.
OUTSIDE: Final[dict[str, Edit]] = {
    "comment-between-steps": _before_push("      # note\n"),
    "comment-at-column-0-between-steps": _before_push("# note\n"),
    "decoy-copy-in-a-top-level-block-scalar": _decoy_only,
    "storage-step-edit": _storage_step_edit,
}


def test_workflow_matches_the_golden_values(workflow_text: str) -> None:
    check_all(workflow_text)


@pytest.mark.parametrize("name", NAMES_FAIL)
def test_a_change_to_the_step_list_fails_the_names_check(
    workflow_text: str, name: str
) -> None:
    with pytest.raises(AssertionError):
        check_names(NAMES_FAIL[name](workflow_text))


@pytest.mark.parametrize("name", PUSH_FAIL)
def test_a_change_to_the_push_step_fails_the_push_check(
    workflow_text: str, name: str
) -> None:
    with pytest.raises(AssertionError):
        check_push_step(PUSH_FAIL[name](workflow_text))


def test_a_change_to_the_checkout_step_fails_the_checkout_check(
    workflow_text: str,
) -> None:
    broken = _edit(
        workflow_text, "persist-credentials: false", "persist-credentials: true"
    )
    with pytest.raises(AssertionError):
        check_checkout_step(broken)


@pytest.mark.parametrize("name", FORMS_FAIL)
def test_a_form_that_hides_or_changes_a_step_fails(
    workflow_text: str, name: str
) -> None:
    with pytest.raises(AssertionError):
        check_all(FORMS_FAIL[name](workflow_text))


@pytest.mark.parametrize("name", OUTSIDE)
def test_an_edit_outside_the_compared_values_passes(
    workflow_text: str, name: str
) -> None:
    check_all(OUTSIDE[name](workflow_text))


@pytest.mark.parametrize(
    ("name", "message"),
    [
        ("duplicate-steps-key", "duplicate key"),
        ("duplicate-job-key", "duplicate key"),
        ("second-document", "2 YAML documents"),
        ("second-document-after-an-end-marker", "2 YAML documents"),
    ],
)
def test_a_duplicate_key_or_a_second_document_fails_for_that_reason(
    workflow_text: str, name: str, message: str
) -> None:
    with pytest.raises(AssertionError, match=message):
        check_names(FORMS_FAIL[name](workflow_text))


@pytest.mark.parametrize("separator", ["\u0085", "\u2028", "\u2029"])
def test_a_line_separator_character_fails_for_that_reason(
    workflow_text: str, separator: str
) -> None:
    broken = _line_separator(separator, "      # more")(workflow_text)
    with pytest.raises(AssertionError, match="line-separator character"):
        check_names(broken)


@pytest.mark.parametrize(
    ("text", "old"), [("a b", "z"), ("a a", "a")], ids=["absent", "twice"]
)
def test_an_edit_whose_anchor_is_not_found_once_raises_lookup_error(
    text: str, old: str
) -> None:
    with pytest.raises(LookupError):
        _edit(text, old, "x")


def test_a_drifted_anchor_is_not_hidden_by_a_failure_expecting_case() -> None:
    """An edit on a text without its anchor must not look like a check that
    failed: the one-character change finds no `-p .mise/lib/` here."""
    with pytest.raises(LookupError):
        check_push_step(_one_character_change("jobs: {}\n"))


def _fake_podman(tmp_path: Path) -> Path:
    fake = tmp_path / "podman"
    fake.write_text("#!/bin/sh\ncat > /dev/null\n")
    fake.chmod(0o755)
    return fake


def test_the_pinned_shell_ignores_bash_env(workflow_text: str, tmp_path: Path) -> None:
    """Run the push step through the workflow's own shell line."""
    push = _step(workflow_text, PUSH_NAME)
    shell, run = str(push["shell"]), str(push["run"])
    hook = tmp_path / "hook"
    hook.write_text(f'echo "$LAMADIST_REGISTRY_PASSWORD" >> "{tmp_path}/marker"\n')
    script = tmp_path / "step.sh"
    script.write_text(f"{run} {_fake_podman(tmp_path)}\n")
    done = subprocess.run(
        [a.replace("{0}", str(script)) for a in shlex.split(shell)],
        cwd=ROOT,
        stdin=subprocess.DEVNULL,
        env={
            "PATH": "/usr/bin",
            "TMPDIR": str(tmp_path),
            "BASH_ENV": str(hook),
            "LAMADIST_CONTAINER_IMAGE": "builder:test",
            "LAMADIST_REGISTRY": "reg.example",
            "LAMADIST_REGISTRY_USER": "pusher",
            "LAMADIST_REGISTRY_PASSWORD": "s3cret",
        },
        capture_output=True,
        text=True,
        check=False,
    )
    assert done.returncode == 0, done.stderr
    assert not (tmp_path / "marker").exists()
