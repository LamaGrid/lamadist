#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Drive a real login over a QEMU serial unix socket and assert
command execution.

Usage: _smoke_login.py SOCKET USER PASSWORD TIMEOUT_SECONDS

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
"""

import re
import socket
import sys
import time

SOCK_PATH, USER, PASSWORD = sys.argv[1], sys.argv[2], sys.argv[3]
TIMEOUT = int(sys.argv[4])
NEW_PASSWORD = PASSWORD + "-Sm0ke!"

deadline = time.monotonic() + TIMEOUT
transcript = bytearray()
consumed = 0  # transcript offset already matched by expect()


def fail(msg: str) -> None:
    tail = transcript[-4000:].decode("utf-8", "replace")
    print(f"SMOKE FAIL: {msg}", file=sys.stderr)
    print("---- serial transcript tail ----", file=sys.stderr)
    print(tail, file=sys.stderr)
    sys.exit(1)


def connect() -> socket.socket:
    while time.monotonic() < deadline:
        try:
            s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            s.connect(SOCK_PATH)
            return s
        except OSError:
            time.sleep(0.5)
    fail(f"could not connect to serial socket {SOCK_PATH}")
    raise AssertionError  # unreachable


def expect(sock: socket.socket, patterns: "list[str]", what: str) -> int:
    """Wait until any pattern matches unconsumed output; return its
    index and consume through the end of the match."""
    global consumed
    regexes = [re.compile(p, re.M) for p in patterns]
    while time.monotonic() < deadline:
        text = transcript[consumed:].decode("utf-8", "replace")
        for i, rx in enumerate(regexes):
            m = rx.search(text)
            if m:
                consumed += len(text[: m.end()].encode("utf-8", "replace"))
                return i
        sock.settimeout(1.0)
        try:
            data = sock.recv(4096)
            if data:
                transcript.extend(data)
        except TimeoutError:
            pass
        except OSError as exc:
            fail(f"serial socket error while waiting for {what}: {exc}")
    fail(f"timeout waiting for {what}")
    raise AssertionError  # unreachable


def send(sock: socket.socket, line: str) -> None:
    sock.sendall(line.encode() + b"\n")


def main() -> None:
    sock = connect()

    expect(sock, [r"login:"], "login prompt")
    send(sock, USER)
    expect(sock, [r"Password:"], "password prompt")
    send(sock, PASSWORD)

    # Forced password change (passwd-expire) or straight to shell.
    password = PASSWORD
    while True:
        idx = expect(
            sock,
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
            send(sock, password)
        elif idx == 1:
            send(sock, NEW_PASSWORD)
            password = NEW_PASSWORD
        elif idx == 2:
            send(sock, NEW_PASSWORD)
        elif idx == 3:
            break
        else:
            fail("login rejected (Login incorrect)")

    # Give the getty/shell handoff a moment; the tty line discipline
    # buffers input typed early anyway.
    time.sleep(2)

    # The quoted marker keeps the echoed command line from matching
    # the expected output.
    # Full path: sbin is not on the non-root PATH.
    send(sock, 'echo SMOKE_"OK"; cat /proc/1/attr/current; /usr/sbin/ss -ltn')
    expect(sock, [r"SMOKE_OK"], "command execution (exec on rootfs)")

    idx = expect(
        sock,
        [r"kernel_t|^kernel\s*$", r"\w+_t[:\s]"],
        "PID 1 SELinux domain",
    )
    if idx == 0:
        fail("PID 1 still in kernel_t: rootfs unlabeled or policy not loaded")

    expect(sock, [r":22\b"], "sshd listening on :22")

    print("SMOKE PASS: login, exec, SELinux domain, and sshd all OK")
    sys.exit(0)


if __name__ == "__main__":
    main()
