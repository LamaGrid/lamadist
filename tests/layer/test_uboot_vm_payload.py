# SPDX-License-Identifier: Apache-2.0
"""Static tests for the U-Boot qemu_arm64 payload behind `vm --firmware u-boot`.

ADR 0013 open question 6 (answered go, 2026-11-15): a U-Boot qemu_arm64
firmware payload under the existing sdboot-uki profile, AAVMF untouched.
The payload exists only when kas/extras/uboot-vm.kas.yml sets
LAMADIST_UBOOT_VM = "1"; the default qemuarm64 build and the SOQuartz
U-Boot do not change.  BitBake is not run: what only a parse or a build
settles (the resolved .config, the built env) is needs-build.

Two optional cross-checks read the pinned tag from an upstream U-Boot
clone under the directory that $LAMADIST_HOST_UPSTREAM_DIR names; they
skip when the variable is unset or the clone is absent.
"""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
LAYER = ROOT / "meta-lamadist"
UBOOT_DIR = LAYER / "recipes-bsp" / "u-boot"
BBAPPEND = UBOOT_DIR / "u-boot_%.bbappend"
INC = UBOOT_DIR / "lamadist-uboot-vm.inc"
FILES = UBOOT_DIR / "files"
SHARED_CFG = FILES / "lamadist-soquartz-efi.cfg"
QEMU_CFG = FILES / "lamadist-qemu-arm64-efi.cfg"
QEMU_ENV = FILES / "lamadist-qemu-arm64.env"
LINK_PATCH = FILES / "0001-efi_loader-link-bootm-for-ExitBootServices.patch"
OVERLAY = ROOT / "kas" / "extras" / "uboot-vm.kas.yml"
QEMU_KAS = ROOT / "kas" / "bsp" / "qemuarm64.kas.yml"
QEMU_LEAF = LAYER / "conf" / "machine" / "qemuarm64-lamadist.conf"
ADR13 = ROOT / "docs" / "adr" / "0013-arm-boot-chain.md"
UPSTREAM_ENV = "LAMADIST_HOST_UPSTREAM_DIR"
# Under os.devnull, which is never a directory, when the variable is unset.
UPSTREAM_UBOOT = Path(os.environ.get(UPSTREAM_ENV, "") or os.devnull, "denx.de/u-boot")
UBOOT_TAG = "v2026.01"

MACHINE = "qemuarm64-lamadist"
GATE = "LAMADIST_UBOOT_VM"


def _code(path: Path) -> list[str]:
    """Non-comment, non-blank lines, stripped."""
    out = []
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if line and not line.startswith("#"):
            out.append(line)
    return out


def _has(lines: list[str], pattern: str) -> bool:
    return any(re.search(pattern, line) for line in lines)


def _cfg(path: Path) -> dict[str, str]:
    state: dict[str, str] = {}
    for raw in path.read_text().splitlines():
        line = raw.strip()
        m = re.match(r"^# CONFIG_(\w+) is not set$", line)
        if m:
            state[m.group(1)] = "n"
            continue
        m = re.match(r"^CONFIG_(\w+)=(.*)$", line)
        if m:
            state[m.group(1)] = m.group(2)
    return state


def _env(path: Path) -> dict[str, str]:
    return dict(line.split("=", 1) for line in _code(path) if "=" in line)


def _top_level(path: Path) -> list[str]:
    """Code lines outside shell/python function bodies and SRC_URI lists."""
    out: list[str] = []
    depth = 0
    cont = False
    for line in _code(path):
        if cont:
            cont = line.endswith("\\") or not line.endswith('"')
            continue
        if depth:
            if line == "}":
                depth -= 1
            continue
        out.append(line)
        if line.endswith("{"):
            depth += 1
        elif re.search(r'= "[^"]*$', line):
            cont = True
    return out


# --- off by default --------------------------------------------------------


def test_bbappend_gates_the_payload_off_by_default() -> None:
    code = _code(BBAPPEND)
    assert _has(code, rf'^{GATE} \?\?= "0"$')
    assert _has(
        code,
        rf"^require \$\{{@'lamadist-uboot-vm\.inc' if d\.getVar\('{GATE}'\) == '1'"
        r" else ''\}$",
    )


def test_bbappend_names_the_qemu_machine_nowhere_else() -> None:
    """Every qemuarm64-lamadist statement lives in the gated include."""
    code = " ".join(_code(BBAPPEND))
    assert MACHINE not in code
    assert "lamadist-qemu-arm64" not in code


def test_only_the_overlay_turns_the_gate_on() -> None:
    hits = []
    for path in [*ROOT.joinpath("kas").rglob("*.yml"), *LAYER.rglob("*.conf")]:
        if re.search(rf"^\s*{GATE}\s*[?:]?=\s*\"1\"", path.read_text(), re.MULTILINE):
            hits.append(path.relative_to(ROOT))
    assert hits == [OVERLAY.relative_to(ROOT)]


