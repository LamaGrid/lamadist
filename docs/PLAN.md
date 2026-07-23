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
  (systemd units).  Optional, off-by-default feature overlays add
  k3s cluster orchestration, an OpenTelemetry collector, and (on
  x86_64) AWS IoT Greengrass (M7/M8).
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
no k3s in CI or test infrastructure (k3s as an optional image
feature is in scope; see M7).  Milestones are sequenced so that
everything through M4 is verifiable entirely in QEMU.

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

**Status:** In Progress (2026-07-14: all steps complete and verified
by an adversarial doc-review pass, except the remote branch prune,
which is blocked on the standing no-push rule)
**Goal:** Every document tells the truth, and the repository is tidy.

- [x] Rewrite this plan as outcome milestones with accurate statuses
- [x] Update README: split features into "Current" and "Roadmap";
  add the logo
- [x] Align mise task names in ARCHITECTURE.md and CONTRIBUTING.md
  with TOOLING.md (the canonical task reference)
- [x] Update the ARCHITECTURE.md layer-tree example to reflect the
  actual multi-machine layout
- [x] Align ARCHITECTURE.md with reality: mark unimplemented
  subsystems as planned (Secure Boot, UKI, EROFS, TPM sealing,
  RAUC), fix compression/SPDX/machine facts, and replace k3s with
  the agreed Podman + Quadlet workload model
- [ ] Prune stale remote branches (`copilot/*`, merged refactor
  branches).  BLOCKED on the standing no-push rule: the local
  counterparts were pruned 2026-07-14 after verifying (by patch-id)
  that every commit is merged or superseded, but deleting remote
  branches requires a push.  The `dependabot/*` branches belong to
  open PRs that the deps-update commit on this branch supersedes;
  close those PRs when it lands.
- [x] Add `.gitignore` entries for local editor and shell files

**Exit criteria:**

- Docs agree with each other and with the code
- A reader of README + PLAN cannot mistake planned features for
  shipped ones

### M1: Usable Image

**Status:** Complete (2026-07-15: the QEMU login smoke passes on
`feat/m1-usable-image` -- serial login as `lama`, command
execution, PID 1 in `init_t`, sshd on :22.  The 2026-07-14 storage
failure was resolved by an `xfs_repair`; the verification run
surfaced and fixed three more defects: the `EXTRA_USERS_PARAMS`
password hash needs `\$` escapes (useradd_base double-evals),
`passwd-expire` cannot work on the read-only root (dropped until
persistent credential state exists), and `ss` ships in
`iproute2-ss` under `/usr/sbin`.  The end-of-build bitbake hang
did not reproduce across four post-repair builds; it was most
likely another symptom of the failing filesystem.)
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

- [x] Point the x86_64 KAS target and `DM_VERITY_IMAGE` at
  `lamadist-image-base`
- [x] Label the rootfs at image-build time (`setfiles` via the
  meta-selinux image class) and disable autorelabel on verity roots
- [x] Boot SELinux permissive until the policy is triaged; ratchet
  to enforcing in M4
- [x] Fill out `packagegroup-lamadist-base`: shell and core
  utilities, iproute2, sudo, tzdata, systemd network/resolve config
- [x] Set `SYSTEMD_DEFAULT_TARGET` to `multi-user.target`
- [x] Define the administrator account story (default user via
  `extrausers` or systemd first-boot credentials)
- [x] Read-only-root accommodations: writable `/var` strategy, mask
  `systemd-remount-fs`, handle UTMP
- [x] Fix the ESP partition type GUID in the WKS template
- [x] Reconcile the x86-64 root-verity partition UUID between docs
  and code.  Resolved 2026-07-14 against the DPS spec: the code
  (`intel.conf`, `2c7357ed-…`) was correct; the docs wrongly used
  the *usr*-verity UUID (`77ff5f63-…`) and are fixed
- [x] Regenerate GitVersion data on every build (stale
  `.cache/gitversion.env`)
- [x] Root-cause the end-of-build bitbake hang; rebuild the builder
  image from current lockfiles
- [x] vm task: add a headless-interactive mode (serial + monitor
  unix sockets in waiting mode, ssh port-forward) so agents and CI
  can drive the console; keep socket paths short (108-char limit)
- [x] Strengthen the CI smoke test: perform a real login and assert
  command execution, not just a `login:` prompt; wire it to
  `mise run test`

**Exit criteria:**

- QEMU x86_64 boot reaches a working login and ssh session
- `mise run test` passes, and fails on the 2026-07-14 defect classes
  (unlabeled rootfs, exec-denied login)

### M2: Wrynose LTS Migration

**Status:** Complete (2026-07-15: all layers on Wrynose, x86_64
build green, M1 QEMU login smoke passes on the Wrynose image)
**Goal:** All layers move from `scarthgap` to the Wrynose LTS
release while the feature surface is still small, using the M1 smoke
test as the acceptance gate.

- [x] Verify every layer in `kas/main.kas.yml`, `kas/bsp/`, and
  `kas/extras/` has a Wrynose (or compatible) branch.  Verified
  2026-07-15: all layers have wrynose branches (including
  meta-tegra) except meta-anaconda (whinlatter pin, documented
  exception in installer.kas.yml) and poky, which is no longer
  branched at all since whinlatter -- replaced by separate
  openembedded-core + bitbake 2.18 repos per upstream guidance
- [x] Include the optional-feature layers in the Wrynose check:
  meta-virtualization and meta-aws both have wrynose branches;
  `kas/extras/aws.yml` is now pinned
