# SPDX-License-Identifier: Apache-2.0
"""Static and stubbed tests for the no-TPM per-device /var key.

ADR 0013 decision 7, owner decision 3: a machine without the tpm2
feature generates a per-device key on the ESP at first boot, adds it
as a LUKS2 keyslot of /var, and its crypttab line unlocks with it.
A tpm2 machine (x86_64) gets none of this.  BitBake is not run: the
inline expressions are evaluated against a stub of bb.utils.contains,
and the key script runs against stub cryptsetup/udevadm/sync.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LAYER = ROOT / "meta-lamadist"
IMAGE_CLASS = LAYER / "classes" / "lamadist-image.bbclass"
LUKS = LAYER / "recipes-core" / "luks"
RECIPE = LUKS / "lamadist-var-notpm-key.bb"
SCRIPT = LUKS / "files" / "lamadist-var-notpm-key"
UNIT = LUKS / "files" / "lamadist-var-notpm-key.service"
POLICY = LAYER / "recipes-security" / "refpolicy" / "files" / "lamadist.te"
POLICY_APPEND = (
    LAYER / "recipes-security" / "refpolicy" / "refpolicy-targeted_%.bbappend"
)
LUKS_README = LUKS / "files" / "README.md"
SECURITY_MD = ROOT / "docs" / "SECURITY.md"
OVERLAY = ROOT / "kas" / "extras" / "no-tpm.kas.yml"
INLINE = re.compile(r"\$\{@(.*?)\}")
KEY_PATH = "/boot/lamadist-keys/var.key"
TPM = {"systemd", "luks", "tpm2"}
NOTPM = {"systemd", "luks"}


class _Utils:
    @staticmethod
    def contains(_var: str, check: str, yes: object, no: object, d: _Data) -> object:
        return yes if check in d.getVar("DISTRO_FEATURES").split() else no


class _Bb:
    utils = _Utils()


class _Data:
    def __init__(self, features: set[str]) -> None:
        self._vars = {
            "DISTRO_FEATURES": " ".join(sorted(features)),
            "LAMADIST_VAR_NOTPM_KEYFILE": _class_default("LAMADIST_VAR_NOTPM_KEYFILE"),
        }

    def getVar(self, name: str) -> str:
        return self._vars[name]


def _class_default(name: str) -> str:
    m = re.search(rf'^{name} \?= "([^"]*)"', IMAGE_CLASS.read_text(), re.MULTILINE)
    assert m, f"{name} default not set"
    return m.group(1)


def _expand(text: str, features: set[str]) -> str:
    d = _Data(features)
    return INLINE.sub(lambda m: str(eval(m.group(1), {"bb": _Bb(), "d": d})), text)


def _echo_of(func: str, features: set[str]) -> str:
    body = re.search(rf"{func}\(\) \{{\n(.*?)\n\}}", IMAGE_CLASS.read_text(), re.DOTALL)
    assert body, f"{func}() not found"
    echo = re.search(r"echo '(.*)' >>", body.group(1))
    assert echo, f"{func} echo not found"
    return _expand(echo.group(1), features)


def _unit_section(name: str) -> str:
    m = re.search(
        rf"^\[{name}\]\n(.*?)(?=^\[|\Z)", UNIT.read_text(), re.MULTILINE | re.DOTALL
    )
    assert m, f"[{name}] missing"
    return m.group(1)


def _unit_values(section: str, key: str) -> list[str]:
    return [
        v
        for line in re.findall(rf"^{key}=(.*)$", _unit_section(section), re.MULTILINE)
        for v in line.split()
    ]


# --- build-time gate: present only without tpm2 ---------------------------


def test_key_recipe_is_skipped_on_tpm2_machines() -> None:
    text = RECIPE.read_text()
    conflict = re.search(
        r'^CONFLICT_DISTRO_FEATURES\s*=\s*"([^"]*)"', text, re.MULTILINE
    )
    assert conflict and "tpm2" in conflict.group(1).split()
    assert re.search(r"^inherit .*\bfeatures_check\b", text, re.MULTILINE)


def test_image_installs_the_key_package_only_without_tpm2() -> None:
    m = re.search(
        r"^IMAGE_INSTALL:append = \"(.*lamadist-var-notpm-key.*)\"$",
        IMAGE_CLASS.read_text(),
        re.MULTILINE,
    )
    assert m, "lamadist-image.bbclass does not install lamadist-var-notpm-key"
    assert "lamadist-var-notpm-key" in _expand(m.group(1), NOTPM).split()
    assert _expand(m.group(1), TPM).strip() == ""


def test_crypttab_notpm_line_names_the_esp_key() -> None:
    assert _class_default("LAMADIST_VAR_NOTPM_KEYFILE") == KEY_PATH
    assert _echo_of("lamadist_crypttab_var", NOTPM) == (
        f"var  PARTLABEL=var  {KEY_PATH}  luks,discard,headless=true"
    )


def test_tpm2_crypttab_line_is_unchanged() -> None:
    assert _echo_of("lamadist_crypttab_var", TPM) == (
        "var  PARTLABEL=var  none  luks,discard,tpm2-device=auto"
    )


def test_esp_is_mounted_root_only_without_tpm2_and_unchanged_with_it() -> None:
    assert _echo_of("lamadist_fstab_boot", TPM) == (
        "LABEL=msdos  /boot  vfat  defaults,x-systemd.automount  0  2"
    )
    fields = _echo_of("lamadist_fstab_boot", NOTPM).split()
    assert fields[:3] == ["LABEL=msdos", "/boot", "vfat"]
    assert "umask=0077" in fields[3].split(",")


def test_esp_automount_forbids_an_idle_timeout() -> None:
    """An idle unmount of /boot would stop the /var mapping under /var."""
    for features in (TPM, NOTPM):
        assert "idle-timeout" not in _echo_of("lamadist_fstab_boot", features)
    text = IMAGE_CLASS.read_text()
    comment = text[: text.index("lamadist_fstab_boot() {")].rsplit("\n\n", 1)[-1]
    assert "x-systemd.idle-timeout" in comment
    assert re.search(r"[Nn]ever add", comment)


def test_key_path_is_the_same_in_script_unit_and_crypttab() -> None:
    script = SCRIPT.read_text()
    keydir = re.search(r"^KEYDIR=(\S+)$", script, re.MULTILINE)
    keyfile = re.search(r'^KEYFILE="\$\{KEYDIR\}/(\S+)"$', script, re.MULTILINE)
    assert keydir and keyfile
    assert f"{keydir.group(1)}/{keyfile.group(1)}" == KEY_PATH
    assert _unit_values("Unit", "RequiresMountsFor") == [str(Path(KEY_PATH).parent)]


# --- unit shape and ordering ------------------------------------------------


def test_unit_has_no_runtime_tpm_condition() -> None:
    """The crypttab is decided at build time, so the key unit must be too."""
    assert "ConditionSecurity" not in UNIT.read_text()


def test_unit_orders_after_format_and_before_the_unlock() -> None:
    after = _unit_values("Unit", "After")
    before = _unit_values("Unit", "Before")
    assert "lamadist-var-encrypt.service" in after
    assert "lamadist-var-encrypt.service" in _unit_values("Unit", "Requires")
    assert {"systemd-cryptsetup@var.service", "cryptsetup-pre.target"} <= set(before)
    assert "cryptsetup-pre.target" in _unit_values("Unit", "Wants")
    assert _unit_values("Unit", "DefaultDependencies") == ["no"]
    assert _unit_values("Install", "WantedBy") == ["sysinit.target"]
    assert _unit_values("Service", "Type") == ["oneshot"]
    assert _unit_values("Service", "RemainAfterExit") == ["yes"]
    assert _unit_values("Service", "ExecStart") == [
        "/usr/lib/lamadist/lamadist-var-notpm-key"
    ]


def test_cryptsetup_domain_may_read_the_esp_key_only_without_tpm2() -> None:
    """The x86_64 policy gains nothing; no-tpm builds get the dosfs read."""
    assert "fs_read_dos_files" not in POLICY.read_text()
    text = POLICY_APPEND.read_text()
    rules = re.search(r'^LAMADIST_SELINUX_NOTPM_RULES = "(.*)"$', text, re.MULTILINE)
    assert rules, "LAMADIST_SELINUX_NOTPM_RULES not set"
    assert _expand(rules.group(1), NOTPM).strip() == "fs_read_dos_files(lvm_t)"
    assert _expand(rules.group(1), TPM).strip() == ""
    prepend = re.search(
        r"^do_compile:prepend\(\) \{\n(.*?)^\}", text, re.MULTILINE | re.DOTALL
    )
    assert prepend
    assert re.search(
        r'"\$\{LAMADIST_SELINUX_NOTPM_RULES\}".*>>\s*\S*/lamadist\.te',
        prepend.group(1),
        re.DOTALL,
    )


# --- no key material in the layer ------------------------------------------


def test_no_key_material_ships_for_the_per_device_key() -> None:
    src_uri = re.search(
        r'^SRC_URI = "(.*?)"', RECIPE.read_text(), re.MULTILINE | re.DOTALL
    )
    assert src_uri
    assert not any(".key" in f for f in src_uri.group(1).split())
    keys = sorted(p.name for p in LAYER.rglob("*.key"))
    assert keys == ["dev-var.key"], keys  # only the public dev key
    assert "/dev/random" in SCRIPT.read_text()


# --- idempotence, against stub cryptsetup ------------------------------------

_STUB_CRYPTSETUP = r"""#!/usr/bin/env python3
# Models LUKS2 keyslots by index in a JSON file: {"slot": key-hex}.
import json, os, sys
log, path = os.environ["NK_LOG"], os.environ["NK_SLOTS"]
args = sys.argv[1:]
with open(log, "a") as f:
    f.write("cryptsetup " + " ".join(args) + "\n")
