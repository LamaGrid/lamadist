#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Payloads for the N7 write test (docs/validation/N7-WRITE-TEST.md).

Eight rows try to change PK, KEK, and db: unsigned writes (U-*), a
write signed by the wrong key (W-db), an unauthenticated delete
(X-PK), and correctly signed writes (S-*) that a store open to
authenticated writes would accept.  Both parts of the test send the
same bytes: the efivarfs layout, 4-byte little-endian attributes and
then the data.  The probe (Part B) splits them again.

Signed rows come from efitools' sign-efi-sig-list in the build
container (ADR 0005) with the public development keys only.  This
module writes that shell script, checks every signed result's
EFI_VARIABLE_AUTHENTICATION_2 layout, and frames the rows.  Stdlib
only; it runs on the host.

usage:
  efivar_payloads.py sign-script KEYDIR OUTDIR  (container paths)
  efivar_payloads.py bins KEYDIR SIGNEDDIR OUTDIR
  efivar_payloads.py esp-offset IMAGE
  efivar_payloads.py expect KEYDIR
"""

from __future__ import annotations

import hashlib
import json
import shlex
import struct
import sys
import uuid
import zlib
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Final

TIMESTAMP: Final = "2099-01-01 00:00:00"
GLOBAL_VARIABLE: Final = "8be4df61-93ca-11d2-aa0d-00e098032b8c"
IMAGE_SECURITY_DATABASE: Final = "d719b2cb-3d3a-4596-a3bc-dad00e67656f"
VENDOR: Final = {
    "PK": GLOBAL_VARIABLE,
    "KEK": GLOBAL_VARIABLE,
    "db": IMAGE_SECURITY_DATABASE,
    "dbx": IMAGE_SECURITY_DATABASE,
}
ESL_FILES: Final = {"PK": "pk.esl", "KEK": "kek.esl", "db": "db.esl"}

WIN_CERT_REVISION: Final = 0x0200
WIN_CERT_TYPE_EFI_GUID: Final = 0x0EF1
CERT_TYPE_PKCS7_GUID: Final = uuid.UUID("4aafd29d-68df-49ee-8aa9-347d375665a7")
ESP_TYPE: Final = uuid.UUID("c12a7328-f81f-11d2-ba4b-00a0c93ec93b")
SECTOR: Final = 512


class PayloadError(Exception):
    """A payload, a signed result, or the image is not what the test needs."""


@dataclass(frozen=True, slots=True)
class Row:
    tag: str
    var: str
    attrs: int
    signer: str | None  # key file stem under the key dir, if signed
    source: str | None  # ESL file under the key dir; None is empty data
    append: bool = False


# Attributes: NV|BS|RT is 0x07; TIME_BASED_AUTHENTICATED_WRITE_ACCESS
# adds 0x20; APPEND_WRITE adds 0x40.  The order is the probe's.
ROWS: Final = (
    Row("U-PK", "PK", 0x07, None, "pk.esl"),
    Row("U-KEK", "KEK", 0x07, None, "kek.esl"),
    Row("U-db", "db", 0x07, None, "db.esl"),
    Row("W-db", "db", 0x27, "db", "kek.esl"),
    Row("X-PK", "PK", 0x00, None, None),
    Row("S-db", "db", 0x67, "kek", "kek.esl", append=True),
    Row("S-KEK", "KEK", 0x67, "pk", "db.esl", append=True),
    Row("S-PK", "PK", 0x27, "pk", None),
)


@dataclass(frozen=True, slots=True)
class Auth2:
    year: int
    payload: bytes


@dataclass(frozen=True, slots=True)
class Expect:
    sha256: str
    crc32: int
    size: int


def sign_argv(row: Row, keydir: str, out: str) -> list[str]:
    """The sign-efi-sig-list command line for a signed row."""
    if row.signer is None:
        raise PayloadError(f"{row.tag} is not a signed row")
    source = f"{keydir}/{row.source}" if row.source else "/dev/null"
    argv = ["sign-efi-sig-list"]
    if row.append:
        argv.append("-a")
    argv += [
        "-t",
        TIMESTAMP,
        "-k",
        f"{keydir}/{row.signer}.key.pem",
        "-c",
        f"{keydir}/{row.signer}.cert.pem",
        row.var,
        source,
        out,
    ]
    return argv


def sign_script(keydir: str, outdir: str) -> str:
    """A shell script that signs every signed row into OUTDIR."""
    lines = ["set -o errexit", f"mkdir -p {shlex.quote(outdir)}"]
    for row in ROWS:
        if row.signer is not None:
            argv = sign_argv(row, keydir, f"{outdir}/{row.tag}.auth")
            lines.append(shlex.join(argv))
    return "\n".join(lines) + "\n"


def frame(attrs: int, body: bytes) -> bytes:
    """The efivarfs layout: attributes, then data."""
    return struct.pack("<I", attrs) + body


def parse_auth2(body: bytes) -> Auth2:
    """Split an EFI_VARIABLE_AUTHENTICATION_2 payload, or raise."""
    if len(body) < 40:
        raise PayloadError("short: no EFI_VARIABLE_AUTHENTICATION_2 header")
    year, _month, _day, _h, _m, _s, pad1, nano, tz, daylight, pad2 = struct.unpack_from(
        "<HBBBBBBIhBB", body, 0
    )
    # UEFI 2.10 8.2.6: Pad1, Nanosecond, TimeZone, Daylight, and Pad2
    # must be zero in an authenticated write.
    if pad1 or nano or tz or daylight or pad2:
        raise PayloadError("time stamp has nonzero Pad, Nanosecond, or zone fields")
    length, revision, cert_type = struct.unpack_from("<IHH", body, 16)
    if revision != WIN_CERT_REVISION:
        raise PayloadError(f"WIN_CERTIFICATE revision {revision:#06x} is not 0x0200")
    if cert_type != WIN_CERT_TYPE_EFI_GUID:
        raise PayloadError(f"certificate type {cert_type:#06x} is not EFI_GUID")
    if body[24:40] != CERT_TYPE_PKCS7_GUID.bytes_le:
        raise PayloadError("certificate GUID is not EFI_CERT_TYPE_PKCS7_GUID")
    if length < 24 or 16 + length > len(body):
        raise PayloadError(f"header length (dwLength) {length} does not fit")
    return Auth2(year, body[16 + length :])


def check_signed(row: Row, body: bytes, keydir: Path) -> None:
    """Raise unless BODY is a well-formed signed payload of ROW's data."""
    try:
        got = parse_auth2(body)
    except PayloadError as err:
        raise PayloadError(f"{row.tag}: {err}") from err
    want = (keydir / row.source).read_bytes() if row.source else b""
    if got.payload != want:
        raise PayloadError(
            f"{row.tag}: signed data is {len(got.payload)} bytes, not the"
            f" {len(want)} bytes of {row.source or 'an empty list'}"
        )


