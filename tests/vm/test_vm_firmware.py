# SPDX-License-Identifier: Apache-2.0
"""Tests for the vm task's firmware choice (`--firmware aavmf|u-boot`).

A fake qemu-system-aarch64 records its arguments, so the tests run the
real task in headless mode with --no-tpm and check the command line it
builds; no emulator starts.  AAVMF stays the default and its command
line does not change; U-Boot boots through -bios from the deploy dir.
"""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
VM = ROOT / ".mise" / "tasks" / "vm"
MACHINE = "qemuarm64-lamadist"


def _setup(tmp_path: Path) -> tuple[dict[str, str], Path, Path]:
    bindir = tmp_path / "bin"
    bindir.mkdir()
    record = tmp_path / "qemu-args"
    fake = bindir / "qemu-system-aarch64"
    fake.write_text(f'#!/bin/sh\nprintf "%s\\n" "$@" > "{record}"\n')
    fake.chmod(0o755)
    deploy = tmp_path / "deploy"
    images = deploy / "images" / MACHINE
    images.mkdir(parents=True)
    (images / "lamadist-image-base.wic").write_bytes(b"\0" * 512)
    code = tmp_path / "AAVMF_CODE.fd"
    code.write_bytes(b"\1")
    vars_ = tmp_path / "AAVMF_VARS.fd"
    vars_.write_bytes(b"\1")
    env = {
        "PATH": f"{bindir}:{os.environ['PATH']}",
        "HOME": str(tmp_path),
        "MISE_CONFIG_ROOT": str(ROOT),
        "LAMADIST_HOST_DEPLOY_DIR": str(deploy),
        "LAMADIST_AAVMF_CODE": str(code),
        "LAMADIST_AAVMF_VARS": str(vars_),
        "usage_bsp": "qemuarm64",
        "usage_headless": "true",
        "usage_no_tpm": "true",
        "usage_tmpdir": str(tmp_path / "run"),
    }
    return env, record, images


def _run(env: dict[str, str], **usage: str) -> subprocess.CompletedProcess[str]:
    full = dict(env)
    full.update({f"usage_{k}": v for k, v in usage.items()})
    return subprocess.run(
        ["bash", str(VM)],
        check=False,
        env=full,
        capture_output=True,
        text=True,
        timeout=60,
    )


def _args(record: Path) -> list[str]:
    return record.read_text().splitlines()


def test_usage_declares_the_firmware_flag() -> None:
    text = VM.read_text()
    m = re.search(
        r'^#USAGE flag "--firmware <firmware>" help="([^"]+)" default="aavmf" \{\n'
        r'#USAGE   choices "aavmf" "u-boot"\n#USAGE \}$',
        text,
        re.MULTILINE,
    )
    assert m, "no --firmware flag with choices aavmf/u-boot, default aavmf"
    assert "qemuarm64" in m.group(1)


def test_default_boot_is_aavmf_pflash_unchanged(tmp_path: Path) -> None:
    env, record, _ = _setup(tmp_path)
    res = _run(env)
    assert res.returncode == 0, res.stdout + res.stderr
    args = _args(record)
    pflash = [a for a in args if a.startswith("if=pflash")]
    assert len(pflash) == 2
    assert f"file={env['LAMADIST_AAVMF_CODE']}" in pflash[0]
    assert "-bios" not in args
    assert "hd1" not in " ".join(args)


def test_u_boot_boots_through_bios_with_no_pflash(tmp_path: Path) -> None:
    env, record, images = _setup(tmp_path)
    (images / "u-boot.bin").write_bytes(b"\1")
    res = _run(env, firmware="u-boot")
    assert res.returncode == 0, res.stdout + res.stderr
    args = _args(record)
    assert args[args.index("-bios") + 1] == str(images / "u-boot.bin")
    assert not any(a.startswith("if=pflash") for a in args)
    # The machine shape is AAVMF's: virt, GICv3, acpi=off.
    assert args[args.index("-machine") + 1] == "virt,gic-version=3,acpi=off"


def test_u_boot_without_a_payload_fails_clearly(tmp_path: Path) -> None:
    env, record, _ = _setup(tmp_path)
    res = _run(env, firmware="u-boot")
    assert res.returncode == 1
    assert "u-boot.bin" in res.stdout
    assert "uboot-vm.kas.yml" in res.stdout
    assert not record.exists()


