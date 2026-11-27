# SPDX-License-Identifier: Apache-2.0
"""A UKI must never ship an empty dm-verity initramfs.

meta-security's dm-verity-image-initramfs sets do_image[nostamp], so
its do_image_cpio re-runs in every bitbake invocation.  With rm_work
inherited, rm_work_rootfs (a do_image_complete postfunc) empties the
recipe's rootfs.  Normally the recipe's own do_rm_work then runs and
drops the stamps, so the next invocation re-runs do_rootfs.  When that
do_rm_work does not run (the invocation fails or is interrupted after
the initramfs do_image_complete, or nothing schedules it because the
image that consumes the initramfs is itself in RM_WORK_EXCLUDE),
do_rootfs stays stamped.  The next invocation over the same TMPDIR
then packs an empty tree (a 1536-byte cpio), and the UKI built from it
panics with "No working init found".

These tests read the layer files; they run no bitbake.
"""

from __future__ import annotations

import re
import sys
import textwrap
import types
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]
LAYER = ROOT / "meta-lamadist"
SECURITY_INC = LAYER / "conf" / "distro" / "include" / "lamadist-security.inc"
UKI_CLASS = LAYER / "classes" / "lamadist-uki.bbclass"

# Size in bytes of a healthy x86_64 cpio archive.
HEALTHY_CPIO_BYTES = 39513088

_ASSIGNMENT = re.compile(
    r"^[ \t]*(?P<name>\w+)(?P<override>:append|:prepend|:remove)?[ \t]*"
    r"(?P<op>\?\?=|\?=|\+=|=\+|\.=|=\.|=)[ \t]*"
    r"(?P<quote>['\"])(?P<value>.*?)(?P=quote)",
    re.MULTILINE,
)


def _effective(text: str, name: str) -> str | None:
    """Return NAME's value after every assignment in TEXT, as BitBake sees it.

    Assignments apply in file order (=, ?=, ??=, +=, =+, .=, =.), then the
    :prepend, :append, and :remove overrides.  A ?= keeps the first value
    that reaches an unset variable; the last ??= is the default used when
    nothing else set the variable.  ${VAR} references to other variables in
    the same text are expanded.  A line that assigns NAME in a form this
    reader cannot parse raises, so no assignment goes unseen.
    """
    mine = [m for m in _ASSIGNMENT.finditer(text) if m["name"] == name]
    lines = re.findall(
        rf"^[ \t]*{re.escape(name)}(?=[ \t]*[:?+.=]).*$", text, re.MULTILINE
    )
    assert len(lines) == len(mine), f"unparsed assignment to {name}: {lines}"

    def expand(value: str) -> str:
        return re.sub(r"\$\{(\w+)\}", lambda m: _effective(text, m[1]) or "", value)

    value: str | None = None
    weak: str | None = None
    late: list[tuple[str, str]] = []
    for m in mine:
        op, override, rhs = m["op"], m["override"], expand(m["value"])
        if override:
            late.append((override, rhs))
        elif op == "=":
            value = rhs
        elif op == "?=":
            value = rhs if value is None else value
        elif op == "??=":
            weak = rhs
        elif op == "+=":
            value = f"{value or ''} {rhs}"
        elif op == "=+":
            value = f"{rhs} {value or ''}"
        elif op == ".=":
            value = (value or "") + rhs
        else:
            value = rhs + (value or "")
    if value is None:
        value = weak
    for override, rhs in late:
        if override == ":prepend":
            value = rhs + (value or "")
        elif override == ":append":
            value = (value or "") + rhs
        else:
            drop = rhs.split()
            value = " ".join(t for t in (value or "").split() if t not in drop)
    return value


def test_the_initramfs_image_is_excluded_from_rm_work() -> None:
    text = SECURITY_INC.read_text()
    assert _effective(text, "INITRAMFS_IMAGE") == "dm-verity-image-initramfs"
    excluded = (_effective(text, "RM_WORK_EXCLUDE") or "").split()
    assert "dm-verity-image-initramfs" in excluded


