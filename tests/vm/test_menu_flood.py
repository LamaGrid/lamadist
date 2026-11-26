# SPDX-License-Identifier: Apache-2.0
"""Tests for the systemd-boot menu key flood (.mise/lib/menu_flood.py).

The verdict is a pure function of the serial transcript, and the sender
runs against a fake socket, so no VM starts.  The transcripts follow the
real U-Boot payload console (window i's serial log): the U-Boot banner,
the load of BOOTAA64.EFI, then either systemd-boot's menu rows or the
kernel.  The real run is the QEMU RED (timeout 0, `--expect menu`) and
GREEN (menu-disabled, `--expect no-menu`) boots of the payload image.
"""

from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[2]
LIB = ROOT / ".mise" / "lib"

UBOOT = (
    "\r\n\r\nU-Boot 2026.01 (Jan 05 2026 - 20:49:22 +0000)\r\n\r\n"
    "DRAM:  2 GiB\r\nNet:   eth0: virtio-net#33\r\n"
    "Programmatic boot starting\r\nBootmeths:  efi\r\n"
    "** Booting bootflow 'virtio-blk#32.bootdev.part_1' with efi\r\n"
    "Using prior-stage device tree\r\n"
    "Booting /\\EFI\\BOOT\\BOOTAA64.EFI\r\n"
)
MENU = (
    "\x1b[?25l\r \r\x1b[2J\x1b[1;1H\x1b[12;20H\x1b[1;30;47m"
    "   LamaDist (slot a) (lamadist-a.conf)   "
    "\x1b[13;20H\x1b[1;37;40m      LamaDist (slot a) (boot.conf)      \r\n"
    "\x1b[15;1H Boot in 5 s.\r\n"
)
KERNEL = (
    "[    0.000000] Booting Linux on physical CPU 0x0000000000 [0x411fd070]\r\n"
    "[    0.000000] Linux version 6.18.35 (oe-user@oe-host)\r\n"
)
LOGIN = "\r\nqemuarm64-lamadist login: "
PROMPT = "\r\n=> "


