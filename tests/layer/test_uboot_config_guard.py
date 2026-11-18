# SPDX-License-Identifier: Apache-2.0
"""The merged U-Boot .config is checked after configure.

openembedded-core merges the fragments over the defconfig and runs
`oldconfig`, which drops a symbol whose dependencies are not met and says
nothing.  The other build guards read the fragment text, the seed file,
and the default environment, so a moved Kconfig could give a U-Boot with
no Secure Boot or no seed while the build stayed green.  The argument
that PK, KEK, and db are write-protected at run time rests on these
symbols, so `lamadist_uboot_check_config` reads `${B}/.config` and stops
the build on any difference, for the SOQuartz U-Boot and for the QEMU
payload.  It takes its lists from the fragments each build merges, so
every fragment line is checked, not a hand-kept subset.

BitBake is not run.  The shell body of the function is extracted and run
against a scratch .config, as test_notpm_preset.py does for its mask.  That
the check fires inside do_configure is needs-build.
"""

from __future__ import annotations

import re
import subprocess
from collections.abc import Sequence
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
UBOOT_DIR = ROOT / "meta-lamadist" / "recipes-bsp" / "u-boot"
BBAPPEND = UBOOT_DIR / "u-boot_%.bbappend"
INC = UBOOT_DIR / "lamadist-uboot-vm.inc"
FRAGMENT = UBOOT_DIR / "files" / "lamadist-soquartz-efi.cfg"
QEMU_FRAGMENT = UBOOT_DIR / "files" / "lamadist-qemu-arm64-efi.cfg"
SEED_CLASS = ROOT / "meta-lamadist" / "classes" / "lamadist-efi-var-seed.bbclass"

FUNC = "lamadist_uboot_check_config"

# The fragments each build merges, in merge order.
BOARD = (FRAGMENT,)
PAYLOAD = (FRAGMENT, QEMU_FRAGMENT)

# The floor that the run-time protection rests on: the board fragment
# must keep these on and off.  The check itself reads every fragment line.
REQUIRED = [
    "EFI_LOADER",
    "BOOTSTD_PROG",
    "BOOTMETH_EFILOADER",
    "EFI_SECURE_BOOT",
    "EFI_VARIABLES_PRESEED",
    "EFI_VARIABLE_NO_STORE",
    "ENV_IS_NOWHERE",
    "FS_FAT",
    "FAT_WRITE",
    "FAT_RENAME",
]
# Decision 3's off list: the prompt, the stores, every boot method, and
# every command that loads or runs something Secure Boot does not verify.
FORBIDDEN = [
    "CMDLINE",
    "EFI_BOOTMGR",
    "EFI_RT_VOLATILE_STORE",
    "EFI_VARIABLE_FILE_STORE",
    "BOOTSTD_DEFAULTS",
    "BOOTMETH_DISTRO",
    "BOOT_DEFAULTS",
    "BOOTMETH_EXTLINUX",
    "BOOTMETH_SCRIPT",
    "BOOTMETH_EXTLINUX_PXE",
    "BOOTMETH_VBE",
    "BOOTMETH_VBE_SIMPLE",
    "BOOTMETH_ANDROID",
    "BOOTMETH_CROS",
    "BOOTMETH_RAUC",
    "BOOTMETH_EFI_BOOTMGR",
    "CMD_BOOTEFI_BOOTMGR",
    "CMD_BOOTI",
    "CMD_BOOTM",
    "CMD_BOOTZ",
    "CMD_ELF",
    "CMD_GO",
    "CMD_MEMORY",
    "CMD_SYSBOOT",
    "CMD_BOOTMENU",
    "CMD_NVEDIT_EFI",
    "CMD_EFIDEBUG",
    "CMD_BOOTEFI_SELFTEST",
    "ENV_IS_IN_MMC",
    "USE_PREBOOT",
]


