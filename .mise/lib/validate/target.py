# SPDX-License-Identifier: Apache-2.0
"""Targets for the live validation suite.

One transport (key-only SSH, sudo with a password on stdin) and two
ways to resolve the endpoint: the emulated guest behind a QEMU port
forward, and the live test device from local configuration.  Steps
never see SSH; every transport detail lives here so that a job-runner
target can replace this file later without touching a feature file.

Root acquisition follows ADR 0010: ``id -u`` rides inside the same
``sudo`` invocation, so a silently failed escalation errors instead
of reading as a pass.
"""

from __future__ import annotations

import os
import re
import shlex
import subprocess
import time
from dataclasses import dataclass
from typing import Final, Protocol

from validate.ssh_audit import Audit
from validate.ssh_audit import run as run_audit


class TargetError(RuntimeError):
    """A transport or escalation failure, distinct from a failed check."""


@dataclass(frozen=True, slots=True)
class Result:
    """What a command produced on the target."""

    rc: int
    stdout: str
    stderr: str


class Target(Protocol):
    """The four operations every check body is written against."""

    name: str

    def run(self, cmd: str) -> Result: ...

    def run_root(self, cmd: str) -> Result: ...

    def reboot(self) -> None: ...

    def wait_ready(self, timeout: float) -> None: ...

    def auth_methods(self) -> list[str]: ...


_SSH_BASE: Final[tuple[str, ...]] = (
    "-o",
    "IdentitiesOnly=yes",
    "-o",
    "BatchMode=yes",
    "-o",
    "PasswordAuthentication=no",
    "-o",
    "KbdInteractiveAuthentication=no",
    "-o",
    "ConnectTimeout=10",
    "-o",
    "LogLevel=ERROR",
)
_SSH_TRANSPORT_RC: Final[int] = 255
_DENIED: Final[re.Pattern[str]] = re.compile(r"Permission denied \(([^)]*)\)")


@dataclass(frozen=True, slots=True)
class SshTarget:
    """Key-only SSH to ``user@host:port``.

    ``known_hosts`` is ``/dev/null`` with ``strict_host_key="no"`` for
    the emulated guest, whose host key is regenerated on every boot,
    and a pinned local file with ``"accept-new"`` for the device.
    """

    name: str
    host: str
    port: int
    user: str
    key: str
    known_hosts: str
    strict_host_key: str
    sudo_password: str
    timeout: float = 60.0

    def _base_argv(self) -> list[str]:
        return [
            "ssh",
            *_SSH_BASE,
            "-o",
            f"UserKnownHostsFile={self.known_hosts}",
            "-o",
            f"StrictHostKeyChecking={self.strict_host_key}",
            "-p",
            str(self.port),
        ]

    def _ssh(self, extra: list[str], cmd: str) -> subprocess.CompletedProcess[str]:
        argv = [*self._base_argv(), *extra, f"{self.user}@{self.host}", cmd]
        try:
            return subprocess.run(
                argv, capture_output=True, text=True, timeout=self.timeout, check=False
            )
        except subprocess.TimeoutExpired as err:
            raise TargetError(
                f"ssh to {self.name} timed out after {self.timeout:.0f}s"
            ) from err

    def run(self, cmd: str) -> Result:
        done = self._ssh(["-i", self.key], cmd)
        if done.returncode == _SSH_TRANSPORT_RC:
            raise TargetError(
                f"ssh transport failure on {self.name}: {done.stderr.strip()}"
            )
        return Result(done.returncode, done.stdout, done.stderr)

    def run_root(self, cmd: str) -> Result:
        wrapped = (
            f"printf '%s\\n' {shlex.quote(self.sudo_password)} | "
            f"sudo -S -p '' sh -c {shlex.quote('id -u; ' + cmd)}"
        )
        res = self.run(wrapped)
        first, _, rest = res.stdout.partition("\n")
        if first.strip() != "0":
            raise TargetError(f"root escalation failed on {self.name}")
        return Result(res.rc, rest, res.stderr)

    def reboot(self) -> None:
        self.run_root("systemctl reboot")

    def wait_ready(self, timeout: float) -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                if self.run("true").rc == 0:
                    return
            except TargetError:
                pass
            time.sleep(3)
        raise TargetError(f"{self.name} not reachable within {timeout:.0f}s")

    def auth_methods(self) -> list[str]:
        """Methods sshd offers, read from a deliberately failing probe."""
        done = self._ssh(
            ["-o", "PreferredAuthentications=none", "-i", "/dev/null"], "true"
        )
        found = _DENIED.search(done.stderr)
        if found is None:
            raise TargetError(
                f"could not read the authentication methods of {self.name}"
            )
        return [m.strip() for m in found.group(1).split(",")]

    def audit(self, timeout: float | None = None) -> Audit:
        """ssh-audit posture facts for this target (the twelfth check).

        SSH-specific by nature; it has no place on the transport-neutral
        Target protocol and retires when a job runner replaces SSH.
        """
        return run_audit(self.host, self.port, timeout=timeout or self.timeout)


def from_env(env: dict[str, str] | None = None) -> SshTarget:
    """Build the target the task described in the environment.

    ``LAMADIST_VALIDATE_TARGET`` is ``qemu`` or ``device``; host, port,
    key, known-hosts file, and sudo password come from the matching
    ``LAMADIST_VALIDATE_*`` variables, set by the task (device values
    arrive through fnox, never from the repo).
    """
    e = os.environ if env is None else env
    name = e.get("LAMADIST_VALIDATE_TARGET", "")
    if name not in ("qemu", "device"):
        raise TargetError("LAMADIST_VALIDATE_TARGET must be 'qemu' or 'device'")
    try:
        return SshTarget(
            name=name,
            host=e["LAMADIST_VALIDATE_HOST"],
            port=int(e["LAMADIST_VALIDATE_PORT"]),
            user=e.get("LAMADIST_VALIDATE_USER", "lama"),
            key=e["LAMADIST_VALIDATE_SSH_KEY"],
            known_hosts=e.get("LAMADIST_VALIDATE_KNOWN_HOSTS", "/dev/null"),
            strict_host_key="no" if name == "qemu" else "accept-new",
            sudo_password=e["LAMADIST_VALIDATE_SUDO_PASSWORD"],
        )
    except KeyError as err:
        raise TargetError(f"missing {err.args[0]} in the environment") from err