def test_u_boot_on_x86_64_fails_clearly(tmp_path: Path) -> None:
    env, record, _ = _setup(tmp_path)
    res = _run(env, bsp="x86_64", firmware="u-boot")
    assert res.returncode == 1
    assert "--firmware u-boot" in res.stdout and "qemuarm64" in res.stdout
    assert not record.exists()


def test_unknown_firmware_fails(tmp_path: Path) -> None:
    env, record, _ = _setup(tmp_path)
    res = _run(env, firmware="edk2")
    assert res.returncode == 1
    assert not record.exists()


def test_image_flag_boots_the_named_disk(tmp_path: Path) -> None:
    env, record, images = _setup(tmp_path)
    (images / "u-boot.bin").write_bytes(b"\1")
    scratch = tmp_path / "scratch.wic"
    scratch.write_bytes(b"\0" * 512)
    res = _run(env, firmware="u-boot", image=str(scratch))
    assert res.returncode == 0, res.stdout + res.stderr
    assert f"file={scratch},format=raw,if=none,id=hd0" in _args(record)


def test_image_flag_rejects_a_missing_file(tmp_path: Path) -> None:
    env, record, _ = _setup(tmp_path)
    res = _run(env, image=str(tmp_path / "nope.wic"))
    assert res.returncode == 1
    assert not record.exists()


def test_extra_disk_attaches_a_second_virtio_disk_after_the_first(
    tmp_path: Path,
) -> None:
    """The stand-in for the board's SD card: same uclass, second device."""
    env, record, images = _setup(tmp_path)
    (images / "u-boot.bin").write_bytes(b"\1")
    extra = tmp_path / "card.wic"
    extra.write_bytes(b"\0" * 512)
    res = _run(env, firmware="u-boot", extra_disk=str(extra))
    assert res.returncode == 0, res.stdout + res.stderr
    args = _args(record)
    drive = f"file={extra},format=raw,if=none,id=hd1,snapshot=on"
    assert drive in args
    first = args.index("virtio-blk-pci,drive=hd0,bootindex=0")
    second = args.index("virtio-blk-pci,drive=hd1")
    assert first < second


@pytest.mark.parametrize("firmware", ["aavmf", ""])
def test_extra_disk_needs_u_boot(tmp_path: Path, firmware: str) -> None:
    env, record, _ = _setup(tmp_path)
    extra = tmp_path / "card.wic"
    extra.write_bytes(b"\0" * 512)
    usage = {"extra_disk": str(extra)}
    if firmware:
        usage["firmware"] = firmware
    res = _run(env, **usage)
    assert res.returncode == 1
    assert not record.exists()


def test_u_boot_secureboot_skips_the_enrolled_vars(tmp_path: Path) -> None:
    """U-Boot's Secure Boot state is its build-time seed: no vars file."""
    env, record, images = _setup(tmp_path)
    (images / "u-boot.bin").write_bytes(b"\1")
    res = _run(env, firmware="u-boot", secureboot="true")
    assert res.returncode == 0, res.stdout + res.stderr
    assert "ovmf-vars-enrolled" not in res.stdout
    assert not any(a.startswith("if=pflash") for a in _args(record))


def test_u_boot_refuses_a_software_tpm_before_swtpm_starts(tmp_path: Path) -> None:
    """The payload has no TCG protocol and the board has no TPM, so a TPM
    run under it proves nothing that transfers.  The task must refuse the
    pairing before it starts swtpm or QEMU."""
    env, record, images = _setup(tmp_path)
    (images / "u-boot.bin").write_bytes(b"\1")
    started = tmp_path / "swtpm-started"
    fake = tmp_path / "bin" / "swtpm"
    fake.write_text(f'#!/bin/sh\ntouch "{started}"\n')
    fake.chmod(0o755)
    res = _run(env, firmware="u-boot", no_tpm="false")
    assert res.returncode == 1, res.stdout + res.stderr
    assert "--no-tpm" in res.stdout
    assert not started.exists()
    assert not record.exists()


def test_u_boot_with_no_tpm_still_boots(tmp_path: Path) -> None:
    env, record, images = _setup(tmp_path)
    (images / "u-boot.bin").write_bytes(b"\1")
    res = _run(env, firmware="u-boot", no_tpm="true")
    assert res.returncode == 0, res.stdout + res.stderr
    assert "-tpmdev" not in _args(record)
