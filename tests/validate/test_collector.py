# SPDX-License-Identifier: Apache-2.0
"""Unit tests for the CI collector target (no network, no device).

The collector makes one SSH call under the forced-command key and
serves every check from that single JSON collection; these tests feed
it a fake connection and assert that contract.
"""

from __future__ import annotations

import json
from typing import cast

import pytest
from validate.target import (
    CollectorTarget,
    Result,
    SshTarget,
    TargetError,
    from_env,
)

_FACTS = {
    "cat /proc/cmdline": {
        "rc": 0,
        "stdout": "root=/dev/mapper/rootfs roothash=" + "a" * 64 + "\n",
        "stderr": "",
    },
    "cat /proc/1/attr/current": {
        "rc": 0,
        "stdout": "system_u:system_r:init_t:s0\n",
        "stderr": "",
    },
}


class _FakeSsh:
    """Just enough of SshTarget for CollectorTarget to drive."""

    def __init__(self, payload: str, name: str = "device") -> None:
        self.name = name
        self._payload = payload
        self.calls = 0

    def run(self, cmd: str) -> Result:
        self.calls += 1
        return Result(0, self._payload, "")

    def auth_methods(self) -> list[str]:
        return ["publickey"]

    def audit(self, timeout: float | None = None) -> str:
        return "AUDIT"


def _collector(payload: str) -> tuple[CollectorTarget, _FakeSsh]:
    fake = _FakeSsh(payload)
    return CollectorTarget(cast(SshTarget, fake)), fake


def test_run_and_run_root_share_one_collection() -> None:
    target, fake = _collector(json.dumps(_FACTS))
    assert "roothash=" in target.run("cat /proc/cmdline").stdout
    assert target.run_root("cat /proc/1/attr/current").rc == 0
    assert fake.calls == 1  # one SSH call answered both


def test_missing_command_fails_closed() -> None:
    target, _ = _collector(json.dumps(_FACTS))
    with pytest.raises(TargetError, match="did not run"):
        target.run("cat /nonexistent")


def test_collector_error_surfaces() -> None:
    target, _ = _collector(json.dumps({"_error": "root helper failed"}))
    with pytest.raises(TargetError, match="root helper failed"):
        target.run("cat /proc/cmdline")


def test_non_json_output_surfaces() -> None:
    target, _ = _collector("this is not json")
    with pytest.raises(TargetError, match="not JSON"):
        target.run("cat /proc/cmdline")


def test_write_operations_are_unavailable() -> None:
    target, _ = _collector(json.dumps(_FACTS))
    with pytest.raises(TargetError, match="collector mode"):
        target.push("/a", "/b")
    with pytest.raises(TargetError, match="collector mode"):
        target.reboot()


def test_audit_and_auth_delegate_to_the_connection() -> None:
    target, _ = _collector(json.dumps(_FACTS))
    assert target.audit() == "AUDIT"
    assert target.auth_methods() == ["publickey"]


def test_from_env_builds_a_strict_collector_in_ci() -> None:
    env = {
        "LAMADIST_VALIDATE_TARGET": "device",
        "LAMADIST_VALIDATE_HOST": "h",
        "LAMADIST_VALIDATE_PORT": "22",
        "LAMADIST_VALIDATE_SSH_KEY": "/k",
        "LAMADIST_VALIDATE_COLLECTOR": "1",
    }
    target = from_env(env)
    assert isinstance(target, CollectorTarget)
    assert target._ssh.strict_host_key == "yes"


def test_from_env_local_device_stays_ssh_accept_new() -> None:
    env = {
        "LAMADIST_VALIDATE_TARGET": "device",
        "LAMADIST_VALIDATE_HOST": "h",
        "LAMADIST_VALIDATE_PORT": "22",
        "LAMADIST_VALIDATE_SSH_KEY": "/k",
    }
    target = from_env(env)
    assert isinstance(target, SshTarget)
    assert target.strict_host_key == "accept-new"