- [x] Update branch pins in all KAS configurations
- [x] Update `LAYERSERIES_COMPAT` in `meta-lamadist`
- [x] Apply Yocto migration-guide changes and fix build fallout.
  ostree (`meta-oe/recipes-extended/ostree`) previously failed to
  parse under bitbake 2.18's pysh shell lexer
  (`bb.pysh.pyshlex.NeedMore`).  Verified root cause:
  `FULL_OPTIMIZATION` referenced the undefined `${DEBUG_FLAGS}`
  (renamed upstream to `DEBUG_LEVELFLAG`).  BitBake leaves undefined
  `${VAR}` references unexpanded, so the literal text flowed into
  ostree's `EXTRA_OECONF` and left raw, unevaluated Python source
  (with Python-style quote escaping) in the shell body of
  `oe_runconf`; pysh's lexer then hit EOF still inside an
  unterminated single quote (`_parse_squote`) and raised
  `NeedMore`.  This is a content-dependent parse failure, not a
  Python-runtime-version issue.  Fixing `FULL_OPTIMIZATION` to use
  `${DEBUG_LEVELFLAG}` (see
  `meta-lamadist/conf/distro/include/lamadist-base.inc`) resolves
  the parse failure directly, so no `BBMASK` is needed.  Build
  attempt 5 reached a full parse pass and surfaced two further
  fallout items:
  - debug-tweaks: Wrynose's `debug-tweaks` `IMAGE_FEATURES` bundle
    was removed upstream.  Fixed in `kas/extras/debug.kas.yml` by
    expanding `EXTRA_IMAGE_FEATURES:append` to the equivalent
    discrete features (`allow-empty-password
    empty-root-password allow-root-login post-install-logging`).
  - BB_HASHSERVE: Wrynose's `bitbake.conf` weakly defaults
    `BB_HASHSERVE ??= 'auto'`, so merely commenting out
    `BB_HASHSERVE = 'auto'` in `kas/main.kas.yml`'s `10_cache` block
    no longer disables hash equivalence.  Combined with
    `SSTATE_MIRRORS`, this tripped sanity.bbclass's "local hash
    equivalence server ... configured an sstate mirror" warning.
    Setting `BB_HASHSERVE = ''` alone is not sufficient either:
    Wrynose also defaults `BB_SIGNATURE_HANDLER` to `OEEquivHash`,
    whose `init_rundepcheck` hard-requires `BB_HASHSERVE` to be set
    and calls `bb.fatal` otherwise during cooker init, before any
    recipe is parsed.  Fixed by setting both `BB_HASHSERVE = ''` and
    `BB_SIGNATURE_HANDLER = 'OEBasicHash'` explicitly in
    `kas/main.kas.yml`, which also makes the prior
    `BB_HASHSERVE_DB_DIR = "${SSTATE_DIR}"` line dead configuration;
    that line was removed and its intent folded into the block's
    FIXME comment for when a private hashserv is deployed.
  Build attempt 6 reached bitbake's dependency-resolution stage and reported
  5 ERRORs, all tracing to `virtual/libx11-native` being filtered out of
  native builds because 'x11' was absent from `DISTRO_FEATURES_NATIVE`:
  - libx11-native: `libsdl2.bb` and `libepoxy.bb` both hardcode
    `PACKAGECONFIG:class-native` to include 'x11' unconditionally.
    `qemu-system-native` pulls them in via its own `PACKAGECONFIG` (`sdl`,
    `epoxy`).  oe-core's `qemuboot.bbclass` unconditionally adds
    `qemu-system-native` to `EXTRA_IMAGEDEPENDS`; genericx86-64's machine
    chain enables that class via `IMAGE_CLASSES += "qemuboot"` for `runqemu`
    support, not via `meta-extsdk-toolchain`.
  While auditing `DISTRO_FEATURES_NATIVE` for the x11 fix, a second latent
  defect was found by code inspection, not itself among attempt 6's 5
  ERRORs:
  - systemd-native: oe-core's `systemd.bb` has no native `BBCLASSEXTEND`, so
    "systemd-native" can never be provided, yet `DISTRO_FEATURES_NATIVE`
    still carried 'systemd'.  `util-linux.bb` inherits `systemd.bbclass` and
    sets `BBCLASSEXTEND = "native nativesdk"`; with 'systemd' in
    `DISTRO_FEATURES_NATIVE`, `util-linux-native` picked up an unresolvable
    `DEPENDS` on `systemd-systemctl-native` via that class's unconditional
    `__anonymous` check.  (`uutils-coreutils` was checked as a candidate
    cause, since it also carries a systemd-gated native `PACKAGECONFIG`, but
    meta-oe's `layer.conf` pins `PREFERRED_PROVIDER_coreutils-native` to GNU
    `coreutils-native`, so `uutils-coreutils-native` is never selected into
    the graph; confirmed by its absence from
    `pn-buildlist`/`task-depends.dot` after the fix below.)
  Restoring 'x11' to `DISTRO_FEATURES_NATIVE` cleared the 5
  originally-reported ERRORs; re-running `bitbake -g lamadist-image-base`
  then surfaced the anticipated circular dependency between
  `util-linux-native` and `systemd-systemctl-native`'s
  `do_create_recipe_spdx` tasks, confirming the second defect -- this time
  as a hard cycle instead of a resolution failure.  Fixed by dropping
  'systemd' from `DISTRO_FEATURES_NATIVE` entirely (see
  `lamadist-base.inc`).
  Attempts 7-9 each fixed one further item: stale pre-migration
  orphans in the repo-default `deploy/` tree colliding with
  `do_populate_lic` (state cleanup, no code change); the
  `systemd-conf` bbappend still installing its journald snippet
  from `WORKDIR` instead of `UNPACKDIR`; and stale scarthgap-era
  buildhistory tripping `version-going-backwards` on
  `libdevmapper` (lvm2 legitimately re-versions it on Wrynose;
  buildhistory re-baselined, no code change).  Build attempt 10
  completed all 7735 tasks and the M1 QEMU login smoke passes on
  the Wrynose image.

