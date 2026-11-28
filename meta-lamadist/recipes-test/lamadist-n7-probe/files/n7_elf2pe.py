#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Write a PE32+ UEFI application from the N7 probe's static ELF file.

usage: n7_elf2pe.py IN.elf OUT.efi

The linker script puts .text and .data at their final relative virtual
addresses, so each ELF section maps one-to-one to a PE section.  The
image has no base relocation table: the firmware loads it at any
address and applies no fix-up.  That is correct only for code that
addresses everything PC-relative, so every relocation the link kept
(--emit-relocs) is checked, and any type that would need a load-time
fix fails the conversion.  ADR 0017 records why there is no gnu-efi.
"""

import itertools
import struct
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final

EM_AARCH64: Final = 183
ET_EXEC: Final = 2
SHT_NOBITS: Final = 8
SHT_RELA: Final = 4
SHF_ALLOC: Final = 0x2

SECTION_ALIGNMENT: Final = 0x1000
FILE_ALIGNMENT: Final = 0x200
IMAGE_FILE_MACHINE_ARM64: Final = 0xAA64
# EXECUTABLE_IMAGE | LARGE_ADDRESS_AWARE; RELOCS_STRIPPED stays clear so
# edk2 may load the image away from its ImageBase.
FILE_CHARACTERISTICS: Final = 0x0022
SUBSYSTEM_EFI_APPLICATION: Final = 10
OPTIONAL_HEADER_SIZE: Final = 240
DATA_DIRECTORIES: Final = 16

# Output sections and their PE characteristics: code (execute, read)
# and initialized data (read, write).
SECTIONS: Final = {".text": 0x60000020, ".data": 0xC0000040}

# AArch64 relocation types that resolve PC-relative or page-relative
# (an ADRP page plus a low-12-bit offset), so the code is correct at any
# load address.  Every other type, absolute words, MOVW absolute, and
# GOT entries among them, is refused.
PC_RELATIVE_RELOCATIONS: Final = frozenset(
    {
        260,  # PREL64
        261,  # PREL32
        262,  # PREL16
        273,  # LD_PREL_LO19
        274,  # ADR_PREL_LO21
        275,  # ADR_PREL_PG_HI21
        276,  # ADR_PREL_PG_HI21_NC
        277,  # ADD_ABS_LO12_NC
        278,  # LDST8_ABS_LO12_NC
        279,  # TSTBR14
        280,  # CONDBR19
        282,  # JUMP26
        283,  # CALL26
        284,  # LDST16_ABS_LO12_NC
        285,  # LDST32_ABS_LO12_NC
        286,  # LDST64_ABS_LO12_NC
        299,  # LDST128_ABS_LO12_NC
    }
)


class ConversionError(Exception):
    """The ELF file cannot become a relocation-free UEFI application."""


@dataclass(frozen=True, slots=True)
class Section:
    name: str
    sh_type: int
    flags: int
    addr: int
    offset: int
    size: int
    info: int


def _align(value: int, alignment: int) -> int:
    return (value + alignment - 1) // alignment * alignment


def _sections(elf: bytes) -> tuple[int, list[Section]]:
    if elf[:4] != b"\x7fELF" or len(elf) < 64:
        raise ConversionError("not an ELF file")
    if elf[4] != 2 or elf[5] != 1:
        raise ConversionError("not a little-endian ELF64 file")
    (etype, machine, _ver, entry, _phoff, shoff, _flags, _ehsize, _phes, _phn) = (
        struct.unpack_from("<HHIQQQIHHH", elf, 16)
    )
    shentsize, shnum, shstrndx = struct.unpack_from("<HHH", elf, 58)
    if machine != EM_AARCH64:
        raise ConversionError(f"ELF machine {machine} is not AArch64 ({EM_AARCH64})")
    if etype != ET_EXEC:
        raise ConversionError(f"ELF type {etype} is not ET_EXEC: link with -static")
    raw = []
    for i in range(shnum):
        raw.append(struct.unpack_from("<IIQQQQIIQQ", elf, shoff + i * shentsize))
    strtab_off, strtab_size = raw[shstrndx][4], raw[shstrndx][5]
    strtab = elf[strtab_off : strtab_off + strtab_size]
    out = []
    for name_off, typ, flags, addr, off, size, _link, info, _al, _es in raw:
        name = strtab[name_off : strtab.index(b"\0", name_off)].decode()
        out.append(Section(name, typ, flags, addr, off, size, info))
    return entry, out


def _check_relocations(elf: bytes, sections: Sequence[Section]) -> None:
    for sec in sections:
        if sec.sh_type != SHT_RELA:
            continue
        target = sections[sec.info]
        if not target.flags & SHF_ALLOC:
            continue
        for pos in range(sec.offset, sec.offset + sec.size, 24):
            r_offset, r_info = struct.unpack_from("<QQ", elf, pos)
            rtype = r_info & 0xFFFFFFFF
            if rtype not in PC_RELATIVE_RELOCATIONS:
                raise ConversionError(
                    f"relocation type {rtype} at {r_offset:#x} in {target.name}"
                    " needs a load-time fix; build the code PC-relative"
                )


def _layout(entry: int, sections: Sequence[Section]) -> list[Section]:
    chosen = []
    for sec in sections:
        if not sec.flags & SHF_ALLOC or sec.size == 0:
            continue
        if sec.name not in SECTIONS:
            raise ConversionError(f"unexpected allocated section {sec.name}")
        if sec.addr < SECTION_ALIGNMENT:
            raise ConversionError(
                f"{sec.name} at {sec.addr:#x} overlaps the headers;"
                f" place it at or above {SECTION_ALIGNMENT:#x}"
            )
        if sec.addr % SECTION_ALIGNMENT:
            raise ConversionError(
                f"{sec.name} at {sec.addr:#x} is not {SECTION_ALIGNMENT:#x}-aligned"
            )
        chosen.append(sec)
    chosen.sort(key=lambda s: s.addr)
    if not chosen or chosen[0].name != ".text":
        raise ConversionError("no .text section at the lowest address")
    for prev, nxt in itertools.pairwise(chosen):
        if prev.addr + prev.size > nxt.addr:
            raise ConversionError(f"{prev.name} overlaps {nxt.name}")
    text = chosen[0]
    if not text.addr <= entry < text.addr + text.size:
        raise ConversionError(f"entry {entry:#x} is outside .text")
    return chosen


def _headers(entry: int, chosen: Sequence[Section], raw_sizes: Sequence[int]) -> bytes:
    nsec = len(chosen)
    headers_size = _align(
        64 + 4 + 20 + OPTIONAL_HEADER_SIZE + 40 * nsec, FILE_ALIGNMENT
    )
    last = chosen[-1]
    size_of_image = _align(last.addr + last.size, SECTION_ALIGNMENT)
    code = sum(r for s, r in zip(chosen, raw_sizes) if s.name == ".text")
    data = sum(r for s, r in zip(chosen, raw_sizes) if s.name != ".text")

    dos = bytearray(64)
    dos[0:2] = b"MZ"
    struct.pack_into("<I", dos, 0x3C, 64)
    coff = struct.pack(
        "<HHIIIHH",
        IMAGE_FILE_MACHINE_ARM64,
        nsec,
        0,
        0,
        0,
        OPTIONAL_HEADER_SIZE,
        FILE_CHARACTERISTICS,
    )
    opt = struct.pack(
        "<HBBIIIII",
        0x20B,  # PE32+
        0,
        0,
        code,
        data,
        0,
        entry,
        chosen[0].addr,
    )
    opt += struct.pack(
        "<QIIHHHHHHIIIIHHQQQQII",
        0,  # ImageBase
        SECTION_ALIGNMENT,
        FILE_ALIGNMENT,
        0,
        0,
        0,
        0,
        0,
        0,
        0,  # Win32VersionValue
        size_of_image,
        headers_size,
        0,  # CheckSum: sbsign writes it
        SUBSYSTEM_EFI_APPLICATION,
        0,  # DllCharacteristics
        0,
        0,
        0,
        0,
        0,  # LoaderFlags
        DATA_DIRECTORIES,
    )
    opt += bytes(8 * DATA_DIRECTORIES)
    assert len(opt) == OPTIONAL_HEADER_SIZE

    table = b""
    pointer = headers_size
    for sec, raw_size in zip(chosen, raw_sizes):
        table += struct.pack(
            "<8sIIIIIIHHI",
            sec.name.encode(),
            sec.size,
            sec.addr,
            raw_size,
            pointer,
            0,
            0,
            0,
            0,
            SECTIONS[sec.name],
        )
        pointer += raw_size
    head = bytes(dos) + b"PE\0\0" + coff + opt + table
    return head + bytes(headers_size - len(head))


def elf_to_pe(elf: bytes) -> bytes:
    """Return the PE32+ image for ELF, or raise ConversionError."""
    entry, sections = _sections(elf)
    _check_relocations(elf, sections)
    chosen = _layout(entry, sections)
    bodies = []
    for sec in chosen:
        if sec.sh_type == SHT_NOBITS:
            body = bytes(sec.size)
        else:
            body = elf[sec.offset : sec.offset + sec.size]
        bodies.append(body + bytes(_align(sec.size, FILE_ALIGNMENT) - sec.size))
    head = _headers(entry, chosen, [len(b) for b in bodies])
    return head + b"".join(bodies)


def main(argv: Sequence[str]) -> int:
    if len(argv) != 3:
        print(__doc__, file=sys.stderr)
        return 2
    with open(argv[1], "rb") as f:
        elf = f.read()
    try:
        pe = elf_to_pe(elf)
    except ConversionError as err:
        print(f"n7_elf2pe: {argv[1]}: {err}", file=sys.stderr)
        return 1
    with open(argv[2], "wb") as f:
        f.write(pe)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