def build_bins(keydir: Path, signed: Path, outdir: Path) -> dict[str, Path]:
    """Write <tag>.bin for every row; check the signed ones first."""
    bodies: dict[str, bytes] = {}
    for row in ROWS:
        if row.signer is not None:
            path = signed / f"{row.tag}.auth"
            if not path.is_file():
                raise PayloadError(f"{row.tag}: no signed payload at {path}")
            body = path.read_bytes()
            check_signed(row, body, keydir)
        elif row.source is not None:
            body = (keydir / row.source).read_bytes()
        else:
            body = b""
        bodies[row.tag] = frame(row.attrs, body)
    outdir.mkdir(parents=True, exist_ok=True)
    paths = {}
    for tag, data in bodies.items():
        paths[tag] = outdir / f"{tag}.bin"
        paths[tag].write_bytes(data)
    return paths


def esp_offset(image: Path) -> int:
    """Byte offset of the EFI system partition in a GPT disk image."""
    with image.open("rb") as f:
        f.seek(SECTOR)
        header = f.read(92)
        if header[:8] != b"EFI PART":
            raise PayloadError(f"{image}: no GPT header at LBA 1")
        entries_lba, count, size = struct.unpack_from("<QII", header, 72)
        f.seek(entries_lba * SECTOR)
        table = f.read(count * size)
    for i in range(count):
        entry = table[i * size : (i + 1) * size]
        if uuid.UUID(bytes_le=entry[:16]) == ESP_TYPE:
            return struct.unpack_from("<Q", entry, 32)[0] * SECTOR
    raise PayloadError(f"{image}: no ESP in the partition table")


def expectations(keydir: Path) -> dict[str, Expect]:
    """The bodies the preseed holds (ADR 0016): the development ESLs."""
    out = {}
    for var, name in ESL_FILES.items():
        data = (keydir / name).read_bytes()
        out[var] = Expect(hashlib.sha256(data).hexdigest(), zlib.crc32(data), len(data))
    return out


def main(argv: Sequence[str]) -> int:
    cmd, args = (argv[1], list(argv[2:])) if len(argv) > 1 else ("", [])
    try:
        if cmd == "sign-script" and len(args) == 2:
            sys.stdout.write(sign_script(args[0], args[1]))
        elif cmd == "bins" and len(args) == 3:
            for tag, path in build_bins(
                Path(args[0]), Path(args[1]), Path(args[2])
            ).items():
                print(f"{tag} {path.stat().st_size} {path}")
        elif cmd == "esp-offset" and len(args) == 1:
            print(esp_offset(Path(args[0])))
        elif cmd == "expect" and len(args) == 1:
            exp = {k: asdict(v) for k, v in expectations(Path(args[0])).items()}
            print(json.dumps(exp, indent=2, sort_keys=True))
        else:
            print(__doc__, file=sys.stderr)
            return 2
    except PayloadError as err:
        print(f"efivar_payloads: {err}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
