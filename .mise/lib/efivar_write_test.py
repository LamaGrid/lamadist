#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Driver and verdict for the N7 write test (docs/validation/N7-WRITE-TEST.md).

`run` drives a headless qemuarm64 guest over its serial socket: log in,
become root, send the Part A script and the payload rows as base64,
run Part A, reboot, run its second-boot check, stop QEMU through the
monitor, and print the verdict.  `verdict` re-reads a saved transcript.

The verdict is a pure function of the serial transcript (evaluate()):
the probe's N7PROBE lines (Part B, before ExitBootServices), the N7A
lines of efivar_part_a.sh (Part A, through efivarfs), and the firmware
and kernel banners that count the boots.  Each row passes only on the
result the design predicts for U-Boot v2026.01 with the preseeded,
read-only store; the RED map in the validation document names the
rows each RED run turns red.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import re
import socket
import sys
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final

sys.path.insert(0, str(Path(__file__).resolve().parent))

import efivar_payloads
from smoke_login import SerialSession, SerialTimeoutError, login

TAGS: Final = tuple(r.tag for r in efivar_payloads.ROWS)
STATE_KEYS: Final = ("secureboot", "setupmode", "PK", "KEK", "db", "dbx")
READ_VARS: Final = ("PK", "KEK", "db", "dbx")

EFI_SUCCESS: Final = 0
EFI_WRITE_PROTECTED: Final = 0x8000000000000008
EFI_NOT_FOUND: Final = 0x800000000000000E
EFI_SECURITY_VIOLATION: Final = 0x800000000000001A

UBOOT_BANNER: Final = re.compile(r"^U-Boot \d{4}\.\d{2}", re.MULTILINE)
# The kernel prints its log timestamp before the banner.
KERNEL_BANNER: Final = re.compile(
    r"^(?:\[\s*\d+\.\d+\] )?Booting Linux on physical CPU", re.MULTILINE
)
# With the tty echo off, the Enter that ends a command is not echoed, so
# the first line it prints starts after the prompt, not at a line start.
# These markers appear only in the guest's output: the script reaches the
# guest as base64, and no typed command contains them.
N7A_LINE: Final = re.compile(r"N7A (STATE|INFO|A1|ROW|DONE) (.*)$", re.MULTILINE)
PROBE_LINE: Final = re.compile(r"N7PROBE (\S+) (.*)$", re.MULTILINE)
EROFS: Final = "Read-only file system"


@dataclass(frozen=True, slots=True)
class Result:
    row: str
    ok: bool
    detail: str


def row_names(firmware: str, probe: bool) -> list[str]:
    rows = [f"A0.{k}" for k in STATE_KEYS] + ["A0.mount", "A0.efi_test"]
    rows += ["A1.remount"]
    rows += [f"A.{t}" for t in TAGS]
    rows += [f"A.post.{k}" for k in STATE_KEYS]
    rows += [f"reboot.{k}" for k in STATE_KEYS] + ["reboot.efi_test", "reboot.banners"]
    if firmware == "u-boot":
        rows.append("uboot.sha256")
    if probe:
        rows += ["probe.runs"] + [f"probe.{t}" for t in TAGS] + ["probe.L1"]
        for phase in ("pre", "post", "boot2"):
            rows += [f"probe.{phase}.{v}" for v in READ_VARS]
    return rows


def _fields(text: str) -> dict[str, str]:
    """key=value pairs; err= takes the rest of the line."""
    head, _sep, err = text.partition(" err=")
    out = dict(tok.split("=", 1) for tok in head.split()[1:] if "=" in tok)
    out["_word"] = head.split()[0] if head.split() else ""
    if _sep:
        out["err"] = err
    return out


def _part_a(
    log: str,
) -> tuple[dict[str, dict[str, str]], dict[str, dict[str, str]], dict[str, str]]:
    states: dict[str, dict[str, str]] = {}
    rows: dict[str, dict[str, str]] = {}
    a1: dict[str, str] = {}
    for kind, rest in N7A_LINE.findall(log):
        f = _fields(rest.rstrip("\r"))
        if kind == "STATE":
            states.setdefault(f["_word"], f)
        elif kind == "ROW":
            rows.setdefault(f["_word"], f)
        elif kind == "A1" and not a1:
            a1 = _fields("A1 " + rest.rstrip("\r"))
    return states, rows, a1


@dataclass(frozen=True, slots=True)
class _Probe:
    reads: dict[tuple[str, str], tuple[int, str, str]]
    rows: dict[str, int]
    l1: int | None
    ended: bool
    errors: tuple[str, ...]


