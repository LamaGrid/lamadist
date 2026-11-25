#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Key-flood test for the systemd-boot menu under the U-Boot payload.

ADR 0013 decision 3: the SOQuartz leaf hides the systemd-boot menu on
the serial console.  A timeout of 0 hides it but keeps a 100 ms key
read, and one byte in that read opens a menu that has no time limit.
`menu-disabled` skips the read (systemd boot.c, run(): the key read sits
in the branch that `menu-disabled` never enters).  This driver shows the
difference on a headless qemuarm64 guest started with
`vm --firmware u-boot --no-tpm --headless --snapshot`.

`run` connects to the guest's serial socket, sends one harmless byte
every INTERVAL seconds from the moment it connects, and stops when the
transcript shows the menu or the kernel.  `--expect menu` is the RED
shape (timeout 0): the menu rows are drawn and the kernel does not boot
for HOLD seconds.  `--expect no-menu` is the GREEN shape
(menu-disabled): the menu rows are never drawn and the default entry
boots to a login prompt.  `verdict` re-reads a saved serial log.

The verdict is a pure function of the serial transcript (evaluate()).
The flood byte is not a digit (a digit selects an entry and boots it
without a menu) and not a menu key.
"""

from __future__ import annotations

import argparse
import re
import socket
import sys
import time
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Protocol

FLOOD_BYTE: Final = b"x"
EXPECTS: Final = ("menu", "no-menu")

UBOOT_BANNER: Final = re.compile(r"^U-Boot \d{4}\.\d{2}", re.MULTILINE)
UBOOT_PROMPT: Final = re.compile(r"^=> ", re.MULTILINE)
# The menu row systemd-boot draws for slot A: title, then the entry id
# (the +3 boot counter is not part of the id).  Nothing but the menu
# prints this pair.
MENU_ROW: Final = re.compile(r"LamaDist \(slot a\) \(lamadist-a\.conf\)")
KERNEL_BANNER: Final = re.compile(
    r"^(?:\[\s*\d+\.\d+\] )?Booting Linux on physical CPU", re.MULTILINE
)
LOGIN_PROMPT: Final = re.compile(r"login:")


@dataclass(frozen=True, slots=True)
class Result:
    row: str
    ok: bool
    detail: str


def evaluate(text: str, expect: str) -> list[Result]:
    """The rows for one transcript; every row must pass."""
    if expect not in EXPECTS:
        raise ValueError(f"expect must be one of {EXPECTS}, not {expect!r}")
    menu = MENU_ROW.search(text) is not None
    kernel = KERNEL_BANNER.search(text) is not None
    login = LOGIN_PROMPT.search(text) is not None
    rows = [
        Result("uboot", UBOOT_BANNER.search(text) is not None, "U-Boot banner seen"),
        Result("no_prompt", UBOOT_PROMPT.search(text) is None, "no U-Boot prompt"),
    ]
    if expect == "menu":
        rows.append(Result("menu_opens", menu, f"menu rows drawn={menu}"))
        rows.append(
            Result("menu_holds", menu and not kernel, f"kernel booted={kernel}")
        )
    else:
        rows.append(Result("no_menu", not menu, f"menu rows drawn={menu}"))
        rows.append(
            Result(
                "default_boots",
                kernel and login,
                f"kernel banner={kernel} login prompt={login}",
            )
        )
    return rows


def render(rows: Sequence[Result], expect: str) -> str:
    lines = [f"ROW {r.row} {'PASS' if r.ok else 'FAIL'} {r.detail}" for r in rows]
    verdict = "PASS" if all(r.ok for r in rows) else "FAIL"
    lines.append(f"VERDICT {verdict} expect={expect}")
    return "\n".join(lines) + "\n"


class SockLike(Protocol):
    def settimeout(self, value: float | None, /) -> None: ...
    def sendall(self, data: bytes, /) -> None: ...
    def recv(self, size: int, /) -> bytes: ...


def flood(
    sock: SockLike, expect: str, timeout: float, hold: float, interval: float
) -> str:
    """Send FLOOD_BYTE every `interval` seconds until the first outcome.

    Returns the transcript.  The sender stops at the first menu row or
    kernel banner, so the flood never reaches the booted system.
    """
    deadline = time.monotonic() + timeout
    transcript = bytearray()
    sending = True
    next_send = 0.0
    menu_at: float | None = None
    menu = kernel = login = False
    sock.settimeout(0.1)
    while time.monotonic() < deadline:
        now = time.monotonic()
        if sending and now >= next_send:
            try:
                sock.sendall(FLOOD_BYTE)
            except TimeoutError:
                pass  # the socket buffer is full: the guest is not reading yet
            next_send = now + interval
        try:
            data: bytes | None = sock.recv(4096)
        except TimeoutError:
            data = None
        if data == b"":
            break  # QEMU closed the socket
        if data:
            transcript.extend(data)
            text = transcript.decode("utf-8", "replace")
            menu = MENU_ROW.search(text) is not None
            kernel = KERNEL_BANNER.search(text) is not None
            login = LOGIN_PROMPT.search(text) is not None
            if menu or kernel:
                sending = False
            if menu and menu_at is None:
                menu_at = time.monotonic()
        if expect == "menu":
            if kernel or (menu_at is not None and time.monotonic() - menu_at >= hold):
                break
        elif menu or (kernel and login):
            break
    return transcript.decode("utf-8", "replace")


def _connect(path: str, timeout: float) -> socket.socket:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            s.connect(path)
        except OSError:
            s.close()
            time.sleep(0.2)
        else:
            return s
    raise ConnectionError(f"could not connect to serial socket {path}")


def _report(text: str, expect: str, out: str | None) -> int:
    rows = evaluate(text, expect)
    report = render(rows, expect)
    sys.stdout.write(report)
    if out:
        Path(out).write_text(report)
    return 0 if all(r.ok for r in rows) else 1


def _run(args: argparse.Namespace) -> int:
    sock = _connect(args.serial_sock, args.timeout)
    try:
        text = flood(sock, args.expect, args.timeout, args.hold, args.interval)
    finally:
        sock.close()
    return _report(text, args.expect, args.out)


def main(argv: Sequence[str]) -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").split("\n", 1)[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--expect", choices=EXPECTS, required=True)
    common.add_argument("--out")
    run = sub.add_parser("run", parents=[common])
    run.add_argument("--serial-sock", required=True)
    run.add_argument("--timeout", type=float, default=900.0)
    run.add_argument("--hold", type=float, default=30.0)
    run.add_argument("--interval", type=float, default=0.1)
    verdict = sub.add_parser("verdict", parents=[common])
    verdict.add_argument("log")
    args = ap.parse_args(argv[1:])
    if args.cmd == "run":
        return _run(args)
    return _report(Path(args.log).read_text(errors="replace"), args.expect, args.out)


if __name__ == "__main__":
    sys.exit(main(sys.argv))
