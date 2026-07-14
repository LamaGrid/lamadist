<!-- SPDX-License-Identifier: Apache-2.0 -->
# LamaDist Development Plan

This document is the roadmap for LamaDist, a Yocto/OE distribution
for homelab devices.  It is organized as a ladder of outcome
milestones rather than activity phases: each milestone ends with a
binary, verifiable exit criterion, and every milestone after M0 must
prove itself with a boot or update cycle in QEMU.

This plan is a living document.  Statuses below must track reality;
if a status is wrong, fixing it is part of the current milestone.

---

## Concept of Operations

- **Operator**: A single administrator managing a large number of
  nodes / devices.
- **Operational scenarios**: Unattended home server, NAS, edge
  compute node, or container workload host.  Devices run 24/7 with
  infrequent physical access; remote management is the norm.
- **Workload model**: Containers managed by Podman with Quadlet
  (systemd units).  Cluster orchestration is deferred to future work
  and is out of scope for the current milestones.
- **Quality attribute priorities** (in order):
  1. Security
  2. Reliability
  3. Maintainability
  4. Performance
- **Deployment model**: Images are built on a development workstation
  (or CI runner), then flashed to target hardware (USB installer,
  network install) or deployed via OTA using RAUC.  The target runs
  immutably; host-specific configuration is injected via kernel
  command line parameters and RAUC bundles.  No configuration
  management tooling (Ansible, Puppet, etc.) is required on the
  target.

### Working Constraints

Until lifted, build and test operations are limited to Podman, QEMU,
static analysis, and unit tests.  No physical hardware testing, and
no k3s.  Milestones are sequenced so that everything through M4 is
verifiable entirely in QEMU.

---

## Current State (2026-07-14)

An honest snapshot, so the milestones below start from truth:

- **Build tooling: mature.**  Containerized KAS builds, a full mise
  task suite (build, check, test, vm, stats, lockfile verification),
  lockfiles, linters, commit hooks, and CI on self-hosted runners.
- **Distro configuration: real.**  `lamadist.conf` decomposed into
  includes; SELinux (refpolicy-targeted), IMA/EVM RPM signing, LUKS
  wiring, a dm-verity image class with a custom WKS template for
  x86_64, SPDX and CVE scanning.
- **Image payload: stub.**  One one-line image recipe and a
  packagegroup containing only `haveged`.  The image boots but is not
  usable: no login/network/ssh story, and the default systemd target
  is `graphical.target` with no graphical stack.  Root cause of the
  unusability (verified by boot test, 2026-07-14): the rootfs carries
  no SELinux labels while `/etc/selinux/config` ships enforcing, so
  on the read-only dm-verity root every exec is denied
  (`Cannot execute /bin/sh: Permission denied` at login).
- **OTA updates: not implemented.**  RAUC exists only as an opt-in
  KAS overlay adding the layer.  No system.conf, no bundle recipe, no
  A/B slot layout, no bootloader integration.  The full design lives
  in [ARCHITECTURE.md](ARCHITECTURE.md) and
  [PARTITIONING.md](PARTITIONING.md).
- **BSP parity: x86_64 only.**  `intel.conf` is the only real
  LamaDist machine config.  RK1 and SOQuartz build upstream
  `secure-core-image` instead of the LamaDist image; Orin NX carries
  dm-verity GUIDs in its KAS file with a TODO.
- **Secure boot: disabled.**  meta-efi-secure-boot is commented out
  in `kas/main.kas.yml`.
- **Release engineering: absent.**  Partial CI; no versioning,
  signing infrastructure, or release automation.

---

## Milestones

### M0: Truth Reset

**Status:** In Progress
**Goal:** Every document tells the truth, and the repository is tidy.

- [x] Rewrite this plan as outcome milestones with accurate statuses
- [ ] Update README: split features into "Current" and "Roadmap";
  add the logo
- [ ] Align mise task names in ARCHITECTURE.md and CONTRIBUTING.md
  with TOOLING.md (the canonical task reference)
- [ ] Update the ARCHITECTURE.md layer-tree example to reflect the
  actual multi-machine layout
- [ ] Prune stale remote branches (`copilot/*`, merged refactor
  branches)
- [ ] Add `.gitignore` entries for local editor and shell files

**Exit criteria:**

- Docs agree with each other and with the code
- A reader of README + PLAN cannot mistake planned features for
  shipped ones

### M1: Usable Image

**Status:** Not Started
**Goal:** `lamadist-image-base` boots to a usable login on QEMU
x86_64 and stays that way, enforced by a smoke test.

