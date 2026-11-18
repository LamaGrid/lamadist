# SPDX-License-Identifier: Apache-2.0
"""Tests for the N7 write-test driver (.mise/lib/efivar_write_test.py).

The driver types into a serial console and waits for what the guest
prints.  FakeGuest stands in for the console, with the one property of
the real tty that matters here: after `stty -echo` the typed Enter is
not echoed, so each command's output starts on the line that holds the
prompt.  fixtures/n7-serial-real.log is the real console output from
that moment, with the real probe lines, the kernel banner, and the
U-Boot banner; test_guest_model_reproduces_the_real_glue ties the model
to it.  ScriptedGuest replays the real login and sudo output of two
runs (fixtures/n7-sudo-*.log) split at every byte: in "root" sudo
gave a root shell, and in "typeahead" the driver typed its stty line
into sudo's lecture.  No VM runs.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import importlib
import importlib.util
import re
import sys
import time
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]
LIB = ROOT / ".mise" / "lib"
KEYS = ROOT / "meta-lamadist" / "files" / "sb-dev"
FIXTURES = Path(__file__).resolve().parent / "fixtures"
FIXTURE = FIXTURES / "n7-serial-real.log"
PROMPT = "qemuarm64-lamadist:/home/lama# "
PASSWORD = "lamadist"
SYNC_LINE = 'stty -echo; set +o emacs +o vi; echo N7SYNC_"$((6*7))"'
TAGS = ["U-PK", "U-KEK", "U-db", "W-db", "X-PK", "S-db", "S-KEK", "S-PK"]

sys.path.insert(0, str(LIB))
SMOKE = importlib.import_module("smoke_login")


def _real() -> str:
    return FIXTURE.read_bytes().decode("utf-8", "replace")


def _load() -> ModuleType:
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


class _Idle:
    """A socket that never has data, so expect() polls the transcript."""

    def settimeout(self, _t: float | None) -> None:
        pass

    def recv(self, _n: int) -> bytes:
        time.sleep(0.01)
        raise TimeoutError


def _part_a(n: int) -> str:
    """The Part A output of the verdict tests' GREEN transcript."""
    from test_efivar_verdict import _boot

    boot: str = _boot(n, "aavmf", False)
    end = "N7A DONE full\r\n" if n == 1 else "N7A DONE boot2\r\n"
    return boot[boot.index("N7A STATE") : boot.index(end) + len(end)]


class FakeGuest(SMOKE.SerialSession):
    """A getty, a login, sudo, and a root bash on a serial tty."""

    def __init__(self, _sock: str, timeout: float) -> None:
        super().__init__("unused", timeout)
        self.echo = True
        self.stage = "getty"
        self.sent: list[str] = []
        self.patterns: list[str] = []
        self.files: dict[str, bytes] = {}
        self.heredoc: str | None = None
        self.heredoc_lines: list[str] = []
        self.boots = 1
        self._out(self._boot_text())

    @staticmethod
    def _boot_text() -> str:
        kernel = next(
            ln for ln in _real().splitlines(keepends=True) if "Booting Linux" in ln
        )
        return kernel + "qemuarm64-lamadist login: "

    def _out(self, text: str) -> None:
        self.transcript.extend(text.encode())

    def connect(self) -> None:
        self._sock = _Idle()

    def expect_capture(self, patterns: list[str], what: str) -> Any:
        self.patterns.extend(patterns)
        return super().expect_capture(patterns, what)

    def send(self, line: str) -> None:
        self.sent.append(line)
        if self.stage == "getty":
            self._out(f"{line}\r\nPassword: ")
            self.stage = "login_pw"
        elif self.stage == "login_pw":
            self._out("\r\nLast login: x\r\nqemuarm64-lamadist:/home/lama$ ")
            self.stage = "user"
        elif self.stage == "sudo_pw":
            self._out(f"\r\n{PROMPT}")
            self.stage = "root"
        elif self.stage == "user" and line == "sudo -s":
            self._out("sudo -s\r\nPassword: ")
            self.stage = "sudo_pw"
        elif self.stage == "root":
            self._root(line)

    def _root(self, line: str) -> None:
        if self.heredoc is not None:
            if line == "N7EOF":
                data = "".join(self.heredoc_lines).encode()
                self.files[self.heredoc] = base64.b64decode(data)
                self.heredoc = None
                self._out(PROMPT)
            else:
                self.heredoc_lines.append(line)
                self._out("> ")
            return
        out = f"{line}\r\n" if self.echo else ""
        echo_after = self.echo
        for part in (p.strip() for p in line.split(";")):
            out += self._command(part)
            if part == "stty -echo":
                echo_after = False
            if self.heredoc is not None:
                self._out(out + "> ")
                self.echo = echo_after
                return
            if part == "systemctl reboot":
                self._out(out + "reboot: Restarting system\r\n" + self._boot_text())
                self.stage = "getty"
                self.echo = True
                self.files = {}
                self.boots += 1
                return
        self.echo = echo_after
        self._out(out + PROMPT)

    def _command(self, cmd: str) -> str:
        if cmd.startswith("echo "):
            text = cmd[5:].replace('"$((6*7))"', "42").replace('"', "")
            return f"{text}\r\n"
        if cmd.startswith("base64 -d > "):
            self.heredoc = cmd.split()[3]
            self.heredoc_lines = []
        elif cmd.startswith("sha256sum "):
            dest = cmd.split()[1]
            digest = hashlib.sha256(self.files[dest]).hexdigest()
            return f"{digest}  {dest}\r\n"
        elif cmd.startswith("bash /run/n7/part_a.sh "):
            return _part_a(1 if cmd.endswith("full") else 2)
        return ""


