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
SEED_CLASS = LAYER / "classes" / "lamadist-efi-var-seed.bbclass"
ESP_CLASS = LAYER / "classes" / "lamadist-esp-slot-a.bbclass"
ADR13 = ROOT / "docs" / "adr" / "0013-arm-boot-chain.md"
ADR16 = ROOT / "docs" / "adr" / "0016-uboot-efi-var-seed-generator.md"
SEEDGEN = LAYER / "lib" / "lamadist" / "efivarseed.py"
PLAN = ROOT / "docs" / "PLAN.md"
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
    "BOOTMETH_EFILOADER",  # the v2026.01 Kconfig symbol (ADR 0013 decision 3)
    "BOOTSTD_PROG",  # boots without a command line, panics on failure
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
    # No prompt: with CMDLINE off every command is gone and
    # BOOTSTD_PROG (depends on !CMDLINE) boots, then panics.
    "CMDLINE",
    # The boot manager would scan auto-generated options over every block
    # device, SD card first.  BOOTMETH_EFILOADER alone finds
    # the pinned medium's removable path.
    "EFI_BOOTMGR",
    "BOOTMETH_EFI_BOOTMGR",
    "CMD_BOOTEFI_BOOTMGR",
    # Off only by today's defaults until the fragment names them.
    "USE_PREBOOT",
    "USB_GADGET",
    "CMD_NVEDIT_EFI",
    "CMD_EFIDEBUG",
    "CMD_BOOTEFI_SELFTEST",
    "EFI_CAPSULE_ON_DISK",
    "EFI_HTTP_BOOT",
    "BOOTMETH_CROS",
    "BOOTMETH_RAUC",
    "CMD_SYSBOOT",
    "CMD_BOOTMENU",
    "OF_BOARD",
    "BUTTON",
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


def test_fragment_pins_the_env_through_a_text_file() -> None:
    state = _cfg_state()
    # AUTOBOOT needs CMDLINE: a BOOTDELAY line would be dead.
    assert "BOOTDELAY" not in state
    assert "ENV_DEFAULT_ENV_TEXT_FILE" in state
    env = {
        k: v for k, v in (line.split("=", 1) for line in _code(ENV_TEXT) if "=" in line)
    }
    assert "bootdelay" not in env
    assert env["fdtfile"] == ""
    assert env["boot_targets"] and " " not in env["boot_targets"], (
        "boot_targets must name the shipping medium only"
    )
    # bootmeth_efi reads these two; upstream values, rk3568_common.h:25,27.
    assert env["kernel_addr_r"] == "0x02000000"
    assert env["fdt_addr_r"] == "0x12000000"


def test_env_text_file_is_one_source_relative_name() -> None:
    """u-boot-configure.inc merges the layer's copy of the fragment
    (find_cfgs), so a sed on ${UNPACKDIR} never reaches .config.  Name the
    env file source-relative, as the seed is, and copy it into ${S}; the
    out-of-tree make finds it through VPATH."""
    assert _cfg_state().get("ENV_DEFAULT_ENV_TEXT_FILE") == '"lamadist-soquartz.env"'
    assert "@" not in FRAGMENT.read_text()
    code = _code(BBAPPEND)
    assert not _has(code, r"sed\b.*LAMADIST_UBOOT_ENV")
    assert _has(
        code,
        r'install\b.*\$\{UNPACKDIR\}/lamadist-soquartz\.env"? +"?\$\{S\}/lamadist-soquartz\.env',
    )


def test_env_text_file_has_its_build_tool() -> None:
    """U-Boot turns the env text file into a header with xxd, which is not
    a HOSTTOOL; oe-core's vim-native provides xxd-native."""
    assert _has(_code(BBAPPEND), r'^DEPENDS:append:soquartz-lamadist = " xxd-native"$')


def test_env_has_no_bootcmd() -> None:
    """With CMDLINE off U-Boot boots through BOOTSTD_PROG; bootcmd is dead."""
    assert not _has(_code(ENV_TEXT), r"^bootcmd=")


def test_preseed_seed_path_is_one_source_relative_name() -> None:
    """The class writes ${S}/<name>; the fragment names the same file."""
    assert _cfg_state().get("EFI_VAR_SEED_FILE") == '"lamadist-efivars.seed"'
    assert re.search(
        r'^LAMADIST_EFI_VAR_SEED_FILE \?= "lamadist-efivars\.seed"$',
        SEED_CLASS.read_text(),
        re.MULTILINE,
    )
    for path in (FRAGMENT, BBAPPEND, ENV_TEXT):
        assert "LAMADIST_UBOOT_EFI_SEED" not in path.read_text(), path.name
    assert not _has(_code(BBAPPEND), r"EFI_VAR_SEED_FILE.*>>")


