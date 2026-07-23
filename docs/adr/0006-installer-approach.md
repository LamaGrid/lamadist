# ADR 0006: Installer Approach -- Signed-UKI Initramfs

## Status

Accepted

## Context

The Installer Pass (docs/installer/SPEC.md) needs a build
definition for a single installer USB whose user flow is minimal,
fail-closed, and verifiable under QEMU+OVMF with Secure Boot
enforcing.  Full analysis: docs/installer/AOA-INSTALLER.md,
reviewed through two Fable security-review rounds.

## Decision

Build a purpose-built installer userland inside the initramfs of
ONE Secure-Boot-signed UKI, extending the existing
lamadist-uki.bbclass and initramfs-framework machinery, plus a
three-partition stick wic layout (ESP / PUBLIC / VAULT).  The
installer module set includes `manifest-parse`, a named, reviewed
strict KEY=VALUE reader, as an in-repo security-boundary
component.  Retire the untested meta-anaconda scaffold
(kas/installer.kas.yml); keep oe-core's init-install-efi.sh and
meta-intel's image-installer.wks.in as references only.

## Alternatives considered

- meta-anaconda: heavyweight dependency set, kickstart model that
  fights the SPEC's three-input flow, SELinux friction (the
  scaffold already stripped it with a TODO), and a UI stack that
  cannot ride inside one signed UKI.  Rejected.
- meta-intel image installer: a wks + init-install-efi.sh shell
  flow; closest in spirit but tied to meta-intel's layout, no
  vault/manifest concepts, and would be forked-and-rewritten
  anyway.  Rejected as a base, kept as reference.
- Purpose-built signed-UKI initramfs: only option where one
  Secure Boot signature covers the entire installer environment
  with no second rootfs to protect.  Accepted.

## Consequences

- Size: userland ~27 MB installed (busybox, glibc, cryptsetup,
  util-linux, tpm2-tss + systemd-cryptenroll for install-time
  TPM2 enrollment, e2fsprogs for the /var seed, setfiles +
  file_contexts for install-time SELinux labeling), ~11-13 MB
  compressed, signed UKI ~25-30 MB -- within FAT32 ESP margins.
- The fail-closed disk-selection/confirm logic is in-repo shell
  and is security-critical; it is gated by the SPEC section 8
  abort matrix and was scoped in the Fable review.
- The installer initramfs runs unlabeled (no SELinux); its sole
  protection is the UKI signature.  Recorded in the SECURITY.md
  installer extension.
- License posture: weak-copyleft or permissive only.  New
  in-image tooling: policycoreutils/setfiles (GPL-2.0),
  e2fsprogs (GPL-2.0 tools, LGPL libs), tpm2-tss (BSD-2-Clause),
  dialog avoided (busybox prompts suffice).  GPL-3 tools
  (dosfstools, mtools, bmap-writer, efitools' efi-updatevar) are
  deliberately excluded from the shipped image; the PUBLIC log
  append uses the kernel vfat write path and the payload write
  uses busybox dd + sha256sum.
- Any addition of a Python tool, full systemd, or further stacks
  to the initramfs changes the size/license calculus and needs a
  fresh note against this ADR.
