# SPDX-License-Identifier: Apache-2.0
"""Static tests for the systemd-boot menu timeout (ADR 0013 decision 3).

The SOQuartz leaf and the U-Boot QEMU payload image take
`timeout menu-disabled`; every other machine keeps the class default of
5.  BitBake is not run.  lamadist_esp_slot_a_populate is a BitBake
python function, so the tests cut its body out of
lamadist-esp-slot-a.bbclass and run it against a fake datastore and a
fake ``bb``; the loader.conf it writes is the file the ESP carries.
What only a build settles (that wic copies this file over its own) is
left to the build, and what only a boot settles (that no key opens a
menu) is left to the QEMU key flood (.mise/lib/menu_flood.py).
"""

from __future__ import annotations

import os
import re
import shutil
import types
from collections.abc import Callable, Mapping
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
LAYER = ROOT / "meta-lamadist"
MACHINE_DIR = LAYER / "conf" / "machine"
ESP_CLASS = LAYER / "classes" / "lamadist-esp-slot-a.bbclass"
LEAF = MACHINE_DIR / "soquartz-lamadist.conf"
OVERLAY = ROOT / "kas" / "extras" / "uboot-vm.kas.yml"

KNOB = "LAMADIST_BOOT_ENTRY_TIMEOUT"
MENU_DISABLED = "menu-disabled"
FUNCTION = "lamadist_esp_slot_a_populate"
UKI = "lamadist-a.efi"


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


def _assigned(path: Path, op: str) -> list[str]:
    """The values of the file's `KNOB[:override] <op> "value"` lines."""
    rx = re.compile(rf'^{KNOB}(?::[\w-]+)* {re.escape(op)} "([^"]*)"$')
    return [m.group(1) for line in _code(path) if (m := rx.match(line))]


def _function_source(name: str) -> str:
    """The body of a ``python NAME () { ... }`` block as a plain def."""
    lines = ESP_CLASS.read_text().splitlines()
    start = lines.index(f"python {name} () {{")
    end = lines.index("}", start)
    return f"def {name}(d):\n" + "\n".join(lines[start + 1 : end]) + "\n"


LoaderConf = Callable[[str], str]


@pytest.fixture
def loader_conf(tmp_path: Path) -> LoaderConf:
    """Run the populate function and return the loader.conf it writes."""
    deploy = tmp_path / "deploy"
    overlay = tmp_path / "overlay"
    deploy.mkdir()
    (deploy / UKI).write_bytes(b"uki")

    def remove(path: str, recurse: bool = False) -> None:
        shutil.rmtree(path, ignore_errors=True)

    def mkdirhier(path: str) -> None:
        os.makedirs(path, exist_ok=True)

    def fatal(msg: str) -> None:
        raise AssertionError(msg)

    bb = types.SimpleNamespace(
        utils=types.SimpleNamespace(remove=remove, mkdirhier=mkdirhier), fatal=fatal
    )
    namespace: dict[str, object] = {"bb": bb}
    exec(_function_source(FUNCTION), namespace)  # noqa: S102

    def write(timeout: str) -> str:
        data = FakeData(
            {
                "LAMADIST_ESP_SLOT_A_DIR": str(overlay),
                "DEPLOY_DIR_IMAGE": str(deploy),
                "LAMADIST_UKI_FILENAME_A": UKI,
                KNOB: timeout,
            }
        )
        fn: Callable[[FakeData], None] = namespace[FUNCTION]  # type: ignore[assignment]
        fn(data)
        return (overlay / "loader" / "loader.conf").read_text()

    return write


# --- the SOQuartz leaf --------------------------------------------------------


def test_soquartz_loader_conf_disables_the_menu(loader_conf: LoaderConf) -> None:
    (value,) = _assigned(LEAF, "?=")
    assert loader_conf(value) == f"timeout {MENU_DISABLED}\n"


def test_soquartz_leaf_explains_the_decision() -> None:
    text = LEAF.read_text()
    assert "open owner decision" not in text
    assert MENU_DISABLED in text


# --- every other machine keeps the class default ----------------------------


def test_class_default_keeps_the_five_second_menu(loader_conf: LoaderConf) -> None:
    (value,) = _assigned(ESP_CLASS, "?=")
    assert value == "5"
    assert loader_conf(value) == "timeout 5\n"


@pytest.mark.parametrize("value", ["0", "5", MENU_DISABLED, "menu-force"])
def test_class_writes_the_value_through_unquoted_and_unchecked(
    loader_conf: LoaderConf, value: str
) -> None:
    assert loader_conf(value) == f"timeout {value}\n"


def test_class_still_never_writes_a_default_line(loader_conf: LoaderConf) -> None:
    for value in ("5", MENU_DISABLED):
        assert not re.search(r"^default\b", loader_conf(value), re.MULTILINE)


def test_timeout_is_a_variable_dependency_of_the_wic() -> None:
    assert re.search(
        rf'^do_image_wic\[vardeps\] \+= "[^"]*\b{KNOB}\b',
        ESP_CLASS.read_text(),
        re.MULTILINE,
    )


SETTER = re.compile(
    rf"^\s*{KNOB}(?::[\w-]+)*\s*(?:\?\?=|\?=|:=|\+=|\.=|=)", re.MULTILINE
)


@pytest.mark.parametrize(
    "line",
    [
        f'{KNOB} = "5"',
        f'{KNOB}:intel = "5"',
        f'{KNOB}:append:intel = " 5"',
        f'    {KNOB}:remove:qemuarm64-lamadist ??= "5"',
    ],
)
def test_the_setter_guard_sees_stacked_overrides(line: str) -> None:
    assert SETTER.search(line)


def test_only_the_class_the_leaf_and_the_payload_overlay_set_the_timeout() -> None:
    """x86_64 and the plain qemuarm64 build keep the class default."""
    setter = SETTER
    files = [
        *LAYER.rglob("*.conf"),
        *LAYER.rglob("*.inc"),
        *LAYER.rglob("*.bb"),
        *LAYER.rglob("*.bbappend"),
        *LAYER.rglob("*.bbclass"),
        *ROOT.joinpath("kas").rglob("*.yml"),
    ]
    hits = sorted(
        p.relative_to(ROOT).as_posix() for p in files if setter.search(p.read_text())
    )
    assert hits == [
        OVERLAY.relative_to(ROOT).as_posix(),
        ESP_CLASS.relative_to(ROOT).as_posix(),
        LEAF.relative_to(ROOT).as_posix(),
    ]


# --- the U-Boot QEMU payload image ------------------------------------------


def test_payload_overlay_disables_the_menu_for_the_qemu_leaf_only() -> None:
    text = OVERLAY.read_text()
    assert _assigned(OVERLAY, "=") == [MENU_DISABLED]
    assert re.search(
        rf'^\s+{KNOB}:qemuarm64-lamadist = "{MENU_DISABLED}"$', text, re.MULTILINE
    )
    assert not re.search(rf"^\s+{KNOB} ", text, re.MULTILINE), "unscoped setting"


def test_payload_overlay_says_the_wic_signature_changes() -> None:
    flat = re.sub(r"[#\s]+", " ", OVERLAY.read_text())
    assert "image itself does not change" not in flat
    assert "do_image_wic" in flat