**Exit criteria:**

- All layers track Wrynose or a documented compatible revision
- `mise run build --bsp x86_64` and the M1 smoke test pass on
  Wrynose
- No `scarthgap` references remain outside historical documentation

### M3: OTA Update Core

**Status:** Pass 1 COMPLETE (2026-07-16, OTA test PASS in QEMU);
pass 2 not started (mapper-device slots depend on M4 LUKS).
Update procedure documented in [OTA.md](OTA.md).  Notable fallout
fixed on the way to green: squashfs needed CONFIG_SQUASHFS_XATTR
(SELinux rejects xattr-less mounts even permissive); RAUC invokes
slot hooks as `slot-post-install`, not the manifest's
`post-install` name; the ESP needed `--fixed-size 512M` to hold
both slots' boot payloads; `/var/lib/rauc` needed a tmpfiles.d
entry; systemd-bless-boot had to be masked (auto-blessed trial
boots behind the health gate); and sd-boot 259.5's `default` key
ignores boot counting, so primary selection moved into the loader
entries' `sort-key` lines.

Pass 1 -- plain signed bundles:

- [x] Implement the split A/B partition layout in WKS (per
  [PARTITIONING.md](PARTITIONING.md))
- [x] Write `system.conf` slot definitions matching the layout
- [x] Create the bundle recipe and development signing keys
- [x] Integrate systemd-boot: slot selection plus a mark-good
  health-check service
- [x] QEMU test: install, reboot, health check, commit; then a
  forced failure that triggers automatic rollback

Pass 2 -- after pass 1 is green:

- [ ] Adaptive (delta) updates via `casync`
- [ ] CMS-encrypted `crypt` bundles
- [ ] Slot targets on decrypted mapper devices to preserve LUKS
  headers (depends on M4 LUKS work)
- [ ] Standalone Fable failure-mode review of the A/B OTA + the
  first-boot provisioning state machines.  Placed here (not the M4
  fold) deliberately: this pass adds the most failure-prone
  features -- casync resumable/partial transfers, crypt bundles,
  mapper-device slots on the LUKS headers -- so a review of
  behavior under interruption (power loss mid-install, partial
  slot writes, double-fault where both slots go bad, warm-`/var`
  edge cases) has the most material here, and it keeps one Fable
  pass per stage.  The QEMU gate proves the happy path and one
  forced rollback; this review targets what the gate cannot
  exercise.

**Exit criteria:**

- Full update cycle (install, reboot, health check, commit) and
  forced-failure rollback demonstrated in QEMU
- Update procedure documented

### M4: Security Hardening Ramp

**Status:** COMPLETE (2026-07-19), folded into a 12-commit clean
series (backup branch `backup/pre-fold-m4`, byte-identical tree
verified).  Enforcing Secure Boot + TPM2 + SELinux OTA gate GREEN
on build 40, which also certifies the dontaudit-disabled
Condition B pass (zero findings) and the read-write /etc overlay
fix.  The policy change set passed its Fable review
(ACCEPT-WITH-CHANGES, both findings documentation-level, applied).
IMA appraisal ships log-only by design; enforcement is M6.
**Goal:** The security architecture becomes enforced reality on
x86_64, verifiable in QEMU with OVMF and swtpm.

- [x] dm-verity end-to-end with the root hash embedded in the UKI
- [x] UKI packaging and direct UEFI boot
- [x] UEFI Secure Boot with project keys (sb-dev keys + sbsigned
  loader/UKIs, in-guest SecureBoot efivar assertion) under OVMF
- [x] Measured Boot against swtpm; TPM2-sealed LUKS unlocking
  (PCR7, keyring-cache first boot, TPM unseal on every later boot)
- [x] LUKS2 on data partitions; OverlayFS for `/etc` and
  application data (read-write verified -- the smoke now asserts
  it after the Condition B RO-/etc finding)
- [x] EROFS root filesystem
- [x] SELinux to enforcing (build 40, dontaudit-off certified);
  IMA measurement + log-mode appraisal only -- appraisal
  ENFORCEMENT deliberately deferred to M6 (signing + overlay
  xattr story), recorded in SECURITY.md

**Exit criteria:**

- Hardened profile boots in QEMU with Secure Boot, measured boot,
  and enforcing SELinux
- The M3 update cycle still passes on the hardened profile

**Milestone-close review (DONE 2026-07-17, pulled ahead of the
fold):** the single Fable whole-body pass over the composed stack.
Full report at `.local/state/agents/m4-security-review.md`.  It
confirmed the boot chain, roothash/UKI coupling, and first-boot
provisioning ordering are sound, RATIFIED the mount_t overlay
posture (with two conditions), and found holes the per-piece gates
missed.  Resolved already:

- [x] BLOCKER-1 plaintext swap partition removed (77783ac)
- [x] SECURITY.md false/overclaimed statements corrected (84ae88b):
  the pbkdf2 "test-profile-only" claim was false (it is
  unconditional), plus the scoped-claim and omission fixes

Gate conditions folded into the M4 stage-B exit -- BOTH CLOSED
2026-07-19 (evidence: `.local/state/agents/condition-b-harvest.md`,
policy review `.local/state/agents/m4-policy-v2-review.md`):

