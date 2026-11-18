# ADR 0017: N7 Probe Toolchain Without gnu-efi

## Status

Proposed (2026-11-18).  Records the licence choice for the test-only
N7 write probe.  The probe has built in a local build, and under
QEMU it loaded and ran under U-Boot and under edk2 (AAVMF).  That
probe was built from an earlier revision of the recipe plus an
untracked one-line append, `inherit nospdx`, which the recipe now
holds itself.  No build has yet parsed the recipe as it stands; any
BitBake run over the layer, CI included, parses it.  That it gives the
same binary is read from the diff (no compile input changed), not
shown by a build.

## Context

The N7 write test proves that U-Boot refuses writes to PK, KEK, and db.
Its Part B needs a Unified Extensible Firmware Interface (UEFI)
application that is signed by the db key and runs before
`ExitBootServices`: from Linux, no write reaches U-Boot at all, so only
code that runs before `ExitBootServices` reaches the preseed check in
`lib/efi_loader/efi_variable.c:299-301` (U-Boot v2026.01).  The probe
calls `SetVariable`, `GetVariable`, `LoadImage`, and `StartImage`,
reads its payloads from the EFI system partition (ESP), and prints one
line per result.  It is a test article: it is built on demand and
never goes into an image.

The usual way to build such an application with the GNU toolchain is
gnu-efi.  openembedded-core (wrynose) has it as
`meta/recipes-bsp/gnu-efi/gnu-efi_4.0.4.bb` with
`LICENSE = "GPL-2.0-or-later & BSD-2-Clause"`.  The files that its
`LIC_FILES_CHKSUM` names for the GPL terms include
`gnuefi/crt0-efi-aarch64.S` and `lib/aarch64/initplat.c`, and the
crt0 start-up code links into every application built with it.  No
recipe in this tree uses gnu-efi today.

Licence check (the license-compliance procedure): the repository has
no native licence scanner for this case, so the manual audit applies.
The expression is conjunctive, so the stricter part governs, and
`-or-later` escalates to the strictest version a recipient may choose.
That puts gnu-efi in the class that needs the owner's explicit
confirmation before it is added.  Under the owner's copyleft policy
(ADR 0001), GPL-2 build tooling also needs a brief options analysis and
a short ADR; this is that ADR.

## Decision

Build the probe freestanding, with no gnu-efi:

- `n7-probe.c` declares only the UEFI tables, protocols, and constants
  it calls, checked against the specification's offsets by
  `_Static_assert`, and is compiled with `-ffreestanding -nostdlib`, so
  nothing from a C library or `libgcc` is linked in.
- A linker script lays out one code section and one data section at
  their final relative virtual addresses.  The link keeps its
  relocations (`--emit-relocs`).
- `n7_elf2pe.py`, a standard-library Python script in the recipe,
  writes the Portable Executable (PE) file from the Executable and
  Linkable Format (ELF) output.  It refuses any relocation that would
  need a load-time fix, so the probe runs at any load address with no
  base relocation table and no self-relocation code.
- `sbsigntool-native` (ADR 0003) signs the probe with the public
  development db key and a second copy with the development KEK key,
  both from `meta-lamadist/files/sb-dev/`.

## Alternatives considered

- gnu-efi from openembedded-core: a known build path (start-up code,
  linker script, and self-relocation), and no UEFI declarations of our
  own.  It adds a new build dependency and links GPL-2.0-or-later code
  into the probe.  The probe never ships, so the copyleft terms would
  bind only a copy that is given to someone else, but the dependency
  still needs the owner's confirmation and a deeper review than this
  test article justifies.  Not adopted.
- `objcopy --target=efi-app-aarch64` from binutils in place of the
  Python writer: no conversion code of our own.  It handles no
  relocations either, and the PE layout it writes depends on the
  linker script in ways that a host unit test cannot pin, because an
  x86_64 host objcopy has no aarch64 EFI target.  Not adopted;
  it stays the fallback if the Python writer fails in the build.
- `UpdateVars.efi` from meta-efi-secure-boot's efitools: that layer is
  not enabled (`kas/main.kas.yml` keeps it commented out), and the
  tool is built with gnu-efi anyway.  Not adopted.

## Consequences

- No new third-party dependency and no copyleft code in the probe
  binary.  The probe source, the linker script, and the PE writer are
  Apache-2.0.  The build uses tools the tree already uses: the cross
  GCC and binutils that build every target recipe, and
  `sbsigntool-native` under ADR 0003.  GCC's runtime library is not
  linked (`-nostdlib`), so its runtime exception is not needed.
- The project carries its own UEFI declarations and PE writer, about
  450 lines that gnu-efi would have supplied.  The unit tests pin the
  PE headers, the section table, and the relocation guard on a
  synthetic ELF file, and accept the result through `sbsign` where the
  host has it.  They cannot show that U-Boot and edk2 load the real
  probe; the QEMU runs in the Status show that.  A layout fault shows
  as a load failure, never a false pass, because the verdict needs
  every probe row.
- The probe recipe is skipped unless `kas/extras/n7-probe.kas.yml` is
  in the build, has no packages, and deploys no binary; a layer test
  keeps it out of every image and packagegroup.
