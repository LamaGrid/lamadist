# SPDX-License-Identifier: Apache-2.0
"""Static tests for the SOQuartz machine leaf (ADR 0013 decisions 1, 3, 10).

BitBake is not run, so every check here reads the leaf, the U-Boot
bbappend and fragment, and the Rockchip WKS as text.  What only a parse
or a build settles (final variable values, the U-Boot .config, the
loader2 contents) is listed in the leaf header as needs-parse or
needs-build.

Two optional cross-checks read upstream clones under the directory that
$LAMADIST_HOST_UPSTREAM_DIR names; they skip when it is unset or the
clone is absent.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
LAYER = ROOT / "meta-lamadist"
MACHINE_DIR = LAYER / "conf" / "machine"
LEAF = MACHINE_DIR / "soquartz-lamadist.conf"
SDBOOT_INC = MACHINE_DIR / "include" / "lamadist-boot-sdboot-uki.inc"
UBOOT_DIR = LAYER / "recipes-bsp" / "u-boot"
BBAPPEND = UBOOT_DIR / "u-boot_%.bbappend"
FRAGMENT = UBOOT_DIR / "files" / "lamadist-soquartz-efi.cfg"
ENV_TEXT = UBOOT_DIR / "files" / "lamadist-soquartz.env"
WKS = LAYER / "files" / "wic" / "lamadist-rockchip-bootdisk.wks.in"
X86_WKS = LAYER / "files" / "wic" / "lamadist-dmverity-bootdisk.wks.in"
KAS = ROOT / "kas" / "bsp" / "soquartz.kas.yml"
PARTITIONING = ROOT / "docs" / "PARTITIONING.md"

UPSTREAM_ENV = "LAMADIST_HOST_UPSTREAM_DIR"


def _upstream_clone(rel: str) -> Path:
    """The clone ``rel`` under $LAMADIST_HOST_UPSTREAM_DIR.

    With the variable unset, the path is under os.devnull, which is never
    a directory, so the cross-checks skip.
    """
    root = os.environ.get(UPSTREAM_ENV, "")
    return Path(root or os.devnull, rel)


UPSTREAM_ROCKCHIP = _upstream_clone("yoctoproject.org/meta-rockchip")
UPSTREAM_UBOOT = _upstream_clone("denx.de/u-boot")


def _code(path: Path) -> list[str]:
    """Non-comment, non-blank lines, stripped."""
    out = []
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if line and not line.startswith("#"):
            out.append(line)
    return out


def _index(lines: list[str], pattern: str) -> int:
    for i, line in enumerate(lines):
        if re.search(pattern, line):
            return i
    raise AssertionError(f"no line matches {pattern!r}")


def _has(lines: list[str], pattern: str) -> bool:
    return any(re.search(pattern, line) for line in lines)


# --- the machine leaf ----------------------------------------------------


def test_leaf_requires_the_shared_includes_and_no_tpm() -> None:
    lines = _code(LEAF)
    assert _has(lines, r"^require conf/machine/include/lamadist-dmverity\.inc$")
    assert _has(lines, r"^require conf/machine/include/lamadist-boot-sdboot-uki\.inc$")
    assert not _has(lines, r"lamadist-tpm2\.inc")
    assert not _has(lines, r"DISTRO_FEATURES.*tpm2")


def test_leaf_requires_the_upstream_soquartz_machine() -> None:
    lines = _code(LEAF)
    assert _has(lines, r"^require conf/machine/soquartz-model-a\.conf$")


def test_fitimage_gate_is_closed_before_the_soc_include() -> None:
    lines = _code(LEAF)
    gate = _index(lines, r'^RK_KERNEL_FITIMAGE\s*=\s*"False"$')
    soc = _index(lines, r"^require conf/machine/soquartz-model-a\.conf$")
    assert gate < soc, "RK_KERNEL_FITIMAGE must precede the SoC include"


def test_kernel_image_type_is_image() -> None:
    assert _has(_code(LEAF), r'^KERNEL_IMAGETYPE\s*=\s*"Image"$')


def test_competing_boot_paths_are_neutralised() -> None:
    lines = _code(LEAF)
    assert _has(lines, r'^UBOOT_EXTLINUX\s*=\s*"0"$')
    assert _has(
        lines,
        r'^MACHINE_ESSENTIAL_EXTRA_RDEPENDS:remove\s*=\s*"u-boot-extlinux"$',
    )


def test_rauc_demo_and_u_boot_env_feature_stay_off() -> None:
    lines = _code(LEAF)
    assert not _has(lines, r"^RK_RAUC_DEMO\b")
    assert not _has(lines, r"MACHINE_FEATURES.*rk-u-boot-env")
    assert not _has(lines, r"^RK_IMAGE_INCLUDES_UBOOT_ENV\b")


def test_u_boot_enters_through_the_wks_dependencies_only() -> None:
    lines = _code(LEAF)
    assert _has(lines, r"^WKS_FILE_DEPENDS\s*=.*\bu-boot\b"), (
        "u-boot must ride WKS_FILE_DEPENDS (do_image_wic recrdeptask do_deploy)"
    )
    # The provider assignment stays in the shared include, fail-closed.
    assert not _has(lines, r"PREFERRED_PROVIDER_virtual/bootloader")
    assert _has(
        _code(SDBOOT_INC),
        r'^PREFERRED_PROVIDER_virtual/bootloader\s*=\s*"systemd-boot"$',
    )


def test_leaf_selects_the_rockchip_wks() -> None:
    assert _has(_code(LEAF), r"^WKS_FILE\s*=\s*'lamadist-rockchip-bootdisk\.wks\.in'$")
    assert WKS.is_file()


def test_console_names_one_uart_and_is_marked_provisional() -> None:
    text = LEAF.read_text()
    lines = _code(LEAF)
    assert _has(lines, r'^SERIAL_CONSOLES\s*=\s*"1500000;ttyS2"$')
    assert _has(lines, r'^LAMADIST_CONSOLES\s*\?=\s*".*console=ttyS2,1500000.*"$')
    assert re.search(r"PROVISIONAL", text), "console choice must be marked provisional"


def test_leaf_header_carries_the_trust_statement() -> None:
    header = []
    for raw in LEAF.read_text().splitlines():
        if not raw.startswith("#"):
            break
        header.append(raw.lstrip("# ").strip())
    head = " ".join(header)
    # Decision 4, unfused form, in one place at the top of the leaf.
    assert "unfused" in head
    assert "not a root of trust" in head
    assert "OS root" in head


def test_leaf_has_no_hardware_or_site_detail() -> None:
    text = LEAF.read_text() + WKS.read_text() + BBAPPEND.read_text()
    assert not re.search(r"\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b", text)


# --- kas -----------------------------------------------------------------


def test_kas_selects_the_leaf_and_drops_the_priority_bump() -> None:
    text = KAS.read_text()
    assert re.search(r"^machine:\s*soquartz-lamadist\s*$", text, re.MULTILINE)
    assert "soquartz64" not in text
    assert "BBFILE_PRIORITY" not in text
    assert "30_soquartz" not in text


# --- the U-Boot bbappend and fragment ------------------------------------

ON = [
    "EFI_LOADER",
    "CMD_BOOTEFI",
    "EFI_BOOTMGR",
    "BOOTMETH_EFI_BOOTMGR",
    "BOOTMETH_EFILOADER",  # ADR 0013 writes BOOTMETH_EFI; the Kconfig symbol is this
    "FS_FAT",
    "FAT_WRITE",
    "FAT_RENAME",
    "EFI_SECURE_BOOT",
    "EFI_VARIABLES_PRESEED",
    "EFI_VARIABLE_NO_STORE",
    "ENV_IS_NOWHERE",
    "ENV_USE_DEFAULT_ENV_TEXT_FILE",
]

# ADR 0013 decision 3, "off".  BOOTMETH_PXE and CMD_BOOTELF are not
# Kconfig symbols in v2026.01 (the PXE boot method is
# BOOTMETH_EXTLINUX_PXE, boot/Kconfig:612; the ELF command is CMD_ELF,
# cmd/Kconfig:523).
OFF = [
    "BOOTMETH_EXTLINUX",
    "BOOTMETH_SCRIPT",
    "BOOTMETH_EXTLINUX_PXE",
    "BOOTMETH_VBE",
    "BOOTMETH_VBE_SIMPLE",
    "BOOTMETH_ANDROID",
    "CMD_BOOTI",
    "CMD_BOOTM",
    "CMD_BOOTZ",
    "CMD_ELF",
    "CMD_GO",
    "CMD_MEMORY",
    "CMD_PXE",
    "CMD_SOURCE",
    "BOOTSTD_DEFAULTS",  # selects BOOTMETH_DISTRO and BOOT_DEFAULTS
    "BOOTMETH_DISTRO",
    "BOOT_DEFAULTS",
    "EFI_RT_VOLATILE_STORE",
    "EFI_MM_COMM_TEE",
    "EFI_VARIABLE_FILE_STORE",
    # every ENV_IS_IN_* (env/Kconfig:89-456) and ENV_IMPORT_FDT (:786)
    "ENV_IS_IN_EEPROM",
    "ENV_IS_IN_FAT",
    "ENV_IS_IN_EXT4",
    "ENV_IS_IN_FLASH",
    "ENV_IS_IN_MMC",
    "ENV_IS_IN_NAND",
    "ENV_IS_IN_SCSI",
    "ENV_IS_IN_NVRAM",
    "ENV_IS_IN_ONENAND",
    "ENV_IS_IN_REMOTE",
    "ENV_IS_IN_SPI_FLASH",
    "ENV_IS_IN_MTD",
    "ENV_IS_IN_UBI",
    "ENV_IMPORT_FDT",
]


def _cfg_state() -> dict[str, str]:
    state: dict[str, str] = {}
    for raw in FRAGMENT.read_text().splitlines():
        line = raw.strip()
        m = re.match(r"^# CONFIG_(\w+) is not set$", line)
        if m:
            state[m.group(1)] = "n"
            continue
        m = re.match(r"^CONFIG_(\w+)=(.*)$", line)
        if m:
            state[m.group(1)] = m.group(2)
    return state


@pytest.mark.parametrize("sym", ON)
def test_fragment_turns_the_efi_options_on(sym: str) -> None:
    assert _cfg_state().get(sym) == "y", f"CONFIG_{sym}=y missing"


@pytest.mark.parametrize("sym", OFF)
def test_fragment_turns_every_other_boot_path_off(sym: str) -> None:
    assert _cfg_state().get(sym) == "n", f"# CONFIG_{sym} is not set missing"


def test_fragment_pins_autoboot_and_env_through_a_text_file() -> None:
    state = _cfg_state()
    assert state.get("BOOTDELAY") == "-2"
    assert "ENV_DEFAULT_ENV_TEXT_FILE" in state
    env = {
        k: v for k, v in (line.split("=", 1) for line in _code(ENV_TEXT) if "=" in line)
    }
    assert env["bootdelay"] == "-2"
    assert env["fdtfile"] == ""
    assert env["boot_targets"] and " " not in env["boot_targets"], (
        "boot_targets must name the shipping medium only"
    )
    # bootmeth_efi reads these two; upstream values, rk3568_common.h:25,27.
    assert env["kernel_addr_r"] == "0x02000000"
    assert env["fdt_addr_r"] == "0x12000000"


def test_preseed_seed_path_is_a_marked_hook() -> None:
    text = FRAGMENT.read_text()
    assert "LAMADIST-SEED-HOOK" in text
    # No seed binary or checked-in .var file anywhere under the bbappend.
    assert not list(UBOOT_DIR.rglob("*.var"))
    assert not list(UBOOT_DIR.rglob("*.esl"))


def test_bbappend_is_machine_scoped() -> None:
    text = BBAPPEND.read_text()
    code = _code(BBAPPEND)
    assert _has(code, r"^SRC_URI:append:soquartz-lamadist\b")
    assert "lamadist-soquartz-efi.cfg" in text
    assert "lamadist-soquartz.env" in text
    assert not _has(code, r"^SRC_URI\s*(\+=|=|\?=)")
    assert not _has(code, r"^SRC_URI:append\s*=")
    assert _has(code, r"^do_configure:prepend:soquartz-lamadist\b")


@pytest.mark.skipif(not UPSTREAM_UBOOT.is_dir(), reason="no U-Boot v2026.01 checkout")
def test_fragment_symbols_exist_in_uboot_v2026_01() -> None:
    kconfigs = "\n".join(
        p.read_text() for p in UPSTREAM_UBOOT.rglob("Kconfig*") if p.is_file()
    )
    for sym in _cfg_state():
        assert re.search(rf"^(menu)?config {sym}$", kconfigs, re.MULTILINE), (
            f"CONFIG_{sym} is not a Kconfig symbol in U-Boot v2026.01"
        )


# --- the WKS -------------------------------------------------------------

# Upstream meta-rockchip files/wic/rockchip.wks (9d02575), lines 21-28.
PRELUDE = {
    "loader1": ("64s", "3552K", 21),
    "v_storage": ("7168s", "256K", 22),
    "reserved": ("7680s", "192K", 23),
    "reserved1": ("8064s", "32K", 24),
    "uboot_env": ("8128s", "32K", 25),
    "reserved2": ("8192s", "4096K", 26),
    "loader2": ("16384s", "4096K", 27),
    "atf": ("24576s", "4096K", 28),
}


def _wks_parts(path: Path) -> list[str]:
    return [line for line in _code(path) if line.startswith("part ")]


def _prelude_rows(parts: list[str]) -> dict[str, tuple[str, str]]:
    rows = {}
    for line in parts:
        name = re.match(r"part (\w+)\s", line)
        offset = re.search(r"--offset (\S+)", line)
        size = re.search(r"--fixed-size (\S+)", line)
        if name and offset and size:
            rows[name.group(1)] = (offset.group(1), size.group(1))
    return rows


def test_wks_prelude_offsets_match_upstream() -> None:
    rows = _prelude_rows(_wks_parts(WKS))
    assert list(rows) == list(PRELUDE), "prelude partitions or their order differ"
    for name, (offset, size, _line) in PRELUDE.items():
        assert rows[name] == (offset, size), f"{name} differs from rockchip.wks"


def test_wks_prelude_leaves_vendor_storage_and_atf_untouched() -> None:
    parts = {re.match(r"part (\w+)", p).group(1): p for p in _wks_parts(WKS)[:8]}  # type: ignore[union-attr]
    for name in ("v_storage", "reserved", "reserved1", "reserved2", "atf", "uboot_env"):
        assert "--source" not in parts[name], f"{name} must stay empty"
    assert "file=${SPL_BINARY}" in parts["loader1"]
    assert "file=u-boot.${UBOOT_SUFFIX}" in parts["loader2"]
    assert not _has(_code(WKS), r"\$\{RK_UBOOT_ENV\}")


def test_wks_prelude_targets_the_boot_medium() -> None:
    for line in _wks_parts(WKS):
        assert "--ondisk mmcblk0" in line, line
    assert "--ondisk sda" not in WKS.read_text()


def test_wks_tail_matches_the_x86_layout() -> None:
    ours = [
        line.replace("--ondisk mmcblk0", "--ondisk sda")
        for line in _code(WKS)
        if "--offset" not in line
    ]
    theirs = _code(X86_WKS)
    assert ours == theirs, "ESP, A/B verity, and LUKS2 var must equal the x86_64 WKS"


@pytest.mark.skipif(not UPSTREAM_ROCKCHIP.is_dir(), reason="no meta-rockchip checkout")
def test_wks_prelude_matches_the_upstream_file() -> None:
    upstream = UPSTREAM_ROCKCHIP / "files" / "wic" / "rockchip.wks"
    rows = _prelude_rows([line for line in _code(upstream) if line.startswith("part ")])
    assert rows == {k: (v[0], v[1]) for k, v in PRELUDE.items()}


# --- docs ----------------------------------------------------------------


def test_partitioning_doc_shows_the_shipped_prelude() -> None:
    text = PARTITIONING.read_text()
    for name in PRELUDE:
        assert name in text, f"docs/PARTITIONING.md lacks {name}"
    assert "lamadist-rockchip-bootdisk.wks.in" in text