Definition of usable: login on serial console as an administrator,
network up via systemd-networkd (DHCP), sshd reachable, standard
core utilities present, persistent journal.

#### Boot-test findings (2026-07-14, QEMU x86_64)

Established by booting the built image headlessly and driving the
serial console:

- **Root cause of "boots but unusable"**: the ext4/verity rootfs has
  no `security.selinux` xattrs (no build-time labeling) while the
  image ships `SELINUX=enforcing`.  systemd never transitions out of
  `kernel_t`, module loads and unit starts are AVC-denied, and
  login's exec of `/bin/sh` is denied.  Autorelabel cannot fix a
  read-only dm-verity root.
- The x86_64 KAS target builds `core-image-minimal`, not
  `lamadist-image-base`, so the distro's own image is never
  exercised.
- The CI smoke test (`mise run vm --ci`) greps only for a `login:`
  prompt and PASSES on this broken image.
- Read-only-root fallout: `systemd-remount-fs` and UTMP writes fail;
  there is no writable `/var` strategy yet.
- The ESP is typed "Microsoft basic data" instead of the ESP type
  GUID in the dm-verity WKS layout.
- `DISTRO_VERSION` is stamped from a stale cached GitVersion value
  (wrong branch, months old) via `.cache/gitversion.env`.
- The build hangs after the final image task (~5 tasks remaining,
  idle workers, "Server refused shutdown" repeating in
  `bitbake-cookerdaemon.log`); artifacts deploy but the command
  never exits.
- The builder container image predates the current lockfiles, so
  `container:builder:verify` fails mid-build (non-fatal but noisy).

#### Steps

- [ ] Point the x86_64 KAS target and `DM_VERITY_IMAGE` at
  `lamadist-image-base`
- [ ] Label the rootfs at image-build time (`setfiles` via the
  meta-selinux image class) and disable autorelabel on verity roots
- [ ] Boot SELinux permissive until the policy is triaged; ratchet
  to enforcing in M4
- [ ] Fill out `packagegroup-lamadist-base`: shell and core
  utilities, iproute2, sudo, tzdata, systemd network/resolve config
- [ ] Set `SYSTEMD_DEFAULT_TARGET` to `multi-user.target`
- [ ] Define the administrator account story (default user via
  `extrausers` or systemd first-boot credentials)
- [ ] Read-only-root accommodations: writable `/var` strategy, mask
  `systemd-remount-fs`, handle UTMP
- [ ] Fix the ESP partition type GUID in the WKS template
- [ ] Regenerate GitVersion data on every build (stale
  `.cache/gitversion.env`)
- [ ] Root-cause the end-of-build bitbake hang; rebuild the builder
  image from current lockfiles
- [ ] vm task: add a headless-interactive mode (serial + monitor
  unix sockets in waiting mode, ssh port-forward) so agents and CI
  can drive the console; keep socket paths short (108-char limit)
- [ ] Strengthen the CI smoke test: perform a real login and assert
  command execution, not just a `login:` prompt; wire it to
  `mise run test`

**Exit criteria:**

- QEMU x86_64 boot reaches a working login and ssh session
- `mise run test` passes, and fails on the 2026-07-14 defect classes
  (unlabeled rootfs, exec-denied login)

### M2: Wrynose LTS Migration

**Status:** Not Started
**Goal:** All layers move from `scarthgap` to the Wrynose LTS
release while the feature surface is still small, using the M1 smoke
test as the acceptance gate.

- [ ] Verify every layer in `kas/main.kas.yml`, `kas/bsp/`, and
  `kas/extras/` has a Wrynose (or compatible) branch; BSP layers
  such as meta-tegra historically trail LTS releases and may need
  pinned revisions or a documented exception
- [ ] Update branch pins in all KAS configurations
- [ ] Update `LAYERSERIES_COMPAT` in `meta-lamadist`
- [ ] Apply Yocto migration-guide changes and fix build fallout

**Exit criteria:**

- All layers track Wrynose or a documented compatible revision
- `mise run build --bsp x86_64` and the M1 smoke test pass on
  Wrynose
- No `scarthgap` references remain outside historical documentation

### M3: OTA Update Core

**Status:** Not Started
**Goal:** A/B updates with automatic rollback proven end-to-end in
QEMU.  This is the largest gap between the stated goals and the
code, so it is staged in two passes.

Pass 1 -- plain signed bundles:

- [ ] Implement the split A/B partition layout in WKS (per
  [PARTITIONING.md](PARTITIONING.md))