def test_default_qemuarm64_files_do_not_mention_the_payload() -> None:
    for path in (QEMU_KAS, QEMU_LEAF):
        text = path.read_text()
        assert GATE not in text, path.name
        assert "uboot-vm" not in text, path.name


def test_overlay_sets_the_gate_and_the_menu_timeout_and_nothing_else() -> None:
    text = OVERLAY.read_text()
    assert re.search(r"^header:\n  version: \d+$", text, re.MULTILINE)
    body = re.search(r"^local_conf_header:\n((?:  .*\n?)+)", text, re.MULTILINE)
    assert body, "overlay has no local_conf_header"
    settings = [
        ln.strip()
        for ln in body.group(1).splitlines()
        if ln.strip()
        and not ln.strip().startswith("#")
        and not ln.rstrip().endswith("|")
    ]
    assert settings == [
        f'{GATE} = "1"',
        f'LAMADIST_BOOT_ENTRY_TIMEOUT:{MACHINE} = "menu-disabled"',
    ]
    for key in ("machine:", "repos:", "target:", "distro:"):
        assert not re.search(rf"^{key}", text, re.MULTILINE), key


# --- the gated include: qemuarm64-lamadist only -----------------------------


def test_include_scopes_every_statement_to_the_qemu_leaf() -> None:
    for line in _top_level(INC):
        if line.startswith(("FILESEXTRAPATHS", "inherit_defer")):
            continue
        name = re.match(r"^([\w$/{}.-]+(?::[\w-]+)*)", line)
        assert name, line
        assert name.group(1).endswith(f":{MACHINE}") or f":{MACHINE} " in line, (
            f"not scoped to {MACHINE}: {line}"
        )
    assert "soquartz-lamadist" not in INC.read_text()


def _src_uri_block() -> list[str]:
    code = _code(INC)
    block: list[str] = []
    for i, line in enumerate(code):
        if line.startswith(f"SRC_URI:append:{MACHINE}"):
            for later in code[i + 1 :]:
                if later == '"':
                    break
                block.append(later.rstrip("\\ ").strip())
    return block


def test_include_reuses_the_board_fragment_then_overrides_it() -> None:
    """Same EFI fragment as the board, merged first; the qemu fragment
    after it (merge_config.sh: the later fragment wins)."""
    block = _src_uri_block()
    names = [entry.removeprefix("file://") for entry in block]
    assert names.index(SHARED_CFG.name) < names.index(QEMU_CFG.name)
    assert QEMU_ENV.name in names
    assert LINK_PATCH.name in names
    assert "lamadist-soquartz.env" not in names


def test_include_carries_the_seed_patch_and_build_tool() -> None:
    code = _code(INC)
    assert _has(
        code, rf'^LAMADIST_UBOOT_SEED_CLASS:{MACHINE} = "lamadist-efi-var-seed"$'
    )
    assert _has(code, rf'^DEPENDS:append:{MACHINE} = " xxd-native"$')
    assert _has(code, rf'^PROVIDES:remove:{MACHINE} = "virtual/bootloader"$')
    assert _has(code, rf'^UBOOT_MACHINE:{MACHINE} = "qemu_arm64_defconfig"$')


def test_include_fails_closed_on_the_seed_and_the_env() -> None:
    text = INC.read_text()
    conf = re.search(
        rf"^do_configure:prepend:{MACHINE} \(\) \{{\n(.*?)^\}}",
        text,
        re.MULTILINE | re.DOTALL,
    )
    assert conf, "no machine-scoped do_configure:prepend"
    body = conf.group(1)
    assert re.search(
        rf'install\b.*\$\{{UNPACKDIR\}}/{re.escape(QEMU_ENV.name)}"? +"?\$\{{S\}}/'
        rf"{re.escape(QEMU_ENV.name)}",
        body,
    )
    assert "${LAMADIST_EFI_VAR_SEED_FILE}" in body
    assert SHARED_CFG.name in body
    assert body.count("bbfatal") >= 2
    comp = re.search(
        rf"^do_compile:append:{MACHINE} \(\) \{{\n(.*?)^\}}",
        text,
        re.MULTILINE | re.DOTALL,
    )
    assert comp, "no machine-scoped do_compile:append env guard"
    assert "u-boot-initial-env" in comp.group(1)
    assert QEMU_ENV.name in comp.group(1)
    assert "bbfatal" in comp.group(1)


# --- the qemu fragment: only what qemu_arm64 needs to boot ------------------

