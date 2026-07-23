# ADR 0007: Secure Boot Chain and Key Enrollment

## Status

Accepted

## Context

The installer must leave the target booting with Secure Boot
enforcing under a chain the project controls, and must get its
keys into real firmware without vendor tooling.  The current M4
chain is shimless: custom PK/KEK/db (meta-lamadist/files/sb-dev/)
with directly-signed systemd-boot and UKIs.  Full analysis:
docs/installer/AOA-SIGNING.md, reviewed through two Fable
security-review rounds; this was the pass's designated
riskiest fork.

## Decision

Keep the custom PK/KEK/db chain.  Enrollment is performed by the
SIGNED INSTALLER USERLAND as the primary mechanism ("B2"): the
initramfs reads `SetupMode`/`SecureBoot`, validates the manifest
first, owns the interactive confirmation, and writes the
`.auth` variable updates directly via efivarfs (`chattr -i`,
then write) -- no external enrollment binary ships.  The signed
UKI carries the expected PK/KEK/db digests; after enrollment and
before any disk enumeration the installer asserts `SecureBoot=1`
and that live variable contents match ("trust verification
gate").  sd-boot's `secure-boot-enroll` ("B1") is demoted to an
explicitly-chosen fleet variant, NOT built this pass.  `.auth`
files (PK self-signed, KEK signed by PK, db signed by KEK) are
generated at build time by extending regen-dev-sb-keys.sh with
efitools' sign-efi-sig-list (build-host-only).  The DEPLOYED
image's loader.conf ships without any enrollment directive and
without a `\loader\keys\` payload.

## Alternatives considered

- Shim + MOK (mokutil): its sole advantage -- booting unenrolled
  on stock Microsoft-key firmware -- requires a Microsoft-signed
  shim obtainable only through the rhboot shim-review process
  (months, legal entity, SBAT/lockdown burden); MOK enrollment
  is interactive by design (defeats headless); not exercisable
  in the QEMU harness; adds mokutil (GPL-2.0) to the image and a
  proprietary third-party signing dependency.  Rejected.
- sd-boot secure-boot-enroll as PRIMARY: `force` auto-enrolls
  interactive installs and any Setup-Mode bystander machine;
  `if-safe` auto-enrolls only in VMs, so the QEMU gate would go
  green while real hardware never enrolls; enrollment would
  precede manifest validation and the trust gate.  Demoted to
  fleet variant.
- sbctl-managed keys: trust-identical to the decision but adds a
  new Go binary for ergonomics the tree already covers.  Rejected
  now; possible future operator-UX layer.

## Consequences

- The first installer boot requires the target in Setup Mode (or
  keys already enrolled); "Secure Boot disabled" halts
  fail-closed with instructions -- an install can never complete
  SB-off.
- Custody/TOFU precondition recorded in SECURITY.md: whoever
  boots first in Setup Mode owns the trust root; stick and
  target custody during that window is a stated precondition;
  the in-UKI digest gate detects wrong-chain enrollment but not
  a fully attacker-controlled first boot.
- Enrollment touches only EFI variables (PK/KEK/db, never dbx --
  avoiding the one irreversible-on-some-firmware variable) and
  runs before any block-device access.
- Remote mis-enrollment is operationally sharp (firmware-menu
  recovery); mitigated by the project holding all private keys.
  Production key custody is M6 scope; the in-tree sb-dev keys
  remain dev-only with zero real-world authenticity.
- The QEMU stage-2 harness gains blank-vars Setup-Mode, SB-off,
  wrong-PK, and tampered-`.auth` cases.
- No new shipped license exposure; efitools (ADR 0005) stays
  build-host-only.