- [x] Condition B: dontaudit-disabled harvest run on build 39
  (23 genuinely-missing rows), fixes landed (83782c2), and the
  build-40 certification pass returned ZERO findings across a
  full dontaudit-off exercise (reboot cycle, units, logins, real
  `rauc install`, exhaustive /etc sweep).  The harvest also
  surfaced the RO-/etc-every-boot defect (overlay workdir setattr,
  dontaudit-concealed) -- fixed and now smoke-asserted.
- [x] Condition A: reconciled INTO the Condition B fix rather than
  dropped piecemeal -- the per-type insurance content reads were
  reclassified as permanent mounter-cred double-checks and
  subsumed by `files_read_all_files(mount_t)`; write-side rules
  stay per-type.  Accepted by the Fable policy review.

Recorded as decisions (brick paths, fix deferred to M6 on the
homelab dev profile, but named per the review):

- MAJOR-3 / W-a: TPM2 enroll does not assert Secure Boot is on
  before sealing to PCR7.  M6 adds an `SecureBoot=1` efivar check
  before enroll (fail loud otherwise).  Until then, provisioning
  MUST occur in the final SB-enabled state.
- W-b: crypttab is TPM-only with no boot-path keyfile fallback, so
  a slow/absent TPM coldplug past the 30 s settle can reboot-loop a
  pending first boot.  M6 decides the fallback; the ARM port (M5)
  hits this first (fTPM not ready at first boot) and must wire a
  fallback before reusing the crypttab logic.
- MAJOR-4: no anti-rollback and the ESP loader entries are
  unauthenticated (downgrade-to-old-signed-slot, entry DoS).  A
  monotonic counter / retired-roothash dbx is M6 scope.
- MINOR-1: exempt the never-yet-good first boot from
  reboot-on-unhealthy (folds with the existing machine-id
  follow-up as first-boot robustness work).

One Fable pass per stage; this was M4's.

### Post-M4 Checkpoint: Manual Validation

This gate blocks M5 *implementation* (the actual ARM port) and the
hardware/icecc work -- NOT the M5 research and design.  Per Lucas
(directive 2026-07-17), the M5 research pre-work and the M5
abstraction-design review are explicitly NOT gated on the manual
sign-off: start both as soon as M4 is complete, before (and in
parallel with) this checkpoint.  Intended order: research pre-work
first, then the abstraction-design review, so the review is
informed by the meta-tegra/meta-rockchip survey (agent's choice to
adjust; series chosen because the review is stronger with the
findings in hand).  Everything else below waits for Lucas.

- [ ] Manual validation of the M4 image by Lucas
- [ ] On success: install onto a local x86_64 device (manual,
  hardware step -- outside the agent working constraints) to serve
  as an icecc build helper (icecc preferred over distcc) and as a
  live test target for future work

Related, not gated on the checkpoint: the USB installer, pulled
forward into an active pass 2026-07-23 (see the Installer Pass
section below).

### Installer Pass (active, pulled forward 2026-07-23)

**Status:** SPEC drafted; AoAs + Fable security review in flight.
**Goal:** ONE installer USB image artifact: the stick is both
installer and manual; encrypted payload vault unlocked by a
per-stick password issued through the secrets manager (fnox
locally); minimal-input interactive flow AND fully headless
manifest-driven install; Secure Boot key enrollment automated
in-flow where firmware state permits.  Contract:
`docs/installer/SPEC.md`.  Verification is QEMU+OVMF / Podman /
static / unit only -- no physical flash, no real-machine
provisioning, no batch tooling.  Priority order:
non-destructiveness > Secure Boot integrity > reproducibility >
image size.

Operator-confirmed forks (2026-07-23): chain shape is the
signing AoA's outcome; generic UEFI x86_64 target; fully-offline
payload-on-stick; per-stick password persists as a LUKS2 recovery
keyslot alongside TPM2 sealing (narrows the W-b first-boot brick
path to a console-recoverable halt on attended machines --
unattended headless remains an M6 item), forward-compatible with
Clevis+Tang+TPM2 pre-bound keys.

- [x] SPEC.md drafted (user flow first) -- DRAFT until review
- [ ] AoAs land: signing/enrollment (riskiest fork, deep search),
  installer approach, secrets backend; recorded as ADRs
- [ ] AT-SCALE.md design-only doc (RFC 8628 portal + JWT
  device-enrollment variant; NOT built this pass)
- [ ] Fable security review of the security-critical design
  passes; SPEC leaves DRAFT
- [ ] SECURITY.md extended with the installer attack surface
- [ ] Stage 1: base image SB-enforcing boot regression (reuse
  existing gate)
- [ ] Stage 2: signing chain + enrollment path validates
  (sbverify; blank-vars Setup Mode enrollment in QEMU)
- [ ] Stage 3: vault unlock with fnox-issued password; recovery
  keyslot + TPM2 keyslot both open the installed target;
  dm-verity anchored per the Storage Immutability Spec
- [ ] Stage 4: stick image boots in QEMU; manual + manifest
  schema on the public partition; ESP carries only signed
  artifacts
- [ ] Stage 5: full user flow green -- scripted interactive
  serial-console install AND headless manifest install, plus the
  fail-closed abort matrix; target reboots into the signed,
  encrypted system and passes the hardened smoke

**Exit criteria:** every SPEC section 8 gate exit-0; one
documented command reproduces the stick from a clean checkout.

### Storage Immutability Spec (design of record, 2026-07-23)

Standing invariant for all platforms, adopted after the M4 close
(Fable-reviewed wording; supersedes the earlier "EROFS and/or
mounted read-only" phrasing, which named hygiene measures as the
control).  Rationale: SELinux is a runtime policy layer; it does
not govern offline media modification and is revocable by the same
privileged domain it constrains.  Immutability must therefore be
enforced at the storage layer with a root of trust independent of
the running OS.

