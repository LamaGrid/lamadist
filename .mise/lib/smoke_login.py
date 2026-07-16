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
5. sshd is listening on :22.

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

    def send(self, line: str) -> None:
        assert self._sock is not None, "connect() not called"
        self._sock.sendall(line.encode() + b"\n")

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
    except SerialTimeoutError as exc:
        print(f"SMOKE FAIL: {exc}", file=sys.stderr)
        print("---- serial transcript tail ----", file=sys.stderr)
        print(session.tail(), file=sys.stderr)
        sys.exit(1)

    print("SMOKE PASS: login, exec, SELinux domain, and sshd all OK")
    sys.exit(0)


if __name__ == "__main__":
    main()
