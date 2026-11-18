# SPDX-License-Identifier: Apache-2.0
"""Tests for the N7 write-test payload helper (.mise/lib/efivar_payloads.py).

The helper defines the eight payload rows, the sign-efi-sig-list
command line for the signed ones, the efivarfs framing (4-byte
attributes, then data) that both test parts send, a check of every
signed payload's EFI_VARIABLE_AUTHENTICATION_2 layout, the ESP offset
in a GPT image, and the expected PK, KEK, and db bodies.  It runs with
the public development keys in meta-lamadist/files/sb-dev only.
"""

from __future__ import annotations

import hashlib
import importlib.util
import shutil
import struct
import subprocess
import sys
import uuid
import zlib
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[2]
HELPER = ROOT / ".mise" / "lib" / "efivar_payloads.py"
KEYS = ROOT / "meta-lamadist" / "files" / "sb-dev"
PKCS7_GUID = bytes.fromhex("9dd2af4adf68ee498aa9347d375665a7")
ESP_TYPE = uuid.UUID("c12a7328-f81f-11d2-ba4b-00a0c93ec93b")
LINUX_TYPE = uuid.UUID("0fc63daf-8483-4772-8e79-3d69d8477de4")


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("efivar_payloads", HELPER)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["efivar_payloads"] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def ep() -> ModuleType:
    return _load()


# --- the rows -------------------------------------------------------------


def test_rows_are_the_eight_design_rows_in_probe_order(ep: ModuleType) -> None:
    got = [(r.tag, r.var, r.attrs, r.signer, r.source) for r in ep.ROWS]
    assert got == [
        ("U-PK", "PK", 0x07, None, "pk.esl"),
        ("U-KEK", "KEK", 0x07, None, "kek.esl"),
        ("U-db", "db", 0x07, None, "db.esl"),
        ("W-db", "db", 0x27, "db", "kek.esl"),
        ("X-PK", "PK", 0x00, None, None),
        ("S-db", "db", 0x67, "kek", "kek.esl"),
        ("S-KEK", "KEK", 0x67, "pk", "db.esl"),
        ("S-PK", "PK", 0x27, "pk", None),
    ]


def test_each_variable_has_its_specification_guid(ep: ModuleType) -> None:
    assert ep.VENDOR == {
        "PK": "8be4df61-93ca-11d2-aa0d-00e098032b8c",
        "KEK": "8be4df61-93ca-11d2-aa0d-00e098032b8c",
        "db": "d719b2cb-3d3a-4596-a3bc-dad00e67656f",
        "dbx": "d719b2cb-3d3a-4596-a3bc-dad00e67656f",
    }


def test_sign_argv_is_pinned(ep: ModuleType) -> None:
    rows = {r.tag: r for r in ep.ROWS}
    k = "/_w/meta-lamadist/files/sb-dev"
    assert ep.sign_argv(rows["S-PK"], k, "/o/S-PK.auth") == [
        "sign-efi-sig-list",
        "-t",
        "2099-01-01 00:00:00",
        "-k",
        f"{k}/pk.key.pem",
        "-c",
        f"{k}/pk.cert.pem",
        "PK",
        "/dev/null",
        "/o/S-PK.auth",
    ]
    assert ep.sign_argv(rows["S-db"], k, "/o/S-db.auth") == [
        "sign-efi-sig-list",
        "-a",
        "-t",
        "2099-01-01 00:00:00",
        "-k",
        f"{k}/kek.key.pem",
        "-c",
        f"{k}/kek.cert.pem",
        "db",
        f"{k}/kek.esl",
        "/o/S-db.auth",
    ]
    assert ep.sign_argv(rows["W-db"], k, "/o/W-db.auth")[1:6] == [
        "-t",
        "2099-01-01 00:00:00",
        "-k",
        f"{k}/db.key.pem",
        "-c",
    ]


def test_sign_argv_refuses_an_unsigned_row(ep: ModuleType) -> None:
    with pytest.raises(ep.PayloadError, match="U-PK"):
        ep.sign_argv(ep.ROWS[0], "/k", "/o/x")


