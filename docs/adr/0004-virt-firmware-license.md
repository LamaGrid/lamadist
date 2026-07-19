# ADR 0004: virt-firmware License

## Status

Accepted

## Context

M4 stage B (D6, W10) builds a pre-enrolled OVMF vars artifact
(`ovmf-vars-enrolled.fd`) so `.mise/tasks/vm --secureboot` can boot
QEMU with PK/KEK/db already enrolled and Secure Boot on.  The only
tool that can enroll certificates into an existing edk2 varstore
in place is `virt-fw-vars` from the `virt-firmware` PyPI package,
added as a build-container Python dependency in
`container/pyproject.toml` and invoked by the new
`.mise/tasks/ovmf-vars` task.  The published wheel
(virt_firmware-26.7.1) carries
`# SPDX-License-Identifier: GPL-2.0-only` in its own source
(`virt/firmware/vars.py`) and its PyPI METADATA declares
`License: GPLv2` -- a copyleft license.  Per our license policy
(ADR 0001), copyleft build/test tooling is allowed but calls for a
brief alternatives-and-obligations analysis plus a short ADR, and
notification is required for any copyleft component, the same
shape of finding as ADR 0003 for `sbsigntool-native`.

## Decision

Depend on `virt-firmware` as a build-container-only Python
dependency (`container/pyproject.toml`) to enroll PK/KEK/db and
enable SecureBoot in the OVMF vars artifact used by
`.mise/tasks/ovmf-vars` / `vm --secureboot`.

## Alternatives considered

- Hand-rolled UEFI variable authenticated-payload construction
  (openssl + a minimal EFI_SIGNATURE_LIST/EFI_VARIABLE_AUTHENTICATION_2
  packer): removes the GPL-2.0 dependency entirely, but reimplements
  a security-critical, easy-to-get-subtly-wrong binary format (UEFI
  authenticated variable enrollment) in project code -- a worse risk
  than a build-time-only copyleft tool, and the exact failure mode
  ADR 0003 already rejected for PE signing.  Rejected.
- `efitools` (`efi-updatevar`/`sign-efi-sig-list`, GPL-2/GPL-3 mixed):
  operates on a *running* UEFI system's variable store via
  `efivarfs`, not an offline OVMF vars template file on the build
  host: there is no running UEFI system at build time to target, so
  it cannot produce an offline-enrolled `OVMF_VARS.fd`.  Not a
  substitute for this use case.  Rejected.
- `qemu`'s own `-fw_cfg`-based enrollment or an EDK2 build-time
  enrollment (`edk2-ovmf` with baked-in default keys): requires
  building edk2 in-tree, which HARD RULE 6 (no in-tree OVMF build)
  precludes; also loses the "always fresh from the pristine host
  template" idempotency the current design relies on.  Rejected.

No permissive, standalone tool exists for enrolling PK/KEK/db into
an offline edk2 varstore file; `virt-firmware` is the de facto
tool for this exact job (used upstream by libvirt/virt-manager
tooling for the same purpose).

## Consequences

- `virt-firmware` runs only inside the build container, invoked by
  `.mise/tasks/ovmf-vars` on the host-copied `OVMF_VARS.fd` template;
  it is never installed into, packaged for, or shipped on the target
  image, and it produces a QEMU test-only deploy artifact
  (`ovmf-vars-enrolled.fd`), not image content.  GPL-2.0-only's
  copyleft terms attach to the `virt-firmware` package itself, not
  to the vars file it modifies (the enrolled output is not a
  derivative work of the tool), so no source-disclosure obligation
  extends to LamaDist's own image content.
- Because `virt-firmware` is a build-container Python dependency
  (`container/pyproject.toml`/`container/requirements.txt`), not a
  BitBake recipe, it is outside the Yocto license-manifest/SPDX SBOM
  machinery that covers ADR 0002 and ADR 0003's target/native
  recipes; its own upstream source and license text remain available
  from PyPI, satisfying GPL-2.0's source-availability terms for the
  unmodified tool.
- This dependency is stage-B-only test infrastructure (M4.A does not
  invoke `ovmf-vars`); it has no effect on the stage-A gate.
- Flagged to Lucas per the copyleft policy's notify-on-any-copyleft
  rule; this ADR is that sign-off request, pending explicit
  confirmation.