def test_the_rm_work_exclusion_adds_to_a_value_set_earlier() -> None:
    # local.conf and other config files set RM_WORK_EXCLUDE before the
    # distro include is parsed.  A weak (?=, ??=) or plain (=) assignment
    # in the include would then drop either their entries or ours.
    text = SECURITY_INC.read_text()
    excluded = (
        _effective("RM_WORK_EXCLUDE = 'earlier'\n" + text, "RM_WORK_EXCLUDE") or ""
    ).split()
    assert "earlier" in excluded
    assert "dm-verity-image-initramfs" in excluded


def test_a_later_empty_assignment_drops_the_exclusion() -> None:
    text = "INITRAMFS_IMAGE = 'img'\nRM_WORK_EXCLUDE += '${INITRAMFS_IMAGE}'\n"
    assert (_effective(text, "RM_WORK_EXCLUDE") or "").split() == ["img"]
    assert _effective(text + "RM_WORK_EXCLUDE = ''\n", "RM_WORK_EXCLUDE") == ""


def test_a_remove_override_drops_the_exclusion() -> None:
    text = "RM_WORK_EXCLUDE += 'a b'\nRM_WORK_EXCLUDE:remove = 'a'\n"
    assert (_effective(text, "RM_WORK_EXCLUDE") or "").split() == ["b"]


def test_a_weak_assignment_does_not_override_an_earlier_one() -> None:
    text = "X ?= 'one'\nX ?= 'two'\nY ??= 'weak'\nY = 'strong'\n"
    assert _effective(text, "X") == "one"
    assert _effective(text, "Y") == "strong"


def test_the_last_weak_default_wins() -> None:
    assert _effective("Z ??= 'one'\nZ ??= 'two'\n", "Z") == "two"
    assert _effective("Z ??= 'weak'\nZ ?= 'soft'\n", "Z") == "soft"


def test_an_assignment_form_the_reader_cannot_parse_is_not_ignored() -> None:
    with pytest.raises(AssertionError, match="unparsed"):
        _effective("RM_WORK_EXCLUDE:intel = 'x'\n", "RM_WORK_EXCLUDE")


def _class_floor() -> int:
    """The class's own default for the initramfs size floor."""
    default = _effective(UKI_CLASS.read_text(), "LAMADIST_UKI_INITRAMFS_MIN_BYTES")
    assert default is not None, "the class sets no default floor"
    return int(default)


def test_the_class_default_floor_is_a_real_floor() -> None:
    # An empty initramfs is 1536 bytes and a healthy one tens of MiB.
    assert 1024 * 1024 <= _class_floor() < HEALTHY_CPIO_BYTES


class _Fatal(Exception):
    pass


class _Data:
    def __init__(self, values: dict[str, str]) -> None:
        self.values = values

    def getVar(self, name: str) -> str | None:
        return self.values.get(name)


def _uki_build_function() -> Any:
    """Load lamadist_uki_build from the class as a plain function."""
    text = UKI_CLASS.read_text()
    match = re.search(
        r"^python lamadist_uki_build \(\) \{\n(.*?)^\}", text, re.MULTILINE | re.DOTALL
    )
    assert match, "lamadist_uki_build not found"
    body = textwrap.indent(textwrap.dedent(match.group(1)), "    ")
    namespace: dict[str, Any] = {}
    exec(f"def lamadist_uki_build(d):\n{body}", namespace)  # noqa: S102
    return namespace["lamadist_uki_build"]


@pytest.fixture
def fake_bb(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    commands: list[str] = []

    def fatal(msg: str) -> None:
        raise _Fatal(msg)

    def run(cmd: str, shell: bool = False) -> tuple[str, str]:
        commands.append(cmd)
        return "", ""

    bb = types.ModuleType("bb")
    process = types.ModuleType("bb.process")
    process.run = run  # type: ignore[attr-defined]
    bb.process = process  # type: ignore[attr-defined]
    bb.fatal = fatal  # type: ignore[attr-defined]
    bb.note = lambda *a, **k: None  # type: ignore[attr-defined]
    bb.debug = lambda *a, **k: None  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "bb", bb)
    monkeypatch.setitem(sys.modules, "bb.process", process)
    monkeypatch.setattr("builtins.bb", bb, raising=False)
    return commands