def test_sign_script_signs_exactly_the_four_signed_rows(ep: ModuleType) -> None:
    script = ep.sign_script("/_w/k", "/_w/out")
    lines = [ln for ln in script.splitlines() if ln.startswith("sign-efi-sig-list")]
    assert len(lines) == 4
    for tag in ("W-db", "S-db", "S-KEK", "S-PK"):
        assert any(ln.endswith(f"/_w/out/{tag}.auth") for ln in lines), tag
    assert script.startswith("set -o errexit\n")
    # The timestamp has a space, so it must be quoted for the shell.
    assert "'2099-01-01 00:00:00'" in script


# --- framing --------------------------------------------------------------


def test_frame_puts_little_endian_attributes_before_the_data(
    ep: ModuleType,
) -> None:
    assert ep.frame(0x27, b"abc") == b"\x27\0\0\0abc"
    assert ep.frame(0, b"") == b"\0\0\0\0"


def _auth2(payload: bytes, *, year: int = 2099, sig: bytes = b"S" * 40) -> bytes:
    time = struct.pack("<HBBBBBBIhBB", year, 1, 1, 0, 0, 0, 0, 0, 0, 0, 0)
    hdr = struct.pack("<IHH", 24 + len(sig), 0x0200, 0x0EF1) + PKCS7_GUID
    return time + hdr + sig + payload


def test_parse_auth2_returns_the_timestamp_and_the_payload(ep: ModuleType) -> None:
    got = ep.parse_auth2(_auth2(b"ESL"))
    assert got.year == 2099
    assert got.payload == b"ESL"


@pytest.mark.parametrize(
    ("mutate", "match"),
    [
        (lambda b: b[:20], "short"),
        (lambda b: b[:20] + b"\x00\x01" + b[22:], "revision"),
        (lambda b: b[:22] + b"\x02\x00" + b[24:], "certificate type"),
        (lambda b: b[:24] + bytes(16) + b[40:], "PKCS7"),
        (lambda b: b[:16] + struct.pack("<I", 9999) + b[20:], "length"),
        # The specification requires Pad1, Nanosecond, TimeZone,
        # Daylight, and Pad2 to be zero.
        (lambda b: b[:8] + b"\x01" + b[9:], "time"),
        (lambda b: b[:15] + b"\x01" + b[16:], "time"),
    ],
)
def test_parse_auth2_refuses_a_malformed_header(
    ep: ModuleType, mutate: object, match: str
) -> None:
    body = _auth2(b"ESL")
    with pytest.raises(ep.PayloadError, match=match):
        ep.parse_auth2(mutate(body))  # type: ignore[operator]


def test_check_signed_matches_the_payload_to_its_source(
    ep: ModuleType, tmp_path: Path
) -> None:
    rows = {r.tag: r for r in ep.ROWS}
    kek = (KEYS / "kek.esl").read_bytes()
    ep.check_signed(rows["S-db"], _auth2(kek), KEYS)
    ep.check_signed(rows["S-PK"], _auth2(b""), KEYS)
    with pytest.raises(ep.PayloadError, match="S-db"):
        ep.check_signed(rows["S-db"], _auth2(kek[:-1]), KEYS)
    with pytest.raises(ep.PayloadError, match="S-PK"):
        ep.check_signed(rows["S-PK"], _auth2(b"x"), KEYS)


def test_build_bins_frames_every_row(ep: ModuleType, tmp_path: Path) -> None:
    signed = tmp_path / "signed"
    signed.mkdir()
    sources = {"W-db": "kek.esl", "S-db": "kek.esl", "S-KEK": "db.esl"}
    for tag, src in sources.items():
        (signed / f"{tag}.auth").write_bytes(_auth2((KEYS / src).read_bytes()))
    (signed / "S-PK.auth").write_bytes(_auth2(b""))
    out = tmp_path / "bins"
    paths = ep.build_bins(KEYS, signed, out)
    assert sorted(paths) == sorted(r.tag for r in ep.ROWS)
    assert paths["X-PK"].read_bytes() == b"\0\0\0\0"
    assert (
        paths["U-KEK"].read_bytes() == b"\x07\0\0\0" + (KEYS / "kek.esl").read_bytes()
    )
    s_kek = paths["S-KEK"].read_bytes()
    assert s_kek[:4] == b"\x67\0\0\0"
    assert s_kek[4:] == (signed / "S-KEK.auth").read_bytes()