def _probe_blocks(log: str) -> list[_Probe]:
    blocks: list[list[tuple[str, str]]] = []
    for kind, rest in PROBE_LINE.findall(log):
        rest = rest.rstrip("\r")
        if kind == "BEGIN":
            blocks.append([])
        elif blocks:
            blocks[-1].append((kind, rest))
    out = []
    for lines in blocks:
        reads: dict[tuple[str, str], tuple[int, str, str]] = {}
        rows: dict[str, int] = {}
        l1 = None
        ended = False
        errors = []
        for kind, rest in lines:
            f = _fields(rest)
            status = int(f.get("status", "-1"), 16) if "status" in f else -1
            if kind == "READ":
                var = rest.split()[1]
                reads.setdefault(
                    (f["_word"], var), (status, f.get("size", ""), f.get("crc", ""))
                )
            elif kind == "ROW":
                rows.setdefault(f["_word"], status)
            elif kind == "L1":
                l1 = status
            elif kind == "END":
                ended = True
            else:
                errors.append(f"{kind} {rest}")
        out.append(_Probe(reads, rows, l1, ended, tuple(errors)))
    return out


def _state_expect(key: str, expect: Mapping[str, efivar_payloads.Expect]) -> str:
    if key in expect:
        return expect[key].sha256
    return {"secureboot": "1", "setupmode": "0", "dbx": "absent"}[key]


def _read_expect(
    var: str, expect: Mapping[str, efivar_payloads.Expect]
) -> tuple[int, str, str]:
    if var in expect:
        e = expect[var]
        return (EFI_SUCCESS, str(e.size), f"0x{e.crc32:08x}")
    return (EFI_NOT_FOUND, "0", "0x00000000")


def evaluate(
    log: str,
    *,
    firmware: str,
    probe: bool,
    expect: Mapping[str, efivar_payloads.Expect],
    uboot_sha: tuple[str | None, str | None, str | None] | None,
) -> list[Result]:
    """Every row of row_names(firmware, probe), in order."""
    res: dict[str, Result] = {}

    def put(row: str, ok: bool, detail: str) -> None:
        res[row] = Result(row, ok, detail)

    states, rows, a1 = _part_a(log)
    pre = states.get("pre", {})
    post = states.get("post", {})
    boot2 = states.get("boot2", {})

    for key in STATE_KEYS:
        want = _state_expect(key, expect)
        got = pre.get(key)
        put(f"A0.{key}", got == want, f"{key}={got} want {want}")
    put("A0.mount", pre.get("mount") == "ro", f"efivarfs {pre.get('mount')} want ro")
    put(
        "A0.efi_test",
        pre.get("efi_test") == "absent",
        f"/dev/efi_test {pre.get('efi_test')}",
    )
    put(
        "A1.remount",
        bool(a1) and a1.get("rc") not in (None, "0") and a1.get("mount") == "ro",
        f"rc={a1.get('rc')} mount={a1.get('mount')} want rc!=0 and ro",
    )
    for tag in TAGS:
        f = rows.get(tag, {})
        err = f.get("err", "")
        ok = f.get("rc") not in (None, "0") and EROFS in err
        put(f"A.{tag}", ok, f"rc={f.get('rc')} err={err or '-'} want {EROFS}")
    for key in STATE_KEYS:
        put(
            f"A.post.{key}",
            bool(pre) and post.get(key) == pre.get(key),
            f"{key} {pre.get(key)} -> {post.get(key)}",
        )
        put(
            f"reboot.{key}",
            bool(pre) and boot2.get(key) == pre.get(key),
            f"{key} {pre.get(key)} -> boot2 {boot2.get(key)}",
        )
    put(
        "reboot.efi_test",
        boot2.get("efi_test") == "absent",
        f"boot2 /dev/efi_test {boot2.get('efi_test')}",
    )

    kernels = len(KERNEL_BANNER.findall(log))
    if firmware == "u-boot":
        firmwares = len(UBOOT_BANNER.findall(log))
        put(
            "reboot.banners",
            firmwares == 2 and kernels == 2,
            f"U-Boot banners {firmwares}, kernel banners {kernels}, want 2 and 2",
        )
        before, after, want = uboot_sha or (None, None, None)
        put(
            "uboot.sha256",
            want is not None and before == want and after == want,
            f"before {before} after {after} want {want}",
        )
    else:
        put("reboot.banners", kernels == 2, f"kernel banners {kernels}, want 2")

    if probe:
        blocks = _probe_blocks(log)
        two = blocks[:2] if len(blocks) >= 2 else []
        bad = [e for b in blocks for e in b.errors]
        put(
            "probe.runs",
            len(blocks) == 2 and all(b.ended for b in blocks) and not bad,
            f"{len(blocks)} runs, want 2; {'; '.join(bad) or 'no errors'}",
        )
        for tag in TAGS:
            got = [b.rows.get(tag) for b in two]
            ok = bool(two) and all(s == EFI_WRITE_PROTECTED for s in got)
            put(
                f"probe.{tag}",
                ok,
                f"status {_hexes(got)} want {EFI_WRITE_PROTECTED:#x}",
            )
        got_l1 = [b.l1 for b in two]
        put(
            "probe.L1",
            bool(two) and all(s == EFI_SECURITY_VIOLATION for s in got_l1),
            f"LoadImage {_hexes(got_l1)} want {EFI_SECURITY_VIOLATION:#x}",
        )
        first = blocks[0] if blocks else None
        second = blocks[1] if len(blocks) > 1 else None
        for var in READ_VARS:
            want_read = _read_expect(var, expect)
            got_pre = first.reads.get(("pre", var)) if first else None
            put(f"probe.pre.{var}", got_pre == want_read, f"{got_pre} want {want_read}")
        for var in READ_VARS:
            a = first.reads.get(("pre", var)) if first else None
            b = first.reads.get(("post", var)) if first else None
            put(f"probe.post.{var}", a is not None and a == b, f"{a} -> {b}")
        for var in READ_VARS:
            a = first.reads.get(("pre", var)) if first else None
            got2 = (
                [second.reads.get((p, var)) for p in ("pre", "post")] if second else []
            )
            ok = a is not None and bool(got2) and all(g == a for g in got2)
            put(f"probe.boot2.{var}", ok, f"{a} -> boot2 {got2}")

    return [res[name] for name in row_names(firmware, probe)]