def _newc(entries: Iterable[tuple[str, int, bytes]]) -> bytes:
    """Build a newc ("070701") cpio archive from (name, mode, data) entries."""
    out = bytearray()

    def add(name: str, mode: int, data: bytes, ino: int) -> None:
        raw = name.encode() + b"\0"
        fields = (ino, mode, 0, 0, 1, 0, len(data), 0, 0, 0, 0, len(raw), 0)
        out.extend(b"070701" + b"".join(b"%08X" % f for f in fields))
        out.extend(raw)
        out.extend(b"\0" * (-len(out) % 4))
        out.extend(data)
        out.extend(b"\0" * (-len(out) % 4))

    for ino, (name, mode, data) in enumerate(entries, 1):
        add(name, mode, data, ino)
    add("TRAILER!!!", 0, b"", 0)
    return bytes(out)


_VERITY_ENV = ("usr/share/misc/dm-verity.env", 0o100644, b"DATA_BLOCK_SIZE=4096\n")
_INIT_SCRIPT = b"#!/bin/sh\nexec /sbin/init\n"


def _good_cpio(filler: int = 0) -> bytes:
    """A whole archive with an executable, non-empty /init."""
    return _newc(
        [
            ("usr", 0o040755, b""),
            _VERITY_ENV,
            ("usr/lib/filler", 0o100644, bytes(filler)),
            ("init", 0o100755, _INIT_SCRIPT),
        ]
    )


def _empty_rootfs_cpio() -> bytes:
    """What IMAGE_CMD:cpio packs from an emptied rootfs: the dm-verity.env
    that deploy_verity_hash writes, and the zero-byte, mode-0644 init it
    appends because the tree has none."""
    return _newc([_VERITY_ENV, ("init", 0o100644, b"")])


def _deploy(tmp_path: Path, cpio: bytes, min_bytes: int | str | None = 0) -> _Data:
    """Fake datastore and deploy directory around CPIO.

    MIN_BYTES is the floor variable's value; None leaves it at the class's
    own default.
    """
    deploy = tmp_path / "deploy"
    verity = tmp_path / "verity"
    deploy.mkdir(parents=True)
    verity.mkdir(parents=True)
    (verity / "lamadist-image-base.erofs-lz4hc.verity.env").write_text(
        "ROOT_HASH=" + "ab" * 32 + "\n"
    )
    (deploy / "linuxx64.efi.stub").write_bytes(b"stub")
    (deploy / "bzImage").write_bytes(b"kernel")
    (deploy / "microcode.cpio").write_bytes(b"\0" * 4096)
    (deploy / "dm-verity-image-initramfs-intel.cpio").write_bytes(cpio)
    values = {
        "DEPLOY_DIR_IMAGE": str(deploy),
        "STAGING_VERITY_DIR": str(verity),
        "DM_VERITY_IMAGE": "lamadist-image-base",
        "DM_VERITY_IMAGE_TYPE": "erofs-lz4hc",
        "EFI_ARCH": "x64",
        "KERNEL_IMAGETYPE": "bzImage",
        "LAMADIST_UKI_INCLUDE_MICROCODE": "1",
        "INITRAMFS_IMAGE": "dm-verity-image-initramfs",
        "INITRAMFS_FSTYPES": "cpio",
        "MACHINE": "intel",
        "KERNEL_VERSION": "6.18",
        "RECIPE_SYSROOT_NATIVE": str(tmp_path / "native"),
        "RECIPE_SYSROOT": str(tmp_path / "sysroot"),
        "prefix": "/usr",
        "UKI_SB_KEY": "",
        "UKI_SB_CERT": "",
        "APPEND": "console=ttyS0,115200 ro",
        "UKIFY_CMD": "ukify build",
        "LAMADIST_UKI_SLOTS": "a b",
    }
    if min_bytes is None:
        values["LAMADIST_UKI_INITRAMFS_MIN_BYTES"] = str(_class_floor())
    else:
        values["LAMADIST_UKI_INITRAMFS_MIN_BYTES"] = str(min_bytes)
    return _Data(values)