# OF_BOARD: qemu_arm64 implies OF_HAS_PRIOR_STAGE, so OF_OMIT_DTB defaults
# on and U-Boot carries no device tree of its own; without OF_BOARD it has
# none at all (dts/Kconfig:172,186,205; qemu-arm.c board_fdt_blob_setup).
# ENV_DEFAULT_ENV_TEXT_FILE: the board env names mmc0 and rk3568 addresses.
# EFI_TCG2_PROTOCOL: off, as on the TPM-less board, so ExitBootServices and
# LoadImage run the board's code path.
# LEGACY_HASHING_AND_CRYPTO, ARMV8_CRYPTO: the board's Secure Boot verifier
# (legacy PKCS#7/X.509/RSA parsers, generic SHA) instead of MbedTLS and the
# ARMv8 CE SHA code qemu_arm64_defconfig picks.
ALLOWED = {
    "OF_BOARD": "y",
    "ENV_DEFAULT_ENV_TEXT_FILE": f'"{QEMU_ENV.name}"',
    "EFI_TCG2_PROTOCOL": "n",
    "LEGACY_HASHING_AND_CRYPTO": "y",
    "ARMV8_CRYPTO": "n",
}
FORBIDDEN_ON = re.compile(
    r"^(CMDLINE|CMD_\w+|EFI_BOOTMGR|BOOTMETH_(?!EFILOADER$)\w+|BOOTSTD_DEFAULTS"
    r"|BOOT_DEFAULTS|AUTOBOOT|USE_PREBOOT|ENV_IS_IN_\w+|EFI_VARIABLE_FILE_STORE"
    r"|EFI_RT_VOLATILE_STORE|EFI_HTTP_BOOT|EFI_CAPSULE_ON_DISK)$"
)


def test_qemu_fragment_sets_only_the_allowed_symbols() -> None:
    assert _cfg(QEMU_CFG) == ALLOWED


def test_qemu_fragment_turns_on_no_boot_path() -> None:
    for sym, val in _cfg(QEMU_CFG).items():
        assert not (FORBIDDEN_ON.match(sym) and val != "n"), sym


def test_qemu_fragment_redefines_only_the_env_name_and_dt_source() -> None:
    """OF_BOARD is the one board "off" line QEMU cannot boot with."""
    shared = _cfg(SHARED_CFG)
    redefined = {sym for sym in _cfg(QEMU_CFG) if sym in shared}
    assert redefined == {"ENV_DEFAULT_ENV_TEXT_FILE", "OF_BOARD"}
    assert "@" not in QEMU_CFG.read_text()


def test_qemu_env_pins_virtio_and_keeps_the_board_shape() -> None:
    env = _env(QEMU_ENV)
    board = _env(FILES / "lamadist-soquartz.env")
    assert set(env) == set(board), "same variables as the board env"
    # One device of the uclass, as the board pins mmc0 (not the SD's mmc1).
    assert env["boot_targets"] == "virtio0"
    assert env["fdtfile"] == ""
    assert "bootcmd" not in env
    assert "bootdelay" not in env
    ram = 0x40000000  # include/configs/qemu-arm.h CFG_SYS_SDRAM_BASE
    kernel = int(env["kernel_addr_r"], 16)
    fdt = int(env["fdt_addr_r"], 16)
    assert kernel == 0x40400000  # board/emulation/qemu-arm/qemu-arm.env
    # QEMU's own DTB sits at the base of RAM: never load over it.
    assert ram < fdt and fdt != ram
    assert fdt >= kernel + (64 << 20) or fdt + (4 << 20) <= kernel


def test_no_seed_or_key_material_is_tracked() -> None:
    assert not list(UBOOT_DIR.rglob("*.seed"))
    assert not list(UBOOT_DIR.rglob("*.esl"))
    assert not list(UBOOT_DIR.rglob("*.var"))


def test_payload_files_carry_no_site_detail() -> None:
    for path in (INC, QEMU_CFG, QEMU_ENV, OVERLAY):
        assert not re.search(
            r"\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b", path.read_text()
        ), path.name


def test_adr13_names_where_the_payload_lives() -> None:
    flat = re.sub(r"\s+", " ", ADR13.read_text())
    assert "lamadist-uboot-vm.inc" in flat
    assert "kas/extras/uboot-vm.kas.yml" in flat


# --- optional cross-checks against the pinned U-Boot tag --------------------


def _upstream(path: str) -> str:
    return subprocess.run(
        ["git", "-C", str(UPSTREAM_UBOOT), "show", f"{UBOOT_TAG}:{path}"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout


@pytest.mark.skipif(not UPSTREAM_UBOOT.is_dir(), reason="no U-Boot checkout")
def test_qemu_defconfig_exists_at_the_tag() -> None:
    assert "CONFIG_ARCH_QEMU=y" in _upstream("configs/qemu_arm64_defconfig")


@pytest.mark.skipif(not UPSTREAM_UBOOT.is_dir(), reason="no U-Boot checkout")
def test_qemu_fragment_symbols_exist_at_the_tag() -> None:
    kconfig = "".join(
        _upstream(path)
        for path in (
            "dts/Kconfig",
            "lib/efi_loader/Kconfig",
            "env/Kconfig",
            "lib/mbedtls/Kconfig",
            "arch/arm/cpu/armv8/Kconfig",
        )
    )
    for sym in _cfg(QEMU_CFG):
        assert re.search(rf"^(menu)?config {sym}$", kconfig, re.MULTILINE), sym
