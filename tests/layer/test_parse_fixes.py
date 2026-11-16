# SPDX-License-Identifier: Apache-2.0
"""Static guards for what the Rockchip BSP needs to parse.

kas and BitBake are not run, so these read the kas files as text, as
the sibling tests do.  What only a parse settles is left to a bitbake
-e check.  The Rockchip kas files name the layers their repos really
have, and the SOQuartz file pins the release branch.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
KAS_DIR = ROOT / "kas" / "bsp"
ROCKCHIP_KAS = ["soquartz", "rk1"]


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
