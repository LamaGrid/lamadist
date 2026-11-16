# SPDX-License-Identifier: Apache-2.0
"""Build U-Boot's EFI variable preseed from PK, KEK, and db signature lists.

U-Boot's ``CONFIG_EFI_VARIABLES_PRESEED`` embeds a variable store in
the binary (``.incbin`` of ``CONFIG_EFI_VAR_SEED_FILE``) and, once it
holds a PK, blocks every runtime write to PK, KEK, db, and dbx.  The
store is the ``ubootefi.var`` layout of U-Boot v2026.01
(``include/efi_variable.h``, ``lib/efi_loader/efi_var_file.c``)::

    header   reserved u64 = 0, magic u64, length u32, crc32 u32
    entry    length u32 (data bytes), attr u32, time u64, guid 16,
             UTF-16LE name + NUL, data; name + data padded to 8 bytes

The variable data is the raw EFI Signature List, which is what
``virt-fw-vars --set-pk/--add-kek/--add-db`` enrolls on the x86_64
gate from the same certificates.  ``time`` is 0 and nothing reads the
clock, so the seed is a pure function of its three inputs.

U-Boot's own ``tools/efivar.py`` writes the same layout (ADR 0016
records why it is not used).  This module imports only the standard
library and is meant to run inside BitBake through ``addpylib``.
"""

from __future__ import annotations

import argparse
import struct
import uuid
import zlib
from collections.abc import Sequence
from pathlib import Path
from typing import Final

MAGIC: Final = 0x0161566966456255  # "UbEfiVa", version 1
GLOBAL_GUID: Final = uuid.UUID("8be4df61-93ca-11d2-aa0d-00e098032b8c")
SECURITY_DB_GUID: Final = uuid.UUID("d719b2cb-3d3a-4596-a3bc-dad00e67656f")

NON_VOLATILE: Final = 0x1
BOOTSERVICE_ACCESS: Final = 0x2
RUNTIME_ACCESS: Final = 0x4
TIME_BASED_AUTH: Final = 0x20
# U-Boot rejects PK, KEK, and db without the time-based auth bit.
AUTH_ATTRS: Final = NON_VOLATILE | BOOTSERVICE_ACCESS | RUNTIME_ACCESS | TIME_BASED_AUTH

_HEADER: Final = struct.Struct("<QQLL")
_ENTRY: Final = struct.Struct("<LLQ16s")
_ESL_HEADER: Final = struct.Struct("<16sLLL")


class SeedError(Exception):
    """An input is missing, empty, or not an EFI Signature List."""


def _check_esl(name: str, data: bytes) -> None:
    """Require ``data`` to be whole EFI_SIGNATURE_LISTs, at least one."""
    off = 0
    while off < len(data):
        if len(data) - off < _ESL_HEADER.size:
            raise SeedError(f"{name}: truncated signature list header")
        _, size, _, _ = _ESL_HEADER.unpack_from(data, off)
        if size < _ESL_HEADER.size or off + size > len(data):
            raise SeedError(f"{name}: signature list size {size} is out of range")
        off += size
    if off == 0:
        raise SeedError(f"{name}: empty (U-Boot would skip it and stay in Setup Mode)")


def _read_esl(name: str, path: Path) -> bytes:
    try:
        data = path.read_bytes()
    except OSError as err:
        raise SeedError(f"{name}: cannot read {path}: {err.strerror}") from err
    _check_esl(name, data)
    return data


def _entry(name: str, guid: uuid.UUID, data: bytes) -> bytes:
    tail = name.encode("utf-16-le") + b"\0\0" + data
    tail += b"\0" * (-len(tail) % 8)
    return _ENTRY.pack(len(data), AUTH_ATTRS, 0, guid.bytes_le) + tail


def build_seed(pk: Path, kek: Path, db: Path) -> bytes:
    """Return the seed holding PK, KEK, and db from three ESL files."""
    body = (
        _entry("PK", GLOBAL_GUID, _read_esl("PK", pk))
        + _entry("KEK", GLOBAL_GUID, _read_esl("KEK", kek))
        + _entry("db", SECURITY_DB_GUID, _read_esl("db", db))
    )
    header = _HEADER.pack(
        0, MAGIC, _HEADER.size + len(body), zlib.crc32(body) & 0xFFFFFFFF
    )
    return header + body


def main(argv: Sequence[str] | None = None) -> int:
    """Write the seed named by ``--output``; return a process exit code."""
    ap = argparse.ArgumentParser(description="Build the U-Boot EFI variable preseed.")
    for flag in ("pk", "kek", "db", "output"):
        ap.add_argument(f"--{flag}", type=Path, required=True)
    args = ap.parse_args(argv)
    try:
        seed = build_seed(args.pk, args.kek, args.db)
    except SeedError as err:
        ap.exit(1, f"error: {err}\n")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(seed)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
