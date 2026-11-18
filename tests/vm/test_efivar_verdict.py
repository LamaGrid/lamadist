# SPDX-License-Identifier: Apache-2.0
"""Tests for the N7 write-test verdict (.mise/lib/efivar_write_test.py).

The verdict is a pure function of the serial transcript: the probe's
N7PROBE lines (Part B, before ExitBootServices), the in-guest script's
N7A lines (Part A, through efivarfs), and the firmware and kernel
banners that count the boots.  These transcripts are built to that
line protocol with console noise around it; no VM runs.  The GREEN
transcript is what the design predicts for U-Boot v2026.01 with the
preseeded store, and each failure case mutates it.
"""

from __future__ import annotations

import hashlib
import importlib.util
import sys
import zlib
from collections.abc import Callable
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[2]
LIB = ROOT / ".mise" / "lib"
KEYS = ROOT / "meta-lamadist" / "files" / "sb-dev"
UBOOT_SHA = "1d8601d8c723d3403d10cb857c47ca97f72162b1569ea8402f481bcecdcd6f99"
TAGS = ["U-PK", "U-KEK", "U-db", "W-db", "X-PK", "S-db", "S-KEK", "S-PK"]
VARS = {"PK": "pk.esl", "KEK": "kek.esl", "db": "db.esl"}
WP = "0x8000000000000008"
SV = "0x800000000000001a"
NF = "0x800000000000000e"
OK = "0x0000000000000000"


