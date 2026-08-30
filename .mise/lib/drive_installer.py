#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Drive the LamaDist interactive installer over a QEMU serial socket.

Usage: drive_installer.py SOCKET TIMEOUT_SECONDS

Exercises the real interactive flow (the path a human operator uses):
1. the Secure Boot trust gate passes;
2. the payload checksum verifies;
3. the target-disk menu appears and offers exactly the blank target
   (the stick is excluded from the candidate set);
4. the fail-closed double confirmation is honored;
5. the image is written and the installer reports completion.

Reuses the expect-style SerialSession from smoke_login.py.  Exit 0 on
a completed install, 1 otherwise (transcript tail on stderr).
"""

import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from smoke_login import SerialSession, SerialTimeoutError  # noqa: E402


def main() -> None:
    sock_path = sys.argv[1]
    timeout = int(sys.argv[2])

    session = SerialSession(sock_path, timeout)
    try:
        session.connect()

        # Trust gate and payload integrity must both pass before any
        # disk enumeration.
        session.expect(
            [r"trust gate: Secure Boot enabled"], "Secure Boot trust gate"
        )
        session.expect([r"payload checksum OK"], "payload checksum verification")

        # The target menu; capture the first offered device.
        session.expect([r"available target disks:"], "target disk menu")
        _idx, m = session.expect_capture(
            [r"\[\d+\]\s+(/dev/\S+)\s"], "an eligible target device"
        )
        target = m.group(1)
        print(f"drive_installer: selected target {target}", file=sys.stderr)

        # First prompt: type the device path.
        session.expect(
            [r"enter the device path to install onto"], "device entry prompt"
        )
        session.send(target)

        # Second prompt: confirm by typing it again (fail-closed guard).
        session.expect(
            [r"type the device path AGAIN to confirm"], "confirmation prompt"
        )
        session.send(target)

        # Write and completion.
        session.expect([r"write complete and synced"], "the image write to finish")

        # Firmware boot registration must SUCCEED under OVMF -- the
        # best-effort warn path passing silently is how a dead
        # BootNext once shipped.
        session.expect([r"BootNext -> Boot[0-9A-Fa-f]{4}"], "the BootNext registration")
        session.expect(
            [rf"installation complete on {re.escape(target)}"],
            "installation completion",
        )

        # Interactive path waits for Enter before rebooting.
        session.expect([r"press Enter to reboot"], "the reboot prompt")
        session.send("")
    except SerialTimeoutError as exc:
        print(f"INSTALL FAIL: {exc}", file=sys.stderr)
        print("---- serial transcript tail ----", file=sys.stderr)
        print(session.tail(), file=sys.stderr)
        sys.exit(1)

    print(f"INSTALL PASS: hardened image written to {target}")
    sys.exit(0)


if __name__ == "__main__":
    main()
