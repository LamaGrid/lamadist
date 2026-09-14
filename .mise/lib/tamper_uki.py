# SPDX-License-Identifier: Apache-2.0
"""Corrupt the UKI inside a disk image so Secure Boot firmware must refuse it.

usage: tamper_uki.py IMAGE UKI

The ESP stores the UKI uncompressed, so a 4 KiB chunk taken 8 MiB into
UKI (deep inside its .linux section) is searched for verbatim in IMAGE,
and 16 bytes are zeroed after every hit.  That breaks the Authenticode
hash without touching FAT metadata: the file still loads, so the
firmware's signature check is the only thing left to stop it.  Exit
status 1 means the UKI's bytes are not in IMAGE at all.
"""

import mmap
import sys
from collections.abc import Sequence
from typing import Final

CHUNK_OFFSET: Final = 8 << 20
CHUNK_LEN: Final = 4096
ZERO_AT: Final = 256
ZERO_LEN: Final = 16


def tamper(image: str, uki: str) -> list[int]:
    """Zero bytes inside every on-disk copy of UKI found in IMAGE.

    Returns the byte offsets that were zeroed; empty when UKI's chunk is
    not present in IMAGE.
    """
    with open(uki, "rb") as f:
        f.seek(CHUNK_OFFSET)
        chunk = f.read(CHUNK_LEN)
    if len(chunk) != CHUNK_LEN:
        raise ValueError(f"{uki} is shorter than {CHUNK_OFFSET + CHUNK_LEN} bytes")
    hits: list[int] = []
    with open(image, "r+b") as f, mmap.mmap(f.fileno(), 0) as m:
        pos = m.find(chunk)
        while pos != -1:
            hits.append(pos)
            pos = m.find(chunk, pos + 1)
        for pos in hits:
            m[pos + ZERO_AT : pos + ZERO_AT + ZERO_LEN] = bytes(ZERO_LEN)
        m.flush()
    return [pos + ZERO_AT for pos in hits]


def main(argv: Sequence[str]) -> int:
    if len(argv) != 3:
        print(__doc__, file=sys.stderr)
        return 2
    image, uki = argv[1], argv[2]
    zeroed = tamper(image, uki)
    if not zeroed:
        print(f"tamper_uki: UKI bytes not found in {image}", file=sys.stderr)
        return 1
    offsets = ", ".join(hex(offset) for offset in zeroed)
    print(f"tamper_uki: zeroed {ZERO_LEN} bytes at {offsets}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
