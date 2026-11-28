# SPDX-License-Identifier: Apache-2.0
"""Tests for the N7 probe's ELF-to-PE writer (ADR 0017).

The probe is linked as a static ELF file whose sections already sit at
their relative virtual addresses; n7_elf2pe.py writes the PE32+ image
that U-Boot and edk2 load.  The probe carries no base relocation table,
so the writer must refuse every relocation that would need a load-time
fix.  These tests build synthetic ELF files, so no cross toolchain is
needed; the real probe is first linked in the window build.
"""

from __future__ import annotations

import importlib.util
import shutil
import struct
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[2]
WRITER = (
    ROOT
    / "meta-lamadist"
    / "recipes-test"
    / "lamadist-n7-probe"
    / "files"
    / "n7_elf2pe.py"
)
SB_DEV = ROOT / "meta-lamadist" / "files" / "sb-dev"

EM_AARCH64 = 183
EM_X86_64 = 62
ET_EXEC = 2
ET_DYN = 3
SHT_PROGBITS = 1
SHT_STRTAB = 3
SHT_RELA = 4
SHT_NOBITS = 8
SHF_WRITE = 0x1
SHF_ALLOC = 0x2
SHF_EXECINSTR = 0x4

R_AARCH64_ABS64 = 257
R_AARCH64_ADR_PREL_PG_HI21 = 275
R_AARCH64_ADD_ABS_LO12_NC = 277
R_AARCH64_CALL26 = 283
R_AARCH64_ADR_GOT_PAGE = 311

TEXT = bytes(range(256)) * 3
DATA = b"N7DATA" + bytes(58)


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("n7_elf2pe", WRITER)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules["n7_elf2pe"] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def w() -> ModuleType:
    return _load()


def _elf(
    *,
    machine: int = EM_AARCH64,
    etype: int = ET_EXEC,
    entry: int = 0x1008,
    text_addr: int = 0x1000,
    data_addr: int = 0x2000,
    data_type: int = SHT_PROGBITS,
    relocs: list[int] | None = None,
    extra: tuple[str, int, int] | None = None,
) -> bytes:
    """A minimal ELF64 LE file: .text, .data, optional .rela.text and
    one optional extra allocated section (name, address, size)."""
    sections: list[tuple[str, int, int, int, bytes, int, int, int]] = [
        # name, type, flags, addr, data, link, info, entsize
        ("", 0, 0, 0, b"", 0, 0, 0),
        (".text", SHT_PROGBITS, SHF_ALLOC | SHF_EXECINSTR, text_addr, TEXT, 0, 0, 0),
        (
            ".data",
            data_type,
            SHF_ALLOC | SHF_WRITE,
            data_addr,
            b"" if data_type == SHT_NOBITS else DATA,
            0,
            0,
            0,
        ),
    ]
    if relocs is not None:
        blob = b"".join(struct.pack("<QQq", 0x10, (1 << 32) | t, 0) for t in relocs)
        sections.append((".rela.text", SHT_RELA, 0, 0, blob, 0, 1, 24))
    if extra is not None:
        name, addr, size = extra
        sections.append((name, SHT_PROGBITS, SHF_ALLOC, addr, bytes(size), 0, 0, 0))
    names = b"\0"
    offsets: dict[str, int] = {}
    for sec in sections[1:]:
        offsets[sec[0]] = len(names)
        names += sec[0].encode() + b"\0"
    names_off = len(names)
    names += b".shstrtab\0"
    sections.append((".shstrtab", SHT_STRTAB, 0, 0, names, 0, 0, 0))
    offsets[".shstrtab"] = names_off

    body = b""
    placed: list[tuple[int, int]] = []
    pos = 64
    for sec in sections:
        data = sec[4]
        placed.append((pos, len(data)))
        body += data
        pos += len(data)
    pad = (-pos) % 8
    body += bytes(pad)
    shoff = pos + pad
    shdrs = b""
    for i, (name, typ, flags, addr, data, link, info, entsize) in enumerate(sections):
        off, size = placed[i]
        if typ == SHT_NOBITS:
            size = len(DATA)
        shdrs += struct.pack(
            "<IIQQQQIIQQ",
            offsets.get(name, 0) if i else 0,
            typ,
            flags,
            addr,
            off,
            size,
            link,
            info,
            8,
            entsize,
        )
    ident = b"\x7fELF" + bytes([2, 1, 1]) + bytes(9)
    header = ident + struct.pack(
        "<HHIQQQIHHHHHH",
        etype,
        machine,
        1,
        entry,
        0,
        shoff,
        0,
        64,
        0,
        0,
        64,
        len(sections),
        len(sections) - 1,
    )
    return header + body + shdrs


