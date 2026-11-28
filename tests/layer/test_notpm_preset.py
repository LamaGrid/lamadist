# SPDX-License-Identifier: Apache-2.0
"""The no-TPM enroll mask must survive oe-core's systemctl preset-all.

oe-core's systemd_handle_machine_id (rootfs-postcommands.bbclass, a
ROOTFS_POSTPROCESS_COMMAND) runs `systemctl --root=... --preset-mode=
enable-only preset-all`.  The luks-var recipe's package preset says
`enable lamadist-var-tpm2-enroll.service`; with the unit masked, that
line makes preset-all print "Failed to preset all unit: Unit ... is
masked", which do_rootfs log_check turns into an error.  The mask is
appended after oe-core's command, so it is not the ordering: the
preset itself must stop asking for the unit on images without tpm2.

BitBake is not run.  The shell body of the mask function is executed
against a scratch root, then the host's systemctl runs preset-all on it.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
IMAGE_CLASS = ROOT / "meta-lamadist" / "classes" / "lamadist-image.bbclass"
UNIT = "lamadist-var-tpm2-enroll.service"
SYSTEMCTL = shutil.which("systemctl")


def _mask_body() -> str:
    m = re.search(
        r"lamadist_mask_tpm2_enroll_service\(\) \{\n(.*?)\n\}",
        IMAGE_CLASS.read_text(),
        re.DOTALL,
    )
    assert m, "lamadist_mask_tpm2_enroll_service() not found"
    return m.group(1)


def test_mask_function_also_presets_the_unit_off() -> None:
    body = _mask_body()
    assert re.search(r"echo 'disable lamadist-var-tpm2-enroll\.service'", body)
    # Earlier than the recipe's 98-<pkg>.preset, so the disable line wins.
    m = re.search(r"\$\{sysconfdir\}/systemd/system-preset/(\d+)-[^\s'\"]+", body)
    assert m and int(m.group(1)) < 98


def _scratch_root(tmp: Path) -> Path:
    unit_dir = tmp / "usr/lib/systemd/system"
    preset_dir = tmp / "usr/lib/systemd/system-preset"
    unit_dir.mkdir(parents=True)
    preset_dir.mkdir(parents=True)
    (unit_dir / UNIT).write_text(
        "[Unit]\nDescription=t\n[Service]\nExecStart=/bin/true\n"
        "[Install]\nWantedBy=sysinit.target\n"
    )
    # What systemd.bbclass writes for SYSTEMD_AUTO_ENABLE = enable.
    (preset_dir / "98-lamadist-luks-var.preset").write_text(f"enable {UNIT}\n")
    return tmp


def _preset_all(root: Path) -> subprocess.CompletedProcess[str]:
    assert SYSTEMCTL
    return subprocess.run(
        [SYSTEMCTL, f"--root={root}", "--preset-mode=enable-only", "preset-all"],
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.mark.skipif(SYSTEMCTL is None, reason="host has no systemctl")
def test_preset_all_is_clean_on_a_masked_no_tpm_root(tmp_path: Path) -> None:
    root = _scratch_root(tmp_path)
    body = _mask_body().replace("${IMAGE_ROOTFS}", str(root))
    body = body.replace("${sysconfdir}", "/etc")
    subprocess.run(["sh", "-ec", body], check=True)
    assert (root / "etc/systemd/system" / UNIT).resolve() == Path("/dev/null")
    out = _preset_all(root)
    assert "masked" not in out.stdout + out.stderr, out.stderr
    assert "Failed" not in out.stdout + out.stderr, out.stderr


@pytest.mark.skipif(SYSTEMCTL is None, reason="host has no systemctl")
def test_preset_all_still_enables_the_unit_on_a_tpm2_root(tmp_path: Path) -> None:
    root = _scratch_root(tmp_path)  # the mask function never runs with tpm2
    out = _preset_all(root)
    assert out.returncode == 0, out.stderr
    wants = root / "etc/systemd/system/sysinit.target.wants" / UNIT
    assert wants.is_symlink()


def _enable_like_the_postinst(root: Path) -> None:
    """systemd.bbclass's postinst runs `systemctl --root=$D enable`, which
    leaves the sysinit.target.wants link that the unit's [Install] asks for."""
    assert SYSTEMCTL
    subprocess.run([SYSTEMCTL, f"--root={root}", "enable", UNIT], check=True)
    wants = root / "etc/systemd/system/sysinit.target.wants" / UNIT
    assert wants.is_symlink(), "the scratch root has no wants link"


def _is_enabled(root: Path) -> str:
    assert SYSTEMCTL
    out = subprocess.run(
        [SYSTEMCTL, f"--root={root}", "is-enabled", UNIT],
        capture_output=True,
        text=True,
        check=False,
    )
    return out.stdout.strip()


def _run_mask_body(root: Path, body: str) -> None:
    body = body.replace("${IMAGE_ROOTFS}", str(root)).replace("${sysconfdir}", "/etc")
    subprocess.run(["sh", "-ec", body], check=True)


