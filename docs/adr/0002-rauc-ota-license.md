# ADR 0002: RAUC OTA License

## Status

Accepted

## Context

LamaDist needs an A/B OTA update client for a Yocto immutable,
dm-verity-backed image.  RAUC (`ext/meta-rauc`, recipe pinned via
`rauc_1.15.1.bb` -> `rauc.inc`) declares
`LICENSE = "LGPL-2.1-or-later"`, verified against the 1.15.1
checkout.  RAUC ships unmodified into the target image, not
just as build tooling, so it is a core, copyleft component and our
license policy (see ADR 0001) requires a brief alternatives analysis
plus a short ADR before shipping it.

## Decision

Ship RAUC as the core OTA update client, unmodified from upstream
sources, under LGPL-2.1-or-later.

## Alternatives considered

- SWUpdate: GPL-2.0-only core.  Stronger copyleft than RAUC's LGPL,
  and its A/B slot model is less turnkey for dm-verity block
  devices than RAUC's bundle/slot abstraction.  Rejected.
- Mender: Apache-2.0 client, so license-wise the cleanest option.
  But the client is tightly coupled to the Mender server/hosted
  ecosystem for practical use, and its Yocto layer is built around
  that ecosystem rather than a standalone updater.  Adopting it
  trades a license concern for an ecosystem-lock-in concern.
  Rejected.
- systemd-sysupdate: LGPL-2.1-or-later, same family as RAUC, and
  already present since we ship systemd.  However, its A/B
  bootloader-integration story is immature relative to RAUC's, which
  has years of production use with U-Boot/GRUB A/B setups.  Rejected
  for now; worth revisiting as it matures.
- OSTree: LGPL-2.0-or-later.  Image-based, content-addressed
  checkout model is a poor fit for raw dm-verity block devices,
  which RAUC targets natively via its slot/bundle model.  Rejected.

Every realistic candidate is either copyleft or ecosystem-coupled;
none is a plain permissive, standalone fit.  RAUC's LGPL-2.1 is the
best match: dynamic-link-library-style obligations attach to RAUC
itself, not to code that merely links or talks to it (D-Bus, CLI),
and we ship it unmodified, so there is no source-disclosure
obligation beyond upstream's own.

## Consequences

- LGPL-2.1-or-later is confined to the RAUC binary and its libraries;
  application code that talks to RAUC via D-Bus or its CLI is
  unaffected.
- Source-availability obligations are satisfied by Yocto's existing
  license-compliance machinery: `LIC_FILES_CHKSUM` pins the upstream
  `COPYING` text, the standard per-image license manifest records
  RAUC's license and recipe, and we already `INHERIT +=
  'create-spdx'` (`meta-lamadist/conf/distro/include/
  lamadist-security.inc`), so the SPDX SBOM lists RAUC's license and
  source coordinates.  No additional archiver step is required
  because we vendor and build from unmodified upstream sources.
- If a permissive, standalone A/B updater with mature dm-verity
  bootloader integration emerges (e.g. systemd-sysupdate maturing),
  RAUC can be revisited without changing the image's license
  posture materially, since it is already the least-restrictive
  realistic option.