Every storage entity (partition, volume, raw region) MUST be
classified into exactly one of four classes; requirements bind per
class:

1. **Immutable** (active root slot, verity hash partitions, /etc
   lower): MUST carry block-level cryptographic integrity
   (dm-verity) whose root hash is anchored in a Secure-Boot-signed
   artifact -- the UKI cmdline on x86_64, the signed FIT on ARM
   (M5).  SHOULD additionally use a read-only-by-format filesystem
   (EROFS) and be mounted read-only, as hygiene.  Runtime-revocable
   controls (SELinux, the `ro` mount flag, `blockdev --setro`, GPT
   read-only attributes) MUST NOT be the sole mechanism: none of
   them detects substitution of the underlying media, and all are
   reversible by a sufficiently privileged runtime domain.
2. **Write-once** (LUKS format + TPM2 enrollment, ssh host keys,
   machine-id): written only inside the guarded first-boot window,
   sealed afterward.
3. **Write-at-update** (inactive A/B slot, ESP UKI payloads):
   written only inside an authenticated update window; the RAUC
   bundle signature MUST be verified before any slot write.  The
   inactive slot is raw-written with no filesystem mounted, so its
   controls are device-level: block-device access confinement plus
   verity verification when the slot is next booted.
4. **Read-write by design** (/var, the merged /etc overlay, the
   ESP boot ledger): no immutability requirement.  The ESP is
   explicitly this class -- UEFI firmware requires FAT, and the
   boot counter / mark-good ledger is written on every boot; its
   protection is Secure Boot signature verification of the UKIs it
   references, not medium immutability.

Enforcement deltas are M6 scope (classification table in
SECURITY.md, write-window audit); x86_64 already satisfies the
immutable-class requirement via dm-verity with the root hash in
the signed UKI.

### M5: Second Platform

**Status:** Not Started
**Goal:** Prove the machine-config pattern ports cleanly to ARM and
restore per-BSP parity.

The first two items -- research pre-work and the abstraction-design
review -- were pulled ahead of M4 completion (Lucas, 2026-07-17,
Fable-budget priority) and are DONE.  The port work below still
waits for the manual sign-off.

- [x] Research pre-work: both surveys complete
  (`.local/state/agents/m5-survey-meta-tegra.md`,
  `m5-survey-meta-rockchip.md`).  Headline: the OS-level stack
  (erofs+dm-verity, LUKS /var, RAUC, SELinux, IMA) ports as-is;
  every firmware-anchored property (systemd-boot+UKI, UEFI SB,
  TPM2/PCR7, boot counters) is per-platform.  Tegra is the larger
  divergence (EDK2 -> L4TLauncher -> signed extlinux, nvbootctrl
  A/B, SWUpdate-blessed, RAUC zero integration); meta-rockchip has
  an in-layer RAUC uboot-backend reference.  PROPRIETARY core boot
  blobs on both ARM platforms (rkbin DDR/BL31/BL32; NVIDIA tegra
  binaries + edk2-non-osi) -- flagged to Lucas per license policy.
- [x] Fable abstraction-design review (M5's one Fable pass,
  2026-07-17): full report at
  `.local/state/agents/m5-abstraction-review.md`.  Decisions
  ACCEPTED as the M5 design of record:
  1. Platform seam: machine-selected `LAMADIST_BOOT_BACKEND` set
     only in machine includes (`lamadist-boot-sdboot-uki.inc`,
     `lamadist-boot-uboot.inc`, `lamadist-boot-l4t.inc` speced),
     per-backend image classes via `IMAGE_CLASSES`, distro layer
     keeps invariants only (EFI_PROVIDER/bootloader/UKI_SB_* move
     OUT of distro includes).
  2. Update backend: RAUC everywhere.  Rockchip = native uboot
     backend; Tegra = custom nvbootctrl backend on the same
     five-verb contract as the existing systemd-boot backend, with
     NVIDIA's auto-verifier masked.  SWUpdate rejected.  TRIPWIRE:
     if fused slot-pairing/ESRT proves unworkable under a custom
     backend, fall back to SWUpdate behind the common health gate
     -- escalate to Lucas (M5/M6 checkbox below).  Firmware
     capsule OTA stays outside the OS bundle contract everywhere.
  3. Boot chains: x86 unchanged (systemd-boot+UKI); Rockchip first
     port = U-Boot extlinux/FIT + U-Boot-env bootcount (NO
     verified boot initially -- state the regression in
     SECURITY.md and the RK machine include); Tegra = L4TLauncher
     + CMS-signed extlinux + nvbootctrl.  The five-point health
     gate contract (trial/commit/burn/fallback/bad) is the
     platform-invariant `test-ota` asserts.
  4. kas rule: "kas selects and pins; layers define" -- explicit
     branch pins, machine names that exist, target
     lamadist-image-base, zero hardware policy in kas.
  5. Machine pattern: thin leaf confs (vendor chain + dmverity.inc
     + boot-<backend>.inc + tpm2.inc-iff-hardware); DPS GUIDs
     become per-ARCH overrides in `lamadist-dmverity.inc`.
  6. Port order: SOQuartz FIRST (upstream machine exists), RK1
     second (stays the exit-criteria board), Orin demoted to
     "speced, gated on meta-tegra wrynose-branch verification".

Safe to start now (no gate, mechanical per review):

- [x] kas stub fixes (d56c06f): rk1.kas.yml adds meta-rockchip,
  both Rockchip targets -> `lamadist-image-base`, orin-nx gains
  `target:` + explicit pins, authored-machine gaps annotated,
  BBFILE_PRIORITY bump marked TODO
