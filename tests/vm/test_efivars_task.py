# SPDX-License-Identifier: Apache-2.0
"""Tests for the test-efivars task's arguments and its --print-plan.

The task runs the N7 write test (docs/validation/N7-WRITE-TEST.md).
These tests run the real task with fake mise, podman, docker, and
qemu-system-aarch64 on PATH that record any call, so they show that
bad arguments stop the task before it starts anything, and that
--print-plan prints the plan and starts nothing.

The plan runs python3 to list the rows.  On a host where python3 is a
mise shim, the shim reads the trust state under HOME, which the tests
point at a scratch dir, and refuses an untrusted tree (a git archive of
the change, say).  So python3 on the fake PATH runs the interpreter that
runs pytest, and the task runs from the scratch dir: no result depends
on the host's mise state.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
TASK = ROOT / ".mise" / "tasks" / "test-efivars"
MACHINE = "qemuarm64-lamadist"
SHA = "1d8601d8c723d3403d10cb857c47ca97f72162b1569ea8402f481bcecdcd6f99"


def _setup(tmp_path: Path) -> tuple[dict[str, str], Path]:
    bindir = tmp_path / "bin"
    bindir.mkdir()
    record = tmp_path / "calls"
    for tool in ("mise", "podman", "docker", "qemu-system-aarch64", "swtpm"):
        fake = bindir / tool
        fake.write_text(f'#!/bin/sh\necho "{tool} $*" >> "{record}"\n')
        fake.chmod(0o755)
    python = bindir / "python3"
    python.write_text(f'#!/bin/sh\nexec "{sys.executable}" "$@"\n')
    python.chmod(0o755)
    deploy = tmp_path / "deploy"
    images = deploy / "images" / MACHINE
    images.mkdir(parents=True)
    (images / "lamadist-image-base-qemuarm64-lamadist.rootfs.wic").write_bytes(
        b"\0" * 512
    )
    (images / "u-boot.bin").write_bytes(b"\1")
    probe = tmp_path / "n7-probe"
    probe.mkdir()
    for name in ("n7-probe.efi", "n7-target.efi"):
        (probe / name).write_bytes(b"MZ")
    env = {
        "PATH": f"{bindir}:{os.environ['PATH']}",
        "HOME": str(tmp_path),
        "MISE_CONFIG_ROOT": str(ROOT),
        "LAMADIST_HOST_DEPLOY_DIR": str(deploy),
        "KAS_WORK_DIR": "/_w",
    }
    return env, record


def _run(env: dict[str, str], **usage: str) -> subprocess.CompletedProcess[str]:
    full = dict(env)
    full.update({f"usage_{k}": v for k, v in usage.items()})
    return subprocess.run(
        ["bash", str(TASK)],
        check=False,
        cwd=env["HOME"],
        env=full,
        capture_output=True,
        text=True,
        timeout=60,
    )


def _plan(out: str) -> dict[str, str]:
    return dict(re.findall(r"^PLAN (\w+)=(.*)$", out, re.MULTILINE))


def test_usage_declares_every_flag() -> None:
    text = TASK.read_text()
    assert re.search(
        r'^#USAGE flag "--firmware <firmware>" help="[^"]+" default="u-boot" \{\n'
        r'#USAGE   choices "u-boot" "aavmf"\n#USAGE \}$',
        text,
        re.MULTILINE,
    )
    for flag in (
        '"--image <wic>"',
        '"--probe <dir>"',
        '"-t --timeout <seconds>"',
        '"--uboot-sha256 <sha256>"',
        '"--evidence <dir>"',
        '"--print-plan"',
    ):
        assert re.search(rf"^#USAGE flag {re.escape(flag)} ", text, re.MULTILINE), flag
    assert re.search(r'"-t --timeout <seconds>" help="[^"]+" default="1800"', text)


@pytest.mark.parametrize(
    ("usage", "message"),
    [
        ({"firmware": "u-boot"}, "--uboot-sha256"),
        ({"firmware": "u-boot", "uboot_sha256": "abc"}, "--uboot-sha256"),
        ({"firmware": "u-boot", "uboot_sha256": SHA.upper()}, "--uboot-sha256"),
        ({"firmware": "aavmf", "uboot_sha256": SHA}, "--uboot-sha256"),
        ({"firmware": "ovmf"}, "--firmware"),
        ({"firmware": "aavmf", "timeout": "0"}, "--timeout"),
        ({"firmware": "aavmf", "timeout": "9m"}, "--timeout"),
        ({"firmware": "aavmf", "image": "/nonexistent/x.wic"}, "--image"),
    ],
)
def test_bad_arguments_stop_before_anything_starts(
    tmp_path: Path, usage: dict[str, str], message: str
) -> None:
    env, record = _setup(tmp_path)
    run = _run(env, **usage)
    assert run.returncode == 2, run.stdout + run.stderr
    assert message in run.stdout + run.stderr
    assert not record.exists()


def test_a_probe_dir_without_both_binaries_is_refused(tmp_path: Path) -> None:
    env, record = _setup(tmp_path)
    (tmp_path / "n7-probe" / "n7-target.efi").unlink()
    run = _run(env, firmware="aavmf", probe=str(tmp_path / "n7-probe"))
    assert run.returncode == 2
    assert "n7-target.efi" in run.stdout + run.stderr
    assert not record.exists()


def test_a_run_dir_inside_the_deploy_dir_is_refused(tmp_path: Path) -> None:
    env, record = _setup(tmp_path)
    # The scratch copy and payloads go under <tree>/.cache/efivars; a
    # deploy dir that contains them would put the probe image there.
    env["LAMADIST_HOST_DEPLOY_DIR"] = str(ROOT / ".cache")
    run = _run(env, firmware="aavmf", print_plan="true")
    assert run.returncode == 1
    assert "deploy" in run.stdout + run.stderr
    assert not record.exists()


def test_the_task_finds_python_on_the_fake_path_not_a_mise_shim(
    tmp_path: Path,
) -> None:
    env, _record = _setup(tmp_path)
    found = subprocess.run(
        ["sh", "-c", "command -v python3"],
        check=True,
        env=env,
        capture_output=True,
        text=True,
    ).stdout.strip()
    assert found == str(tmp_path / "bin" / "python3")


def test_print_plan_for_the_green_run_starts_nothing(tmp_path: Path) -> None:
    env, record = _setup(tmp_path)
    run = _run(
        env,
        firmware="u-boot",
        uboot_sha256=SHA,
        probe=str(tmp_path / "n7-probe"),
        print_plan="true",
    )
    assert run.returncode == 0, run.stdout + run.stderr
    assert not record.exists()
    plan = _plan(run.stdout)
    assert plan["firmware"] == "u-boot"
    assert plan["probe"] == str(tmp_path / "n7-probe")
    assert plan["image"].endswith(".rootfs.wic")
    assert plan["uboot_bin"].endswith(f"images/{MACHINE}/u-boot.bin")
    assert plan["uboot_sha256"] == SHA
    assert plan["run_dir"].startswith(str(ROOT / ".cache" / "efivars" / "run-"))
    assert plan["rows"] == "U-PK U-KEK U-db W-db X-PK S-db S-KEK S-PK"
    vm = plan["vm"].split()
    assert vm[:10] == [
        "--bsp",
        "qemuarm64",
        "--firmware",
        "u-boot",
        "--no-tpm",
        "--headless",
        "--allow-reboot",
        "--snapshot",
        "--timeout",
        "1800",
    ]
    assert vm[vm.index("--image") + 1] == plan["run_dir"] + "/scratch.wic"
    assert "--secureboot" not in vm
    assert plan["esp"] == (
        "mmd ::/n7; mmove ::/EFI/BOOT/BOOTAA64.EFI ::/n7/sdboot.efi;"
        " mcopy n7-probe.efi ::/EFI/BOOT/BOOTAA64.EFI;"
        " mcopy <rows>.bin n7-target.efi ::/n7/"
    )


def test_print_plan_for_r1_uses_aavmf_with_secure_boot(tmp_path: Path) -> None:
    env, record = _setup(tmp_path)
    run = _run(env, firmware="aavmf", print_plan="true")
    assert run.returncode == 0, run.stdout + run.stderr
    assert not record.exists()
    plan = _plan(run.stdout)
    vm = plan["vm"].split()
    assert vm[vm.index("--firmware") + 1] == "aavmf"
    assert "--secureboot" in vm
    assert plan["probe"] == "none"
    assert plan["esp"] == "unchanged"
    assert "uboot_sha256" not in plan


def test_print_plan_takes_an_explicit_image(tmp_path: Path) -> None:
    env, _record = _setup(tmp_path)
    img = tmp_path / "r2" / "lamadist-image-base.wic"
    img.parent.mkdir()
    img.write_bytes(b"\0")
    run = _run(
        env, firmware="u-boot", uboot_sha256=SHA, image=str(img), print_plan="true"
    )
    assert run.returncode == 0, run.stdout + run.stderr
    assert _plan(run.stdout)["image"] == str(img)
