# SPDX-License-Identifier: Apache-2.0
"""Tests for the CI push path of the builder-image build task.

A fake podman records each call and the stdin it was given, so the
tests check the contract: an image is pushed only when the run has a
registry and its credential, the password travels on stdin and is in no
podman call's environment, the login writes to an auth file in a
temporary directory that is gone when the script exits, and TLS
verification is on unless the site turns it off.
The script runs its tools by absolute path or through a pinned PATH,
so an executable earlier on the caller's PATH never runs.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Final

import pytest

ROOT: Final[Path] = Path(__file__).resolve().parents[2]
TASK: Final[Path] = ROOT / ".mise" / "tasks" / "container" / "builder" / "build"
SCRIPT: Final[Path] = ROOT / ".mise" / "lib" / "builder-ci.sh"
BASH: Final[str] = "/usr/bin/bash"
IMAGE: Final[str] = "reg.example/lamagrid/lamadist-builder"
# The time tag: four digits, dash, two digits, dash, two digits, T, six digits, Z.
TIME_TAG: Final[str] = rf"{re.escape(IMAGE)}:\d{{4}}-\d\d-\d\dT\d{{6}}Z"
CREDENTIAL: Final[Mapping[str, str]] = {
    "LAMADIST_REGISTRY": "reg.example",
    "LAMADIST_REGISTRY_USER": "pusher",
    "LAMADIST_REGISTRY_PASSWORD": "s3cret",
}


def _fake_podman(tmp_path: Path, push_status: int = 0) -> Path:
    """Make a fake podman that records its calls.

    Each call also appends its environment to a file, under a line that
    names the call's verb.  On login it saves stdin and writes the file
    named by --authfile=PATH, as podman would.  On push it exits with
    push_status.
    """
    bindir = tmp_path / "bin"
    bindir.mkdir()
    fake = bindir / "podman"
    fake.write_text(
        "#!/bin/sh\n"
        f'printf "%s\\n" "$*" >> "{tmp_path}/calls"\n'
        f'{{ echo "== $1"; env; }} >> "{tmp_path}/envs"\n'
        'if [ "$1" = login ]; then\n'
        f'  cat > "{tmp_path}/stdin"\n'
        '  for a in "$@"; do\n'
        '    case "$a" in --authfile=*) echo auth > "${a#--authfile=}" ;; esac\n'
        "  done\n"
        "fi\n"
        f'if [ "$1" = push ]; then exit {push_status}; fi\n'
    )
    fake.chmod(0o755)
    return bindir


def _marker_tools(tmp_path: Path, *names: str) -> Path:
    """Make a directory of executables that record being run."""
    shimdir = tmp_path / "shims"
    shimdir.mkdir()
    for name in names:
        shim = shimdir / name
        shim.write_text(f'#!/bin/sh\necho "{name}" >> "{tmp_path}/marker"\n')
        shim.chmod(0o755)
    return shimdir


def _run(
    tmp_path: Path,
    command: Sequence[str] | None = None,
    path_prefix: Path | None = None,
    push_status: int = 0,
    extra: Mapping[str, str] | None = None,
    script: Path | str = SCRIPT,
    cwd: Path | None = None,
    **env: str,
) -> subprocess.CompletedProcess[str]:
    bindir = _fake_podman(tmp_path, push_status)
    fake = str(bindir / "podman")
    temp = tmp_path / "tmp"
    temp.mkdir()
    base = {
        k: v
        for k, v in os.environ.items()
        if not k.startswith(("LAMADIST_", "CONTAINER_REGISTRY", "BUILDER_UID"))
    }
    path = base["PATH"] if path_prefix is None else f"{path_prefix}:{base['PATH']}"
    return subprocess.run(
        command or [BASH, "-p", str(script), fake],
        cwd=cwd,
        stdin=subprocess.DEVNULL,
        env={
            **base,
            "PATH": path,
            "TMPDIR": str(temp),
            "LAMADIST_CONTAINER_IMAGE": "builder:test",
            **(extra or {}),
            **env,
        },
        capture_output=True,
        text=True,
        check=False,
    )


def _calls(tmp_path: Path) -> list[str]:
    return (tmp_path / "calls").read_text().splitlines()


def _authfiles(calls: Sequence[str]) -> list[str]:
    """The --authfile=PATH value of each login and push call."""
    return [
        arg.removeprefix("--authfile=")
        for call in calls
        if call.startswith(("login", "push"))
        for arg in call.split()
        if arg.startswith("--authfile=")
    ]


def test_without_a_registry_the_image_is_built_and_not_pushed(
    tmp_path: Path,
) -> None:
    done = _run(tmp_path, LAMADIST_REGISTRY_PASSWORD="pw")
    assert done.returncode == 0, done.stderr
    calls = _calls(tmp_path)
    assert calls[0].startswith("build ")
    assert calls[0].endswith(f" builder:test {SCRIPT.parent}/../../container/")
    assert not [c for c in calls if c.startswith(("login", "push"))]


def test_the_workflow_call_builds_the_container_directory_of_the_workspace(
    tmp_path: Path,
) -> None:
    # The workflow runs `exec /usr/bin/bash -p .mise/lib/builder-ci.sh` with
    # the workspace as the working directory, so the script's own path is
    # relative.  Use a copy of the script in a workspace of its own, so
    # the context cannot come from this repository's path.
    workspace = tmp_path / "workspace"
    lib = workspace / ".mise" / "lib"
    lib.mkdir(parents=True)
    (workspace / "container").mkdir()
    shutil.copy(SCRIPT, lib / SCRIPT.name)
    done = _run(
        tmp_path,
        script=f".mise/lib/{SCRIPT.name}",
        cwd=workspace,
        LAMADIST_REGISTRY_PASSWORD="pw",
    )
    assert done.returncode == 0, done.stderr
    (build,) = [c for c in _calls(tmp_path) if c.startswith("build ")]
    context = build.split()[-1]
    assert (workspace / context).resolve() == (workspace / "container").resolve()


def test_without_an_image_name_it_exits_1_before_any_build(tmp_path: Path) -> None:
    done = _run(tmp_path, LAMADIST_CONTAINER_IMAGE="", extra=CREDENTIAL)
    assert done.returncode == 1
    assert not (tmp_path / "calls").exists()
    assert "LAMADIST_CONTAINER_IMAGE" in done.stderr


def test_without_a_credential_the_image_is_built_and_not_pushed(
    tmp_path: Path,
) -> None:
    done = _run(tmp_path, LAMADIST_REGISTRY="reg.example")
    assert done.returncode == 0, done.stderr
    assert not [c for c in _calls(tmp_path) if c.startswith(("login", "push"))]
    assert "not pushed" in done.stdout


def test_with_a_credential_it_logs_in_on_stdin_and_pushes_both_tags(
    tmp_path: Path,
) -> None:
    done = _run(tmp_path, extra=CREDENTIAL)
    assert done.returncode == 0, done.stderr
    calls = _calls(tmp_path)
    (authfile,) = set(_authfiles(calls))
    login = [c for c in calls if c.startswith("login")]
    assert login == [
        (
            f"login --authfile={authfile} --tls-verify=true --password-stdin"
            " -u pusher reg.example"
        )
    ]
    assert (tmp_path / "stdin").read_text() == "s3cret"
    assert "s3cret" not in "\n".join(calls) + done.stdout + done.stderr
    pushes = [c for c in calls if c.startswith("push")]
    assert len(pushes) == 2
    assert all(
        p.startswith(f"push --authfile={authfile} --tls-verify=true reg.example/")
        for p in pushes
    )
    tags = [c for c in calls if c.startswith("tag ")]
    assert len(tags) == 2
    assert re.fullmatch(f"tag builder:test {TIME_TAG}", tags[0])
    assert tags[1] == f"tag builder:test {IMAGE}:latest"
    assert re.fullmatch(
        rf"push --authfile={re.escape(authfile)} --tls-verify=true {TIME_TAG}",
        pushes[0],
    )
    assert pushes[1].endswith(f" {IMAGE}:latest")
    # Both tag calls come before the first push.
    assert max(map(calls.index, tags)) < min(map(calls.index, pushes))


@pytest.mark.parametrize(
    "credential",
    [
        pytest.param(CREDENTIAL, id="registry-user-and-password"),
        pytest.param({"LAMADIST_REGISTRY_PASSWORD": "s3cret"}, id="password-only"),
    ],
)
def test_no_podman_call_has_the_password_in_its_environment(
    tmp_path: Path, credential: Mapping[str, str]
) -> None:
    done = _run(tmp_path, extra=credential)
    assert done.returncode == 0, done.stderr
    envs = (tmp_path / "envs").read_text()
    # The build call ran, and its environment is in the file.
    assert "== build\n" in envs
    assert "LAMADIST_CONTAINER_IMAGE=builder:test" in envs
    assert "LAMADIST_REGISTRY_PASSWORD" not in envs
    assert "s3cret" not in envs


def test_no_podman_call_has_the_password_when_the_copys_name_is_exported(
    tmp_path: Path,
) -> None:
    # A variable that arrives exported keeps its export attribute when the
    # script assigns to it, so the script has to remove the attribute.
    done = _run(tmp_path, extra=CREDENTIAL, _registry_password="preset")
    assert done.returncode == 0, done.stderr
    envs = (tmp_path / "envs").read_text()
    assert "== build\n" in envs
    assert "== push\n" in envs
    assert "s3cret" not in envs
    assert (tmp_path / "stdin").read_text() == "s3cret"


def test_the_login_and_pushes_share_one_auth_file_that_is_removed(
    tmp_path: Path,
) -> None:
    done = _run(tmp_path, extra=CREDENTIAL)
    assert done.returncode == 0, done.stderr
    authfiles = _authfiles(_calls(tmp_path))
    assert len(authfiles) == 3
    assert len(set(authfiles)) == 1
    authdir = Path(authfiles[0]).parent
    assert authdir.parent == tmp_path / "tmp"
    assert not authdir.exists()


def test_the_auth_directory_is_removed_after_a_failed_push(tmp_path: Path) -> None:
    done = _run(tmp_path, push_status=3, extra=CREDENTIAL)
    assert done.returncode == 3
    (authfile,) = set(_authfiles(_calls(tmp_path)))
    assert not Path(authfile).parent.exists()
    assert list((tmp_path / "tmp").iterdir()) == []


def test_the_script_text_holds_the_temporary_auth_file() -> None:
    text = SCRIPT.read_text()
    assert "$(mktemp -d)" in text
    assert "trap " in text
    assert " EXIT" in text
    for verb in ("login", "push"):
        assert f'"${{_podman}}" {verb} --authfile="${{_authfile}}"' in text


def test_the_site_can_turn_tls_verification_off(tmp_path: Path) -> None:
    done = _run(
        tmp_path,
        LAMADIST_REGISTRY="reg.example",
        LAMADIST_REGISTRY_USER="pusher",
        LAMADIST_REGISTRY_PASSWORD="s3cret",
        LAMADIST_REGISTRY_TLS_VERIFY="false",
    )
    assert done.returncode == 0, done.stderr
    for call in _calls(tmp_path):
        if call.startswith(("login", "push")):
            assert "--tls-verify=false" in call


def test_a_credential_without_a_user_fails_before_any_push(
    tmp_path: Path,
) -> None:
    done = _run(
        tmp_path,
        LAMADIST_REGISTRY="reg.example",
        LAMADIST_REGISTRY_PASSWORD="s3cret",
    )
    assert done.returncode != 0
    assert not [c for c in _calls(tmp_path) if c.startswith(("login", "push"))]
    assert "LAMADIST_REGISTRY_USER" in done.stderr


def test_an_executable_earlier_on_path_never_runs(tmp_path: Path) -> None:
    # The commands the script runs through PATH: date, id (BUILDER_UID
    # is unset), and mktemp and rm for the auth directory.
    shimdir = _marker_tools(tmp_path, "date", "id", "mktemp", "rm")
    done = _run(tmp_path, path_prefix=shimdir, extra=CREDENTIAL)
    assert done.returncode == 0, done.stderr
    assert not (tmp_path / "marker").exists()
    assert (tmp_path / "stdin").read_text() == "s3cret"


def test_the_podman_variable_is_ignored(tmp_path: Path) -> None:
    shimdir = _marker_tools(tmp_path, "podman")
    done = _run(tmp_path, PODMAN=str(shimdir / "podman"), extra=CREDENTIAL)
    assert done.returncode == 0, done.stderr
    assert not (tmp_path / "marker").exists()
    assert [c for c in _calls(tmp_path) if c.startswith("push")]


def test_the_task_ci_branch_runs_the_script_in_privileged_mode(
    tmp_path: Path,
) -> None:
    lib = tmp_path / "root" / ".mise" / "lib"
    lib.mkdir(parents=True)
    stub = lib / "builder-ci.sh"
    stub.write_text(f'#!/bin/sh\necho "$0 $-" > "{tmp_path}/ran"\n')
    stub.chmod(0o755)
    done = _run(
        tmp_path,
        command=[str(TASK)],
        MISE_CONFIG_ROOT=str(tmp_path / "root"),
        usage_ci="true",
    )
    assert done.returncode == 0, done.stderr
    ran = (tmp_path / "ran").read_text().split()
    assert ran[0] == str(stub)
    assert "p" in ran[1]