slots = {int(k): v for k, v in json.load(open(path)).items()}
def opt(name):
    return args[args.index(name) + 1] if name in args else None
def key(p):
    return open(p, "rb").read().hex()
def save():
    json.dump({str(k): v for k, v in slots.items()}, open(path, "w"))
if os.environ.get("NK_CUT") == args[0]:
    sys.exit(137)  # power cut: this command never reached the header
if args[0] == "open" and "--test-passphrase" in args:
    rc = os.environ.get("NK_TEST_RC")
    if rc:
        print("stub: transient test failure", file=sys.stderr)
        sys.exit(int(rc))
    sys.exit(0 if key(opt("--key-file")) in slots.values() else 2)
if args[0] == "luksKillSlot":
    n = int(args[-1])
    if n not in slots:
        print(f"Keyslot {n} is not active.", file=sys.stderr)
        sys.exit(1)
    if key(opt("--key-file")) not in [v for k, v in slots.items() if k != n]:
        sys.exit(2)
    del slots[n]
    save()
    sys.exit(0)
if args[0] == "luksAddKey":
    if key(opt("--key-file")) not in slots.values():
        sys.exit(2)
    n = int(opt("--key-slot")) if "--key-slot" in args else min(set(range(32)) - set(slots))
    if n in slots:
        print(f"Key slot {n} is full.", file=sys.stderr)
        sys.exit(1)
    slots[n] = key(args[-1])
    save()
    sys.exit(0)
