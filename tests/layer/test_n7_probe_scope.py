# SPDX-License-Identifier: Apache-2.0
"""Static tests that keep the N7 write probe a test-only artifact.

The probe is a db-signed UEFI application that tries to write PK, KEK,
and db before ExitBootServices (ADR 0017).  It must never reach an
image: no image recipe, packagegroup, class, or configuration file may
name it, its recipe is skipped unless kas/extras/n7-probe.kas.yml sets
the gate, it has no packages, and it deploys no binary.  It is signed
only with the public development keys in files/sb-dev.  BitBake is not
run.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
LAYER = ROOT / "meta-lamadist"
PROBE_DIR = LAYER / "recipes-test" / "lamadist-n7-probe"
RECIPE = PROBE_DIR / "lamadist-n7-probe.bb"
SOURCE = PROBE_DIR / "files" / "n7-probe.c"
LDS = PROBE_DIR / "files" / "n7-probe.lds"
OVERLAY = ROOT / "kas" / "extras" / "n7-probe.kas.yml"
GATE = "LAMADIST_N7_PROBE"

# Payload rows in the order the probe runs them; L1 runs between
# S-KEK and S-PK, so the db append is in place and PK is still set.
ROWS = ["U-PK", "U-KEK", "U-db", "W-db", "X-PK", "S-db", "S-KEK", "S-PK"]

LAYER_SUFFIXES = {".bb", ".bbappend", ".bbclass", ".inc", ".conf"}
PROBE_NAME = re.compile(r"lamadist-n7-probe|\bn7-probe\b")


def _code(path: Path) -> list[str]:
    """Non-comment, non-blank lines, stripped."""
    out = []
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if line and not line.startswith("#"):
            out.append(line)
    return out


def probe_scope_violations(root: Path) -> list[str]:
    """Files under ROOT that name the probe or set its gate, other than
    the probe's own recipe directory and its kas overlay."""
    layer = root / "meta-lamadist"
    probe_dir = layer / "recipes-test" / "lamadist-n7-probe"
    overlay = root / "kas" / "extras" / "n7-probe.kas.yml"
    hits: list[str] = []
    candidates = [
        p for p in layer.rglob("*") if p.is_file() and p.suffix in LAYER_SUFFIXES
    ]
    candidates += [p for p in (root / "kas").rglob("*.yml") if p.is_file()]
    for path in sorted(candidates):
        if path == overlay or probe_dir in path.parents:
            continue
        for line in _code(path):
            if PROBE_NAME.search(line) or GATE in line:
                hits.append(str(path.relative_to(root)))
                break
    return hits


# --- the probe is in no image --------------------------------------------


def test_no_image_packagegroup_or_config_names_the_probe() -> None:
    assert probe_scope_violations(ROOT) == []


def _mini_tree(tmp_path: Path) -> Path:
    (tmp_path / "meta-lamadist" / "recipes-test" / "lamadist-n7-probe").mkdir(
        parents=True
    )
    (tmp_path / "kas" / "extras").mkdir(parents=True)
    (tmp_path / "kas" / "extras" / "n7-probe.kas.yml").write_text(
        f'local_conf_header:\n  n7: |\n    {GATE} = "1"\n'
    )
    return tmp_path


@pytest.mark.parametrize(
    ("relpath", "text"),
    [
        (
            "meta-lamadist/recipes-core/images/lamadist-image-base.bb",
            'IMAGE_INSTALL:append = " lamadist-n7-probe"\n',
        ),
        (
            "meta-lamadist/recipes-core/packagegroups/packagegroup-lamadist-base.bb",
            'RDEPENDS:${PN} += "lamadist-n7-probe"\n',
        ),
        (
            "meta-lamadist/classes/lamadist-image.bbclass",
            'do_image[depends] += "lamadist-n7-probe:do_compile"\n',
        ),
        ("kas/extras/debug.kas.yml", f'    {GATE} = "1"\n'),
    ],
)
def test_the_scope_check_catches_the_probe_pulled_into_a_build(
    tmp_path: Path, relpath: str, text: str
) -> None:
    """RED fixture: the same check fails on a tree that puts the probe
    in an image, a packagegroup, an image task, or a second overlay."""
    root = _mini_tree(tmp_path)
    target = root / relpath
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text)
    assert probe_scope_violations(root) == [relpath]
    with pytest.raises(AssertionError):
        assert probe_scope_violations(root) == []


def test_the_scope_check_ignores_comments(tmp_path: Path) -> None:
    root = _mini_tree(tmp_path)
    img = root / "meta-lamadist" / "recipes-core" / "images" / "x.bb"
    img.parent.mkdir(parents=True)
    img.write_text("# the n7-probe stays out of this image\n")
    assert probe_scope_violations(root) == []


# --- the recipe is skipped unless its overlay sets the gate --------------


def test_recipe_defaults_its_gate_off_and_skips_without_it() -> None:
    code = _code(RECIPE)
    assert f'{GATE} ??= "0"' in code
    text = RECIPE.read_text()
    assert re.search(rf"d\.getVar\('{GATE}'\) != '1'", text)
    assert "bb.parse.SkipRecipe" in text


def test_overlay_turns_the_gate_on_and_keeps_the_workdir() -> None:
    text = OVERLAY.read_text()
    assert re.search(rf'^\s*{GATE} = "1"$', text, re.MULTILINE)
    assert re.search(
        r'^\s*RM_WORK_EXCLUDE \+= "lamadist-n7-probe"$', text, re.MULTILINE
    )
    # The overlay changes nothing but the probe: no image content and
    # no firmware configuration.
    for word in ("IMAGE_INSTALL", "LAMADIST_UBOOT", "CONFIG_", "SRC_URI"):
        assert word not in text, word


