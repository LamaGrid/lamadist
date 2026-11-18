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


def _drive_path(record: Path) -> Path:
    """The path of the boot disk (id=hd0) in the recorded QEMU arguments."""
    for arg in _args(record):
        m = re.fullmatch(r"file=(.+),format=raw,if=none,id=hd0", arg)
        if m:
            return Path(m.group(1))
    raise AssertionError("no hd0 drive in the recorded QEMU arguments")


@pytest.mark.parametrize(
    ("suffix", "packer"),
    [
        (".zst", ["zstd", "-q"]),
        (".xz", ["xz"]),
        (".gz", ["gzip"]),
        (".bz2", ["bzip2"]),
    ],
)
def test_a_compressed_image_is_decompressed_into_the_run_dir(
    tmp_path: Path, suffix: str, packer: list[str]
) -> None:
    """A raw copy in the deploy dir is in no sstate manifest, so BitBake's
    cleanup handlers never remove it, and it would outlive the fresh
    compressed image it came from and boot in its place.  The task must
    write the raw copy to the per-run directory instead."""
    env, record, images = _setup(tmp_path)
    (images / "lamadist-image-base.wic").unlink()
    raw = tmp_path / "payload.wic"
    raw.write_bytes(b"\0" * 4096)
    subprocess.run([*packer, "-k", str(raw)], check=True)
    packed = images / f"lamadist-image-base.wic{suffix}"
    (tmp_path / f"payload.wic{suffix}").rename(packed)
    before = sorted(p.name for p in images.iterdir())

    res = _run(env)

    assert res.returncode == 0, res.stdout + res.stderr
    assert sorted(p.name for p in images.iterdir()) == before
    drive = _drive_path(record)
    assert drive.parent == tmp_path / "run"
    assert drive.read_bytes() == raw.read_bytes()


def test_every_stream_decompressor_writes_a_sparse_copy() -> None:
    """A redirect writes every zero byte, so a 9 GB image would fill the
    run directory (often a memory file system).  zstd -o writes holes on
    its own; the stream formats go through cp --sparse=always."""
    text = VM.read_text()
    for tool, suffix in (("xz", "xz"), ("gzip", "gz"), ("bzip2", "bz2")):
        branch = rf"^\s*\*\.{suffix}\) ({tool} -d -c .*) ;;$"
        m = re.search(branch, text, re.MULTILINE)
        assert m, f"no .{suffix} branch"
        sink = r'\| cp --sparse=always /dev/stdin "\$\{_raw_image\}"$'
        assert re.search(sink, m.group(1))
        assert ">" not in m.group(1)
    zst = r'^\s*\*\.zst\) zstd -d -q -f -o "\$\{_raw_image\}"'
    assert re.search(zst, text, re.MULTILINE)


def test_a_compressed_image_named_with_image_is_decompressed(tmp_path: Path) -> None:
    """QEMU reads the drive as raw; handing it a compressed file would boot
    garbage.  --image gets the same decompression as a deploy-dir find."""
    env, record, _images = _setup(tmp_path)
    raw = tmp_path / "scratch.wic"
    raw.write_bytes(b"\1" + b"\0" * 4095)
    subprocess.run(["xz", "-k", str(raw)], check=True)
    packed = tmp_path / "scratch.wic.xz"
    packed_bytes = packed.read_bytes()

    res = _run(env, image=str(packed))

    assert res.returncode == 0, res.stdout + res.stderr
    drive = _drive_path(record)
    assert drive.parent == tmp_path / "run"
    assert drive.read_bytes() == raw.read_bytes()
    assert packed.read_bytes() == packed_bytes


def test_a_raw_image_named_with_image_is_booted_as_given(tmp_path: Path) -> None:
    env, record, _images = _setup(tmp_path)
    scratch = tmp_path / "scratch.img"
    scratch.write_bytes(b"\0" * 512)

    res = _run(env, image=str(scratch))

    assert res.returncode == 0, res.stdout + res.stderr
    assert _drive_path(record) == scratch


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