sys.exit(1)
"""

DEVKEY_BYTES = b"d" * 32


def _keyslot() -> int:
    m = re.search(r"^KEYSLOT=(\d+)$", SCRIPT.read_text(), re.MULTILINE)
    assert m, "the script names no fixed KEYSLOT"
    return int(m.group(1))


def _setup(tmp_path: Path) -> tuple[Path, Path, dict[str, str]]:
    bindir = tmp_path / "bin"
    bindir.mkdir()
    (bindir / "cryptsetup").write_text(_STUB_CRYPTSETUP)
    for tool in ("udevadm", "sync"):
        (bindir / tool).write_text(f'#!/bin/sh\necho "{tool} $*" >> "$NK_LOG"\n')
    for f in bindir.iterdir():
        f.chmod(0o755)
    devkey = tmp_path / "dev-var.key"
    devkey.write_bytes(DEVKEY_BYTES)
    (tmp_path / "slots").write_text(json.dumps({"0": DEVKEY_BYTES.hex()}))
    script = SCRIPT.read_text()
    for var, val in (
        ("DEV", tmp_path / "var-dev"),
        ("DEVKEY", devkey),
        ("KEYDIR", tmp_path / "esp" / "lamadist-keys"),
    ):
        script, n = re.subn(rf"^{var}=.*$", f"{var}={val}", script, flags=re.MULTILINE)
        assert n == 1, var
    patched = tmp_path / "notpm-key"
    patched.write_text(script)
    env = {
        **os.environ,
        "PATH": f"{bindir}:{os.environ['PATH']}",
        "NK_LOG": str(tmp_path / "log"),
        "NK_SLOTS": str(tmp_path / "slots"),
    }
    return patched, tmp_path / "esp" / "lamadist-keys" / "var.key", env


def _run(script: Path, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["sh", str(script)], env=env, capture_output=True, text=True, check=False
    )


def _log(tmp_path: Path) -> list[str]:
    return (tmp_path / "log").read_text().splitlines()


def _slots(tmp_path: Path) -> dict[int, str]:
    return {int(k): v for k, v in json.loads((tmp_path / "slots").read_text()).items()}


def _assert_converged(tmp_path: Path, key: Path) -> None:
    """Dev slot plus exactly one per-device slot, holding the ESP key."""
    slots = _slots(tmp_path)
    assert sorted(slots) == [0, _keyslot()], slots
    assert slots[0] == DEVKEY_BYTES.hex()
    assert slots[_keyslot()] == key.read_bytes().hex()
    assert len(key.read_bytes()) == 32


def test_fixed_keyslot_is_not_the_dev_keyfile_slot() -> None:
    assert 0 < _keyslot() < 32


def test_no_key_generates_syncs_then_adds_the_slot(tmp_path: Path) -> None:
    script, key, env = _setup(tmp_path)
    done = _run(script, env)
    assert done.returncode == 0, done.stderr
    assert key.read_bytes() != DEVKEY_BYTES
    _assert_converged(tmp_path, key)
    assert sorted(p.name for p in key.parent.iterdir()) == ["var.key"]  # no temp left
    log = _log(tmp_path)
    add = next(i for i, l in enumerate(log) if l.startswith("cryptsetup luksAddKey"))
    assert any(l.startswith("sync ") for l in log[:add]), log  # fsync before add
    assert f"--key-file {tmp_path / 'dev-var.key'}" in log[add]
    assert f"--key-slot {_keyslot()}" in log[add]
    assert log[add].endswith(str(key))


def test_key_and_slot_present_is_a_noop(tmp_path: Path) -> None:
    script, key, env = _setup(tmp_path)
    assert _run(script, env).returncode == 0
    first = key.read_bytes()
    slots = _slots(tmp_path)
    (tmp_path / "log").unlink()
    done = _run(script, env)
    assert done.returncode == 0, done.stderr
    assert key.read_bytes() == first
    assert _slots(tmp_path) == slots
    assert not any("luksAddKey" in l or "luksKillSlot" in l for l in _log(tmp_path))


def test_planted_32_byte_key_is_never_enrolled(tmp_path: Path) -> None:
    """A 32-byte file that does not unlock is replaced, not enrolled."""
    script, key, env = _setup(tmp_path)
    key.parent.mkdir(parents=True)
    planted = b"k" * 32
    key.write_bytes(planted)
    done = _run(script, env)
    assert done.returncode == 0, done.stderr
    assert key.read_bytes() != planted
    assert planted.hex() not in _slots(tmp_path).values()
    _assert_converged(tmp_path, key)


def test_truncated_key_without_a_slot_is_regenerated(tmp_path: Path) -> None:
    script, key, env = _setup(tmp_path)
    key.parent.mkdir(parents=True)
    key.write_bytes(b"")
    done = _run(script, env)
    assert done.returncode == 0, done.stderr
    _assert_converged(tmp_path, key)


def test_transient_test_failure_fails_the_unit_and_changes_nothing(
    tmp_path: Path,
) -> None:
    """Only exit 2 means "no key matches"; anything else is an error."""
    script, key, env = _setup(tmp_path)
    assert _run(script, env).returncode == 0
    first, slots = key.read_bytes(), _slots(tmp_path)
    (tmp_path / "log").unlink()
    for rc in ("1", "3", "4", "5"):
        done = _run(script, {**env, "NK_TEST_RC": rc})
        assert done.returncode != 0, rc
        assert "stub: transient test failure" in done.stderr  # not discarded
    assert key.read_bytes() == first
    assert _slots(tmp_path) == slots
    assert not any("luksAddKey" in l or "luksKillSlot" in l for l in _log(tmp_path))


def test_repeated_boots_and_key_loss_keep_one_per_device_slot(tmp_path: Path) -> None:
    """Lost, torn, or replaced keys reuse one slot; no growth."""
    script, key, env = _setup(tmp_path)

    def other(p: Path) -> None:
        p.write_bytes(b"o" * 32)

    for damage in (
        None,
        None,
        Path.unlink,
        lambda p: p.write_bytes(b"x" * 7),
        other,
        None,
        None,
    ):
        if damage is not None:
            damage(key)
        done = _run(script, env)
        assert done.returncode == 0, done.stderr
        _assert_converged(tmp_path, key)


def test_power_cut_after_kill_before_add_converges(tmp_path: Path) -> None:
    script, key, env = _setup(tmp_path)
    assert _run(script, env).returncode == 0
    old = key.read_bytes()
    key.unlink()
    cut = _run(script, {**env, "NK_CUT": "luksAddKey"})
    assert cut.returncode != 0
    assert sorted(_slots(tmp_path)) == [0]  # old slot killed, new one not added
    done = _run(script, env)
    assert done.returncode == 0, done.stderr
    assert key.read_bytes() != old
    _assert_converged(tmp_path, key)


def test_power_cut_after_key_write_before_kill_converges(tmp_path: Path) -> None:
    script, key, env = _setup(tmp_path)
    assert _run(script, env).returncode == 0
    old = key.read_bytes()
    key.unlink()
    cut = _run(script, {**env, "NK_CUT": "luksKillSlot"})
    assert cut.returncode != 0
    assert _slots(tmp_path)[_keyslot()] == old.hex()  # stale slot still there
    done = _run(script, env)
    assert done.returncode == 0, done.stderr
    assert old.hex() not in _slots(tmp_path).values()  # stale key revoked
    _assert_converged(tmp_path, key)


def test_key_is_written_in_place_with_no_rename_on_fat() -> None:
    """A vfat rename can leave two names on one cluster chain: avoid it."""
    script = SCRIPT.read_text()
    assert not re.search(r"^\s*mv\b", script, re.MULTILINE)
    assert "var.key.new" not in script


# --- documentation honesty ---------------------------------------------------

SHARED_SENTENCE = (
    "While the public development keyfile slot remains, a no-TPM /var opens "
    "with a public key, so the per-device key adds no protection at rest; "
    "that lasts until the pending owner decision to kill or gate the dev "
    "keyfile slot (meta-lamadist/recipes-core/luks/files/README.md)."
)


def _flat(path: Path) -> str:
    return " ".join(path.read_text().split())


def test_docs_state_the_public_key_sentence_verbatim() -> None:
    assert SHARED_SENTENCE in _flat(SECURITY_MD)
    assert SHARED_SENTENCE in _flat(LUKS_README)


def test_security_md_names_the_real_exposure_and_limits() -> None:
    text = _flat(SECURITY_MD)
    assert "any copy of it" in text  # wider than physical access
    assert "hygiene, not a control" in text  # the umask
    assert "no integrity and no revocation" in text


def test_readme_ties_key_loss_recovery_to_the_dev_slot() -> None:
    """Regeneration needs the dev slot to authorise the new key."""
    text = _flat(LUKS_README)
    assert "a missing or torn key is regenerated" not in text
    assert "only while the dev keyfile slot exists" in text


# --- QEMU overlay ------------------------------------------------------------


def test_no_tpm_overlay_removes_the_tpm2_feature() -> None:
    text = OVERLAY.read_text()
    assert re.search(
        r"^\s*DISTRO_FEATURES:remove\s*=\s*'\s*tpm2\s*'", text, re.MULTILINE
    )
    assert re.search(
        r"^\s*SECURE_CORE_IMAGE_EXTRA_INSTALL:remove\s*=\s*'\s*packagegroup-tpm2\s*'",
        text,
        re.MULTILINE,
    )