- [ ] Write `system.conf` slot definitions matching the layout
- [ ] Create the bundle recipe and development signing keys
- [ ] Integrate systemd-boot: slot selection plus a mark-good
  health-check service
- [ ] QEMU test: install, reboot, health check, commit; then a
  forced failure that triggers automatic rollback

Pass 2 -- after pass 1 is green:

- [ ] Adaptive (delta) updates via `casync`
- [ ] CMS-encrypted `crypt` bundles
- [ ] Slot targets on decrypted mapper devices to preserve LUKS
  headers (depends on M4 LUKS work)

**Exit criteria:**

- Full update cycle (install, reboot, health check, commit) and
  forced-failure rollback demonstrated in QEMU
- Update procedure documented

### M4: Security Hardening Ramp

**Status:** Not Started
**Goal:** The security architecture becomes enforced reality on
x86_64, verifiable in QEMU with OVMF and swtpm.

- [ ] dm-verity end-to-end with the root hash embedded in the UKI
- [ ] UKI packaging and direct UEFI boot
- [ ] UEFI Secure Boot with project keys (re-enable
  meta-efi-secure-boot) under OVMF
- [ ] Measured Boot against swtpm; TPM2-sealed LUKS unlocking
- [ ] LUKS2 on data partitions; OverlayFS for `/etc` and
  application data
- [ ] EROFS root filesystem
- [ ] SELinux to enforcing; IMA/EVM appraisal enabled

**Exit criteria:**

- Hardened profile boots in QEMU with Secure Boot, measured boot,
  and enforcing SELinux
- The M3 update cycle still passes on the hardened profile

### M5: Second Platform

**Status:** Not Started
**Goal:** Prove the machine-config pattern ports cleanly to ARM and
restore per-BSP parity.

- [ ] Port the `intel.conf` pattern to RK1 first (closest to
  mainline); create a real machine config in `meta-lamadist`
- [ ] All BSP configs build `lamadist-image-base` (drop the upstream
  `secure-core-image` targets)
- [ ] Move Orin NX dm-verity GUIDs from the KAS file into a machine
  include; decide Orin NX's fate based on meta-tegra's Wrynose
  support
- [ ] Boot smoke test for the ARM image under qemuarm64

Physical flashing and hardware testing remain out of scope until the
working constraints are lifted.

**Exit criteria:**

- RK1 image builds green and the image boots under qemuarm64
- No BSP bypasses the LamaDist image or distro configuration

### M6: Release Engineering

**Status:** Not Started
**Goal:** Repeatable, signed, versioned releases.

- [ ] CI matrix builds (x86_64 + ARM) with boot tests
- [ ] GitVersion-derived semver propagated into `DISTRO_VERSION` and
  artifact names
- [ ] RPM signing infrastructure and key management; signed release
  artifacts
- [ ] SBOM (SPDX 3.0.1) published with artifacts
- [ ] Tag-triggered release workflow with notes generated from
  Conventional Commits
- [ ] CVE monitoring cadence and a security-update SLA

**Exit criteria:**

- One tagged v0.x release from `main` with artifacts, SBOM, and
  generated release notes

---

## Branding

Branding work runs in parallel with the technical milestones and has
no gate of its own.

- [ ] Create a new GitHub organization named `lamadist` to reserve
  the name, configured with the same settings as the LamaGrid
  organization.  Create it now; migrate the repository later.
  (Manual step: GitHub provides no API for organization creation.)
- [ ] Adopt the project mascot: Lama, a samurai wombat (`logo.png`
  and `sticker.png` at the repository root).
- [ ] Use the logo in the README and documentation.
- [ ] Make the CLI more delightful: friendlier output, color,
  progress indication, and helpful errors across the mise task
  suite.

---

## Future Work

Deferred until the milestones above are complete:

- Cluster orchestration for container workloads (tooling TBD)
- Remaining BSPs beyond the reference x86_64 + first ARM board
- Installer images (anaconda-based) and network install workflows
- Ecosystem integration: monitoring, logging, cloud services
- Performance profiling and tuning
- LTS / backport policy and long-term maintenance tracks

---

## History

- **2026-07**: Plan restructured from activity phases into outcome
  milestones.  The prior Phase 0 (architecture documentation and
  tooling baseline) completed in March 2026 and is preserved in git
  history.

---

## Notes

- Each milestone should be completed before moving to the next, but
  some overlap is acceptable
- Milestones may be adjusted based on priorities, resources, and
  community feedback
- Security and quality should never be compromised for speed
