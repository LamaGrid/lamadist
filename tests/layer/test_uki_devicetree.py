# SPDX-License-Identifier: Apache-2.0
"""Static tests for the device tree inside the UKI (ADR 0013 decisions 1, 3, 10).

BitBake is not run.  lamadist_uki_build is a BitBake python function, so
the tests cut its body out of lamadist-uki.bbclass and run it against a
fake datastore and a fake ``bb`` that records the ukify command lines.
That settles which flags the build passes.  What only a build or a boot
settles (the section list of the real UKI, the stub installing the
tree) is left to a build or a QEMU boot.

One optional cross-check reads an upstream meta-rockchip clone under the
directory that $LAMADIST_HOST_UPSTREAM_DIR names; it skips when the
variable is unset or the clone is absent.
"""

from __future__ import annotations

import os
import re
import sys
import types
from collections.abc import Callable, Mapping
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
LAYER = ROOT / "meta-lamadist"
MACHINE_DIR = LAYER / "conf" / "machine"
UKI_CLASS = LAYER / "classes" / "lamadist-uki.bbclass"
SOQUARTZ = MACHINE_DIR / "soquartz-lamadist.conf"
INTEL = MACHINE_DIR / "intel.conf"
QEMUARM64 = MACHINE_DIR / "qemuarm64-lamadist.conf"

OPT_IN = "LAMADIST_UKI_EMBED_DTB"
BOARD_DTB = "rk3566-soquartz-model-a.dtb"
UPSTREAM_ENV = "LAMADIST_HOST_UPSTREAM_DIR"
# Under os.devnull, which is never a directory, when the variable is unset.
UPSTREAM_ROCKCHIP = Path(
    os.environ.get(UPSTREAM_ENV, "") or os.devnull, "yoctoproject.org/meta-rockchip"
)


class BBFatal(Exception):
    """Stand-in for bb.fatal."""


class FakeData:
    """The slice of the BitBake datastore the class reads."""

    def __init__(self, values: Mapping[str, str]) -> None:
        self._values = dict(values)

    def getVar(self, name: str) -> str | None:
        return self._values.get(name)


def _code(path: Path) -> list[str]:
    """Non-comment, non-blank lines, stripped."""
    return [
        s
        for raw in path.read_text().splitlines()
        if (s := raw.strip()) and not s.startswith("#")
    ]


def _function_source(name: str) -> str:
    """The body of a ``python NAME () { ... }`` block as a plain def."""
    lines = UKI_CLASS.read_text().splitlines()
    start = lines.index(f"python {name} () {{")
    end = lines.index("}", start)
    return f"def {name}(d):\n" + "\n".join(lines[start + 1 : end]) + "\n"


def _init_cpio() -> bytes:
    """A whole newc archive with an executable, non-empty /init."""
    out = bytearray()
    for name, mode, data in (
        ("init", 0o100755, b"#!/bin/sh\n"),
        ("TRAILER!!!", 0, b""),
    ):
        raw = name.encode() + b"\0"
        fields = (1, mode, 0, 0, 1, 0, len(data), 0, 0, 0, 0, len(raw), 0)
        out += b"070701" + b"".join(b"%08X" % f for f in fields) + raw
        out += b"\0" * (-len(out) % 4) + data
        out += b"\0" * (-len(out) % 4)
    return bytes(out)


BuildFn = Callable[[Mapping[str, str]], list[str]]


@pytest.fixture
def build(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> BuildFn:
    """Run lamadist_uki_build and return the ukify command lines."""
    deploy = tmp_path / "deploy"
    verity = tmp_path / "verity"
    deploy.mkdir()
    verity.mkdir()
    for name in (
        "linuxaa64.efi.stub",
        "Image",
        BOARD_DTB,
        "second-board.dtb",
    ):
        (deploy / name).write_bytes(b"x")
    # <image>-<machine>.<fstype>; the build walks its newc headers.
    (deploy / "initramfs-test.cpio.zst").write_bytes(_init_cpio())
    (verity / "img.ext4.verity.env").write_text("ROOT_HASH=abc123\n")

    commands: list[str] = []

    def run(cmd: str, shell: bool = False) -> tuple[str, str]:
        commands.append(cmd)
        return "", ""

    def fatal(msg: str) -> None:
        raise BBFatal(msg)

    bb = types.ModuleType("bb")
    process = types.ModuleType("bb.process")
    process.run = run  # type: ignore[attr-defined]
    bb.process = process  # type: ignore[attr-defined]
    bb.note = lambda msg: None  # type: ignore[attr-defined]
    bb.debug = lambda level, msg: None  # type: ignore[attr-defined]
    bb.fatal = fatal  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "bb", bb)
    monkeypatch.setitem(sys.modules, "bb.process", process)

    base = {
        "DEPLOY_DIR_IMAGE": str(deploy),
        "STAGING_VERITY_DIR": str(verity),
        "DM_VERITY_IMAGE": "img",
        "DM_VERITY_IMAGE_TYPE": "ext4",
        "EFI_ARCH": "aa64",
        "KERNEL_IMAGETYPE": "Image",
        "INITRAMFS_IMAGE": "initramfs",
        "INITRAMFS_FSTYPES": "cpio.zst",
        "MACHINE": "test",
        "RECIPE_SYSROOT_NATIVE": "/n",
        "RECIPE_SYSROOT": "/t",
        "prefix": "/usr",
        "LAMADIST_UKI_SLOTS": "a b",
        "UKIFY_CMD": "ukify build",
        # The fixture cpio is a few hundred bytes, not tens of MiB.
        "LAMADIST_UKI_INITRAMFS_MIN_BYTES": "0",
    }
    namespace: dict[str, object] = {}
    exec(_function_source("lamadist_uki_build"), namespace)  # noqa: S102

    def go(extra: Mapping[str, str]) -> list[str]:
        commands.clear()
        fn: Callable[[FakeData], None] = namespace["lamadist_uki_build"]  # type: ignore[assignment]
        fn(FakeData({**base, **extra}))
        return list(commands)

    return go