def test_recipe_has_no_packages_and_deploys_no_binary() -> None:
    code = _code(RECIPE)
    assert "inherit nopackages" in code
    assert not any(re.search(r"\binherit\b.*\bdeploy\b", line) for line in code)
    text = RECIPE.read_text()
    for word in ("do_deploy", "DEPLOYDIR", "DEPLOY_DIR"):
        assert word not in text
    assert 'EXCLUDE_FROM_WORLD = "1"' in code


def test_recipe_makes_no_spdx_document() -> None:
    # The probe is a test article that never ships, so it has no SPDX
    # document to make, and its SPDX tasks fail when the probe build runs
    # with an empty deploy dir and a shared TMPDIR.  nospdx (oe-core
    # meta/classes-recipe/nospdx.bbclass) deletes only those tasks.
    assert "inherit nospdx" in _code(RECIPE)


def test_recipe_is_aarch64_only() -> None:
    assert 'COMPATIBLE_HOST = "aarch64.*-linux"' in _code(RECIPE)


# --- signing inputs -------------------------------------------------------


def test_signing_inputs_are_only_the_public_development_keys() -> None:
    text = RECIPE.read_text()
    assert 'N7_SIGN_DIR = "${LAMADIST_LAYERDIR}/files/sb-dev"' in _code(RECIPE)
    refs = re.findall(r"(\S*)/(\w+)\.(key|cert)\.pem", text)
    assert refs, "the recipe signs nothing"
    assert {(d, n) for d, n, _ in refs} == {
        ("${N7_SIGN_DIR}", "db"),
        ("${N7_SIGN_DIR}", "kek"),
    }


def test_a_key_change_re_signs_and_the_path_stays_out_of_the_signature() -> None:
    """The keys are read by path inside do_compile, so BitBake sees no
    change to their content unless file-checksums names them.  The
    absolute path is excluded, as lamadist-efi-var-seed does."""
    text = RECIPE.read_text()
    m = re.search(r'do_compile\[file-checksums\] \+?= "([^"]*)"', text)
    assert m, "do_compile[file-checksums] missing"
    assert set(m.group(1).replace("\\", " ").split()) == {
        f"${{N7_SIGN_DIR}}/{n}.{k}.pem:True"
        for n in ("db", "kek")
        for k in ("key", "cert")
    }
    m = re.search(r'do_compile\[vardepsexclude\] \+?= "([^"]*)"', text)
    assert m, "do_compile[vardepsexclude] missing"
    assert "N7_SIGN_DIR" in m.group(1).split()
    assert not re.search(r"do_compile\[vardeps\][^\n]*N7_SIGN_DIR", text)


def test_probe_is_signed_by_db_and_the_target_by_kek() -> None:
    text = RECIPE.read_text()
    assert re.search(
        r"sbsign --key \$\{N7_SIGN_DIR\}/db\.key\.pem "
        r"--cert \$\{N7_SIGN_DIR\}/db\.cert\.pem[^\n]*n7-probe\.efi",
        text,
    )
    assert re.search(
        r"sbsign --key \$\{N7_SIGN_DIR\}/kek\.key\.pem "
        r"--cert \$\{N7_SIGN_DIR\}/kek\.cert\.pem[^\n]*n7-target\.efi",
        text,
    )


# --- freestanding build (ADR 0017) ----------------------------------------


def test_build_is_freestanding_and_keeps_its_relocations() -> None:
    text = RECIPE.read_text()
    for flag in (
        "-ffreestanding",
        "-nostdlib",
        "-static",
        "--emit-relocs",
        "-fno-jump-tables",
        "-fno-tree-switch-conversion",
        "-fno-tree-loop-distribute-patterns",
    ):
        assert flag in text, flag
    assert "n7_elf2pe.py" in text
    assert "gnu-efi" not in text


def test_probe_source_includes_no_header() -> None:
    assert not re.search(r"^\s*#\s*include\b", SOURCE.read_text(), re.MULTILINE)


def test_probe_runs_the_rows_in_order_with_l1_before_s_pk() -> None:
    src = SOURCE.read_text()
    calls = re.findall(r'run_row\([^;]*?u"\\\\n7\\\\([\w-]+)\.bin"', src)
    assert calls == ROWS
    l1 = src.index("run_l1();")
    assert src.index('u"\\\\n7\\\\S-KEK.bin"') < l1 < src.index('u"\\\\n7\\\\S-PK.bin"')


def test_linker_script_places_text_above_the_headers() -> None:
    text = LDS.read_text()
    assert re.search(r"\.\s*=\s*0x1000\s*;", text)
    assert "ENTRY(efi_main)" in text


# --- the R2 store symbols stay out of the tree ----------------------------


def test_no_tracked_file_turns_on_a_writable_variable_store() -> None:
    """The R2 RED firmware lives only in an untracked overlay."""
    pattern = re.compile(
        r"^\s*CONFIG_EFI_(RT_VOLATILE_STORE|VARIABLE_FILE_STORE)=y", re.MULTILINE
    )
    hits = [
        str(p.relative_to(ROOT))
        for base in (LAYER, ROOT / "kas")
        for p in base.rglob("*")
        if p.is_file() and pattern.search(p.read_text(errors="replace"))
    ]
    assert hits == []
