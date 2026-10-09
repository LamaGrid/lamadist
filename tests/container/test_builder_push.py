# SPDX-License-Identifier: Apache-2.0
"""Tests for the CI push path of the builder-image build task.

A fake podman records each call and the stdin it was given, so the
tests check the contract: an image is pushed only when the run has a
registry and its credential, the password travels on stdin, and TLS
verification is on unless the site turns it off.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TASK = ROOT / ".mise" / "tasks" / "container" / "builder" / "build"


def _fake_podman(tmp_path: Path) -> Path:
    bindir = tmp_path / "bin"
    bindir.mkdir()
    fake = bindir / "podman"
    fake.write_text(
        "#!/bin/sh\n"
        f'printf "%s\\n" "$*" >> "{tmp_path}/calls"\n'
        'if [ "$1" = login ]; then\n'
        f'  cat > "{tmp_path}/stdin"\n'
        "fi\n"
    )
    fake.chmod(0o755)
    return bindir


def _run(tmp_path: Path, **env: str) -> subprocess.CompletedProcess[str]:
    bindir = _fake_podman(tmp_path)
    base = {
        k: v
        for k, v in os.environ.items()
        if not k.startswith(("LAMADIST_REGISTRY", "CONTAINER_REGISTRY"))
    }
    return subprocess.run(
        [str(TASK)],
        env={
            **base,
            "PATH": f"{bindir}:{base['PATH']}",
            "MISE_CONFIG_ROOT": str(ROOT),
            "LAMADIST_CONTAINER_IMAGE": "builder:test",
            "usage_ci": "true",
            **env,
        },
        capture_output=True,
        text=True,
        check=False,
    )


def _calls(tmp_path: Path) -> list[str]:
    return (tmp_path / "calls").read_text().splitlines()


def test_without_a_registry_the_image_is_built_and_not_pushed(
    tmp_path: Path,
) -> None:
    done = _run(tmp_path, LAMADIST_REGISTRY_PASSWORD="pw")
    assert done.returncode == 0, done.stderr
    calls = _calls(tmp_path)
    assert calls[0].startswith("build ")
    assert not [c for c in calls if c.startswith(("login", "push"))]


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
    done = _run(
        tmp_path,
        LAMADIST_REGISTRY="reg.example",
        LAMADIST_REGISTRY_USER="pusher",
        LAMADIST_REGISTRY_PASSWORD="s3cret",
    )
    assert done.returncode == 0, done.stderr
    calls = _calls(tmp_path)
    login = [c for c in calls if c.startswith("login")]
    assert login == [
        "login --tls-verify=true --password-stdin -u pusher reg.example"
    ]
    assert (tmp_path / "stdin").read_text() == "s3cret"
    assert "s3cret" not in "\n".join(calls) + done.stdout + done.stderr
    pushes = [c for c in calls if c.startswith("push")]
    assert len(pushes) == 2
    assert all(p.startswith("push --tls-verify=true reg.example/") for p in pushes)
    assert pushes[1].endswith(":latest")


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
