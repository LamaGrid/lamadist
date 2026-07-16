#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Drive a RAUC A/B install + forced-failure rollback end-to-end
against a QEMU guest, over the same serial socket smoke_login.py
uses plus an ssh port-forward for file transfer and commands.

Usage: ota_test.py --serial-sock SOCK --ssh-port PORT --bundle
    BUNDLE.raucb [--user USER] [--password PASSWORD]
    [--timeout SECONDS] [--max-boot-attempts N]

Flow:
1. Boot slot A (already running when this starts) and log in.
2. scp the bundle over, `rauc install` it, and confirm the other
   slot (b) is reported good/pending; reboot.
3. Confirm the guest is now booted on slot b (kernel cmdline
   `lamadist.slot=b`), the health service committed the boot
   (`lamadist-health.service` Result=success), and `rauc status`
   agrees slot b is good.
4. Touch the forced-unhealthy test flag, install the bundle again
   (now targeting the inactive slot a), and reboot.
5. The health check fails on slot a every time (the flag lives on
   the shared /var partition), systemd-boot burns down its boot
   counter across however many attempts, and falls back to slot b.
   Watch that play out over the same serial connection and assert
   the final slot is b and rauc status now reports slot a bad.

Exit 0 on success, 1 on failure (with the transcript tail on
stderr), matching smoke_login.py's convention.
"""

import argparse
import re
import shlex
import shutil
import subprocess
import sys
import time

from smoke_login import SerialSession, SerialTimeoutError, login

# Not /tmp OR /var/tmp: fs-perms-volatile-tmp.txt links both into
# the RAM-backed /var/volatile tmpfs (sized at half the guest's
# RAM), which cannot hold a >1G bundle.  /var/cache sits on the
# on-disk writable /var partition.
REMOTE_BUNDLE_DIR = "/var/cache/lamadist-ota"
REMOTE_BUNDLE_PATH = f"{REMOTE_BUNDLE_DIR}/bundle.raucb"
FORCE_UNHEALTHY_FLAG = "/var/lamadist-force-unhealthy"
SSH_HOST = "127.0.0.1"
SSH_OPTS = [
    "-o", "StrictHostKeyChecking=no",
    "-o", "UserKnownHostsFile=/dev/null",
    "-o", "LogLevel=ERROR",
    "-o", "ConnectTimeout=10",
]
_PER_CALL_MAX = 60  # seconds; never let one ssh/scp call eat the whole budget


class OtaTestError(RuntimeError):
    """A test assertion failed or a driven step errored out."""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--serial-sock", required=True)
    parser.add_argument("--ssh-port", required=True, type=int)
    parser.add_argument("--bundle", required=True)
    parser.add_argument("--user", default="lama")
    parser.add_argument("--password", default="lamadist")
    parser.add_argument("--timeout", type=int, default=2400)
    parser.add_argument("--max-boot-attempts", type=int, default=6)
    parser.add_argument(
        "--boot-attempt-timeout",
        type=int,
        default=120,
        help="Per-attempt window (seconds) while watching the boot-counted "
        "rollback; bounds a single stuck login so the retry loop can move "
        "on instead of burning the whole --timeout on one missed prompt",
    )
    return parser.parse_args()


def check_sshpass() -> None:
    if shutil.which("sshpass") is None:
        print(
            "OTA TEST FAIL: sshpass not found (required for "
            "password-authenticated ssh/scp against the guest)",
            file=sys.stderr,
        )
        sys.exit(1)


def _remaining(deadline: float) -> int:
    return max(1, min(_PER_CALL_MAX, int(deadline - time.monotonic())))


def ssh_run(
    args: argparse.Namespace, deadline: float, command: str, check: bool = True
) -> "subprocess.CompletedProcess[str]":
    cmd = [
        "sshpass", "-p", args.password,
        "ssh", *SSH_OPTS, "-p", str(args.ssh_port),
        f"{args.user}@{SSH_HOST}", command,
    ]
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=_remaining(deadline)
        )
    except subprocess.TimeoutExpired as exc:
        raise OtaTestError(f"ssh command timed out: {command!r}") from exc
    if check and result.returncode != 0:
        raise OtaTestError(
            f"ssh command failed (rc={result.returncode}): {command!r}\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )
    return result


def sudo_run(
    args: argparse.Namespace, deadline: float, command: str, check: bool = True
) -> "subprocess.CompletedProcess[str]":
    """Run a root command on the guest.  The wheel sudoers drop-in
    requires a password, so feed it on stdin with -S; -p '' keeps the
    prompt out of captured output."""
    return ssh_run(
        args, deadline,
        f"printf '%s\\n' {shlex.quote(args.password)} | "
        f"sudo -S -p '' sh -c {shlex.quote(command)}",
        check=check,
    )


def scp_to_guest(
    args: argparse.Namespace, deadline: float, local_path: str, remote_path: str
) -> None:
    cmd = [
        "sshpass", "-p", args.password,
        "scp", *SSH_OPTS, "-P", str(args.ssh_port),
        local_path, f"{args.user}@{SSH_HOST}:{remote_path}",
    ]
    # The bundle is >1G and QEMU user-mode networking is slow, so this
    # one call gets the whole remaining budget, not _PER_CALL_MAX.
    budget = max(1, int(deadline - time.monotonic()))
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=budget
        )
    except subprocess.TimeoutExpired as exc:
        raise OtaTestError(f"scp timed out copying {local_path}") from exc
    if result.returncode != 0:
        raise OtaTestError(
            f"scp failed (rc={result.returncode}):\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )


def wait_for_ssh(args: argparse.Namespace, deadline: float) -> None:
    while time.monotonic() < deadline:
        try:
            result = ssh_run(args, deadline, "true", check=False)
            if result.returncode == 0:
                return
        except OtaTestError:
            pass
        time.sleep(2)
    raise OtaTestError("ssh never became reachable on the guest")


def reboot_guest(args: argparse.Namespace, deadline: float) -> None:
    # Fire-and-forget: the connection drops mid-response once the
    # guest actually reboots, so a nonzero/broken-pipe result here is
    # expected, not a failure.
    sudo_run(args, deadline, "systemctl reboot", check=False)


def login_and_get_slot(
    session: SerialSession, user: str, password: str
) -> str:
    """Log in over serial and read the active slot back out of the
    running kernel's /proc/cmdline (the `lamadist.slot=` param is
    part of this milestone's fixed slot-discovery interface
    contract)."""
    login(session, user, password)
    time.sleep(1)  # let the shell prompt settle before the next command
    session.send("cat /proc/cmdline")
    _idx, match = session.expect_capture(
        [r"lamadist\.slot=([ab])"], "slot in /proc/cmdline"
    )
    return match.group(1)


def await_fallback_slot(
    session: SerialSession,
    user: str,
    password: str,
    expected_slot: str,
    max_attempts: int,
    attempt_timeout: int,
) -> str:
    """Watch the guest cycle through boot-counted retries of the bad
    slot until systemd-boot falls back to expected_slot, purely over
    the serial connection (no ssh -- the guest may reboot again
    mid-handshake before the health check even finishes).

    Each attempt gets its own short deadline instead of the session's
    overall one: a health-triggered reboot can cut a login handshake
    off mid-flight (e.g. waiting on a "Password:" prompt that will
    never come because the getty behind it just died), and without a
    per-attempt bound that single stuck expect() would swallow the
    entire --timeout budget on one missed prompt instead of moving on
    to the next boot cycle."""
    overall_deadline = session.deadline
    last_error: Exception = OtaTestError(
        "rollback did not converge within max_boot_attempts"
    )
    for attempt in range(1, max_attempts + 1):
        if time.monotonic() >= overall_deadline:
            break
        session.deadline = min(overall_deadline, time.monotonic() + attempt_timeout)
        try:
            slot = login_and_get_slot(session, user, password)
        except SerialTimeoutError as exc:
            last_error = exc
            continue
        finally:
            session.deadline = overall_deadline
        if slot == expected_slot:
            return slot
        last_error = OtaTestError(
            f"rollback attempt {attempt}/{max_attempts}: "
            f"booted slot {slot}, want {expected_slot}"
        )
    raise last_error


def rauc_status_raw(args: argparse.Namespace, deadline: float) -> str:
    return sudo_run(args, deadline, "rauc status --output-format=json").stdout


def _slot_status_mentions(raw_json: str, bootname: str, ok_keywords: "list[str]") -> bool:
    """Best-effort proximity check: does the given slot's bootname
    appear near one of the acceptable status keywords?  RAUC's exact
    --output-format=json field names/nesting are unconfirmed against
    the real 1.15.1 build; this stays a loose window match instead of
    a strict schema so it survives minor field-name differences, and
    should get tightened once real output is on hand."""
    window = 300
    for m in re.finditer(rf'"bootname"\s*:\s*"{re.escape(bootname)}"', raw_json):
        start = max(0, m.start() - window)
        end = min(len(raw_json), m.end() + window)
        nearby = raw_json[start:end]
        if any(re.search(rf'"{kw}"', nearby) for kw in ok_keywords):
            return True
    return False


def install_bundle(
    args: argparse.Namespace, deadline: float, other_slot: str, ok_keywords: "list[str]"
) -> None:
    sudo_run(
        args, deadline,
        f"mkdir -p {REMOTE_BUNDLE_DIR} && chown {args.user} {REMOTE_BUNDLE_DIR}",
    )
    scp_to_guest(args, deadline, args.bundle, REMOTE_BUNDLE_PATH)
    sudo_run(args, deadline, f"rauc install {REMOTE_BUNDLE_PATH}")
    raw = rauc_status_raw(args, deadline)
    if not _slot_status_mentions(raw, other_slot, ok_keywords):
        raise OtaTestError(
            f"rauc status did not mark slot {other_slot} as one of "
            f"{ok_keywords} after install:\n{raw}"
        )


def assert_health_committed(args: argparse.Namespace, deadline: float, slot: str) -> None:
    result = ssh_run(
        args, deadline, "systemctl show -p Result --value lamadist-health.service"
    )
    if result.stdout.strip() != "success":
        raise OtaTestError(
            f"lamadist-health.service on slot {slot} did not report "
            f"Result=success (got {result.stdout.strip()!r}); health "
            "check likely did not run, or failed"
        )
    raw = rauc_status_raw(args, deadline)
    if not _slot_status_mentions(raw, slot, ["good"]):
        raise OtaTestError(
            f"rauc status did not report boot-status good for slot "
            f"{slot} after mark-good:\n{raw}"
        )


def run(session: SerialSession, args: argparse.Namespace) -> None:
    deadline = session.deadline

    # Phase 1: already booted on slot a (installer image default);
    # confirm and install the first update.
    slot = login_and_get_slot(session, args.user, args.password)
    if slot != "a":
        raise OtaTestError(f"expected initial boot on slot a, got slot {slot}")

    wait_for_ssh(args, deadline)
    print("==> Installing first bundle (targets inactive slot b)...")
    install_bundle(args, deadline, other_slot="b", ok_keywords=["good", "pending"])
    reboot_guest(args, deadline)

    # Phase 2: confirm the reboot landed on slot b, health committed.
    slot = login_and_get_slot(session, args.user, args.password)
    if slot != "b":
        raise OtaTestError(f"post-update boot expected slot b, got slot {slot}")
    wait_for_ssh(args, deadline)
    assert_health_committed(args, deadline, slot="b")
    print("==> Slot b installed, booted, and committed good.")

    # Phase 3: forced failure -- flag persists on the shared /var
    # partition, so the next boot into the freshly-updated (and
    # still-pending) slot a will fail health every time.
    sudo_run(args, deadline, f"touch {FORCE_UNHEALTHY_FLAG}")
    print("==> Installing second bundle (targets inactive slot a) with force-unhealthy flag set...")
    install_bundle(args, deadline, other_slot="a", ok_keywords=["good", "pending"])
    reboot_guest(args, deadline)

    # Phase 4: watch the boot-counted rollback play out and land back
    # on slot b.
    print("==> Watching for automatic rollback to slot b...")
    slot = await_fallback_slot(
        session, args.user, args.password, expected_slot="b",
        max_attempts=args.max_boot_attempts,
        attempt_timeout=args.boot_attempt_timeout,
    )
    wait_for_ssh(args, deadline)
    raw = rauc_status_raw(args, deadline)
    if not _slot_status_mentions(raw, "a", ["bad"]):
        raise OtaTestError(f"rauc status did not report slot a as bad after rollback:\n{raw}")
    print("==> Rolled back to slot b; slot a marked bad.")


def main() -> None:
    args = parse_args()
    check_sshpass()

    session = SerialSession(args.serial_sock, args.timeout)
    try:
        session.connect()
        run(session, args)
    except (SerialTimeoutError, OtaTestError) as exc:
        print(f"OTA TEST FAIL: {exc}", file=sys.stderr)
        print("---- serial transcript tail ----", file=sys.stderr)
        print(session.tail(8000), file=sys.stderr)
        sys.exit(1)

    print("OTA TEST PASS: install, reboot, health commit, and forced-failure rollback all OK")
    sys.exit(0)


if __name__ == "__main__":
    main()