def _merged(fragments: Sequence[Path]) -> dict[str, str]:
    """Symbol -> the .config line the fragments ask for, the later fragment
    winning.  An "is not set" symbol maps to its "is not set" line."""
    want: dict[str, str] = {}
    for frag in fragments:
        for line in frag.read_text().splitlines():
            m = re.fullmatch(r"(CONFIG_\w+)=.*", line) or re.fullmatch(
                r"# (CONFIG_\w+) is not set", line
            )
            if m:
                want[m.group(1)[len("CONFIG_") :]] = line
    return want


def _on(fragments: Sequence[Path]) -> list[str]:
    return sorted(s for s, ln in _merged(fragments).items() if ln.endswith("=y"))


def _set_not_y(fragments: Sequence[Path]) -> list[str]:
    return sorted(
        s
        for s, ln in _merged(fragments).items()
        if not ln.startswith("#") and not ln.endswith("=y")
    )


def _off(fragments: Sequence[Path]) -> list[str]:
    return sorted(s for s, ln in _merged(fragments).items() if ln.startswith("#"))


def _seed_name() -> str:
    m = re.search(
        r'^LAMADIST_EFI_VAR_SEED_FILE \?= "([^"]+)"$',
        SEED_CLASS.read_text(),
        re.MULTILINE,
    )
    assert m, "the seed class names no default seed file"
    return m.group(1)


def _body() -> str:
    m = re.search(
        rf"^{FUNC} \(\) \{{\n(.*?)^\}}",
        BBAPPEND.read_text(),
        re.MULTILINE | re.DOTALL,
    )
    assert m, f"{FUNC}() not found in the U-Boot bbappend"
    return m.group(1)


def _good_config(fragments: Sequence[Path] = BOARD) -> list[str]:
    """A merged .config as the real builds produce it: every fragment line
    as written (window j showed each one resolves so)."""
    return [
        "#",
        "# Automatically generated file; DO NOT EDIT.",
        "#",
        *_merged(fragments).values(),
    ]


def _run(
    tmp: Path,
    lines: list[str] | None,
    fragments: Sequence[Path] = BOARD,
) -> subprocess.CompletedProcess[str]:
    """Run the extracted body with ${B} at a scratch build dir and the
    fragments as its arguments.  A None `lines` leaves the build dir with
    no .config at all."""
    build = tmp / "build"
    build.mkdir()
    if lines is not None:
        (build / ".config").write_text("\n".join(lines) + "\n")
    body = _body().replace("${B}", str(build))
    body = body.replace("${LAMADIST_EFI_VAR_SEED_FILE}", _seed_name())
    prelude = 'bbfatal() { echo "FATAL: $*" >&2; exit 1; }\n'
    args = " ".join(f"'{f}'" for f in fragments)
    return subprocess.run(
        ["sh", "-eu", "-c", f"{prelude}set -- {args}\n{body}"],
        capture_output=True,
        text=True,
        check=False,
    )


def _without(lines: list[str], sym: str) -> list[str]:
    return [
        ln
        for ln in lines
        if not ln.startswith(f"CONFIG_{sym}=") and ln != f"# CONFIG_{sym} is not set"
    ]


# --- static: both builds call one check after configure --------------------


def test_the_function_reads_the_built_config_and_stops_the_build() -> None:
    body = _body()
    assert "${B}/.config" in body
    assert "bbfatal" in body
    assert "${LAMADIST_EFI_VAR_SEED_FILE}" in body


@pytest.mark.parametrize(
    ("path", "machine", "fragments"),
    [
        (BBAPPEND, "soquartz-lamadist", BOARD),
        (INC, "qemuarm64-lamadist", PAYLOAD),
    ],
)
def test_each_build_checks_the_fragments_it_merges_after_configure(
    path: Path, machine: str, fragments: Sequence[Path]
) -> None:
    m = re.search(
        rf"^do_configure:append:{machine} \(\) \{{\n(.*?)^\}}",
        path.read_text(),
        re.MULTILINE | re.DOTALL,
    )
    assert m, f"no do_configure:append:{machine} in {path.name}"
    args = " ".join(f'"${{UNPACKDIR}}/{f.name}"' for f in fragments)
    assert re.search(rf"^\s*{FUNC} {re.escape(args)}\s*$", m.group(1), re.MULTILINE)


