# ADR 0005: efitools License

## Status

Accepted

## Context

M4 stage B (D6, W8) generates the LamaDist Secure Boot
DEVELOPMENT-ONLY PK/KEK/db key chain in
`meta-lamadist/files/sb-dev/`.  `regen-dev-sb-keys.sh` writes each
key as a PEM pair, a DER cert, and an EFI Signature List (ESL); the
ESL form is built by shelling out to `cert-to-efi-sig-list`, which
comes from the `efitools` package.  `efitools` was added to
`container/packages.txt` / `container/packages.lock`
(`efitools=1.9.2-1ubuntu3`) as a build-container apt dependency for
this one call.  Debian/Ubuntu's `efitools` packaging mixes
GPL-2-only and GPL-3-or-later source files -- a copyleft license.
Per our license policy (ADR 0001), copyleft build/test tooling is
allowed but calls for a brief alternatives-and-obligations analysis
plus a short ADR, and notification is required for any copyleft
component, the same shape of finding as ADR 0003
(`sbsigntool-native`) and ADR 0004 (`virt-firmware`).

## Decision

Depend on `efitools` as a build-container-only apt package
(`container/packages.txt`), used solely for `cert-to-efi-sig-list`
in `regen-dev-sb-keys.sh` to produce the `.esl` form of each sb-dev
cert.

## Alternatives considered

- `virt-fw-sigdb` (part of the `virt-firmware` PyPI package already
  depended on per ADR 0004, also GPL-2.0-only): its
  `--add-cert GUID FILE -o out.esl` mode builds the same
  EFI_SIGNATURE_LIST container format as `cert-to-efi-sig-list` and
  would avoid introducing a second copyleft build dependency for
  this one call.  Not adopted here: `regen-dev-sb-keys.sh` is a
  POSIX `sh` script that otherwise only shells out to the `openssl`
  CLI; routing ESL generation through a Python entry point tested
  and documented primarily for its own vars-file/sigdb workflows
  (`.mise/tasks/ovmf-vars`) adds an interpreter/pip coupling to a
  key-regeneration script for no license benefit -- the dependency
  is GPL-2.0-only either way.  Left as a future simplification if
  the `efitools` dependency needs to be dropped for a reason other
  than license.
- Hand-rolled EFI_SIGNATURE_LIST packer (openssl + a minimal
  container-format writer): removes the copyleft dependency
  entirely, but reimplements a security-critical, easy-to-get-
  subtly-wrong binary format (the same UEFI signature-list
  structure ADR 0004 already rejected hand-rolling for vars
  enrollment) in project code -- a worse risk than a
  build-time-only copyleft tool.  Rejected.

## Consequences

- `efitools` runs only inside the build container, invoked by
  `regen-dev-sb-keys.sh` when the sb-dev key chain is regenerated
  (a manual, infrequent operation, not part of `bitbake` or
  `mise run test`); its binaries are never installed into, packaged
  for, or shipped on the target image.  The GPL-2/GPL-3 terms attach
  to the `efitools` binaries themselves, not to the `.esl` files
  they generate as output (the ESLs are committed alongside the PEM/
  DER forms as public, DEVELOPMENT-ONLY key material, the same as
  the RAUC dev CA), so no source-disclosure obligation extends to
  LamaDist's own image content.
- Because `efitools` is an apt package (`container/packages.txt`/
  `container/packages.lock`), not a BitBake recipe, it is outside
  the Yocto license-manifest/SPDX SBOM machinery that covers ADR
  0002 and ADR 0003's target/native recipes; its own upstream
  source and license text remain available via Debian/Ubuntu's
  archive, satisfying GPL-2/GPL-3's source-availability terms for
  the unmodified package.
- This dependency is stage-B-only dev-key tooling; it has no effect
  on the stage-A gate and is not invoked by any automated build or
  test task.
- Flagged to Lucas per the copyleft policy's notify-on-any-copyleft
  rule; this ADR is that sign-off request, pending explicit
  confirmation.