def _pe_fields(pe: bytes) -> dict[str, int]:
    lfanew = struct.unpack_from("<I", pe, 0x3C)[0]
    machine, nsec, _ts, _sym, _nsym, opt_size, chars = struct.unpack_from(
        "<HHIIIHH", pe, lfanew + 4
    )
    opt = lfanew + 24
    f: dict[str, int] = {
        "lfanew": lfanew,
        "machine": machine,
        "nsec": nsec,
        "opt_size": opt_size,
        "chars": chars,
        "magic": struct.unpack_from("<H", pe, opt)[0],
        "entry": struct.unpack_from("<I", pe, opt + 16)[0],
        "image_base": struct.unpack_from("<Q", pe, opt + 24)[0],
        "sect_align": struct.unpack_from("<I", pe, opt + 32)[0],
        "file_align": struct.unpack_from("<I", pe, opt + 36)[0],
        "size_of_image": struct.unpack_from("<I", pe, opt + 56)[0],
        "size_of_headers": struct.unpack_from("<I", pe, opt + 60)[0],
        "subsystem": struct.unpack_from("<H", pe, opt + 68)[0],
        "n_rva": struct.unpack_from("<I", pe, opt + 108)[0],
        "sections": opt + opt_size,
    }
    return f


def _sections(pe: bytes) -> list[tuple[str, int, int, int, int, int]]:
    f = _pe_fields(pe)
    out = []
    for i in range(f["nsec"]):
        base = f["sections"] + 40 * i
        name = pe[base : base + 8].rstrip(b"\0").decode()
        vsize, va, raw_size, raw_ptr = struct.unpack_from("<IIII", pe, base + 8)
        chars = struct.unpack_from("<I", pe, base + 36)[0]
        out.append((name, vsize, va, raw_size, raw_ptr, chars))
    return out


# --- headers -------------------------------------------------------------


def test_writes_a_pe32plus_efi_application_for_arm64(w: ModuleType) -> None:
    pe = w.elf_to_pe(_elf())
    f = _pe_fields(pe)
    assert pe[:2] == b"MZ"
    assert pe[f["lfanew"] : f["lfanew"] + 4] == b"PE\0\0"
    assert f["machine"] == 0xAA64
    assert f["magic"] == 0x20B
    assert f["opt_size"] == 240
    assert f["subsystem"] == 10
    assert f["n_rva"] == 16


def test_entry_point_is_the_elf_entry(w: ModuleType) -> None:
    assert _pe_fields(w.elf_to_pe(_elf(entry=0x1010)))["entry"] == 0x1010


def test_image_is_executable_and_keeps_relocations_unstripped(w: ModuleType) -> None:
    """edk2 loads an image whose relocations are stripped only at its
    ImageBase; without the flag and with no table it loads anywhere."""
    chars = _pe_fields(w.elf_to_pe(_elf()))["chars"]
    assert chars & 0x0002  # IMAGE_FILE_EXECUTABLE_IMAGE
    assert not chars & 0x0001  # IMAGE_FILE_RELOCS_STRIPPED


def test_alignment_and_sizes(w: ModuleType) -> None:
    pe = w.elf_to_pe(_elf())
    f = _pe_fields(pe)
    assert f["sect_align"] == 0x1000
    assert f["file_align"] == 0x200
    assert f["size_of_headers"] == 0x200
    assert f["size_of_image"] == 0x3000
    assert f["image_base"] == 0


def test_every_data_directory_is_empty(w: ModuleType) -> None:
    pe = w.elf_to_pe(_elf())
    f = _pe_fields(pe)
    dirs = pe[f["sections"] - 128 : f["sections"]]
    assert dirs == bytes(128)


# --- sections ------------------------------------------------------------


def test_sections_map_to_their_elf_addresses_and_bytes(w: ModuleType) -> None:
    pe = w.elf_to_pe(_elf())
    secs = _sections(pe)
    assert [s[0] for s in secs] == [".text", ".data"]
    text, data = secs
    assert (text[1], text[2]) == (len(TEXT), 0x1000)
    assert (data[1], data[2]) == (len(DATA), 0x2000)
    assert pe[text[4] : text[4] + len(TEXT)] == TEXT
    assert pe[data[4] : data[4] + len(DATA)] == DATA
    assert text[5] == 0x60000020  # code, execute, read
    assert data[5] == 0xC0000040  # initialized data, read, write


def test_raw_data_is_contiguous_and_file_aligned(w: ModuleType) -> None:
    """sbsign hashes the file in section order and warns on gaps."""
    pe = w.elf_to_pe(_elf())
    secs = _sections(pe)
    assert secs[0][4] == 0x200
    for s in secs:
        assert s[3] % 0x200 == 0 and s[4] % 0x200 == 0
    assert secs[1][4] == secs[0][4] + secs[0][3]
    assert len(pe) == secs[1][4] + secs[1][3]