def test_the_payload_merges_its_fragments_in_the_order_it_checks_them() -> None:
    names = re.findall(r"file://(\S+\.cfg)", INC.read_text())
    assert names == [f.name for f in PAYLOAD]


def test_the_check_is_not_a_prepend_that_runs_before_the_merge() -> None:
    for path in (BBAPPEND, INC):
        assert not re.search(
            rf"^do_configure:prepend:\S+ \(\) \{{[^}}]*{FUNC}",
            path.read_text(),
            re.MULTILINE,
        ), path.name


def test_the_function_keeps_no_symbol_list_of_its_own() -> None:
    body = _body()
    for sym in [*REQUIRED, *FORBIDDEN]:
        assert not re.search(rf"\b{sym}\b", body), f"{sym} is named in the body"
    assert '"$@"' in body


def test_the_fragment_keeps_the_floor_the_protection_rests_on() -> None:
    frag = FRAGMENT.read_text()
    for sym in REQUIRED:
        assert re.search(rf"^CONFIG_{sym}=y$", frag, re.MULTILINE), sym
    for sym in FORBIDDEN:
        assert re.search(rf"^# CONFIG_{sym} is not set$", frag, re.MULTILINE), sym


def test_every_boot_method_the_fragment_turns_off_is_checked() -> None:
    off = re.findall(
        r"^# CONFIG_((?:BOOTMETH_|BOOTSTD_)\w+) is not set$",
        FRAGMENT.read_text(),
        re.MULTILINE,
    )
    assert off, "the fragment turns no boot method off"
    assert set(off) <= set(_off(BOARD)) & set(_off(PAYLOAD))


# --- behaviour: the extracted body, run on scratch .config files ------------


@pytest.mark.parametrize("fragments", [BOARD, PAYLOAD], ids=["board", "payload"])
def test_a_good_config_passes(tmp_path: Path, fragments: Sequence[Path]) -> None:
    out = _run(tmp_path, _good_config(fragments), fragments)
    assert out.returncode == 0, out.stderr


def test_a_missing_config_fails(tmp_path: Path) -> None:
    out = _run(tmp_path, None)
    assert out.returncode != 0
    assert "FATAL" in out.stderr and ".config" in out.stderr


def test_an_empty_config_fails(tmp_path: Path) -> None:
    assert _run(tmp_path, []).returncode != 0


def test_no_fragment_named_fails(tmp_path: Path) -> None:
    out = _run(tmp_path, _good_config(), ())
    assert out.returncode != 0
    assert "fragments" in out.stderr


def test_fragments_that_set_nothing_fail(tmp_path: Path) -> None:
    empty = tmp_path / "empty.cfg"
    empty.write_text("# a comment only\n")
    out = _run(tmp_path, _good_config(), (empty,))
    assert out.returncode != 0


@pytest.mark.parametrize("sym", _on(BOARD))
def test_a_board_symbol_that_oldconfig_dropped_fails(tmp_path: Path, sym: str) -> None:
    out = _run(tmp_path, _without(_good_config(), sym))
    assert out.returncode != 0
    assert sym in out.stderr


@pytest.mark.parametrize("sym", _on(PAYLOAD))
def test_a_payload_symbol_that_oldconfig_dropped_fails(
    tmp_path: Path, sym: str
) -> None:
    lines = _without(_good_config(PAYLOAD), sym)
    out = _run(tmp_path, lines, PAYLOAD)
    assert out.returncode != 0
    assert sym in out.stderr


@pytest.mark.parametrize("sym", _on(BOARD))
def test_a_board_symbol_printed_off_fails(tmp_path: Path, sym: str) -> None:
    lines = [*_without(_good_config(), sym), f"# CONFIG_{sym} is not set"]
    out = _run(tmp_path, lines)
    assert out.returncode != 0
    assert sym in out.stderr


