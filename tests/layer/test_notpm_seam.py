# SPDX-License-Identifier: Apache-2.0
"""Static tests for the no-TPM /var seam (ADR 0013 decision 7).

A machine without the tpm2 feature must build and boot its units with
no TPM requirement, while a tpm2 machine (x86_64) keeps its TPM-only
crypttab line.  BitBake is not run: the one inline expression the
crypttab line uses is evaluated against a stub of bb.utils.contains.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
LAYER = ROOT / "meta-lamadist"
IMAGE_CLASS = LAYER / "classes" / "lamadist-image.bbclass"
LUKS = LAYER / "recipes-core" / "luks"
LUKS_RECIPE = LUKS / "lamadist-luks-var.bb"
ENROLL_UNIT = LUKS / "files" / "lamadist-var-tpm2-enroll.service"
INLINE = re.compile(r"\$\{@(.*?)\}")


class _Utils:
    @staticmethod
    def contains(_var: str, check: str, yes: object, no: object, d: _Data) -> object:
        return yes if check in d.getVar("DISTRO_FEATURES").split() else no


class _Bb:
    utils = _Utils()


class _Data:
    """Stub of the BitBake datastore: just getVar."""

    def __init__(self, features: set[str], keyfile: str) -> None:
        self._vars = {
            "DISTRO_FEATURES": " ".join(sorted(features)),
            "LAMADIST_VAR_NOTPM_KEYFILE": keyfile,
        }

    def getVar(self, name: str) -> str:
        return self._vars[name]


def _expand(text: str, d: _Data) -> str:
    """Expand ${@...} inline Python the way BitBake does, for tests."""
    return INLINE.sub(lambda m: str(eval(m.group(1), {"bb": _Bb(), "d": d})), text)


def _crypttab_var_line(features: set[str], keyfile: str = "none") -> str:
    body = re.search(
        r"lamadist_crypttab_var\(\) \{\n(.*?)\n\}", IMAGE_CLASS.read_text(), re.DOTALL
    )
    assert body, "lamadist_crypttab_var() not found"
    echo = re.search(r"echo '(var .*)' >>", body.group(1))
    assert echo, "crypttab echo not found"
    return _expand(echo.group(1), _Data(features, keyfile))


def _required_distro_features() -> set[str]:
    m = re.search(
        r'^REQUIRED_DISTRO_FEATURES\s*=\s*"([^"]*)"',
        LUKS_RECIPE.read_text(),
        re.MULTILINE,
    )
    assert m, "REQUIRED_DISTRO_FEATURES not set"
    return set(m.group(1).split())


def test_tpm2_machine_keeps_its_tpm_only_crypttab_line() -> None:
    line = _crypttab_var_line({"systemd", "luks", "tpm2"})
    assert line == "var  PARTLABEL=var  none  luks,discard,tpm2-device=auto"


def test_machine_without_tpm2_has_no_tpm_option_in_crypttab() -> None:
    line = _crypttab_var_line({"systemd", "luks"})
    assert "tpm2" not in line
    assert line.startswith("var  PARTLABEL=var  ")


def test_crypttab_fallback_hook_is_marked_and_carries_no_key_material() -> None:
    text = IMAGE_CLASS.read_text()
    assert "FALLBACK SECRET HOOK (ADR 0013 decision 7" in text
    line = _crypttab_var_line({"systemd", "luks"}, "/boot/lamadist-keys/var.key")
    fields = line.split()
    assert fields[2] == "/boot/lamadist-keys/var.key"  # the per-device key
    assert "dev-var.key" not in line


def test_luks_var_recipe_does_not_require_tpm2() -> None:
    required = _required_distro_features()
    assert "tpm2" not in required
    assert {"systemd", "luks"} <= required


def _mask_command(features: set[str]) -> str:
    m = re.search(
        r'^ROOTFS_POSTPROCESS_COMMAND \+= "(.*lamadist_mask_tpm2_enroll_service.*)"$',
        IMAGE_CLASS.read_text(),
        re.MULTILINE,
    )
    assert m, "no ROOTFS_POSTPROCESS_COMMAND masks the enroll unit"
    return _expand(m.group(1), _Data(features, "none"))


def test_enroll_unit_has_no_runtime_tpm_condition() -> None:
    """ConditionSecurity=tpm2 trusts firmware PCR-bank reporting."""
    assert "ConditionSecurity" not in ENROLL_UNIT.read_text()


def test_enroll_unit_is_masked_at_build_time_only_without_tpm2() -> None:
    assert _mask_command({"systemd", "luks", "tpm2"}).strip() == ""
    assert _mask_command({"systemd", "luks"}).split(";")[0].strip() == (
        "lamadist_mask_tpm2_enroll_service"
    )
    body = re.search(
        r"lamadist_mask_tpm2_enroll_service\(\) \{\n(.*?)\n\}",
        IMAGE_CLASS.read_text(),
        re.DOTALL,
    )
    assert body
    assert re.search(
        r"ln -sf /dev/null \\?\s*\$\{IMAGE_ROOTFS\}\$\{sysconfdir\}"
        r"/systemd/system/lamadist-var-tpm2-enroll\.service",
        body.group(1),
    )


# Every unit that names a TPM, and the build-time gate that keeps it off
# the machines it does not belong to.  Runtime ConditionSecurity= is not a
# gate here: crypttab is fixed at build time, and the two can disagree.
BUILD_TIME_GATED = {
    "lamadist-var-tpm2-enroll.service": "masked without tpm2 (lamadist-image)",
    "lamadist-var-notpm-key.service": "installed only without tpm2",
}


def test_no_service_file_that_names_a_tpm_is_ungated() -> None:
    """Guard: a new TPM-dependent unit must not slip in ungated."""
    offenders = [
        p.relative_to(ROOT)
        for p in LAYER.rglob("*.service")
        if re.search(r"tpm", p.read_text(), re.IGNORECASE)
        and p.name not in BUILD_TIME_GATED
    ]
    assert not offenders, offenders


def test_no_unit_gates_on_tpm_at_runtime() -> None:
    offenders = [
        p.relative_to(ROOT)
        for p in LAYER.rglob("*.service")
        if re.search(r"^ConditionSecurity=!?tpm2", p.read_text(), re.MULTILINE)
    ]
    assert not offenders, offenders


# oe-core's image.bbclass sets ROOTFS_POSTPROCESS_COMMAND[vardeps] to the
# expanded value, so only a bare function name puts the function body in
# the do_rootfs signature; a "name;" token names no variable.
SIGNED_POSTPROCESS = [
    "lamadist_crypttab_var",
    "lamadist_mask_tpm2_enroll_service",
    "lamadist_fstab_boot",
]


@pytest.mark.parametrize("func", SIGNED_POSTPROCESS)
def test_postprocess_function_body_is_in_the_do_rootfs_signature(func: str) -> None:
    commands = re.findall(
        r'^ROOTFS_POSTPROCESS_COMMAND \+= "(.*)"$',
        IMAGE_CLASS.read_text(),
        re.MULTILINE,
    )
    tokens = " ".join(_expand(c, _Data({"systemd", "luks"}, "none")) for c in commands)
    assert func in tokens.split()
    assert f"{func};" not in tokens


def test_notpm_key_field_is_the_hook_for_the_first_boot_key_unit() -> None:
    """A first-boot key unit sets LAMADIST_VAR_NOTPM_KEYFILE and no more."""
    default = re.search(
        r'^LAMADIST_VAR_NOTPM_KEYFILE \?= "([^"]*)"',
        IMAGE_CLASS.read_text(),
        re.MULTILINE,
    )
    assert default
    # A path, never key material: the key itself is made at first boot.
    assert default.group(1).startswith("/")
    key = "/boot-keys/var.key"
    notpm = _crypttab_var_line({"systemd", "luks"}, key).split()
    assert notpm[2] == key
    assert not any("tpm2" in f for f in notpm)
    tpm = _crypttab_var_line({"systemd", "luks", "tpm2"}, key).split()
    assert tpm[2] == "none"  # the hook never reaches a tpm2 machine


def test_notpm_crypttab_line_is_headless() -> None:
    """A missing key fails the unlock at once, with no prompt."""
    notpm = _crypttab_var_line({"systemd", "luks"}, "/k").split()[3].split(",")
    assert "headless=true" in notpm
    tpm = _crypttab_var_line({"systemd", "luks", "tpm2"}).split()[3].split(",")
    assert "headless=true" not in tpm