@pytest.fixture
def guest() -> FakeGuest:
    g = FakeGuest("unused", 1.5)
    g.connect()
    return g


def _to_root(wt: ModuleType, g: FakeGuest) -> None:
    password = wt.login(g, "lama", "lamadist")
    wt._root_shell(g, password)


# --- the model against the real console -----------------------------------


def test_guest_model_reproduces_the_real_glue(guest: FakeGuest) -> None:
    """The earlier two-command protocol, run on the model, ends with the
    real console's bytes: the prompt, then the output on its line."""
    for line in ("lama", "lamadist", "sudo -s", "lamadist"):
        guest.send(line)
    guest.send("stty -echo; set +o emacs +o vi")
    guest.send('echo N7SYNC_"$((6*7))"')
    real_tail = _real().split("$((", 1)[1]
    assert real_tail.startswith(PROMPT + "N7SYNC_42\r\n")
    assert guest.transcript.decode().endswith(real_tail)


# --- the sync after stty --------------------------------------------------


def test_root_shell_syncs_with_echo_off(wt: ModuleType, guest: FakeGuest) -> None:
    _to_root(wt, guest)
    assert guest.echo is False
    assert guest.stage == "root"


def test_nothing_is_typed_ahead_of_stty(wt: ModuleType, guest: FakeGuest) -> None:
    """A line typed while stty runs is only partly echoed, as in the
    real log, so stty and the sync go out as one line."""
    _to_root(wt, guest)
    line = next(s for s in guest.sent if "stty -echo" in s)
    assert "N7SYNC_" in line, guest.sent


# --- the digest after a file transfer -------------------------------------


def test_file_transfer_checks_the_digest_with_echo_off(
    wt: ModuleType, guest: FakeGuest
) -> None:
    guest.stage = "root"
    guest.echo = False
    guest.transcript.extend(PROMPT.encode())
    data = bytes(range(256)) * 3
    wt._send_file(guest, data, "/run/n7/x.bin")
    assert guest.files["/run/n7/x.bin"] == data


# --- the whole run, both boots --------------------------------------------


def _args(tmp_path: Path) -> argparse.Namespace:
    bins = tmp_path / "bins"
    bins.mkdir()
    for tag in TAGS:
        (bins / f"{tag}.bin").write_bytes(f"payload {tag}".encode() * 7)
    script = tmp_path / "part_a.sh"
    script.write_text("echo part a\n")
    return argparse.Namespace(
        part_a=str(script),
        bins=str(bins),
        serial_sock="unused",
        monitor_sock=str(tmp_path / "no-monitor"),
        timeout=3,
        firmware="aavmf",
        probe=False,
        keys=str(KEYS),
        log=str(tmp_path / "no-log"),
        out=str(tmp_path / "verdict.txt"),
        uboot_bin="",
        uboot_sha256=None,
        uboot_sha_before=None,
    )


