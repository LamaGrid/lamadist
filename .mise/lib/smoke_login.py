#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Drive a real login over a QEMU serial unix socket and assert
command execution.

Usage: smoke_login.py SOCKET USER PASSWORD TIMEOUT_SECONDS

Asserts, in order:
1. a getty login prompt appears;
2. the user can log in (handling a forced password change too,
   should an image ever ship with an expired password);
3. the shell executes commands (catches the 2026-07-14 defect
   class: unlabeled rootfs + enforcing SELinux denying every exec);
4. PID 1 runs in a real SELinux domain, not kernel_t (catches an
   unlabeled rootfs even in permissive mode);
5. sshd is listening on :22;
6. root (/) is mounted erofs (M4 W1: verity-sealed EROFS root,
   replacing ext4);
7. /var is mounted from an unlocked LUKS2 dm-crypt mapper, not the
   raw partition (M4 W4: lamadist-luks-var first-boot format);
8. /etc is an active overlay mount (M4 W5: overlayfs-etc, upper on
   the LUKS-backed /var) AND is mounted read-write -- overlayfs
   silently falls back to a read-only mount when its workdir setup
   fails (the Condition B harvest caught exactly that: a
   dontaudit-hidden mount_t var_t:dir denial left /etc RO on every
   boot, breaking machine-id persistence and /etc config writes,
   with the gate none the wiser).

Exit 0 on success, 1 on failure (with the transcript tail on
stderr).

