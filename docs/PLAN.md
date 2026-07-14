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
  branches)
- [x] Add `.gitignore` entries for local editor and shell files

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

### Durable State and Resume

- Git is the only source of truth for progress: commits on work
  branches plus the checkboxes in this plan.  An agent resuming work
  derives "next action" from `git log` and this document, never from
  conversation memory.
- In-flight scratch state (background task IDs, container names,
  deploy paths, log locations) is journaled to
  `.cache/agents/worklog.md` (git-ignored) as it is created, not at
  the end of a turn, so a compaction or crash loses nothing.
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
because it consumes the same quota.  Handling is layered:

- **Crash-only design.**  Because progress truth lives on disk (git,
  plan checkboxes, journal written as work happens), a hangup at any
  instant is just another crash and is already resumable.  No work
  unit may hold unjournaled critical state longer than one turn.
- **Host processes outlive the session.**  Podman builds, QEMU VMs,
  and their log files keep running and accumulating during an
  outage.  A limit hit does not waste build wall-clock time.  On
  resume, the entry protocol adopts running or finished work from
  the journal (task IDs, container names, log paths) instead of
  restarting it.
- **Out-of-band resume.**  A project-level pitchfork cron daemon
  (`pitchfork.toml`, `daemons.agent-resume`) runs
  `mise run agent:resume` every 30 minutes; the default `finish`
  retrigger means runs never overlap.  The launcher skips cheaply
  when an interactive session is already running in this project or
  a recorded limit reset has not passed; on a limit error it records
  a one-hour backoff and exits.  Pitchfork runs host-side and costs
  no API quota, so the schedule survives any outage.  Opt-in: start
  the pitchfork supervisor, then `pitchfork start agent-resume`.
- **Graceful wind-down.**  When usage nears a limit: stop spawning
  sub-agents and workflows, flush the journal with an explicit NEXT
  action, and launch pending long host-side operations (builds)
  first so they run unattended through the outage.
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
