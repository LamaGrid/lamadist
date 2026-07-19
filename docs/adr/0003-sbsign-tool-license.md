# ADR 0003: sbsigntool-native License

## Status

Accepted

## Context

M4 stage B (D6) signs the sd-boot loader and the two per-slot UKIs
for Secure Boot using project dev keys.  Both
`meta-lamadist/recipes-bsp/systemd-boot/systemd-boot_%.bbappend`
(loader signing) and `meta-lamadist/classes/lamadist-uki.bbclass`
(UKI signing, via ukify's inferred `sbsign` tool invocation) declare
`DEPENDS += "sbsigntool-native"`.  This recipe comes from
`ext/meta-secure-core/meta-signing-key/recipes-devtools/sbsigntool/
sbsigntool_0.9.5.bb`, whose `LICENSE = "GPL-3.0-or-later"` -- a
strong copyleft license.  Per our license policy (ADR 0001), tools
under GPL-3.0-or-later are allowed but call for a brief
alternatives-and-obligations analysis plus a short ADR, and for
security-owner sign-off before landing, the same as ADR 0002 for
RAUC.

## Decision

Depend on `sbsigntool-native` as a native (build-host-only) BitBake
dependency to sign `systemd-bootx64.efi` and the two per-slot UKIs.

## Alternatives considered

- `pesign`: Red Hat's PE-signing tool.  Also GPL-licensed (GPL-2.0)
  and considerably less commonly paired with systemd-boot/ukify
  workflows upstream; no meta-layer in this stack already vendors
  it.  No license advantage over sbsigntool, and worse ecosystem
  fit.  Rejected.
- `systemd-sbsign` / `systemd-measure` (built into systemd itself,
  LGPL-2.1-or-later): covers UKI measurement, not PE signing in the
  form ukify's `--secureboot-private-key`/`--secureboot-certificate`
  flags expect on this systemd version; ukify's own tool-inference
  (`src/ukify/ukify.py`) selects `sbsign` when both are given, and
  there is no config knob in 259.5 to redirect that to a systemd
  built-in.  Not a drop-in substitute today.  Rejected for now.
- Hand-rolled PE signing (openssl + a minimal PE-authenticode
  script): removes the GPL-3.0 dependency entirely, but reimplements
  a security-critical, easy-to-get-subtly-wrong file format (PE/COFF
  Authenticode) in project code, which is a worse risk than a
  build-time-only copyleft tool.  Rejected.

## Consequences

- `sbsigntool-native` is a `-native` BitBake recipe: it runs only on
  the build host during `do_install`/`do_deploy`/the UKI-build
  prefunc, and its binary is never installed into, packaged for, or
  shipped on the target image.  GPL-3.0-or-later's copyleft terms
  attach to the `sbsign` binary itself, not to the PE files it signs
  (signing output is not a derivative work of the signing tool), so
  no source-disclosure obligation extends to LamaDist's own image
  content.
- Source-availability obligations are satisfied the same way as
  RAUC's (ADR 0002): Yocto's license-manifest machinery records the
  recipe and its license, and `create-spdx`
  (`lamadist-security.inc`) includes it in the SBOM alongside every
  other native/target recipe.
- Because this is dev-key tooling for stage B only (M4.A ships
  unsigned), this dependency has no effect on the stage-A gate; it
  activates once `UKI_SB_KEY`/`UKI_SB_CERT` are non-empty.
- Flagged to Lucas per the copyleft policy's ask-before-adding rule
  for strong-copyleft components; this ADR is that sign-off request,
  pending explicit confirmation.