def test_bbappend_inherits_the_seed_class_for_the_leaf_only() -> None:
    code = _code(BBAPPEND)
    assert not _has(code, r"^inherit\s+lamadist-efi-var-seed")
    assert _has(
        code, r'^LAMADIST_UBOOT_SEED_CLASS:soquartz-lamadist = "lamadist-efi-var-seed"$'
    )
    assert _has(code, r"^inherit_defer \$\{LAMADIST_UBOOT_SEED_CLASS\}$")


def test_bbappend_fails_closed_without_the_seed() -> None:
    text = BBAPPEND.read_text()
    assert "${LAMADIST_EFI_VAR_SEED_FILE}" in text
    assert "bbfatal" in text


def test_leaf_shows_no_boot_menu() -> None:
    """No systemd-boot menu on the UART, and no key read that opens one.

    A timeout of 0 keeps a 100 ms key read; `menu-disabled` skips it
    (ADR 0013 decision 3).  The class exposes the knob.
    """
    assert _has(_code(LEAF), r'^LAMADIST_BOOT_ENTRY_TIMEOUT \?= "menu-disabled"$')
    assert "LAMADIST_BOOT_ENTRY_TIMEOUT" in ESP_CLASS.read_text()


def test_no_seed_or_var_file_is_tracked_under_the_bbappend() -> None:
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


LINK_PATCH = (
    UBOOT_DIR / "files" / "0001-efi_loader-link-bootm-for-ExitBootServices.patch"
)


def test_link_patch_is_wired_for_the_leaf_only() -> None:
    """With CMDLINE off nothing builds boot/bootm.o, yet
    efi_exit_boot_services() calls bootm_disable_interrupts() and
    board_quiesce_devices() (lib/efi_loader/efi_boottime.c:2240,2243), so
    the final link fails.  The patch links bootm.o through LIB_BOOTM, and
    only on the SOQuartz leaf."""
    code = _code(BBAPPEND)
    block = []
    for i, line in enumerate(code):
        if line.startswith("SRC_URI:append:soquartz-lamadist"):
            for later in code[i + 1 :]:
                block.append(later)
                if later == '"':
                    break
    assert f"file://{LINK_PATCH.name}" in " ".join(block)
    assert not any(LINK_PATCH.name in line for line in code if line not in block)


def test_link_patch_carries_upstream_status_and_stays_small() -> None:
    text = LINK_PATCH.read_text()
    assert re.search(r"^Upstream-Status: \S", text, re.MULTILINE)
    assert re.search(r"^Signed-off-by: ", text, re.MULTILINE)
    touched = re.findall(r"^diff --git a/(\S+) b/", text, re.MULTILINE)
    assert touched == ["boot/Makefile", "lib/efi_loader/Kconfig"]
    assert re.search(
        r"^\+obj-\$\(CONFIG_LIB_BOOTM\) \+= bootm\.o bootm_os\.o$", text, re.MULTILINE
    )
    assert re.search(r"^\+\s*select LIB_BOOTM if ARM$", text, re.MULTILINE)
    # The patch adds no command, boot method, or CMDLINE select.
    added = [
        ln
        for ln in text.splitlines()
        if ln.startswith("+") and not ln.startswith("+++")
    ]
    assert not any(re.search(r"CMD_|BOOTMETH_|CMDLINE", ln) for ln in added)


@pytest.mark.parametrize("sym", ["CMDLINE", "CMD_BOOTM", "CMD_BOOTI", "CMD_BOOTZ"])
def test_link_patch_keeps_the_prompt_and_boot_commands_off(sym: str) -> None:
    """The link fix must never be paid for with the command line."""
    assert _cfg_state().get(sym) == "n"
    assert f"CONFIG_{sym}=y" not in FRAGMENT.read_text()


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


# --- doc and text claims (ADR 0013 corrections, PLAN) ---------------------


def _flat(path: Path) -> str:
    """The file's prose with comment markers and wrapping collapsed."""
    text = re.sub(r"^\s*(#|\*)\s?", "", path.read_text(), flags=re.MULTILINE)
    return re.sub(r"\s+", " ", text)


DBX_TEXTS = [ADR13, ADR16, SEEDGEN, FRAGMENT, BBAPPEND]


