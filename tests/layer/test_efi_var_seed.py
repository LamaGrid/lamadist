# SPDX-License-Identifier: Apache-2.0
"""Tests for the build-time U-Boot EFI variable preseed (ADR 0013 decision 3).

The seed generator turns the sb-dev PK, KEK, and db EFI Signature
Lists into the file U-Boot's ``EFI_VARIABLES_PRESEED`` embeds.  The
reader below is an independent walk of U-Boot v2026.01
``efi_var_restore()`` (lib/efi_loader/efi_var_file.c) over the layout
in include/efi_variable.h, so a generator bug cannot hide behind a
matching writer bug.  Every input is a throwaway built in the test;
no key, certificate, or seed is read from or written to the tree.
"""

from __future__ import annotations

import struct
import sys
import uuid
import zlib
from dataclasses import dataclass
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
LAYER = ROOT / "meta-lamadist"
sys.path[0:0] = [str(LAYER / "lib")]

from lamadist import efivarseed

MAGIC = 0x0161566966456255
GLOBAL_GUID = uuid.UUID("8be4df61-93ca-11d2-aa0d-00e098032b8c")
SECDB_GUID = uuid.UUID("d719b2cb-3d3a-4596-a3bc-dad00e67656f")
X509_GUID = uuid.UUID("a5c059a1-94e4-4aa7-87b5-ab155c2bf072")
OWNER = uuid.UUID("0d648e51-9f2d-453a-bbc1-2200cf8ebe0e")
NV, BS, RT, AT = 0x1, 0x2, 0x4, 0x20
AUTH_ATTRS = NV | BS | RT | AT
HEADER = struct.Struct("<QQLL")
ENTRY = struct.Struct("<LLQ16s")


@dataclass(frozen=True)
class Var:
    name: str
    guid: uuid.UUID
    attr: int
    time: int
    data: bytes


def make_esl(cert: bytes) -> bytes:
    """One EFI_SIGNATURE_LIST holding one X.509 entry."""
    sig = OWNER.bytes_le + cert
    size = 28 + len(sig)
    return X509_GUID.bytes_le + struct.pack("<LLL", size, 0, len(sig)) + sig


def read_seed(blob: bytes) -> dict[str, Var]:
    """Walk the seed the way efi_var_restore() does; fail on a bad frame."""
    reserved, magic, length, crc = HEADER.unpack_from(blob)
    assert reserved == 0
    assert magic == MAGIC
    assert length == len(blob)
    assert crc == zlib.crc32(blob[HEADER.size :]) & 0xFFFFFFFF
    out: dict[str, Var] = {}
    off = HEADER.size
    while off < length:
        size, attr, time, guid = ENTRY.unpack_from(blob, off)
        name_at = off + ENTRY.size
        end = name_at
        while blob[end : end + 2] != b"\0\0":
            end += 2
        name = blob[name_at:end].decode("utf-16-le")
        data_at = end + 2
        data = blob[data_at : data_at + size]
        out[name] = Var(name, uuid.UUID(bytes_le=guid), attr, time, data)
        off = (data_at + size + 7) & ~7
    assert off == length
    return out


@pytest.fixture
def esls(tmp_path: Path) -> dict[str, Path]:
    paths = {}
    for name in ("pk", "kek", "db"):
        path = tmp_path / f"{name}.esl"
        path.write_bytes(make_esl(f"throwaway {name} cert".encode()))
        paths[name] = path
    return paths


def build(esls: dict[str, Path]) -> bytes:
    return efivarseed.build_seed(esls["pk"], esls["kek"], esls["db"])


def test_seed_holds_pk_kek_and_db(esls: dict[str, Path]) -> None:
    seed = read_seed(build(esls))
    assert set(seed) == {"PK", "KEK", "db"}
    for name in ("PK", "KEK", "db"):
        assert seed[name].data == esls[name.lower()].read_bytes()


def test_vendor_guids_match_the_uefi_variables(esls: dict[str, Path]) -> None:
    seed = read_seed(build(esls))
    assert seed["PK"].guid == GLOBAL_GUID
    assert seed["KEK"].guid == GLOBAL_GUID
    assert seed["db"].guid == SECDB_GUID


def test_attributes_are_nv_bs_rt_and_time_based_auth(esls: dict[str, Path]) -> None:
    """U-Boot refuses an authenticated variable without the AT bit."""
    seed = read_seed(build(esls))
    assert {v.attr for v in seed.values()} == {AUTH_ATTRS}


def test_seed_is_reproducible(esls: dict[str, Path]) -> None:
    """No wall clock: the same inputs give the same bytes, and time is 0."""
    first, second = build(esls), build(esls)
    assert first == second
    assert {v.time for v in read_seed(first).values()} == {0}


def test_entries_are_eight_byte_aligned(esls: dict[str, Path]) -> None:
    assert len(build(esls)) % 8 == 0


def test_an_empty_input_is_refused(esls: dict[str, Path]) -> None:
    """U-Boot skips a zero-length variable, which would leave Setup Mode."""
    esls["pk"].write_bytes(b"")
    with pytest.raises(efivarseed.SeedError, match="PK"):
        build(esls)


def test_a_non_esl_input_is_refused(esls: dict[str, Path]) -> None:
    esls["db"].write_bytes(b"-----BEGIN CERTIFICATE-----\n")
    with pytest.raises(efivarseed.SeedError, match="db"):
        build(esls)


def test_a_missing_input_is_refused(esls: dict[str, Path]) -> None:
    esls["kek"].unlink()
    with pytest.raises(efivarseed.SeedError, match="KEK"):
        build(esls)


def test_cli_writes_the_seed(esls: dict[str, Path], tmp_path: Path) -> None:
    out = tmp_path / "out" / "seed.bin"
    rc = efivarseed.main(
        [
            "--pk",
            str(esls["pk"]),
            "--kek",
            str(esls["kek"]),
            "--db",
            str(esls["db"]),
            "--output",
            str(out),
        ]
    )
    assert rc == 0
    assert out.read_bytes() == build(esls)