def _hexes(values: Sequence[int | None]) -> str:
    return ",".join("-" if v is None else f"{v:#x}" for v in values) or "-"


def render(results: Sequence[Result]) -> str:
    lines = [f"N7 ROW {r.row} {'PASS' if r.ok else 'FAIL'} {r.detail}" for r in results]
    verdict = "PASS" if results and all(r.ok for r in results) else "FAIL"
    return "\n".join([*lines, f"N7 VERDICT {verdict}"]) + "\n"


# --- driver ---------------------------------------------------------------

# A read can end anywhere, and `$` matches at the end of what has arrived,
# so a bare `# ?$` matches the "#" of sudo's lecture line
# "    #1) Respect the privacy of others." when a read ends just after it.
# A prompt counts only in the shell's `host:path# ` shape, starting a line
# or right after the ST that ends an OSC context sequence.
_PROMPT_HEAD: Final = r"(?:^|\x1b\\)[\w.-]+:[^\s#$]*"
ROOT_PROMPT: Final = _PROMPT_HEAD + r"# ?$"
USER_PROMPT: Final = _PROMPT_HEAD + r"\$ ?$"


def _root_shell(session: SerialSession, password: str) -> None:
    session.send("sudo -s")
    # Only output after the echo of this line can be sudo's.  A "Password:"
    # before it is login's, and a password typed there would reach a shell.
    session.expect([r"sudo -s\r\n"], "the echo of sudo -s")
    idx = session.expect([r"[Pp]assword.*: ?$", ROOT_PROMPT, USER_PROMPT], "sudo")
    if idx == 2:
        raise SerialTimeoutError("sudo -s returned to the user shell")
    if idx == 0:
        session.send(password)
        session.expect([ROOT_PROMPT], "root shell")
    # No echo and no line editing, so typed data never comes back as
    # output that a pattern could match.  The sync rides on the same line:
    # a second line typed ahead would be echoed only up to the point where
    # stty runs, and the reply to it would follow the prompt.  The marker
    # is computed in the guest, so the typed text never contains it.
    session.send('stty -echo; set +o emacs +o vi; echo N7SYNC_"$((6*7))"')
    session.expect([r"N7SYNC_42"], "root shell sync")


def _send_file(session: SerialSession, data: bytes, dest: str) -> None:
    encoded = base64.encodebytes(data).decode()
    session.send(f"base64 -d > {dest} <<'N7EOF'")
    for line in encoded.splitlines():
        session.send(line)
    session.send("N7EOF")
    digest = hashlib.sha256(data).hexdigest()
    session.send(f"sha256sum {dest}")
    # The digest follows the prompt on its line (no echo), and only the
    # guest's sha256sum prints it: the data went out as base64.
    session.expect([rf"{digest}\s"], f"{dest} to arrive intact")