- [x] Move DPS/dm-verity GUIDs to per-arch overrides in
  `lamadist-dmverity.inc` (TRANSLATED_TARGET_ARCH overrides
  x86-64/aarch64); deleted from intel.conf + orin kas; x86-64
  expansion verified unchanged via bitbake -e
- [x] Verify (2026-07-17): meta-tegra AND meta-tegra-community
  both have wrynose branches (LAYERSERIES_COMPAT wrynose, L4T
  39.2.0) -- Orin's branch question resolves positively, demotion
  now rests only on divergence size and blob surface;
  `rk3588-turing-rk1.dtb` mainlined in 6.7 and
  `turing-rk1-rk3588_defconfig` in U-Boot 2024.10, both predate
  our 6.18/2026.01 pins (file-level confirmation at first ARM
  build)

Gated on the manual sign-off (implementation):

- [ ] Backend-class refactor: split lamadist-uki/esp-slot-a into
  `lamadist-boot-sdboot-uki` backend class; un-hard-wire
  `lamadist-image-base.bb` inherits; author
  `lamadist-boot-sdboot-uki.inc` and re-prove the x86 gate
- [ ] `rauc-conf` per-backend system.conf templating +
  backend-neutral pending-detection in lamadist-health-check
  (replace the loader-entry filename probe with `rauc status`)
- [ ] `soquartz.conf` (thin leaf per pattern) +
  `lamadist-boot-uboot.inc` + RK wks template (fixed-sector
  prelude incl. REQUIRED uboot_env partition, A/B verity after
  sector 32768); update PARTITIONING.md's Rockchip layout (it
  omits uboot_env -- MAJOR doc finding)