def test_build_bins_refuses_a_missing_or_wrong_signed_payload(
    ep: ModuleType, tmp_path: Path
) -> None:
    signed = tmp_path / "signed"
    signed.mkdir()
    with pytest.raises(ep.PayloadError, match="W-db"):
        ep.build_bins(KEYS, signed, tmp_path / "bins")


# --- the ESP in the image -------------------------------------------------


def _gpt(tmp_path: Path, parts: list[tuple[uuid.UUID, int, int]]) -> Path:
    img = bytearray(512 * 64)
    img[512:520] = b"EFI PART"
    struct.pack_into("<QII", img, 512 + 72, 2, 128, 128)
    for i, (ptype, first, last) in enumerate(parts):
        off = 1024 + 128 * i
        img[off : off + 16] = ptype.bytes_le
        img[off + 16 : off + 32] = uuid.uuid4().bytes_le
        struct.pack_into("<QQ", img, off + 32, first, last)
    path = tmp_path / "disk.img"
    path.write_bytes(bytes(img))
    return path


def test_esp_offset_finds_the_esp_by_its_type(ep: ModuleType, tmp_path: Path) -> None:
    img = _gpt(tmp_path, [(LINUX_TYPE, 34, 2047), (ESP_TYPE, 2048, 4095)])
    assert ep.esp_offset(img) == 2048 * 512


def test_esp_offset_refuses_no_esp_or_no_gpt(ep: ModuleType, tmp_path: Path) -> None:
    img = _gpt(tmp_path, [(LINUX_TYPE, 34, 2047)])
    with pytest.raises(ep.PayloadError, match="ESP"):
        ep.esp_offset(img)
    bare = tmp_path / "bare.img"
    bare.write_bytes(bytes(4096))
    with pytest.raises(ep.PayloadError, match="GPT"):
        ep.esp_offset(bare)


# --- expectations ---------------------------------------------------------


def test_expectations_are_the_seeded_lists(ep: ModuleType) -> None:
    exp = ep.expectations(KEYS)
    assert sorted(exp) == ["KEK", "PK", "db"]
    for var, name in (("PK", "pk.esl"), ("KEK", "kek.esl"), ("db", "db.esl")):
        data = (KEYS / name).read_bytes()
        assert exp[var].sha256 == hashlib.sha256(data).hexdigest()
        assert exp[var].crc32 == zlib.crc32(data)
        assert exp[var].size == len(data)


def test_cli_prints_the_esp_offset(ep: ModuleType, tmp_path: Path) -> None:
    img = _gpt(tmp_path, [(ESP_TYPE, 2048, 4095)])
    run = subprocess.run(
        [sys.executable, str(HELPER), "esp-offset", str(img)],
        check=True,
        capture_output=True,
        text=True,
    )
    assert run.stdout == f"{2048 * 512}\n"


def test_cli_refuses_an_unknown_command() -> None:
    run = subprocess.run(
        [sys.executable, str(HELPER), "nonsense"],
        check=False,
        capture_output=True,
        text=True,
    )
    assert run.returncode == 2


@pytest.mark.skipif(
    shutil.which("sign-efi-sig-list") is None, reason="efitools not on this host"
)
def test_real_efitools_output_passes_the_check(ep: ModuleType, tmp_path: Path) -> None:
    """The layout check accepts what efitools actually writes."""
    for row in ep.ROWS:
        if row.signer is None:
            continue
        out = tmp_path / f"{row.tag}.auth"
        subprocess.run(
            ep.sign_argv(row, str(KEYS), str(out)), check=True, capture_output=True
        )
        ep.check_signed(row, out.read_bytes(), KEYS)