def _quit_qemu(monitor: str) -> None:
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
            s.settimeout(5)
            s.connect(monitor)
            s.sendall(b"quit\n")
            time.sleep(1)
    except OSError:
        pass


def _sha256(path: Path) -> str | None:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None


def _run(args: argparse.Namespace) -> int:
    script = Path(args.part_a).read_bytes()
    bins = {t: (Path(args.bins) / f"{t}.bin").read_bytes() for t in TAGS}
    session = SerialSession(args.serial_sock, args.timeout)
    err = ""
    try:
        session.connect()
        password = login(session, "lama", "lamadist")
        _root_shell(session, password)
        session.send("mkdir -p /run/n7")
        _send_file(session, script, "/run/n7/part_a.sh")
        for tag, data in bins.items():
            _send_file(session, data, f"/run/n7/{tag}.bin")
        session.send("bash /run/n7/part_a.sh full")
        session.expect([r"^N7A DONE full"], "Part A")
        session.send("systemctl reboot")
        password = login(session, "lama", password)
        _root_shell(session, password)
        session.send("mkdir -p /run/n7")
        _send_file(session, script, "/run/n7/part_a.sh")
        session.send("bash /run/n7/part_a.sh boot2")
        session.expect([r"^N7A DONE boot2"], "Part A second boot")
    except SerialTimeoutError as exc:
        err = str(exc)
    finally:
        _quit_qemu(args.monitor_sock)

    log_path = Path(args.log)
    log = (
        log_path.read_text("utf-8", "replace")
        if log_path.is_file()
        else session.tail(10**9)
    )
    sha = None
    if args.firmware == "u-boot":
        sha = (args.uboot_sha_before, _sha256(Path(args.uboot_bin)), args.uboot_sha256)
    results = evaluate(
        log,
        firmware=args.firmware,
        probe=args.probe,
        expect=efivar_payloads.expectations(Path(args.keys)),
        uboot_sha=sha,
    )
    report = render(results)
    if err:
        report = f"N7 DRIVER ERROR {err}\n" + report.replace(
            "N7 VERDICT PASS", "N7 VERDICT FAIL"
        )
    Path(args.out).write_text(report)
    sys.stdout.write(report)
    return 0 if report.rstrip().endswith("N7 VERDICT PASS") else 1


def _verdict(args: argparse.Namespace) -> int:
    log = Path(args.log).read_text("utf-8", "replace")
    sha = None
    if args.firmware == "u-boot":
        sha = (args.uboot_sha_before, args.uboot_sha_after, args.uboot_sha256)
    report = render(
        evaluate(
            log,
            firmware=args.firmware,
            probe=args.probe,
            expect=efivar_payloads.expectations(Path(args.keys)),
            uboot_sha=sha,
        )
    )
    sys.stdout.write(report)
    return 0 if report.rstrip().endswith("N7 VERDICT PASS") else 1


def main(argv: Sequence[str]) -> int:
    ap = argparse.ArgumentParser(prog="efivar_write_test.py")
    sub = ap.add_subparsers(dest="cmd", required=True)
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--firmware", choices=("u-boot", "aavmf"), required=True)
    common.add_argument("--probe", action="store_true")
    common.add_argument("--keys", required=True)
    common.add_argument("--log", required=True)
    common.add_argument("--uboot-sha256")
    common.add_argument("--uboot-sha-before")
    run = sub.add_parser("run", parents=[common])
    run.add_argument("--serial-sock", required=True)
    run.add_argument("--monitor-sock", required=True)
    run.add_argument("--part-a", required=True)
    run.add_argument("--bins", required=True)
    run.add_argument("--uboot-bin", default="")
    run.add_argument("--timeout", type=int, required=True)
    run.add_argument("--out", required=True)
    verdict = sub.add_parser("verdict", parents=[common])
    verdict.add_argument("--uboot-sha-after")
    quit_ = sub.add_parser("quit")
    quit_.add_argument("monitor_sock")
    args = ap.parse_args(argv[1:])
    if args.cmd == "quit":
        _quit_qemu(args.monitor_sock)
        return 0
    if args.cmd == "run":
        return _run(args)
    return _verdict(args)


if __name__ == "__main__":
    sys.exit(main(sys.argv))