- [ ] `rk1.conf` authored in meta-lamadist (no upstream rk1
  machine exists -- PLAN's earlier note corrected)
- [ ] Boot smoke test for the ARM image under qemuarm64
- [ ] M5 fold doc refresh: ARCHITECTURE.md/PARTITIONING.md still
  describe aspirational LUKS rootfs slots, UKI-on-ESP for Orin,
  and kernel 6.6 (actual: verity slots, LUKS /var only, no UKI
  off-x86, kernel 6.18)

Physical flashing and hardware testing remain out of scope until the
working constraints are lifted.

**Exit criteria:**

- RK1 image builds green and the image boots under qemuarm64
- No BSP bypasses the LamaDist image or distro configuration
- The nvbootctrl-vs-SWUpdate tripwire (review decision 2) is
  either untriggered or resolved with Lucas before Orin work

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
- [ ] Storage Immutability Spec enforcement: per-entity
  classification table in SECURITY.md, plus a write-window audit
  (RAUC signature check precedes every slot write; first-boot
  write-once units are guarded and one-shot)

**Exit criteria:**

- One tagged v0.x release from `main` with artifacts, SBOM, and
  generated release notes

### M7: Optional Workload Features

**Status:** Not Started
**Goal:** A documented optional-feature pattern, proven by two
features on all platforms: an OpenTelemetry collector and k3s.
Optional features are off by default and live behind KAS overlays
so the base image never grows.

The pattern (already latent in `kas/extras/`): one overlay per
feature adds layers, `DISTRO_FEATURES`, and a feature
packagegroup; `mise run build --feature <name>` composes overlays;
each feature ships its own smoke assertion and SELinux policy so
M4's enforcing gate stays green.

- [ ] Document the optional-feature pattern (overlay +
  packagegroup + smoke assertion + policy module) in
  ARCHITECTURE.md and TOOLING.md; add `--feature` composition to
  the build task
- [ ] otel-collector overlay (all platforms): run the official
  otel-collector-contrib image as a Quadlet `.container` unit with
  config in `/etc/otelcol` and state under `/var`; journald and
  hostmetrics receivers, OTLP exporter.  Decision checkbox:
  confirm the Quadlet route over a from-scratch Go recipe (no OE
  recipe exists for the collector; meta-oe only has the C++
  library)
- [ ] k3s overlay (all platforms): meta-virtualization k3s with
  `DISTRO_FEATURES += "virtualization k8s seccomp"`, the kernel
  config fragment applied to each BSP kernel, and split
  `k3s-server` / `k3s-agent` package selection; state lives in
  `/var/lib/rancher`
- [ ] SELinux: policy modules (or documented permissive domains
  pending M4 triage) for otelcol and k3s services
- [ ] Extend the QEMU smoke: with the otel overlay, the collector
  unit is active and exports pipeline metrics; with the k3s
  overlay, `k3s kubectl get node` reports Ready on a single node

**Exit criteria:**

- Base image without overlays is byte-identical to the M6 baseline
  (features are truly optional)
- Each feature overlay builds and passes its smoke assertion in
  QEMU x86_64

### M8: AWS IoT Greengrass (x86_64)

**Status:** Not Started
**Goal:** An optional Greengrass overlay for x86_64 turns a
LamaDist node into a Greengrass core device, with a clear pattern
for enabling additional components.

Image-side vs runtime-side split: the image bakes the nucleus, its
Java runtime, credentials plumbing, and per-component OS
prerequisites; the components themselves arrive through Greengrass
deployments (cloud or `greengrass-cli` local) into writable state.
Greengrass state roots at `/var/lib/greengrass` (`/greengrass/v2`
symlink), on the writable `/var` partition.

- [ ] Greengrass overlay: meta-aws `greengrass-bin` (nucleus
  2.16.x) with `corretto-17-bin`, a systemd unit, the
  `ggc_user`/`ggc_group` accounts, and state on `/var`; pin the
  meta-aws branch
- [ ] Decision checkbox: classic Java nucleus vs `greengrass-lite`
  (C runtime, image-provided component deployment, much smaller
  footprint but a subset of component features).  Default: classic
  nucleus, since the required component list below leans on it
- [ ] Provisioning story: document cloud provisioning (claim certs
  / fleet provisioning via `greengrass-plugin-fleetprovisioning`)
  and keep CI cloud-free
- [ ] Component prerequisites in the image, one checkbox each:
  - [ ] Lambda runtimes (Python, Node.js): ship `python3` and
    `nodejs`; the Lambda launcher and Lambda manager components
    are runtime-deployed
  - [ ] Docker application manager: decision required -- real
    `docker` from meta-virtualization vs `podman-docker` compat
    shim (unsupported by AWS but keeps one container engine)
  - [ ] MQTT 5 broker (EMQX): runtime component; requires Docker
    on Linux AND bundles EMQX, which is BUSL-1.1 since v5.9 --
    **Lucas must sign off before this ships**
  - [ ] PKCS#11 provider: bake `greengrass-plugin-pkcs11` plus
    `tpm2-pkcs11` / `p11-kit` so keys can live in the TPM
  - [ ] MQTT bridge, client device auth, shadow manager, disk
    spooler, log manager, system log forwarder (LogManager's
    system log feed): pure runtime components -- verify no image
    deps beyond the nucleus, document enabling each
  - [ ] System Manager Agent: runtime component; document the SSM
    registration flow and its writable-state needs
  - [ ] Development overlay additions: Greengrass CLI and Local
    debug console, gated behind the debug/dev overlay only
- [ ] Document the add-a-component pattern: deployment recipe
  (cloud or local), image prerequisites checklist, SELinux
  expectations, and where state lands on the read-only root
- [ ] SELinux policy for the nucleus and component processes
  (permissive domains until M4-style triage, then enforcing)
- [ ] QEMU smoke (cloud-free): nucleus service active, and a local
  `greengrass-cli` deployment of a helloworld component succeeds

**Exit criteria:**

- Greengrass overlay builds for x86_64; base image unaffected
- In QEMU: nucleus healthy and a local component deployment runs
  end-to-end without cloud access
- Component-enabling pattern documented well enough that adding a
  new AWS-provided component is a checklist, not a project

---

## Agent Execution Strategy

The milestones above are sized to be executed by AI agent sessions,
including multi-agent workflow runs ("Ultracode"), where three
realities dominate: context windows compact mid-task, Yocto builds
outlive any single turn, and long operations can hang (see the
2026-07-14 bitbake hang).  These rules make the work survivable and
resumable regardless of which agent, session, or schedule picks it
up.

### Work Units

- Execute one milestone step per work unit: one branch, one
  verifiable check, roughly one hour of agent attention.  Builds and
  boots run as background tasks, never as in-turn waits.
- A work unit ends in exactly one of: a commit plus a checked box in
  this plan, or a blocked note with diagnostics.  Nothing ends
  silently.

### Review Policy (Fable reviewers)

Per Lucas (2026-07-17):

- At most ONE `claude-fable-5` reviewer per milestone stage --
  either a whole-body review or a targeted critical-aspect review,
  the orchestrator's choice.
- Every milestone SHOULD close with one Fable whole-body reviewer
  at the fold, generalizing the M4-fold pattern.  Milestone
  sections may schedule that pass explicitly (M4 fold, M5 research
  kickoff, M3 pass 2); where a milestone does not, the fold review
  still applies by default.
- Fable sub-agents remain restricted to planning, architecture,
  and review; effort capped at xhigh.  All other sub-agent work
  routes to haiku/sonnet/opus per the global routing table.

### Durable State and Resume

- Git is the only source of truth for progress: commits on work
  branches plus the checkboxes in this plan.  An agent resuming work
  derives "next action" from `git log` and this document, never from
  conversation memory.
- In-flight scratch state (background task IDs, container names,
  deploy paths, log locations) is journaled to
  `.local/state/agents/journal.md` (git-ignored) as it is created,
  not at the end of a turn, so a compaction or crash loses
  nothing.
- Multi-agent workflow scripts are persisted to files, and
  interrupted runs resume via the workflow runner's resume mechanism
  (completed agent calls replay from cache; identical script and
  args yield a full cache hit).

### Token-Limit Error Handling

- Never stream raw build output into agent context.  Bitbake logs
  run to megabytes; extract with filtered greps for the decisive
  lines only (`ERROR|Tasks Summary|denied|Failed`).
- Sub-agents swallow verbose compilation streams and return
  high-signal summaries.  A sub-agent that makes no state progress
  for three consecutive turns must yield with a status report
  instead of burning context.
- Workflow runs check the remaining token budget before each
  fan-out; below a floor (~50k), stop spawning, write partial
  results and a remaining-work list to the journal, and exit
  cleanly.  A truncated run that reports is recoverable; one that
  dies mid-fan-out is not.
- Before predictable compaction points (long waits on builds), flush
  status to the journal so the post-compaction session can re-derive
  state from disk.

### Long-Operation Supervision

Every background operation gets a liveness contract:

- An expected-duration budget (cold build: hours; warm build:
  ~40 min; QEMU boot: minutes).
- A liveness signal: new task lines in the build log, transcript
  growth for console sessions.
- A monitor whose filter matches success AND failure signatures
  (`Tasks Summary` and `ERROR`, not just the happy path); silence is
  never treated as success.
- A stall action when the budget or liveness fails: capture
  diagnostics (tail of `bitbake-cookerdaemon.log`, process tree,
  serial transcript), stop the container or VM, and record the step
  as blocked with the evidence attached.  The 2026-07-14
  end-of-build hang (idle workers, "Server refused shutdown") is the
  canonical case this catches.

### Scheduled Restarts and Auto-Resume

- Long campaigns (full milestone execution, migration builds) run
  under a scheduled heartbeat: a recurring in-session wakeup every
  20-30 minutes checks liveness, and the project-level pitchfork
  cron daemon (see API Limit Outages below) recovers from killed
  sessions.
- Each restart follows the same entry protocol: re-read the standing
  hard rules, read this plan and the journal, inventory stranded
  state (`podman ps`, `pgrep qemu`, background task files), clean or
  adopt it, then resume the first unchecked step.  The protocol is
  idempotent -- running it twice must be safe.
- Restarts never re-run a completed work unit: completion is judged
  by commits and checkboxes, not by session memory.

### API Limit Outages (5-hour and weekly)

Hard provider limits (the rolling 5-hour window and the weekly cap)
cut off API access entirely: the session hangs up mid-task, and
in-band recovery (heartbeat wakeups, scheduled routines) fails too,
because it consumes the same quota.  Handling is proactive first,
with crash-only recovery as the backstop:

- **Proactive pause-and-sleep (primary).**  When a nearing-limit
  warning arrives, do not work until the hangup.  Immediately:
  pause all API-consuming sub-agents and workflow runs (TaskStop;
  interrupted workflows resume later from the run cache via
  `resumeFromRunId`), flush the journal with an explicit NEXT
  action, launch any pending long host-side operations (builds)
  so the outage wastes no wall-clock time, then start one
  background sleep task (a tool call, e.g. `sleep <seconds>` in
  the background) sized to return one minute AFTER the reset time
  given in the warning.  Make no further API-consuming moves; the
  sleep task's completion re-invokes the session exactly when
  quota is back, and work resumes from the journal.
- **Crash-only design (backstop).**  Because progress truth lives
  on disk (git, plan checkboxes, journal written as work happens),
  a hangup at any instant is just another crash and is already
  resumable.  No work unit may hold unjournaled critical state
  longer than one turn.
- **Host processes outlive the session.**  Podman builds, QEMU VMs,
  and their log files keep running and accumulating during an
  outage.  A limit hit does not waste build wall-clock time.  On
  resume, the entry protocol adopts running or finished work from
  the journal (task IDs, container names, log paths) instead of
  restarting it.
- **Out-of-band resume (fallback only).**  A project-level
  pitchfork cron daemon (`pitchfork.toml`, `daemons.agent-resume`)
  runs `mise run agent:resume` every 30 minutes; the default
  `finish` retrigger means runs never overlap.  The launcher skips
  cheaply when an interactive session is already running in this
  project or a recorded limit reset has not passed; on a limit
  error it records a one-hour backoff and exits.  Pitchfork runs
  host-side and costs no API quota.  It exists only for hard
  cutoffs that arrive without warning or kill the session process
  itself; the proactive sleep above is the normal path.  Opt-in:
  start the pitchfork supervisor, then
  `pitchfork start agent-resume`.
- **Weekly pacing.**  Schedule token-heavy phases (fan-out reviews,
  migration fallout fixing) early in the weekly window; reserve the
  tail for supervision-only heartbeats and host-side builds.

### Workflow Mapping (for later Ultracode runs)

- M1: a pipeline of small fix branches, each verified by the QEMU
  boot smoke test.  Single-agent capable; panel review before merge.
- M2: fan out per-layer Wrynose branch-availability checks in
  parallel, then a serialized migration with the M1 smoke test as
  the gate after each layer bump.
- M3/M4: implement serially (partition and boot changes conflict
  structurally); use finder/verifier panels only for review passes.
- Reviews at any milestone: independent finders per dimension, then
  adversarial verification of each finding before it is reported.
- M7/M8: feature overlays are independent of each other and of
  M5/M6; each is a small serial implementation gated by its own
  QEMU smoke, parallelizable across agents once the M7 pattern
  step is merged.

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

- Cluster orchestration beyond single-node k3s (multi-node, HA
  control plane)
- Remaining BSPs beyond the reference x86_64 + first ARM board
- Network install workflows and batch/fleet flashing.  The
  single-USB installer itself was pulled forward 2026-07-23 into
  the active Installer Pass (see that section); what remains here
  is the at-scale build-out: the RFC 8628 password portal, JWT
  device enrollment (designed in docs/installer/AT-SCALE.md, not
  built), and Clevis+Tang+TPM2 pre-bound network unlocking
- Ecosystem integration beyond M7/M8: additional exporters,
  dashboards, and cloud services
- Performance profiling and tuning
- LTS / backport policy and long-term maintenance tracks
- Test-pyramid / coverage-gap review.  The suite is heavy on the
  QEMU end-to-end end and thin on the data-type and unit layers
  the working style calls for (the RAUC backend logic, the
  boot-entry sort-key math, and the smoke-assertion parsing all
  lack isolated tests).  A review to map where confidence looks
  higher than it is; a good Fable fit but not gated to Fable.
- RAUC deployment infrastructure -- the fleet/server side of OTA
  the local QEMU install/rollback proof does not cover: a hosted
  update server (hawkBit integration vs. a plain signed-bundle
  HTTP endpoint -- an AoA, and hawkBit's EPL-2.0 license needs the
  copyleft-policy check), the bundle build/sign/publish pipeline,
  device registration and polling, and rollout/campaign
  management.  Standalone infrastructure work (kept separate from
  the coverage review above -- it is build, not review); the
  server-vs-hawkBit design choice could warrant a design pass, but
  the build itself is ordinary implementation, not necessarily
  Fable.

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