@pytest.mark.parametrize("path", DBX_TEXTS, ids=lambda p: p.name)
def test_no_text_claims_dbx_is_write_protected(path: Path) -> None:
    """U-Boot protects only authenticated variables that exist (the
    seed holds PK, KEK, and db; there is no dbx entry)."""
    flat = _flat(path)
    assert not re.search(r"dbx is (immutable|write-protected)", flat)
    assert not re.search(r"dbx[^.]{0,40}(write-protect|immutable)", flat), path.name
    assert not re.search(
        r"(refus|block|protect)[^.]{0,60}PK, KEK, db, and dbx", flat
    ), path.name
    assert not re.search(r"write-protected including dbx", flat)
    assert not re.search(r"PK, KEK, db, and dbx come from a build-time seed", flat)


@pytest.mark.parametrize("path", [ADR13, ADR16], ids=lambda p: p.name)
def test_adrs_state_what_protects_dbx(path: Path) -> None:
    flat = _flat(path)
    assert re.search(r"PK, KEK, and db are write-protected", flat), path.name
    assert re.search(r"dbx is absent", flat), path.name


def _decision_3() -> str:
    flat = _flat(ADR13)
    start = flat.index("3. The U-Boot configuration is an explicit fragment")
    return flat[start : flat.index("4. The trust statement", start)]


def test_adr13_decision_3_uses_the_v2026_01_symbol_names() -> None:
    d3 = _decision_3()
    for sym in (
        "BOOTMETH_EFILOADER",
        "CMD_ELF",
        "EFI_VARIABLES_PRESEED",
        "BOOTSTD_DEFAULTS",
        "BOOTMETH_DISTRO",
        "BOOT_DEFAULTS",
        "CMDLINE",
        "BOOTSTD_PROG",
    ):
        assert sym in d3, sym
    assert not re.search(r"\bBOOTMETH_PXE\b", d3)
    assert "CMD_BOOTELF" not in d3
    assert not re.search(r"\bBOOTMETH_EFI\b", d3)


def test_adr13_decision_3_turns_the_efi_boot_manager_off() -> None:
    d3 = _decision_3()
    on = d3[d3.index("- on:") : d3.index("- off:")]
    off = d3[d3.index("- off:") :]
    assert "EFI_BOOTMGR" not in on
    assert "BOOTMETH_EFI_BOOTMGR" in off
    assert re.search(r"only the pinned medium", d3)


def test_adr13_names_the_shipped_leaf() -> None:
    flat = _flat(ADR13)
    assert "soquartz-lamadist.conf" in flat
    assert "`soquartz.conf`" not in flat


def _plan_item(start: str) -> str:
    text = PLAN.read_text()
    i = text.index(start)
    j = text.index("\n- [", i + 1)
    return text[i:j]


@pytest.mark.parametrize(
    "start",
    [
        "- [x] `soquartz-lamadist.conf`",
        "- [x] Preseed generator",
        "- [x] Device tree inside the UKI",
    ],
)
def test_plan_ticks_the_m5_items_with_their_build_record(start: str) -> None:
    """Each ticked item names the evidence window that built it on an
    earlier tree, and says that a build at the tip is still pending."""
    item = _flat_text(_plan_item(start))
    assert re.search(r"\bwindow [a-z]\b", item)
    assert "earlier tree" in item
    assert "a build at the tip is pending" in item
    assert "static; build pending" not in item


def _flat_text(text: str) -> str:
    return re.sub(r"\s+", " ", text)


def test_bbappend_guards_the_built_default_env() -> None:
    """The built u-boot-initial-env must equal the layer's env text, or the
    build dies (a wrong default environment must not ship silently)."""
    text = BBAPPEND.read_text()
    m = re.search(
        r"^do_compile:append:soquartz-lamadist \(\) \{\n(.*?)^\}",
        text,
        re.MULTILINE | re.DOTALL,
    )
    assert m, "no soquartz-lamadist-scoped do_compile:append guard"
    body = m.group(1)
    assert "bbfatal" in body
    assert "u-boot-initial-env" in body
    assert "lamadist-soquartz.env" in body
    assert "sort" in body


def test_adr_names_the_bootm_nm_kill_switch() -> None:
    text = (ROOT / "docs" / "adr" / "0013-arm-boot-chain.md").read_text()
    for sym in (
        "bootm_run_states",
        "bootm_boot_start",
        "boot_selected_os",
        "do_bootm_linux",
    ):
        assert sym in text, sym
    assert re.search(r"`nm` on the built u-boot ELF", text)
    assert "(checked at v2026.07)" in text