def _load() -> ModuleType:
    sys.path.insert(0, str(LIB))
    spec = importlib.util.spec_from_file_location(
        "efivar_write_test", LIB / "efivar_write_test.py"
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["efivar_write_test"] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def wt() -> ModuleType:
    return _load()


@pytest.fixture(scope="module")
def expect(wt: ModuleType) -> dict[str, object]:
    return wt.efivar_payloads.expectations(KEYS)


def _sha(var: str) -> str:
    return hashlib.sha256((KEYS / VARS[var]).read_bytes()).hexdigest()


def _read(phase: str, var: str) -> str:
    if var == "dbx":
        status, size, crc = NF, 0, 0
    else:
        data = (KEYS / VARS[var]).read_bytes()
        status, size, crc = OK, len(data), zlib.crc32(data)
    return (
        f"N7PROBE READ {phase} {var} status={status} attr=0x00000027"
        f" size={size} crc=0x{crc:08x}\r\n"
    )


def _probe() -> str:
    out = "N7PROBE BEGIN v1\r\n"
    out += "".join(_read("pre", v) for v in ("PK", "KEK", "db", "dbx"))
    for tag in TAGS:
        if tag == "S-PK":
            out += f"N7PROBE L1 n7-target status={SV}\r\n"
        out += f"N7PROBE ROW {tag} attr=0x00000027 size=1400 status={WP}\r\n"
    out += "".join(_read("post", v) for v in ("PK", "KEK", "db", "dbx"))
    return out + "N7PROBE END v1\r\n"


def _state(phase: str) -> str:
    sha = {v: _sha(v) for v in VARS}
    return (
        f"N7A STATE {phase} secureboot=1 setupmode=0 PK={sha['PK']}"
        f" KEK={sha['KEK']} db={sha['db']} dbx=absent mount=ro"
        " efi_test=absent\r\n"
    )


def _boot(n: int, firmware: str, probe: bool) -> str:
    out = ""
    if firmware == "u-boot":
        out += (
            "\r\nU-Boot 2026.01 (Nov 17 2026 - 08:40:00 +0000)\r\n\r\nDRAM:  2 GiB\r\n"
        )
        out += "Scanning bootdev 'virtio-blk#0.bootdev':\r\n"
    else:
        out += 'BdsDxe: loading Boot0001 "UEFI Misc Device"\r\n'
    if probe:
        out += _probe()
    out += "[    0.000000] Booting Linux on physical CPU 0x0000000000 [0x411fd070]\r\n"
    out += "[    1.2] efivars: Registered efivars operations\r\n"
    out += "qemuarm64-lamadist login: lama\r\nPassword: \r\n$ sudo -s\r\n# \r\n"
    if n == 1:
        out += _state("pre")
        out += "N7A INFO selinux=unconfined_t enforce=0 chattr=/usr/bin/chattr\r\n"
        out += "N7A A1 rc=32 mount=ro err=mount: /sys/firmware/efi/efivars:"
        out += " mount point not mounted or bad option.\r\n"
        for tag in TAGS:
            verb = "cannot remove" if tag == "X-PK" else "failed to open"
            out += (
                f"N7A ROW {tag} rc=1 err={verb} '/sys/firmware/efi/efivars/x':"
                " Read-only file system\r\n"
            )
        out += _state("post") + "N7A DONE full\r\n"
        out += "# systemctl reboot\r\n[  OK  ] Reached target System Reboot.\r\n"
        out += "reboot: Restarting system\r\n"
    else:
        out += _state("boot2") + "N7A DONE boot2\r\n"
    return out


def _green(firmware: str = "u-boot", probe: bool = True) -> str:
    return _boot(1, firmware, probe) + _boot(2, firmware, probe)


def _eval(
    wt: ModuleType,
    expect: dict[str, object],
    log: str,
    *,
    firmware: str = "u-boot",
    probe: bool = True,
    sha: tuple[str, str, str] | None = (UBOOT_SHA, UBOOT_SHA, UBOOT_SHA),
) -> dict[str, tuple[bool, str]]:
    results = wt.evaluate(
        log,
        firmware=firmware,
        probe=probe,
        expect=expect,
        uboot_sha=sha if firmware == "u-boot" else None,
    )
    names = [r.row for r in results]
    assert names == wt.row_names(firmware, probe)
    return {r.row: (r.ok, r.detail) for r in results}


def _failed(got: dict[str, tuple[bool, str]]) -> set[str]:
    return {row for row, (ok, _d) in got.items() if not ok}


# --- the row set ----------------------------------------------------------


def test_row_names_cover_both_parts_and_the_reboot(wt: ModuleType) -> None:
    rows = wt.row_names("u-boot", True)
    assert len(rows) == len(set(rows)) == 54
    for tag in TAGS:
        assert f"A.{tag}" in rows
        assert f"probe.{tag}" in rows
    for must in ("A0.mount", "A1.remount", "reboot.banners", "uboot.sha256"):
        assert must in rows
    assert "probe.L1" in rows
    assert "uboot.sha256" not in wt.row_names("aavmf", True)
    assert not any(r.startswith("probe.") for r in wt.row_names("u-boot", False))


# --- GREEN ----------------------------------------------------------------


@pytest.mark.parametrize("probe", [True, False])
def test_green_transcript_passes_every_row(
    wt: ModuleType, expect: dict[str, object], probe: bool
) -> None:
    got = _eval(wt, expect, _green(probe=probe), probe=probe)
    assert _failed(got) == set(), got
    assert (
        wt.render(
            wt.evaluate(
                _green(probe=probe),
                firmware="u-boot",
                probe=probe,
                expect=expect,
                uboot_sha=(UBOOT_SHA, UBOOT_SHA, UBOOT_SHA),
            )
        ).splitlines()[-1]
        == "N7 VERDICT PASS"
    )


# --- the failure cases ----------------------------------------------------

Mutation = Callable[[str], str]


def _replace_once(old: str, new: str) -> Mutation:
    def mutate(log: str) -> str:
        assert old in log, old
        return log.replace(old, new, 1)

    return mutate


def _sub_all(old: str, new: str) -> Mutation:
    def mutate(log: str) -> str:
        assert old in log, old
        return log.replace(old, new)

    return mutate


def _seedless_pk(log: str) -> str:
    """No PK in the store: the probe reads NOT_FOUND and efivarfs has
    no PK file, in every phase of both boots."""
    log = _sub_all(f"PK={_sha('PK')}", "PK=absent")(log)
    for phase in ("pre", "post"):
        missing = _read(phase, "dbx").replace(" dbx ", " PK ")
        log = _sub_all(_read(phase, "PK"), missing)(log)
    return log


@pytest.mark.parametrize(
    ("case", "mutate", "red"),
    [
        (
            "the seed failed: PK is missing from the store",
            lambda log: _seedless_pk(log),
            {"A0.PK", "probe.pre.PK"},
        ),
        (
            "EPERM where EROFS is expected",
            _replace_once(
                "N7A ROW U-PK rc=1 err=failed to open '/sys/firmware/efi/efivars/x':"
                " Read-only file system",
                "N7A ROW U-PK rc=1 err=failed to open '/sys/firmware/efi/efivars/x':"
                " Operation not permitted",
            ),
            {"A.U-PK"},
        ),
        (
            "a reset loop: the firmware starts twice in the first boot",
            _replace_once(
                "[    0.000000] Booting Linux on physical CPU",
                "U-Boot 2026.01 (Nov 17 2026 - 08:40:00 +0000)\r\n"
                "[    0.000000] Booting Linux on physical CPU 0x0\r\n"
                "U-Boot 2026.01 (Nov 17 2026 - 08:40:00 +0000)\r\n"
                "[    0.000000] Booting Linux on physical CPU",
            ),
            {"reboot.banners"},
        ),
        (
            "an rc 0 write through efivarfs",
            _replace_once(
                "N7A ROW S-db rc=1 err=failed to open '/sys/firmware/efi/efivars/x':"
                " Read-only file system",
                "N7A ROW S-db rc=0 err=-",
            ),
            {"A.S-db"},
        ),
        (
            "/dev/efi_test present",
            _replace_once("mount=ro efi_test=absent", "mount=ro efi_test=present"),
            {"A0.efi_test"},
        ),
        (
            "efivarfs mounted read-write and the remount succeeds",
            lambda log: _replace_once("N7A A1 rc=32 mount=ro", "N7A A1 rc=0 mount=rw")(
                _replace_once("dbx=absent mount=ro", "dbx=absent mount=rw")(log)
            ),
            {"A0.mount", "A1.remount"},
        ),
        (
            "a probe write succeeds before ExitBootServices",
            _replace_once(
                f"ROW S-PK attr=0x00000027 size=1400 status={WP}",
                f"ROW S-PK attr=0x00000027 size=1400 status={OK}",
            ),
            {"probe.S-PK"},
        ),
        (
            "L1: the KEK-signed image loads",
            _replace_once(
                f"N7PROBE L1 n7-target status={SV}", f"N7PROBE L1 n7-target status={OK}"
            ),
            {"probe.L1"},
        ),
        (
            "a probe write changes db in the same boot",
            _replace_once(
                _read("post", "db"),
                _read("post", "db")
                .replace("size=", "size=9")
                .replace("crc=0x", "crc=0x1"),
            ),
            {"probe.post.db"},
        ),
        (
            "a write persists across the reset",
            lambda log: _sub_all(
                f"N7A STATE boot2 secureboot=1 setupmode=0 PK={_sha('PK')}",
                "N7A STATE boot2 secureboot=0 setupmode=1 PK=absent",
            )(log),
            {"reboot.secureboot", "reboot.setupmode", "reboot.PK"},
        ),
        (
            "an efivarfs write changes KEK in the same boot",
            _replace_once(
                f"N7A STATE post secureboot=1 setupmode=0 PK={_sha('PK')} KEK={_sha('KEK')}",
                f"N7A STATE post secureboot=1 setupmode=0 PK={_sha('PK')} KEK={'0' * 64}",
            ),
            {"A.post.KEK"},
        ),
        (
            "the probe chain-load returned",
            _replace_once(
                "N7PROBE END v1\r\n",
                f"N7PROBE END v1\r\nN7PROBE CHAIN sdboot status={NF}\r\n",
            ),
            {"probe.runs"},
        ),
    ],
)
def test_each_failure_turns_exactly_its_rows_red(
    wt: ModuleType,
    expect: dict[str, object],
    case: str,
    mutate: Mutation,
    red: set[str],
) -> None:
    got = _eval(wt, expect, mutate(_green()))
    assert _failed(got) == red, case


def test_a_changed_uboot_binary_is_red(
    wt: ModuleType, expect: dict[str, object]
) -> None:
    other = "0" * 64
    for sha in ((UBOOT_SHA, other, UBOOT_SHA), (other, other, UBOOT_SHA)):
        got = _eval(wt, expect, _green(), sha=sha)
        assert _failed(got) == {"uboot.sha256"}


def test_no_probe_output_fails_every_probe_row(
    wt: ModuleType, expect: dict[str, object]
) -> None:
    got = _eval(wt, expect, _green(probe=False), probe=True)
    assert _failed(got) == {r for r in got if r.startswith("probe.")}


def test_a_missing_second_boot_fails_the_reboot_rows(
    wt: ModuleType, expect: dict[str, object]
) -> None:
    log = _boot(1, "u-boot", True)
    got = _eval(wt, expect, log)
    assert {r for r in got if r.startswith("reboot.")} <= _failed(got)
    assert "probe.boot2.PK" in _failed(got)
    assert "A0.PK" not in _failed(got)


def test_aavmf_counts_kernel_banners_only(
    wt: ModuleType, expect: dict[str, object]
) -> None:
    got = _eval(wt, expect, _green(firmware="aavmf"), firmware="aavmf")
    assert _failed(got) == set()


def test_render_prints_one_line_per_row_and_the_verdict(
    wt: ModuleType, expect: dict[str, object]
) -> None:
    log = _replace_once("mount=ro efi_test=absent", "mount=ro efi_test=present")(
        _green()
    )
    results = wt.evaluate(
        log,
        firmware="u-boot",
        probe=True,
        expect=expect,
        uboot_sha=(UBOOT_SHA, UBOOT_SHA, UBOOT_SHA),
    )
    lines = wt.render(results).splitlines()
    assert len(lines) == len(results) + 1
    assert lines[-1] == "N7 VERDICT FAIL"
    assert any(ln.startswith("N7 ROW A0.efi_test FAIL ") for ln in lines)
    assert any(ln.startswith("N7 ROW A0.PK PASS") for ln in lines)


# --- output that follows the prompt on the same line ----------------------
#
# After `stty -echo` the typed Enter is not echoed, so the first line a
# command prints starts right after the prompt (the real console is in
# fixtures/n7-serial-real.log).  The parser takes such a line, and the
# kernel banner carries its log timestamp.


@pytest.mark.parametrize("probe", [True, False])
def test_the_first_n7a_line_after_a_prompt_still_counts(
    wt: ModuleType, expect: dict[str, object], probe: bool
) -> None:
    log = _green(firmware="aavmf", probe=probe)
    glued = _sub_all("# \r\nN7A STATE", "# N7A STATE")(log)
    assert glued.count("# N7A STATE") == 2
    got = _eval(wt, expect, glued, firmware="aavmf", probe=probe)
    assert _failed(got) == set(), got


def test_the_first_n7probe_line_after_other_text_still_counts(
    wt: ModuleType, expect: dict[str, object]
) -> None:
    glued = _sub_all("':\r\nN7PROBE BEGIN v1", "':N7PROBE BEGIN v1")(_green())
    assert glued.count("':N7PROBE BEGIN") == 2
    got = _eval(wt, expect, glued)
    assert _failed(got) == set(), got


def test_kernel_banner_carries_its_log_timestamp(wt: ModuleType) -> None:
    log = "[    0.000000] Booting Linux on physical CPU 0x0000000000 [0x411fd070]\r\n"
    assert len(wt.KERNEL_BANNER.findall(log)) == 1
