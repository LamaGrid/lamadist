# SPDX-License-Identifier: Apache-2.0
"""Static tests for the preseed plumbing: nothing secret or generated is tracked.

The seed is a build artifact (ADR 0013 decision 3).  The layer must
never carry one, and must carry key material only where it is the
documented, public development chain.  BitBake is not run.
"""

from __future__ import annotations

import re
import struct
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
LAYER = ROOT / "meta-lamadist"
SB_DEV = LAYER / "files" / "sb-dev"
CLASS = LAYER / "classes" / "lamadist-efi-var-seed.bbclass"

# Development-only material that is public by design (see each README).
DEV_KEY_ALLOWLIST = {
    LAYER / "files" / "sb-dev",
    LAYER / "files" / "rauc-dev",
    LAYER / "recipes-core" / "luks" / "files" / "dev-var.key",
}
SEED_MAGIC = struct.pack("<Q", 0x0161566966456255)
SEED_NAMES = ("*.seed", "*.var", "*.auth", "ubootefi*")
KEY_NAMES = ("*.key", "*.key.pem", "*.p12", "*.pfx")


def _layer_files() -> list[Path]:
    return [p for p in LAYER.rglob("*") if p.is_file()]


def _allowed(path: Path) -> bool:
    return any(path == a or a in path.parents for a in DEV_KEY_ALLOWLIST)


def _blob_head(path: Path) -> bytes:
    with path.open("rb") as f:
        return f.read(16)


def test_no_seed_is_tracked_in_the_layer() -> None:
    hits = [
        p.relative_to(ROOT)
        for p in _layer_files()
        if any(p.match(n) for n in SEED_NAMES)
    ]
    assert hits == []


def test_no_file_in_the_layer_is_a_u_boot_variable_store() -> None:
    """A renamed seed is still a checked-in binary: match on the magic."""
    hits = [
        p.relative_to(ROOT) for p in _layer_files() if _blob_head(p)[8:16] == SEED_MAGIC
    ]
    assert hits == []


def test_no_new_private_key_is_tracked_in_the_layer() -> None:
    hits = [
        p.relative_to(ROOT)
        for p in _layer_files()
        if not _allowed(p)
        and (
            any(p.match(n) for n in KEY_NAMES) or b"PRIVATE KEY-----" in p.read_bytes()
        )
    ]
    assert hits == []


def test_the_seed_class_reads_only_the_public_esls() -> None:
    """The generator needs signature lists, never a private key."""
    text = CLASS.read_text()
    for name in ("pk", "kek", "db"):
        assert f"{name}.esl" in text
    assert not re.search(r"\.key(\.pem)?\b", text)


@pytest.mark.parametrize("name", ["pk", "kek", "db"])
def test_committed_esl_carries_the_committed_cert(name: str) -> None:
    """The seed and the x86_64 enrollment name one hierarchy, not two."""
    esl = (SB_DEV / f"{name}.esl").read_bytes()
    der = (SB_DEV / f"{name}.cert.der").read_bytes()
    list_size, hdr_size, sig_size = struct.unpack_from("<LLL", esl, 16)
    assert list_size == len(esl)
    assert esl[28 + hdr_size + 16 : list_size] == der
    assert sig_size == 16 + len(der)


# --- anchors from this layer, stable task signature -----------------------

LAYER_CONF = LAYER / "conf" / "layer.conf"
ANCHOR_VARS = (
    "LAMADIST_EFI_VAR_SEED_PK",
    "LAMADIST_EFI_VAR_SEED_KEK",
    "LAMADIST_EFI_VAR_SEED_DB",
    "LAMADIST_EFI_VAR_SEED_GEN",
)


def test_layer_conf_exports_its_own_directory() -> None:
    """An immediate (:=) copy of LAYERDIR, valid after layer.conf parses."""
    text = LAYER_CONF.read_text()
    assert re.search(r'^LAMADIST_LAYERDIR := "\$\{LAYERDIR\}"$', text, re.MULTILINE)


def test_the_trust_anchors_resolve_against_this_layer_not_bbpath() -> None:
    text = CLASS.read_text()
    code = "\n".join(l for l in text.splitlines() if not l.lstrip().startswith("#"))
    assert "BBPATH" not in code, "a stray file earlier on BBPATH would replace the PK"
    for var, name in (
        ("PK", "files/sb-dev/pk.esl"),
        ("KEK", "files/sb-dev/kek.esl"),
        ("DB", "files/sb-dev/db.esl"),
        ("GEN", "lib/lamadist/efivarseed.py"),
    ):
        assert re.search(
            rf'^LAMADIST_EFI_VAR_SEED_{var}\s+\?= "\$\{{LAMADIST_LAYERDIR\}}/{name}"$',
            text,
            re.MULTILINE,
        ), var


def test_the_build_log_names_each_anchor_and_its_hash() -> None:
    text = CLASS.read_text()
    assert "hashlib.sha256" in text
    assert "bb.note" in text


def test_the_task_signature_does_not_carry_checkout_paths() -> None:
    """The file-checksums flag covers content; the absolute paths must not."""
    text = CLASS.read_text()
    m = re.search(r'do_lamadist_efi_var_seed\[vardepsexclude\] \+?= "([^"]*)"', text)
    assert m, "vardepsexclude missing"
    assert set(ANCHOR_VARS) <= set(m.group(1).split())


def test_the_seed_task_has_no_redundant_self_dependency() -> None:
    """The task is ordered before do_configure; do_deploy follows it."""
    assert "do_deploy[depends]" not in CLASS.read_text()
