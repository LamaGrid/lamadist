# SPDX-License-Identifier: Apache-2.0
"""Static guards for what the Rockchip BSP needs to parse.

kas and BitBake are not run, so these read the kas files and the U-Boot
bbappend as text, as the sibling tests do.  What only a parse settles is
left to a bitbake -e check.  The Rockchip kas files name the layers
their repos really have, and the SOQuartz file pins the release branch.
The SOQuartz leaf drops virtual/bootloader from U-Boot's PROVIDES, so
oe-core base.bbclass does not skip U-Boot behind systemd-boot.  The
U-Boot bbappend parses on every machine, not only on the leaf.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
KAS_DIR = ROOT / "kas" / "bsp"
ROCKCHIP_KAS = ["soquartz", "rk1"]
BBAPPEND = ROOT / "meta-lamadist" / "recipes-bsp" / "u-boot" / "u-boot_%.bbappend"
ADR13 = ROOT / "docs" / "adr" / "0013-arm-boot-chain.md"


def _repo_block(bsp: str, repo: str) -> list[str]:
    """The lines of one entry under `repos:` in a BSP kas file."""
    lines = (KAS_DIR / f"{bsp}.kas.yml").read_text().splitlines()
    start = lines.index(f"  {repo}:")
    block: list[str] = []
    for line in lines[start + 1 :]:
        if line.strip() and not line.startswith("    "):
            break
        block.append(line)
    return block


def _repo_field(bsp: str, repo: str, key: str) -> str:
    for line in _repo_block(bsp, repo):
        m = re.fullmatch(rf"    {key}: '?([^']*)'?", line)
        if m:
            return m.group(1)
    raise AssertionError(f"{bsp}.kas.yml: {repo} has no {key}")


def _repo_layers(bsp: str, repo: str) -> list[str]:
    block = _repo_block(bsp, repo)
    assert "    layers:" in block, f"{bsp}.kas.yml: {repo} lists no layers"
    layers: list[str] = []
    for line in block[block.index("    layers:") + 1 :]:
        m = re.fullmatch(r"      ([\w-]+):", line)
        if not m:
            break
        layers.append(m.group(1))
    return layers


# --- The Rockchip kas files name the layers their repos really have -------


def test_soquartz_pins_both_rockchip_layers_to_the_release_branch() -> None:
    for repo in ("meta-arm", "meta-rockchip"):
        assert _repo_field("soquartz", repo, "branch") == "wrynose"


@pytest.mark.parametrize("bsp", ROCKCHIP_KAS)
def test_meta_arm_lists_its_real_layers(bsp: str) -> None:
    assert set(_repo_layers(bsp, "meta-arm")) == {"meta-arm", "meta-arm-toolchain"}


@pytest.mark.parametrize("bsp", ROCKCHIP_KAS)
def test_meta_secure_core_enables_meta_tpm2_only(bsp: str) -> None:
    url = _repo_field("qemuarm64", "meta-secure-core", "url")
    assert _repo_field(bsp, "meta-secure-core", "url") == url
    assert _repo_field(bsp, "meta-secure-core", "path") == "ext/meta-secure-core"
    assert _repo_layers(bsp, "meta-secure-core") == ["meta-tpm2"]


def _code(path: Path) -> list[str]:
    return [
        ln.strip()
        for ln in path.read_text().splitlines()
        if ln.strip() and not ln.strip().startswith("#")
    ]


# --- The leaf drops virtual/bootloader from U-Boot's PROVIDES -------------


def test_provides_removal_is_scoped_to_the_leaf() -> None:
    code = _code(BBAPPEND)
    assert any(
        re.match(r'^PROVIDES:remove:soquartz-lamadist = "virtual/bootloader"$', ln)
        for ln in code
    )
    assert not any(
        re.match(r"^PROVIDES\b(?!:remove:soquartz-lamadist)", ln) for ln in code
    )


def test_adr13_decision_10_records_the_provides_mechanism() -> None:
    text = re.sub(r"\s+", " ", ADR13.read_text())
    assert "PROVIDES:remove:soquartz-lamadist" in text


# --- The inherit line must expand to nothing off the leaf -----------------


def _inherit_line_expansion() -> str:
    """Expand the bbappend's inherit_defer argument with no leaf override."""
    code = _code(BBAPPEND)
    default = None
    for line in code:
        m = re.match(r'^LAMADIST_UBOOT_SEED_CLASS\s*(\?\?=|\?=|=|:=)\s*"(.*)"$', line)
        if m:
            default = m.group(2)
    inherit = [ln for ln in code if ln.startswith("inherit_defer")]
    assert len(inherit) == 1
    arg = inherit[0].split(None, 1)[1].strip()
    if arg == "${LAMADIST_UBOOT_SEED_CLASS}":
        assert default is not None, (
            "variable has no default, so the line expands to a bare ${...}"
        )
        return default
    return arg


def test_inherit_expands_to_nothing_without_the_leaf_override() -> None:
    assert _inherit_line_expansion() == ""


def test_leaf_override_still_names_the_seed_class() -> None:
    assert any(
        re.match(
            r'^LAMADIST_UBOOT_SEED_CLASS:soquartz-lamadist = "lamadist-efi-var-seed"$',
            ln,
        )
        for ln in _code(BBAPPEND)
    )