def test_the_uki_build_refuses_an_initramfs_under_the_class_floor(
    tmp_path: Path, fake_bb: list[str]
) -> None:
    d = _deploy(tmp_path, _empty_rootfs_cpio(), min_bytes=None)
    with pytest.raises(_Fatal, match="floor"):
        _uki_build_function()(d)
    assert fake_bb == []


def test_the_floor_refusal_says_how_to_recover(
    tmp_path: Path, fake_bb: list[str]
) -> None:
    d = _deploy(tmp_path, _empty_rootfs_cpio(), min_bytes=None)
    with pytest.raises(_Fatal) as refusal:
        _uki_build_function()(d)
    assert "bitbake -c rootfs -f dm-verity-image-initramfs" in str(refusal.value)
    assert "TMPDIR" in str(refusal.value)


def test_the_floor_is_inclusive_of_its_own_size(
    tmp_path: Path, fake_bb: list[str]
) -> None:
    cpio = _good_cpio()
    d = _deploy(tmp_path / "at", cpio, min_bytes=len(cpio))
    _uki_build_function()(d)
    assert len(fake_bb) == 2
    fake_bb.clear()
    d = _deploy(tmp_path / "over", cpio, min_bytes=len(cpio) + 1)
    with pytest.raises(_Fatal, match="floor"):
        _uki_build_function()(d)
    assert fake_bb == []


@pytest.mark.parametrize("value", ["", "1M", "abc", "1.5"])
def test_a_floor_that_is_not_an_integer_names_the_variable(
    tmp_path: Path, fake_bb: list[str], value: str
) -> None:
    d = _deploy(tmp_path, _good_cpio(), min_bytes=value)
    name = "LAMADIST_UKI_INITRAMFS_MIN_BYTES"
    match = rf"{name} must be an integer.*{re.escape(repr(value))}"
    with pytest.raises(_Fatal, match=match):
        _uki_build_function()(d)
    assert fake_bb == []


def test_the_uki_build_accepts_a_full_initramfs(
    tmp_path: Path, fake_bb: list[str]
) -> None:
    d = _deploy(tmp_path, _good_cpio(filler=2 * _class_floor()), min_bytes=None)
    _uki_build_function()(d)
    assert len(fake_bb) == 2
    assert all("dm-verity-image-initramfs-intel.cpio" in c for c in fake_bb)


def _uki_image_wic_depends(values: dict[str, str]) -> list[str]:
    """Expand the class's do_image_wic[depends] for the given variables.

    Weak defaults (?=) in the class fill any variable VALUES omits; an
    inline ${@...} expression is evaluated against them.
    """
    text = UKI_CLASS.read_text()
    known = dict(values)
    for m in re.finditer(r'^(\w+)\s*\?=\s*"(.*?)"', text, re.MULTILINE):
        known.setdefault(m.group(1), m.group(2))
    d = _Data(known)
    tokens: list[str] = []
    for m in re.finditer(
        r'^do_image_wic\[depends\]\s*\+=\s*"(.*?)"', text, re.MULTILINE | re.DOTALL
    ):
        value = re.sub(
            r"\$\{@(.*?)\}",
            lambda e: str(eval(e.group(1), {"d": d})),
            m.group(1),
        )
        tokens += value.replace("\\\n", " ").split()
    return tokens


def test_a_microcode_uki_waits_for_the_microcode_deploy() -> None:
    depends = _uki_image_wic_depends({"LAMADIST_UKI_INCLUDE_MICROCODE": "1"})
    assert "intel-microcode:do_deploy" in depends


def test_a_uki_without_microcode_does_not_pull_it_in() -> None:
    depends = _uki_image_wic_depends({})
    assert not any("microcode" in t for t in depends)
