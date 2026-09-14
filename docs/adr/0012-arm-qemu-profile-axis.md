# ADR 0012: QEMU Test Profiles Are Keyed to the Boot Backend

## Status

Accepted (2026-09-14)

## Context

With the vendor documentation for the M5 targets collected, the
question was whether the emulated aarch64 gate should grow a unique
virtual test profile per device (Turing RK1 / RK3588, Pine64 SOQuartz
/ RK3566, Jetson Orin NX), and whether it should.  The `vm` task
already carried three board-named profiles that set only a CPU model,
a core count, and a memory size on QEMU's generic `virt` machine.

What QEMU 10.2 can and cannot express was verified against the
binary, the meta-arm layer, and the vendor layers before deciding:

- `virt` has no machine model for any Rockchip or Tegra part.  No
  board firmware, DDR training, OTP or eFuse state, SoC peripheral,
  console UART, or fixed-sector boot prelude is emulable at any
  effort.
- `-cpu` is one model for every core; `virt` has no per-cluster CPU
  type, so a big.LITTLE pair such as RK3588's A76+A55 cannot be
  expressed.  The cluster geometry can: `-smp 8,clusters=2,cores=4`
  hands the guest a real two-cluster `cpu-map`.
- `virt` boots only the CPU models on its own allowlist.
  `cortex-a78ae` exists in the QEMU 10.2.3 binary but is not on that
  list there, nor in upstream `hw/arm/virt.c` at the time of writing,
  so the `orin-nx` profile had never been able to start on this x86
  host, and no CI path exercised any profile.
- The meta-arm `qemuarm64-secureboot` machine (TF-A, OP-TEE, a
  software fTPM) is not a trust chain: it authenticates and measures
  nothing on any QEMU platform, exposes `/dev/tpm0` only with
  `tee-supplicant` from meta-arm's own CI overlay, boots a raw kernel
  image rather than a FIT, and would need one of `virt`'s two pflash
  banks, both of which the gate already spends on AAVMF.
- The gate's only stated Secure Boot gap was unenrolled AAVMF
  variables; the signed UKI was never verified on aarch64, while the
  x86_64 gate already boots enrolled OVMF variables built by the
  `ovmf-vars` task.

## Decision

1. A QEMU test profile is keyed to the boot backend
   (`LAMADIST_BOOT_BACKEND`), never to a board.  Today that axis has
   one member, `sdboot-uki` on AAVMF, which is the backend the x86_64
   gate proves.  A second member exists only when a second backend has
   a QEMU story that is worth its cost; none is scheduled.
2. The board-named profiles are removed.  The `vm` task takes plain
   `--cpu`, `--smp`, and `--mem` passthrough flags for aarch64,
   documented as cosmetic plus topology: `--smp` reaches QEMU verbatim,
   so an RK3588-shaped `8,clusters=2,cores=4` exercises cluster
   scheduling paths, but microarchitecture, DVFS, and every board
   property stay out of reach.
3. A green emulated run proves the LamaDist side of a contract (the
   OS stack, the boot backend, the update and health-gate logic) and
   never the vendor firmware beneath it.  No measured-boot,
   anti-rollback, or trust-chain claim may be made from a QEMU run.
4. The aarch64 gate closes its Secure Boot gap on the backend it
   already runs: `ovmf-vars --bsp qemuarm64` enrolls the project
   PK/KEK/db into the Secure Boot capable AAVMF varstore, `vm -S` boots
   it and asserts `SecureBoot=1` in-guest, and a deliberately
   corrupted UKI must be refused: `vm --ci --secureboot --tamper-uki`
   zeroes bytes inside the UKI on a scratch copy of the image and
   passes only when the firmware declines to start it.  The refusal is
   the deliverable.
5. `vm --no-tpm` is the harness knob for the state in which no usable
   TPM exists when `/var` is unlocked.  That state is the shipping
   state of the first Rockchip port and the expected first-boot state
   of an OP-TEE fTPM whose storage depends on userspace, so the
   crypttab fallback it exposes will be designed and tested against it.

## Alternatives considered

- Silicon-faithful per-device profiles: impossible without a QEMU
  machine model per SoC, which nobody ships and which would still omit
  the closed DDR and boot-ROM stages.  Rejected.
- Patching `virt`'s CPU allowlist to admit `cortex-a78ae`: a one-line
  QEMU change that means carrying a QEMU fork in the builder container
  and on every host for zero fidelity, since TCG executes identically
  regardless of the model name.  `max` or `cortex-a76` cover the same
  ground.  Rejected.
- A second machine on meta-arm's `qemuarm64-secureboot` as a
  `uboot-fit` backend profile: its cost was understated by an order of
  magnitude (AAVMF eviction, a meta-arm repin that perturbs the three
  board builds, a second sstate lineage, a FIT boot path and key anchor
  that do not exist, a RAUC backend swap) and its benefit overstated
  (no trust chain, no measured boot).  Deferred behind a time-boxed
  spike with two kill-switch checks, and only if the enrolled-AAVMF
  path proves insufficient.
- Keeping board-named shape presets as convenience aliases: the name
  is the problem, because a green `rk1` run gets cited as RK1
  coverage.  Rejected; the shapes live in documentation as example
  flag sets.

## Consequences

- `--profile` and the `orin-nx`, `rk1`, and `soquartz` names are gone
  from the `vm` task and docs; the false "QEMU >= 8" rationale is
  corrected to the allowlist that actually governs it.
- The aarch64 CI job enrolls variables and runs its smoke under Secure
  Boot, so the signed UKI is verified in CI on aarch64 as it already
  is locally on x86_64 (the x86_64 CI job builds but runs no smoke).
  Asserting `SecureBoot=1` in-guest needs efivarfs, which the aarch64
  kernel only offered as a module the image never shipped; the kernel
  now builds it in on every linux-yocto machine (x86_64, qemuarm64,
  the Rockchip boards; Orin's NVIDIA kernel is untouched), which also
  exposes the EFI variables that boot counting and systemd-boot's
  loader interface depend on.
- The enrolled db certificate and the UKI signing key are the same
  committed development keys (`meta-lamadist/files/sb-dev/`), so the
  gate proves the enforcement mechanism, never key custody; production
  custody stays M6 scope.  The aarch64 enrolment starts from a distro
  AAVMF template that is already initialized (Debian and Ubuntu ship
  the blank one as erased flash that `virt-fw-vars` cannot parse), so
  that template's own throwaway test keys remain in the CI-only
  varstore beside ours.  The gate asserts our UKI is trusted and a
  tampered one refused, not that db holds our key alone, so the extra
  entries do not weaken what it proves.
- The ARM boards' real boot chain is a separate decision.  U-Boot can
  act as the UEFI provider with Secure Boot variables preseeded into
  the BootROM-verified U-Boot image, which would let the boards run
  the same `sdboot-uki` backend as x86_64 and the gate, with OP-TEE
  reduced to supplying the fTPM.  That supersedes the first-port
  extlinux/FIT decision of the M5 abstraction review and needs its own
  ADR and security review before any board work assumes it.
- M5's exit criteria are unchanged; the RK1 half still waits on a
  LamaDist machine configuration that does not exist yet.