# --- the build passes --devicetree only on opt-in ------------------------


@pytest.mark.parametrize("extra", [{}, {OPT_IN: "0"}, {OPT_IN: ""}])
def test_no_devicetree_unless_the_machine_opts_in(
    build: BuildFn, extra: dict[str, str]
) -> None:
    cmds = build({"KERNEL_DEVICETREE": f"rockchip/{BOARD_DTB}", **extra})
    assert len(cmds) == 2
    assert all("--devicetree" not in c for c in cmds)


def test_opt_in_embeds_the_board_dtb_in_every_slot(build: BuildFn) -> None:
    cmds = build({OPT_IN: "1", "KERNEL_DEVICETREE": f"rockchip/{BOARD_DTB}"})
    assert len(cmds) == 2
    for cmd in cmds:
        # The kernel deploys DTBs flat in DEPLOY_DIR_IMAGE: no rockchip/.
        assert re.search(rf"--devicetree=\S+/deploy/{re.escape(BOARD_DTB)}( |$)", cmd)
        assert cmd.count("--devicetree") == 1
        assert "--devicetree-auto" not in cmd


def test_opt_in_with_several_dtbs_embeds_only_the_first(build: BuildFn) -> None:
    # ukify's --devicetree takes one file (a repeat silently keeps the
    # last), so the class picks the first KERNEL_DEVICETREE entry.
    cmds = build(
        {
            OPT_IN: "1",
            "KERNEL_DEVICETREE": f"rockchip/{BOARD_DTB} rockchip/second-board.dtb",
        }
    )
    for cmd in cmds:
        assert cmd.count("--devicetree") == 1
        assert BOARD_DTB in cmd
        assert "second-board.dtb" not in cmd


def test_opt_in_without_a_devicetree_is_fatal(build: BuildFn) -> None:
    with pytest.raises(BBFatal, match="KERNEL_DEVICETREE"):
        build({OPT_IN: "1", "KERNEL_DEVICETREE": ""})


def test_opt_in_with_a_missing_dtb_file_is_fatal(build: BuildFn) -> None:
    with pytest.raises(BBFatal, match="absent.dtb"):
        build({OPT_IN: "1", "KERNEL_DEVICETREE": "rockchip/absent.dtb"})


# --- the UKI task waits for the kernel's DTB deploy on opt-in ------------


def _depends_expr() -> str:
    for line in _code(UKI_CLASS):
        m = re.match(r'^do_image_wic\[depends\] \+= "\$\{@(.+)\}"$', line)
        # The class has other do_image_wic[depends] lines (microcode).
        if m and OPT_IN in m.group(1):
            return m.group(1)
    raise AssertionError("no do_image_wic[depends] expression in the class")


@pytest.mark.parametrize(
    ("flag", "expected"),
    [("1", "virtual/kernel:do_deploy"), ("0", ""), (None, "")],
)
def test_task_depends_on_kernel_deploy_only_on_opt_in(
    flag: str | None, expected: str
) -> None:
    values = {} if flag is None else {OPT_IN: flag}
    result = eval(_depends_expr(), {"d": FakeData(values)})
    assert result.strip() == expected


def test_taskhash_tracks_the_opt_in_and_the_device_tree_list() -> None:
    text = UKI_CLASS.read_text()
    vardeps = re.search(r"do_image_wic\[vardeps\] \+= \"([^\"]*)\"", text)
    assert vardeps is not None
    names = vardeps.group(1).replace("\\", " ").split()
    assert OPT_IN in names
    assert "KERNEL_DEVICETREE" in names


# --- the opt-in is set for the SOQuartz leaf only ------------------------


def test_soquartz_leaf_opts_in() -> None:
    assert f'{OPT_IN} = "1"' in _code(SOQUARTZ)


@pytest.mark.parametrize("conf", [INTEL, QEMUARM64], ids=lambda p: p.name)
def test_intel_and_qemuarm64_leave_the_opt_in_unset(conf: Path) -> None:
    assert not any(OPT_IN in line for line in _code(conf))


def test_no_shared_include_sets_the_opt_in() -> None:
    for inc in (MACHINE_DIR / "include").iterdir():
        assert OPT_IN not in inc.read_text(), inc.name


def test_class_default_is_off() -> None:
    assert f'{OPT_IN} ?= "0"' in _code(UKI_CLASS)


def test_upstream_soquartz_machine_lists_one_flat_dtb() -> None:
    conf = UPSTREAM_ROCKCHIP / "conf" / "machine" / "soquartz-model-a.conf"
    if not conf.exists():
        pytest.skip("meta-rockchip checkout absent")
    m = re.search(r'^KERNEL_DEVICETREE\s*=\s*"([^"]*)"', conf.read_text(), re.MULTILINE)
    assert m is not None
    assert m.group(1).split() == [f"rockchip/{BOARD_DTB}"]