The `SerialSession` class and `login()` function below are the
reusable expect-style serial-console machinery; other drivers
(e.g. .mise/lib/ota_test.py) import them instead of re-implementing
socket handling.
"""

import re
import socket
import sys
import time


class SerialTimeoutError(RuntimeError):
    """An expected serial pattern never appeared before the deadline."""


class SerialSession:
    """Minimal expect-style driver for a QEMU serial console exposed
    as a unix domain socket (chardev socket,server=on,wait=off)."""

    def __init__(self, sock_path: str, timeout: float):
        self.sock_path = sock_path
        self.deadline = time.monotonic() + timeout
        self.transcript = bytearray()
        self._consumed = 0  # transcript offset already matched by expect()
        self._sock: "socket.socket | None" = None

    def connect(self) -> None:
        while time.monotonic() < self.deadline:
            try:
                s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                s.connect(self.sock_path)
                self._sock = s
                return
            except OSError:
                time.sleep(0.5)
        raise SerialTimeoutError(
            f"could not connect to serial socket {self.sock_path}"
        )

    def expect(self, patterns: "list[str]", what: str) -> int:
        """Wait until any pattern matches unconsumed output; return
        its index and consume through the end of the match."""
        idx, _match = self.expect_capture(patterns, what)
        return idx

    def expect_capture(
        self, patterns: "list[str]", what: str
    ) -> "tuple[int, re.Match[str]]":
        """As expect(), but also return the match object so callers
        can pull capture groups (e.g. a slot letter) out of it."""
        assert self._sock is not None, "connect() not called"
        regexes = [re.compile(p, re.M) for p in patterns]
        while time.monotonic() < self.deadline:
            text = self.transcript[self._consumed :].decode("utf-8", "replace")
            for i, rx in enumerate(regexes):
                m = rx.search(text)
                if m:
                    self._consumed += len(text[: m.end()].encode("utf-8", "replace"))
                    return i, m
            self._sock.settimeout(1.0)
            try:
                data = self._sock.recv(4096)
                if data:
                    self.transcript.extend(data)
            except TimeoutError:
                pass
            except OSError as exc:
                raise SerialTimeoutError(
                    f"serial socket error while waiting for {what}: {exc}"
                ) from exc
        raise SerialTimeoutError(f"timeout waiting for {what}")

    # QEMU's emulated 16550 overruns when a whole line lands in one
    # burst: the guest drains a 16-byte RX FIFO under interrupt while
    # the line discipline echoes every byte back, and once input
    # outpaces that, bytes get dropped or doubled.  Observed live:
    # mangled command echoes ("$(((7004*3))"), a journalctl whose
    # "--no-pager | tail" suffix never arrived, and -- the smoke
    # killer -- a 293-char assertion line corrupted into an
    # unbalanced quote that left bash silently waiting at PS2
    # forever.  Pace input like expect's `send -s`: FIFO-sized
    # chunks with a breather for the guest to drain and echo.
    _SEND_CHUNK = 16
    _SEND_DELAY = 0.02

    def send(self, line: str) -> None:
        assert self._sock is not None, "connect() not called"
        data = line.encode() + b"\n"
        for i in range(0, len(data), self._SEND_CHUNK):
            self._sock.sendall(data[i : i + self._SEND_CHUNK])
            time.sleep(self._SEND_DELAY)

    def tail(self, n: int = 4000) -> str:
        return self.transcript[-n:].decode("utf-8", "replace")


def login(session: SerialSession, user: str, password: str) -> str:
    """Drive a getty login prompt to a shell, handling a forced
    password change transparently.  Returns the password actually in
    effect afterward (changed if the image forced an expiry)."""
    new_password = password + "-Sm0ke!"

    session.expect([r"login:"], "login prompt")
    session.send(user)
    session.expect([r"Password:"], "password prompt")
    session.send(password)

    while True:
        idx = session.expect(
            [
                r"Current password:",
                r"Retype new password:",
                r"New password:",
                r"\$ ?$|Last login",
                r"Login incorrect",
            ],
            "shell after login",
        )
        if idx == 0:
            session.send(password)
        elif idx == 1:
            session.send(new_password)
            password = new_password
        elif idx == 2:
            session.send(new_password)
        elif idx == 3:
            return password
        else:
            raise SerialTimeoutError("login rejected (Login incorrect)")


def main() -> None:
    sock_path, user, password = sys.argv[1], sys.argv[2], sys.argv[3]
    timeout = int(sys.argv[4])
    secureboot = len(sys.argv) > 5 and sys.argv[5] == "secureboot"

    session = SerialSession(sock_path, timeout)
    try:
        session.connect()
        password = login(session, user, password)

        # Give the getty/shell handoff a moment; the tty line
        # discipline buffers input typed early anyway.
        time.sleep(2)

        # The quoted marker keeps the echoed command line from
        # matching the expected output.  Full path: sbin is not on
        # the non-root PATH.
        session.send(
            'echo SMOKE_"OK"; cat /proc/1/attr/current; /usr/sbin/ss -ltn'
        )
        session.expect([r"SMOKE_OK"], "command execution (exec on rootfs)")

        idx = session.expect(
            [r"kernel_t|^kernel\s*$", r"\w+_t[:\s]"],
            "PID 1 SELinux domain",
        )
        if idx == 0:
            raise SerialTimeoutError(
                "PID 1 still in kernel_t: rootfs unlabeled or policy not loaded"
            )

        session.expect([r":22\b"], "sshd listening on :22")

        # Hardening assertions (M4 stage A): erofs root, /etc overlay,
        # /var on an unlocked LUKS2 mapper.  Read straight from
        # /proc/mounts with bash builtins (read/case) plus coreutils
        # (cat, readlink, basename) only -- findmnt/lsblk live in
        # util-linux's per-binary split packages
        # (util-linux-findmnt/-lsblk) that packagegroup-lamadist-base
        # does not currently RDEPENDS on, and no other recipe in the
        # base image RDEPENDS on util-linux-findmnt/-lsblk either.
        # The dm/uuid check
        # distinguishes a LUKS2 crypt mapper from e.g. the rootfs
        # verity mapper, which also lives under /dev/mapper.
        # Nothing pins the four markers below to a fixed emission
        # order -- it only holds today because /etc's overlay upperdir
        # lives on /var (D5), so /var must mount before /etc can, and
        # root always mounts earliest.  Matching them with four
        # sequential expect() calls would be a trap: expect() consumes
        # the transcript up to its match, so an out-of-order marker
        # would get silently skipped by an earlier call and then
        # time out on its own (later) call with a misleading message.
        # Emit a single sentinel after the loop instead, wait for it
        # once, then match all four patterns against that fixed block
        # of text with plain re.search() -- order-independent.
        mounts_offset = len(session.transcript)
        session.send(
            "while read -r _d _m _f _o _x _y; do "
            'case "$_m" in '
            '"/") echo ROOTFS_FSTYPE_"$_f" ;; '
            '"/etc") echo ETC_FSTYPE_"$_f"; echo ETC_OPTS_"$_o" ;; '
            '"/var") echo VAR_SOURCE_"$_d"; '
            'echo VAR_DM_UUID_"$(cat /sys/class/block/"$(basename "$(readlink -f "$_d")")"/dm/uuid 2>/dev/null)" ;; '
            'esac; done < /proc/mounts; echo MOUNTS_"DONE"'
        )
        # The quoted marker (as with SMOKE_"OK" above) keeps the
        # echoed command line from satisfying this expect -- only the
        # loop's real output can, so mounts_text below is guaranteed
        # to contain the full marker block.
        session.expect([r"MOUNTS_DONE\b"], "the /proc/mounts dump to finish")
        mounts_text = session.transcript[mounts_offset:].decode("utf-8", "replace")

        for pattern, what in (
            (r"ROOTFS_FSTYPE_erofs\b", "root filesystem is erofs"),
            (
                r"VAR_SOURCE_/dev/mapper/var\b",
                "/var is backed by the dm-mapper var device",
            ),
            (
                r"VAR_DM_UUID_.*LUKS2",
                "/var mapper is an unlocked LUKS2 device, not raw/verity",
            ),
            (r"ETC_FSTYPE_overlay\b", "/etc overlay is mounted"),
            # /proc/mounts options always lead with rw or ro; an
            # overlay whose workdir setup failed mounts ro.
            (r"ETC_OPTS_rw(,|\b)", "/etc overlay is mounted read-write"),
        ):
            if not re.search(pattern, mounts_text, re.M):
                raise SerialTimeoutError(f"timeout waiting for {what}")

        # Stage-B assertion (M4.B): the guest itself must report
        # Secure Boot enabled -- selecting SB firmware host-side is
        # not proof (a mis-enrolled or drifted vars file boots with
        # SB off and everything still loads).  Byte 5 of the
        # SecureBoot efivar (4 attribute bytes + 1 value byte) is 1
        # when enforcing.  The quoted marker keeps the echoed
        # command from matching, as elsewhere.
        if secureboot:
            session.send(
                'echo SB_"STATE"_$(od -An -tu1 -j4 -N1 '
                "/sys/firmware/efi/efivars/"
                "SecureBoot-8be4df61-93ca-11d2-aa0d-00e098032b8c"
                ' | tr -d " ")'
            )
            session.expect(
                [r"SB_STATE_1\b"], "Secure Boot enabled in-guest (efivar)"
            )
    except SerialTimeoutError as exc:
        print(f"SMOKE FAIL: {exc}", file=sys.stderr)
        print("---- serial transcript tail ----", file=sys.stderr)
        print(session.tail(), file=sys.stderr)
        sys.exit(1)

    print(
        "SMOKE PASS: login, exec, SELinux domain, sshd, erofs root, "
        "LUKS var, and rw etc overlay all OK"
    )
    sys.exit(0)


if __name__ == "__main__":
    main()