def test_a_nobits_data_section_becomes_zeros(w: ModuleType) -> None:
    pe = w.elf_to_pe(_elf(data_type=SHT_NOBITS))
    data = _sections(pe)[1]
    assert data[1] == len(DATA)
    assert pe[data[4] : data[4] + len(DATA)] == bytes(len(DATA))


# --- refusals ------------------------------------------------------------


def test_pc_relative_relocations_are_accepted(w: ModuleType) -> None:
    w.elf_to_pe(
        _elf(
            relocs=[
                R_AARCH64_CALL26,
                R_AARCH64_ADR_PREL_PG_HI21,
                R_AARCH64_ADD_ABS_LO12_NC,
            ]
        )
    )


@pytest.mark.parametrize("rtype", [R_AARCH64_ABS64, R_AARCH64_ADR_GOT_PAGE])
def test_a_load_time_relocation_is_refused(w: ModuleType, rtype: int) -> None:
    """An absolute address would point into the link-time layout, not
    the load address, and nothing fixes it up at run time."""
    with pytest.raises(w.ConversionError, match=str(rtype)):
        w.elf_to_pe(_elf(relocs=[R_AARCH64_CALL26, rtype]))


def test_an_unknown_allocated_section_is_refused(w: ModuleType) -> None:
    with pytest.raises(w.ConversionError, match=r"\.got"):
        w.elf_to_pe(_elf(extra=(".got", 0x3000, 16)))


def test_another_machine_is_refused(w: ModuleType) -> None:
    with pytest.raises(w.ConversionError, match="machine"):
        w.elf_to_pe(_elf(machine=EM_X86_64))


def test_a_position_independent_executable_is_refused(w: ModuleType) -> None:
    with pytest.raises(w.ConversionError, match="ET_EXEC"):
        w.elf_to_pe(_elf(etype=ET_DYN))


def test_a_section_below_the_headers_is_refused(w: ModuleType) -> None:
    with pytest.raises(w.ConversionError, match="0x1000"):
        w.elf_to_pe(_elf(text_addr=0x200, entry=0x208))


def test_an_unaligned_section_is_refused(w: ModuleType) -> None:
    with pytest.raises(w.ConversionError, match="align"):
        w.elf_to_pe(_elf(data_addr=0x2100))


def test_an_entry_outside_text_is_refused(w: ModuleType) -> None:
    with pytest.raises(w.ConversionError, match="entry"):
        w.elf_to_pe(_elf(entry=0x2000))


def test_not_an_elf_file_is_refused(w: ModuleType) -> None:
    with pytest.raises(w.ConversionError, match="ELF"):
        w.elf_to_pe(b"MZ" + bytes(126))


# --- command line --------------------------------------------------------


def test_main_writes_the_image(w: ModuleType, tmp_path: Path) -> None:
    src = tmp_path / "p.elf"
    dst = tmp_path / "p.efi"
    src.write_bytes(_elf())
    assert w.main(["n7_elf2pe.py", str(src), str(dst)]) == 0
    assert dst.read_bytes() == w.elf_to_pe(_elf())


def test_main_fails_without_writing_on_a_refusal(
    w: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    src = tmp_path / "p.elf"
    dst = tmp_path / "p.efi"
    src.write_bytes(_elf(relocs=[R_AARCH64_ABS64]))
    assert w.main(["n7_elf2pe.py", str(src), str(dst)]) == 1
    assert not dst.exists()
    assert "257" in capsys.readouterr().err


@pytest.mark.skipif(
    shutil.which("sbsign") is None or shutil.which("sbverify") is None,
    reason="sbsigntool not on this host",
)
def test_sbsign_signs_and_verifies_the_image(w: ModuleType, tmp_path: Path) -> None:
    """The build signs the probe with sbsign; the image must parse."""
    src = tmp_path / "p.efi"
    out = tmp_path / "p.signed.efi"
    src.write_bytes(w.elf_to_pe(_elf()))
    res = subprocess.run(
        [
            "sbsign",
            "--key",
            str(SB_DEV / "db.key.pem"),
            "--cert",
            str(SB_DEV / "db.cert.pem"),
            "--output",
            str(out),
            str(src),
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert res.returncode == 0, res.stdout + res.stderr
    assert "warning" not in (res.stdout + res.stderr).lower()
    res = subprocess.run(
        ["sbverify", "--cert", str(SB_DEV / "db.cert.pem"), str(out)],
        check=False,
        capture_output=True,
        text=True,
    )
    assert res.returncode == 0, res.stdout + res.stderr
