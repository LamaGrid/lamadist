# ADR 0016: U-Boot EFI Variable Seed Generator

## Status

Proposed (2026-11-15).  Closes the generator question that ADR 0013
decision 3 left to the kill-switch spike.  Pending the build checks
in the Consequences.

## Context

ADR 0013 decision 3 has the U-Boot boards enforce Secure Boot from a
preseed: `CONFIG_EFI_VARIABLES_PRESEED` embeds a variable store in the
U-Boot binary, and once it holds a PK, U-Boot refuses every runtime
write to PK, KEK, db, and dbx (`lib/efi_loader/efi_variable.c`,
`efi_set_variable_int()`, v2026.01).  The seed must come from the same
PK/KEK/db the x86_64 gate enrolls, and it is never a checked-in
binary.  The ADR named two generators: U-Boot's in-tree
`tools/efivar.py` (GPL-2.0-only build tooling, so the copyleft policy
of ADR 0001 asks for this analysis) or a dump from a U-Boot run.

How U-Boot consumes the seed (v2026.01):

- `lib/efi_loader/Kconfig`: `EFI_VARIABLES_PRESEED` and
  `EFI_VAR_SEED_FILE`, a file "in the same format as the storage in
  the EFI system partition" (`ubootefi.var`).
- `lib/efi_loader/efi_var_seed.S`: `.incbin CONFIG_EFI_VAR_SEED_FILE`
  into `.rodata.efi_seed.init`.  `lib/efi_loader/Makefile` makes the
  object depend on `$(srctree)/$(EFI_VAR_SEED_FILE)`, so the path must
  be relative to the source tree (an absolute path breaks the
  prerequisite).
- `efi_init_variables()` calls `efi_var_restore(seed, safe=true)`;
  `efi_var_restore()` (`efi_var_file.c`) checks the header (reserved
  0, magic, CRC-32 of the body) and inserts each entry, skipping
  zero-length ones.  Layout: `include/efi_variable.h`.
- PK, KEK, and db are stored as raw EFI Signature Lists with
  `NV|BS|RT|TIME_BASED_AUTH` attributes (`efivar.py` sets the same, and
  `efi_set_variable_int()` rejects these variables without the
  time-based bit).  A PK present means User Mode
  (`efi_init_secure_state()`); an absent or empty PK means Setup Mode,
  where Secure Boot enforces nothing.

## Decision

Generate the seed with a small project-owned generator,
`meta-lamadist/lib/lamadist/efivarseed.py` (Apache-2.0, standard
library only), driven by `classes/lamadist-efi-var-seed.bbclass`.  The
class writes `${S}/lamadist-efivars.seed` between `do_patch` and
`do_configure` from `files/sb-dev/{pk,kek,db}.esl` and deploys a copy
beside the bootloader image.  The u-boot bbappend of a machine leaf
inherits the class; it is the only place that names the seed.

## Alternatives considered

- **U-Boot `tools/efivar.py`** (GPL-2.0-only; a standalone CLI, so no
  GPL code is linked into or shipped with our output, but the
  copyleft policy still asks for this analysis).  Not adopted:
  - it stamps `time.time()` into each time-based entry, so two builds
    of the same keys give different seeds and the build is not
    reproducible;
  - it imports `OpenSSL.crypto` at the top of the file for its `sign`
    command, which `set` never uses, adding a pyOpenSSL native
    dependency;
  - it is not installed by oe-core's `u-boot-tools` recipes, so using
    it means a second fetch of the U-Boot source (or a patch to carry
    it) in a native recipe, tied to the U-Boot version.
  Our generator is byte-identical to `efivar.py set` for the same
  three ESLs once `efivar.py`'s timestamps are zeroed (checked once by
  hand against the v2026.01 file).
- **A dump from a U-Boot run**: needs a built, booted U-Boot to build
  U-Boot, and the dump carries run-time state.  Not hermetic.  Rejected.
- **`virt-fw-vars`** (already a GPL-2.0-only build dependency, ADR
  0004): it edits edk2 varstores.  Whether it can write the
  `ubootefi.var` layout was not checked; the generator above is
  smaller than the check.

This differs from the ESL packer ADR 0005 rejected: the generator does
not build Signature Lists.  It frames the existing `.esl` files, which
`cert-to-efi-sig-list` still produces, in a three-field store whose
layout is fixed by the two U-Boot files above and covered by a test
that walks the output the way `efi_var_restore()` does.

## Consequences

- No new copyleft dependency; nothing from U-Boot's tree is copied.
  The seed is compiled into U-Boot, which is GPL-2.0-or-later on its
  own terms.
- The seed is reproducible (time 0, no clock) and never tracked;
  `tests/layer` fails if a seed or an unlisted private key appears in
  the layer.
- The seed carries the dev key chain until M6 supplies production
  keys; the class reads the `.esl` paths from variables, so M6
  overrides them without editing the class.
- Format drift: a U-Boot bump that changes the store layout is caught
  by build check 1 below, not by the unit tests.  Build checks owed:
  1. Dump the deployed seed with U-Boot's `efivar.py print` (or boot
     U-Boot under QEMU and run `printenv -e`) and confirm PK, KEK, and
     db with attributes 0x27.
  2. Confirm `.incbin` finds the seed in an out-of-tree (`O=`) build
     with a source-relative `CONFIG_EFI_VAR_SEED_FILE`.  If it does
     not, the bbappend also copies the seed into `${B}`.
  3. Boot a QEMU U-Boot with the seed: `SecureBoot` is 1,
     `SetupMode` is 0, a db-signed UKI boots, and an unsigned one is
     refused.