@pytest.fixture(scope="module")
def mf() -> ModuleType:
    sys.path.insert(0, str(LIB))
    spec = importlib.util.spec_from_file_location("menu_flood", LIB / "menu_flood.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["menu_flood"] = mod
    spec.loader.exec_module(mod)
    return mod


def _failed(mf: ModuleType, text: str, expect: str) -> set[str]:
    return {r.row for r in mf.evaluate(text, expect) if not r.ok}


# --- the verdict ------------------------------------------------------------


def test_the_red_shape_is_a_menu_that_holds(mf: ModuleType) -> None:
    assert _failed(mf, UBOOT + MENU, "menu") == set()


def test_the_green_shape_is_a_default_boot_with_no_menu(mf: ModuleType) -> None:
    assert _failed(mf, UBOOT + KERNEL + LOGIN, "no-menu") == set()


def test_red_fails_on_a_run_that_never_opens_the_menu(mf: ModuleType) -> None:
    assert _failed(mf, UBOOT + KERNEL + LOGIN, "menu") == {"menu_opens", "menu_holds"}


def test_green_fails_when_the_flood_opens_the_menu(mf: ModuleType) -> None:
    assert _failed(mf, UBOOT + MENU, "no-menu") == {"no_menu", "default_boots"}


def test_red_fails_when_the_menu_does_not_hold(mf: ModuleType) -> None:
    assert _failed(mf, UBOOT + MENU + KERNEL, "menu") == {"menu_holds"}


def test_green_needs_the_login_prompt_not_just_the_kernel(mf: ModuleType) -> None:
    assert _failed(mf, UBOOT + KERNEL, "no-menu") == {"default_boots"}


@pytest.mark.parametrize("expect", ["menu", "no-menu"])
def test_a_u_boot_prompt_fails_both_shapes(mf: ModuleType, expect: str) -> None:
    text = UBOOT + (MENU if expect == "menu" else KERNEL + LOGIN) + PROMPT
    assert _failed(mf, text, expect) == {"no_prompt"}


def test_a_transcript_without_the_firmware_banner_fails(mf: ModuleType) -> None:
    assert "uboot" in _failed(mf, MENU, "menu")


def test_the_other_boot_entry_alone_is_not_the_menu(mf: ModuleType) -> None:
    """The menu is the pair of title and entry id, which only it prints."""
    assert not mf.MENU_ROW.search("LamaDist (slot a) title only\r\n")
    assert not mf.MENU_ROW.search("lamadist.slot=a root=PARTLABEL=rootfs_a")


def test_an_unknown_expectation_is_refused(mf: ModuleType) -> None:
    with pytest.raises(ValueError):
        mf.evaluate(UBOOT, "hidden")


def test_the_report_ends_with_one_verdict_line(mf: ModuleType) -> None:
    rows = mf.evaluate(UBOOT + MENU, "menu")
    assert mf.render(rows, "menu").splitlines()[-1] == "VERDICT PASS expect=menu"
    rows = mf.evaluate(UBOOT + MENU, "no-menu")
    assert mf.render(rows, "no-menu").splitlines()[-1] == "VERDICT FAIL expect=no-menu"


# --- the sender -------------------------------------------------------------


class FakeSock:
    """A guest that answers the first byte with scripted output chunks."""

    def __init__(self, chunks: list[str]) -> None:
        self.chunks = [c.encode() for c in chunks]
        self.sent = bytearray()
        self.sent_when_released = 0

    def settimeout(self, _value: float | None, /) -> None:
        pass

    def close(self) -> None:
        pass

    def sendall(self, data: bytes, /) -> None:
        self.sent += data

    def recv(self, _size: int, /) -> bytes:
        if not self.sent or not self.chunks:
            raise TimeoutError
        self.sent_when_released = len(self.sent)
        return self.chunks.pop(0)


def test_the_sender_sends_only_the_flood_byte(mf: ModuleType) -> None:
    sock = FakeSock([UBOOT, MENU])
    mf.flood(sock, "menu", timeout=5, hold=0.05, interval=0.001)
    assert set(sock.sent) == set(mf.FLOOD_BYTE)
    # A digit selects an entry without a menu, and Q quits the loader.
    assert not any(chr(b).isdigit() for b in sock.sent)
    assert b"Q" not in sock.sent


def test_the_sender_stops_when_the_menu_opens(mf: ModuleType) -> None:
    sock = FakeSock([UBOOT, MENU])
    text = mf.flood(sock, "menu", timeout=5, hold=0.2, interval=0.001)
    assert len(sock.sent) == sock.sent_when_released
    assert mf.MENU_ROW.search(text)


def test_the_sender_stops_when_the_kernel_starts(mf: ModuleType) -> None:
    sock = FakeSock([UBOOT, KERNEL, LOGIN])
    text = mf.flood(sock, "no-menu", timeout=5, hold=0.05, interval=0.001)
    assert len(sock.sent) <= sock.sent_when_released
    assert not _failed(mf, text, "no-menu")


def test_a_closed_socket_ends_the_run_with_what_was_read(mf: ModuleType) -> None:
    class Closed(FakeSock):
        def recv(self, size: int, /) -> bytes:
            return super().recv(size) if self.chunks else b""

    text = mf.flood(Closed([UBOOT]), "no-menu", timeout=5, hold=0.05, interval=0.001)
    assert "U-Boot 2026.01" in text
    assert "default_boots" in _failed(mf, text, "no-menu")


# --- run: the socket and the log --------------------------------------------

# What the guest printed before a driver that starts late can connect, and
# what an in-time driver reads from the socket (the log holds all of it).
LOADER_START = "Booting /\\EFI\\BOOT\\BOOTAA64.EFI\r\n"
IN_TIME = [LOADER_START, KERNEL, LOGIN]


def _run(
    mf: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    chunks: list[str],
    *extra: str,
    expect: str = "no-menu",
) -> int:
    """`run` against a fake socket that carries `chunks`."""
    sock = FakeSock(chunks)
    monkeypatch.setattr(mf, "_connect", lambda _path, _timeout: sock)
    argv = ["menu_flood.py", "run", "--serial-sock", "unused", "--expect", expect]
    return mf.main([*argv, "--timeout", "0.5", "--interval", "0.001", *extra])


def _log(tmp_path: Path, text: str) -> str:
    """Write a serial log, byte for byte, and return its path."""
    path = tmp_path / "serial.log"
    path.write_bytes(text.encode())
    return str(path)


def test_run_passes_when_the_flood_was_there_before_systemd_boot(
    mf: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    log = _log(tmp_path, UBOOT + KERNEL + LOGIN)
    assert _run(mf, monkeypatch, IN_TIME, "--log", log) == 0
    out = capsys.readouterr().out
    for row in ("uboot", "same_boot", "flood_in_time", "default_boots"):
        assert f"ROW {row} PASS" in out
    assert out.splitlines()[-1] == "VERDICT PASS expect=no-menu"


@pytest.mark.parametrize(
    "chunks",
    [
        pytest.param([KERNEL, LOGIN], id="after-systemd-boot"),
        pytest.param([LOGIN], id="after-the-kernel"),
    ],
)
def test_a_late_start_fails_although_the_log_is_clean(
    mf: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    chunks: list[str],
) -> None:
    """The log of a clean boot must not pass a flood that came too late."""
    log = _log(tmp_path, UBOOT + KERNEL + LOGIN)
    assert _run(mf, monkeypatch, chunks, "--log", log) == 1
    out = capsys.readouterr().out
    assert "ROW flood_in_time FAIL" in out
    assert "ROW uboot PASS" in out
    assert out.splitlines()[-1] == "VERDICT FAIL expect=no-menu"


def test_run_fails_when_the_socket_is_not_part_of_the_log(
    mf: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A log that does not hold the socket's bytes fails: a cut log."""
    log = _log(tmp_path, UBOOT + KERNEL)
    assert _run(mf, monkeypatch, IN_TIME, "--log", log) == 1
    assert "ROW same_boot FAIL" in capsys.readouterr().out


@pytest.mark.parametrize("expect", ["menu", "no-menu"])
def test_a_silent_socket_is_not_part_of_any_log(
    mf: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    expect: str,
) -> None:
    """An empty transcript is inside every log, so the row must refuse it."""
    log = _log(tmp_path, UBOOT + (MENU if expect == "menu" else KERNEL + LOGIN))
    assert _run(mf, monkeypatch, [], "--log", log, expect=expect) == 1
    assert "ROW same_boot FAIL" in capsys.readouterr().out


def test_same_boot_cannot_tell_two_boots_with_the_same_bytes_apart(
    mf: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Containment only: two `timeout 0` boots print the same bytes to the menu."""
    log = _log(tmp_path, UBOOT + MENU)
    args = ("--log", log, "--hold", "0.05")
    assert _run(mf, monkeypatch, [UBOOT, MENU], *args, expect="menu") == 0
    assert "ROW same_boot PASS" in capsys.readouterr().out


def test_the_flood_must_come_before_the_kernel_banner(
    mf: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A late start that sees only a second boot's loader start must fail."""
    chunks = [KERNEL, LOADER_START, KERNEL, LOGIN]
    log = _log(tmp_path, UBOOT + "".join(chunks))
    assert _run(mf, monkeypatch, chunks, "--log", log) == 1
    out = capsys.readouterr().out
    assert "ROW flood_in_time FAIL" in out
    assert "ROW same_boot PASS" in out


def test_run_compares_the_socket_with_the_log_byte_for_byte(
    mf: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Carriage returns count: the log read as text would lose them."""
    log = _log(tmp_path, (UBOOT + KERNEL + LOGIN).replace("\r\n", "\n"))
    assert _run(mf, monkeypatch, IN_TIME, "--log", log) == 1
    assert "ROW same_boot FAIL" in capsys.readouterr().out


def test_a_named_log_that_is_missing_is_an_error(
    mf: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    missing = str(tmp_path / "missing.log")
    assert _run(mf, monkeypatch, IN_TIME, "--log", missing) == 2
    seen = capsys.readouterr()
    assert "missing.log" in seen.err
    assert "VERDICT" not in seen.out


def test_run_without_a_log_sees_only_the_socket(
    mf: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert _run(mf, monkeypatch, IN_TIME) == 1
    out = capsys.readouterr().out
    assert "ROW uboot FAIL" in out
    assert "same_boot" not in out


def test_verdict_alone_cannot_tell_a_flooded_boot(mf: ModuleType) -> None:
    """`verdict` reads a log only, so it has no socket rows."""
    rows = {r.row for r in mf.evaluate(UBOOT + KERNEL + LOGIN, "no-menu")}
    assert rows == {"uboot", "no_prompt", "no_menu", "default_boots"}


def test_the_menu_run_needs_no_flood_row(mf: ModuleType) -> None:
    """A menu that opened needs a flood byte; `menu` has no late-start row."""
    rows = {r.row for r in mf.evaluate(UBOOT + MENU, "menu", UBOOT + MENU, True)}
    assert rows == {"uboot", "no_prompt", "menu_opens", "menu_holds", "same_boot"}


def test_the_menu_row_is_what_the_class_entries_draw(mf: ModuleType) -> None:
    """The class gives both entries one title, so the menu draws "title (id)"."""
    src = (ROOT / "meta-lamadist/classes/lamadist-esp-slot-a.bbclass").read_text()
    (title,) = re.findall(r'"title\s+(.+?)\\n"', src)
    names = re.findall(r"os\.path\.join\(entries_dir, '([^']+)'\)", src)
    assert names == ["lamadist-a+3.conf", "boot.conf"]
    assert len(re.findall(r"f\.write\((?:[^)]*\+ )?entry\)", src)) == 2
    ids = [re.sub(r"\+\d+(?=\.conf$)", "", n) for n in names]
    assert mf.MENU_ROW.search(f"{title} ({ids[0]})")
    assert f"{title} ({ids[1]})" in MENU


def test_the_run_gives_up_at_the_timeout(mf: ModuleType) -> None:
    sock = FakeSock([UBOOT])
    text = mf.flood(sock, "menu", timeout=0.1, hold=30, interval=0.001)
    assert "U-Boot 2026.01" in text
    assert "menu_opens" in _failed(mf, text, "menu")