@pytest.mark.parametrize("sym", _set_not_y(PAYLOAD))
def test_a_changed_value_fails(tmp_path: Path, sym: str) -> None:
    lines = [*_without(_good_config(PAYLOAD), sym), f'CONFIG_{sym}="other"']
    out = _run(tmp_path, lines, PAYLOAD)
    assert out.returncode != 0
    assert sym in out.stderr


@pytest.mark.parametrize("sym", _off(BOARD))
def test_a_board_symbol_turned_on_fails(tmp_path: Path, sym: str) -> None:
    out = _run(tmp_path, [*_without(_good_config(), sym), f"CONFIG_{sym}=y"])
    assert out.returncode != 0
    assert sym in out.stderr


@pytest.mark.parametrize("sym", _off(PAYLOAD))
def test_a_payload_symbol_turned_on_fails(tmp_path: Path, sym: str) -> None:
    lines = [*_without(_good_config(PAYLOAD), sym), f"CONFIG_{sym}=y"]
    out = _run(tmp_path, lines, PAYLOAD)
    assert out.returncode != 0
    assert sym in out.stderr


@pytest.mark.parametrize("sym", _off(BOARD))
def test_a_board_symbol_that_is_absent_passes(tmp_path: Path, sym: str) -> None:
    """EFI_RT_VOLATILE_STORE depends on EFI_VARIABLE_FILE_STORE, so it is
    absent from the .config, not printed off.  Absent is off."""
    out = _run(tmp_path, _without(_good_config(), sym))
    assert out.returncode == 0, out.stderr


_T_ON = "CONFIG_LAMADIST_T=y"
_T_OFF = "# CONFIG_LAMADIST_T is not set"


@pytest.mark.parametrize(
    ("first", "last", "config", "ok"),
    [
        (_T_ON, _T_OFF, [], True),
        (_T_ON, _T_OFF, [_T_ON], False),
        (_T_OFF, _T_ON, [_T_ON], True),
        (_T_OFF, _T_ON, [], False),
    ],
)
def test_the_later_fragment_wins(
    tmp_path: Path, first: str, last: str, config: list[str], ok: bool
) -> None:
    frags = (tmp_path / "a.cfg", tmp_path / "b.cfg")
    frags[0].write_text(f"{first}\nCONFIG_LAMADIST_KEEP=y\n")
    frags[1].write_text(f"{last}\n")
    lines = [
        f'CONFIG_EFI_VAR_SEED_FILE="{_seed_name()}"',
        "CONFIG_LAMADIST_KEEP=y",
        *config,
    ]
    out = _run(tmp_path, lines, frags)
    assert (out.returncode == 0) is ok, out.stderr


def test_a_seed_file_that_is_not_the_one_the_class_writes_fails(
    tmp_path: Path,
) -> None:
    lines = [
        'CONFIG_EFI_VAR_SEED_FILE="other.seed"'
        if ln.startswith("CONFIG_EFI_VAR_SEED_FILE=")
        else ln
        for ln in _good_config()
    ]
    out = _run(tmp_path, lines)
    assert out.returncode != 0
    assert "EFI_VAR_SEED_FILE" in out.stderr


def test_a_commented_out_line_does_not_count_as_on(tmp_path: Path) -> None:
    lines = [
        "# CONFIG_EFI_SECURE_BOOT=y" if ln == "CONFIG_EFI_SECURE_BOOT=y" else ln
        for ln in _good_config()
    ]
    assert _run(tmp_path, lines).returncode != 0


def test_a_symbol_with_a_longer_name_does_not_stand_in(tmp_path: Path) -> None:
    lines = [
        "CONFIG_EFI_SECURE_BOOT_EXTRA=y" if ln == "CONFIG_EFI_SECURE_BOOT=y" else ln
        for ln in _good_config()
    ]
    assert _run(tmp_path, lines).returncode != 0