@pytest.mark.skipif(SYSTEMCTL is None, reason="host has no systemctl")
def test_enroll_unit_is_masked_even_with_the_wants_link_present(
    tmp_path: Path,
) -> None:
    """Behaviour, not text: with the link the postinst leaves in place,
    systemd itself reports the unit as masked once the mask function ran,
    so neither the link nor a dependency on the name can start it."""
    root = _scratch_root(tmp_path)
    _enable_like_the_postinst(root)
    assert _is_enabled(root) == "enabled"
    _run_mask_body(root, _mask_body())
    assert _is_enabled(root) == "masked"


@pytest.mark.skipif(SYSTEMCTL is None, reason="host has no systemctl")
def test_the_masked_check_fails_when_the_mask_line_is_removed(
    tmp_path: Path,
) -> None:
    """The control: without the `ln -sf /dev/null` line the same check
    prints `enabled`, so the test above can tell a mask from no mask."""
    root = _scratch_root(tmp_path)
    _enable_like_the_postinst(root)
    unmasked = re.sub(r"ln -sf /dev/null \\\n[^\n]*\n", "", _mask_body())
    assert "/dev/null" not in unmasked
    _run_mask_body(root, unmasked)
    assert _is_enabled(root) == "enabled"


# --- static proofs for the next build window -------------------------------

CLASS_TEXT = IMAGE_CLASS.read_text()
LUKS_RECIPE = ROOT / "meta-lamadist/recipes-core/luks/lamadist-luks-var.bb"

# Every ROOTFS_POSTPROCESS_COMMAND / IMAGE_INSTALL line of the image class,
# expanded for a tpm2 image.  A tpm2 image runs the same functions as
# before the no-TPM path: the mask and its preset live only inside the
# function the tpm2 path never calls.  The bare names (no ";") put the
# function bodies in the do_rootfs signature.
TPM2_POSTPROCESS = [
    "lamadist_sudoers_wheel; ",
    "lamadist_ci_sudoers; ",
    "lamadist_install_authorized_keys; ",
    "lamadist_crypttab_var",
    "lamadist_fstab_var; ",
    "lamadist_mask_ldconfig_service; ",
    "",  # the no-tpm2 mask: empty with tpm2
    "lamadist_etc_overlay_unit; ",
    "lamadist_fstab_boot",
]


def _expand_tpm2(text: str) -> str:
    class Utils:
        @staticmethod
        def contains(_v: str, _c: str, yes: str, _no: str, _d: object) -> str:
            return yes  # tpm2 is in DISTRO_FEATURES

    return re.sub(
        r"\$\{@(.*?)\}",
        lambda m: eval(m.group(1), {"bb": type("B", (), {"utils": Utils}), "d": None}),
        text,
    )


def test_tpm2_image_postprocess_and_install_are_unchanged() -> None:
    got = [
        _expand_tpm2(m)
        for m in re.findall(
            r'^ROOTFS_POSTPROCESS_COMMAND \+= "(.*)"$', CLASS_TEXT, re.MULTILINE
        )
    ]
    assert got == TPM2_POSTPROCESS
    install = re.findall(r'^IMAGE_INSTALL:append = "(.*)"$', CLASS_TEXT, re.MULTILINE)
    assert [_expand_tpm2(i) for i in install] == [""]


def test_tpm2_package_preset_inputs_are_unchanged() -> None:
    recipe = LUKS_RECIPE.read_text()
    assert "SYSTEMD_AUTO_ENABLE" not in recipe  # default: enable
    assert re.search(
        r"SYSTEMD_SERVICE:\$\{PN\} = \" \\\n    lamadist-var-encrypt\.service \\\n"
        r"    lamadist-var-tpm2-enroll\.service \\\n\"",
        recipe,
    )
    # The only preset this fix writes is made inside the mask function.
    assert not list((ROOT / "meta-lamadist").rglob("*.preset"))
    writes = [m.start() for m in re.finditer(r"system-preset", CLASS_TEXT)]
    body = re.search(
        r"lamadist_mask_tpm2_enroll_service\(\) \{.*?\n\}", CLASS_TEXT, re.DOTALL
    )
    assert body
    comment_end = CLASS_TEXT.index("lamadist_mask_tpm2_enroll_service() {")
    code_writes = [w for w in writes if w >= comment_end]
    assert all(body.start() <= w < body.end() for w in code_writes)


def test_enroll_unit_cannot_start_on_a_no_tpm_image() -> None:
    """Masked in rootfs, and no preset step can enable it again."""
    body = _mask_body()
    assert "ln -sf /dev/null" in body and UNIT in body
    # preset-all runs inside ROOTFS_POSTPROCESS_COMMAND; the disable line
    # makes the result independent of whether it runs before or after.
    assert f"echo 'disable {UNIT}'" in body
    # And the mask is queued exactly once, for images without tpm2.
    assert CLASS_TEXT.count("'lamadist_mask_tpm2_enroll_service'") == 1