@pytest.fixture
def run(
    wt: ModuleType, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> tuple[int, FakeGuest, str]:
    made: list[FakeGuest] = []

    def factory(sock: str, timeout: float) -> FakeGuest:
        g = FakeGuest(sock, timeout)
        made.append(g)
        return g

    monkeypatch.setattr(wt, "SerialSession", factory)
    rc = wt._run(_args(tmp_path))
    return rc, made[0], (tmp_path / "verdict.txt").read_text()


def test_full_run_passes_through_the_reboot(run: tuple[int, FakeGuest, str]) -> None:
    rc, g, report = run
    assert "N7 DRIVER ERROR" not in report, report
    assert report.rstrip().endswith("N7 VERDICT PASS"), report
    assert rc == 0
    assert g.boots == 2


def test_no_pattern_matches_text_the_driver_typed(
    run: tuple[int, FakeGuest, str],
) -> None:
    _rc, g, _report = run
    typed = "\n".join(g.sent)
    assert g.patterns
    for pattern in g.patterns:
        assert re.search(pattern, typed, re.MULTILINE) is None, pattern


def test_sync_marker_is_computed_in_the_guest(run: tuple[int, FakeGuest, str]) -> None:
    _rc, g, _report = run
    assert not any("N7SYNC_42" in s for s in g.sent)


# --- the real probe block and banners -------------------------------------


def test_real_probe_block_passes_the_probe_rows(wt: ModuleType) -> None:
    real = _real()
    results = wt.evaluate(
        real + real,
        firmware="aavmf",
        probe=True,
        expect=wt.efivar_payloads.expectations(KEYS),
        uboot_sha=None,
    )
    bad = {r.row: r.detail for r in results if r.row.startswith("probe.") and not r.ok}
    assert bad == {}


def test_real_banners_count_once_each(wt: ModuleType) -> None:
    real = _real()
    assert len(wt.UBOOT_BANNER.findall(real)) == 1
    assert len(wt.KERNEL_BANNER.findall(real)) == 1


# --- prompt waits at every read boundary ----------------------------------
#
# A serial read can end anywhere, and expect() matches `$` at the end of
# what has arrived so far.  ScriptedGuest replays the real console output
# between the driver's lines and hands one of those outputs over in two
# reads, split at a given byte.  Every other output arrives in one read.
# expect() only consumes on a match, so one split per run reaches every
# buffer end a wait can see.  The guest refuses a line typed while its
# output is still arriving, or a line other than the one it waits for.

Step = tuple[str | None, str]


class WrongInput(AssertionError):
    """The driver typed a line the guest was not yet waiting for."""


class _Reads:
    """recv() hands out queued output; with none left, the deadline
    passes, so expect() fails at once instead of waiting."""

    def __init__(self, guest: ScriptedGuest) -> None:
        self.guest = guest

    def settimeout(self, _t: float | None) -> None:
        pass

    def recv(self, _n: int) -> bytes:
        if self.guest.queue:
            return self.guest.queue.pop(0)
        self.guest.deadline = 0.0
        raise TimeoutError


class ScriptedGuest(SMOKE.SerialSession):
    def __init__(
        self,
        steps: list[Step],
        split: tuple[int, int] | None = None,
        *,
        strict: bool = True,
    ) -> None:
        super().__init__("unused", 5.0)
        self.steps = steps
        self.split = split
        self.strict = strict
        self.step = 0
        self.queue: list[bytes] = []
        self.sent: list[str] = []
        self._sock = _Reads(self)
        self._emit()

    def connect(self) -> None:
        pass

    def _emit(self) -> None:
        out = self.steps[self.step][1].encode()
        if self.split and self.split[0] == self.step and 0 < self.split[1] < len(out):
            self.queue += [out[: self.split[1]], out[self.split[1] :]]
        else:
            self.queue.append(out)
        self.step += 1

    def send(self, line: str) -> None:
        self.sent.append(line)
        what = "the password" if line == PASSWORD else repr(line)
        pending = b"".join(self.queue)
        want = self.steps[self.step][0] if self.step < len(self.steps) else None
        if pending.strip() and self.strict:
            raise WrongInput(f"{what} typed with {pending[:40]!r} still to come")
        if line != want:
            if self.strict:
                waits = "the password" if want == PASSWORD else repr(want)
                raise WrongInput(f"{what} typed where the guest waits for {waits}")
            return
        self._emit()


def _sudo_log(run: str) -> str:
    return (FIXTURES / f"n7-sudo-{run}.log").read_bytes().decode()


def _cut(text: str, end: str) -> tuple[str, str]:
    head, rest = text.split(end, 1)
    return head + end, rest


def _real_steps(run: str) -> list[Step]:
    """The guest's output after each line the driver types, from the
    real log of the run.  In "typeahead" the driver typed its stty line
    inside sudo's lecture; the replay drops that typed text, and the
    real failure after it, and answers the password with the root
    prompt of "root"."""
    log = _sudo_log(run).replace("stty -echo; set ", "")
    getty, rest = _cut(log, "login: ")
    user, rest = _cut(rest, "Password: ")
    shell, rest = _cut(rest, "$ ")
    sudo, _rest = _cut(rest, "Password: ")
    assert "\r\n" + PROMPT in _sudo_log("root")
    return [
        (None, getty),
        ("lama", user),
        (PASSWORD, shell),
        ("sudo -s", sudo),
        (PASSWORD, "\r\n" + PROMPT),
        (SYNC_LINE, f"{SYNC_LINE}\r\nN7SYNC_42\r\n{PROMPT}"),
    ]


def _splits(steps: list[Step]) -> list[tuple[int, int] | None]:
    return [None] + [
        (i, k)
        for i, (_in, out) in enumerate(steps)
        for k in range(1, len(out.encode()))
    ]


def _replay(wt: ModuleType, steps: list[Step], split: tuple[int, int] | None) -> str:
    g = ScriptedGuest(steps, split)
    try:
        password = wt.login(g, "lama", PASSWORD)
        wt._root_shell(g, password)
    except (WrongInput, SMOKE.SerialTimeoutError) as exc:
        return f"split {split}: {exc}"
    if g.step != len(steps):
        return f"split {split}: stopped at step {g.step} of {len(steps)}"
    return ""


def test_the_replay_reproduces_the_typeahead_run(wt: ModuleType) -> None:
    """The typeahead run's prefix: sudo's lecture has arrived up to
    "    #", and the driver must still wait for the password prompt."""
    steps = _real_steps("typeahead")
    sudo = steps[3][1].encode()
    split = (3, sudo.index(b"    #1)") + len(b"    #"))
    assert _replay(wt, steps, split) == ""


@pytest.mark.parametrize("run", ["root", "typeahead"])
def test_root_shell_waits_for_each_real_prompt_at_every_split(
    wt: ModuleType, run: str
) -> None:
    steps = _real_steps(run)
    splits = _splits(steps)
    failures = [f for s in splits if (f := _replay(wt, steps, s))]
    assert failures == [], (
        f"{len(failures)} of {len(splits)} splits fail:\n" + "\n".join(failures[:8])
    )


# --- the password never lands at a shell prompt ---------------------------


def _refusal_steps() -> list[Step]:
    """Login's own "Password: " is still unread, and sudo -s returns to
    the user's shell with no prompt of its own.  The shell output is the
    real one after sudo exits (the typeahead run, its last line)."""
    log = _sudo_log("typeahead")
    login, _rest = _cut(log, "Password: ")
    back = log[log.rindex("\x1b]3008;end=") :]
    return [(None, login), ("sudo -s", f"sudo -s\r\n{back}")]


def test_the_password_never_goes_to_a_shell_prompt(
    wt: ModuleType, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """At every split, the run ends in a DRIVER ERROR and the password
    is never typed after sudo -s."""
    steps = _refusal_steps()
    monkeypatch.setattr(wt, "login", lambda _s, _u, password: password)
    args = _args(tmp_path)
    failures = []
    for split in _splits(steps):
        g = ScriptedGuest(steps, split, strict=False)
        monkeypatch.setattr(wt, "SerialSession", lambda _sock, _t, g=g: g)
        rc = wt._run(args)
        report = (tmp_path / "verdict.txt").read_text()
        after = g.sent[g.sent.index("sudo -s") + 1 :] if "sudo -s" in g.sent else []
        if PASSWORD in after:
            failures.append(f"split {split}: the password was typed after sudo -s")
        if rc == 0 or not report.startswith("N7 DRIVER ERROR"):
            failures.append(f"split {split}: no DRIVER ERROR: {report[:80]!r}")
    assert failures == [], "\n".join(failures[:8])
