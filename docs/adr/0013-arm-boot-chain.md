# ADR 0013: ARM Boards Boot Chain

## Status

Proposed (2026-09-20)

## Context

ADR 0012 left the ARM boards' real boot chain as a separate decision
and named the candidate: U-Boot as the UEFI provider, with the Secure
Boot variables preseeded into the U-Boot image, so the boards run the
same `sdboot-uki` backend as x86_64 and the emulated gate.  The M5
abstraction review's design of record (docs/PLAN.md, review decisions
2, 3, and 6) says otherwise: U-Boot extlinux/FIT, a U-Boot-env boot
counter, RAUC's native `uboot` backend, and no verified boot on the
first port.  The two cannot both stand.  Three options were weighed:
(a) U-Boot as the UEFI provider, (b) the design of record, and (c) a
community EDK2 firmware where one exists.  The draft went through a
security review and a completeness pass; their findings are folded in
below, and every claim that only a build or a board can settle is a
named kill-switch check rather than an assumption.

What was verified before deciding (U-Boot at the pinned tag v2026.01,
systemd 259.5, RAUC 1.15.1 and the unpacked sources under `build/`,
meta-rockchip at the checked-out scarthgap commit 9690180, upstream
OP-TEE and the two EDK2 projects at master on 2026-09-20):

- The tree has one boot backend implemented end to end, `sdboot-uki`,
  and every ARM sibling the seam names (`lamadist-boot-uboot.inc`,
  `soquartz.conf`, `rk1.conf`, a Rockchip WKS) is speced and absent.
  The aarch64 UKI path already boots under AAVMF with the project
  PK/KEK/db enrolled and `SecureBoot=1` asserted in-guest
  (`.github/workflows/ci.yml`, the qemuarm64 job's enroll and
  `test --secureboot` steps), so the backend logic the boards would
  inherit is proven on aarch64, not only on x86_64.
- Nothing in the OTA path touches an EFI variable.  The five-verb
  backend, the health gate's pending probe, the bundle hook, and
  `ota_test.py` are ESP-file and `/proc/cmdline` operations.  The
  in-repo efivarfs consumers are the installer's trust gate, its
  `LoaderDevicePartUUID` read, and the device validator's
  `SecureBoot` assertion.
- systemd-boot's boot counter is a file rename done by the loader
  itself before `ExitBootServices`.  U-Boot 2026.01 implements that
  rename: `efi_file_setinfo` (`lib/efi_loader/efi_file.c`, starting
  at line 950) calls `fs_rename` when the file name changes.  The
  rename needs `FAT_RENAME`, which depends on `FAT_WRITE`; neither
  has a default (`fs/fat/Kconfig`), and neither board defconfig sets
  them.  First-party verification; the rename's exact `+2-1` output
  form is not yet observed (kill-switch check 4).
- `EFI_LOADER`, `CMD_BOOTEFI`, `EFI_BOOTMGR`, and the EFI boot
  methods default on for ARMv8, but `turing-rk1-rk3588` and the
  `soquartz-*-rk3566` defconfigs name no `CONFIG_EFI_*`, no
  `FAT_WRITE`, no `DM_RTC`, no `VIDEO`, no `TEE`/`OPTEE`, and no
  `TPM`; RK1 disables SPI flash.  Both set `SPL_FIT_SIGNATURE` and
  `SPL_ATF`.  U-Boot's UEFI targets EBBR, not full UEFI.
- The same defaults leave every non-EFI boot path on: `BOOTSTD` and
  the extlinux, script, and PXE boot methods (`BOOTMETH_EXTLINUX` is
  `default y`), `booti`/`bootm`/`go`/`mw` commands, an interruptible
  two-second autoboot, and a `boot_targets` scan of mmc, nvme, scsi,
  usb, pxe, and dhcp (`include/configs/rockchip-common.h`).  EFI
  Secure Boot verifies only images that pass through the EFI loader
  (`efi_image_authenticate`), so with these defaults an
  `extlinux.conf` plus an unsigned kernel on any medium boots with no
  key involved.  Any Secure Boot claim depends on compiling those
  paths out.
- `EFI_SECURE_BOOT` verifies Authenticode signatures against db, as
  on x86, and must be enabled deliberately.  The non-volatile store
  is a `choice` defaulting to `EFI_VARIABLE_FILE_STORE`
  (`/ubootefi.var` on the ESP, depends on `FAT_WRITE`), else
  `EFI_MM_COMM_TEE` (StandaloneMM in OP-TEE, RPMB), else
  `EFI_VARIABLE_NO_STORE`; with `FAT_WRITE` off the choice lands on
  `NO_STORE` silently.
- The file store cannot install trust anchors from Linux:
  `efi_var_restore` (`efi_var_file.c`) skips every authenticated,
  shim-lock, and volatile variable on restore, so PK/KEK/db/dbx do
  not survive a reboot through the file store at all.  They persist
  only through `EFI_VARIABLES_PRESEED` (compiled into U-Boot, then
  write-protected including dbx, and exclusive with
  `EFI_MM_COMM_TEE`) or through StandaloneMM on RPMB.  With the
  preseed, `SecureBoot=1` follows from PK presence alone.
  Non-authenticated variables (`Boot####`, `BootOrder`) do restore
  from the file, and U-Boot reads that file from the first ESP it
  finds, before any signature check.
- Runtime `SetVariable` returns `EFI_UNSUPPORTED` after
  `ExitBootServices` unless `EFI_RT_VOLATILE_STORE` is on, which
  refuses authenticated variables, does not persist, and says in its
  own help text that it violates the specification.  efivarfs mounts
  read-only; systemd's random-seed unit downgrades its write failure
  to a notice, so the health gate is unaffected.
- U-Boot's EFI boot method loads a device tree from the boot medium
  (`/dtb/<fdtfile>` and siblings, `boot/bootmeth_efi.c`) and hands it
  to the EFI application; it falls back to its built-in FDT only when
  none is found.  `lamadist-uki.bbclass` embeds no device tree in the
  UKI today.
- Below U-Boot there is one anchor, the BootROM checking a signed
  loader against a key hash in OTP, and neither board reaches it with
  open tooling: mainline `mkimage` writes SHA-256 hashes into the
  Rockchip header and never a signature (`tools/rkcommon.c`), the
  signing tool ships only as a prebuilt binary in the proprietary
  rkbin tree, upstream OP-TEE carries a fusing path for rk3588 only
  (`CFG_RK_SECURE_BOOT`, simulation on by default, documented as able
  to brick the device, optee_os >= 4.5.0), and rk3566/rk3568 have no
  upstream OP-TEE platform port.  A burned key hash by itself
  verifies only the first loader; extending trust to U-Boot, BL31,
  and BL32 also needs SPL FIT signature enforcement with a key in
  SPL's control device tree, which the defconfigs do not carry.
  meta-rockchip pins the DDR TPL, BL31, and BL32 to rkbin, whose
  licence forbids reverse engineering.
- The fTPM (meta-arm `optee-ftpm`, ms-tpm-20-ref) is real but gated
  to QEMU machines, needs a from-source OP-TEE in place of the rkbin
  BL32, and stores its state in RPMB or through `tee-supplicant`, so
  `/dev/tpm0` appears only after userspace starts.  The upstream
  rk3588 OP-TEE port writes the hardware unique key into OTP at first
  use.  U-Boot can drive an fTPM (`TPM2_FTPM_TEE`), but nothing
  measures the TPL, BL31, BL32, or U-Boot itself: the first measured
  object is what U-Boot loads.
- RAUC's native `uboot` backend uses only `BOOT_ORDER` and
  `BOOT_<slot>_LEFT`, runs `fw_printenv`/`fw_setenv`, needs a
  persistent env partition that docs/PARTITIONING.md's Rockchip
  layout omits, and its `get_state` reports `good` for a trial slot
  exactly as the custom backend does, so it does not unblock the
  deferred `rauc status` pending detection either.
- No EDK2 port exists for the Turing RK1 (edk2-rk3588 has no Turing
  platform); one exists for SOQuartz (quartz64_uefi v2.3), without
  Secure Boot.  Neither has capsule update, ESRT, a TPM stack, or a
  Yocto recipe; edk2-rk3588's last tag is v1.1 (2025-04).
- meta-rockchip's SoC includes (`rk3566.inc`, `rk3588s.inc`) set
  `KERNEL_CLASSES = "kernel-fitimage"`, `KERNEL_IMAGETYPE ?=
  "fitImage"`, `PREFERRED_PROVIDER_optee-os = "rockchip-rkbin"`, and
  require `rockchip-wic.inc`, which requires `rockchip-extlinux.inc`
  (`UBOOT_EXTLINUX ?= "1"`, `u-boot-extlinux` and `kernel-image`
  added to `MACHINE_ESSENTIAL_EXTRA_RDEPENDS`), the feature-gated
  `rk-u-boot-env` wiring, and the RAUC demo overrides.  The
  scarthgap checkout defines no soquartz or rk1 machine;
  `kas/bsp/soquartz.kas.yml` pins no meta-rockchip branch while
  `rk1.kas.yml` pins wrynose.
- `lamadist-boot-sdboot-uki.inc` hard-sets `EFI_PROVIDER` and
  `PREFERRED_PROVIDER_virtual/bootloader` to systemd-boot;
  `lamadist-luks-var.bb` requires the `tpm2` distro feature; the
  crypttab line in `lamadist-image.bbclass` is unconditional
  (`tpm2-device=auto`), and its own comment anticipates a machine
  without a TPM needing a seam that does not exist yet.
- docs/PLAN.md's Storage Immutability Spec requires the active root's
  verity hash to be anchored in a Secure-Boot-signed artifact on
  every platform, and forbids runtime-revocable controls as the sole
  mechanism.

## Decision

1. The Rockchip boards boot through U-Boot acting as the UEFI
   provider and run the unchanged `sdboot-uki` backend.  The chain is
   BootROM -> rkbin DDR TPL -> SPL -> BL31 -> U-Boot 2026.01 with
   `EFI_LOADER`, `EFI_SECURE_BOOT`, and `EFI_VARIABLES_PRESEED` ->
   systemd-boot at the removable-media path (`EFI/BOOT/BOOTAA64.EFI`)
   -> per-slot signed UKI -> dm-verity root.  The per-board device
   tree ships inside the UKI (`ukify --devicetree`, covered by the db
   signature) so the stub installs it; `lamadist-uki.bbclass` gains
   that plumbing and each leaf names its `KERNEL_DEVICETREE`.
   `soquartz.conf` and `rk1.conf` require
   `lamadist-boot-sdboot-uki.inc`; `lamadist-boot-uboot.inc` is not
   authored.  The systemd-boot backend script, the health gate and
   its pending probe, the bundle hook, `system.conf`, both
   slot-manager masks, `ota_test.py`, and docs/OTA.md carry over with
   no change.
2. The decision is conditional and ordered.  It stands only while
   the kill-switch checks in the Consequences pass, in this order:
   the layer re-verification (check 11), the two machine leaves, the
   build-time checks (1 and 2), the QEMU-hosted mechanism checks (3
   to 7 and 12 to 15), then the board.  If a trial-boot entry does
   not rename from `+3` to `+2-1` under U-Boot's EFI loader (check
   4), U-Boot cannot burn a try, the sort-key fallback never fires,
   option (a) has no rollback, and this ADR is void; the design of
   record then reverts to option (b) with the SECURITY.md regression
   it already owes.
3. The U-Boot configuration is an explicit fragment in meta-lamadist
   (a `COMPATIBLE_MACHINE`-scoped `u-boot` bbappend), never a reliance
   on ARMv8 defaults, and it removes every boot path that Secure Boot
   does not cover:
   - on: `EFI_LOADER`, `CMD_BOOTEFI`, `EFI_BOOTMGR`,
     `BOOTMETH_EFI_BOOTMGR`, `BOOTMETH_EFI`, `FS_FAT`, `FAT_WRITE`,
     `FAT_RENAME`, `EFI_SECURE_BOOT`, `EFI_VARIABLES_PRESEED` with a
     generated seed, `ENV_IS_NOWHERE`;
   - off: `BOOTMETH_EXTLINUX`, `BOOTMETH_SCRIPT`,
     `BOOTMETH_EXTLINUX_PXE`, `BOOTMETH_PXE`, `BOOTMETH_VBE` and
     `BOOTMETH_VBE_SIMPLE`, `BOOTMETH_ANDROID`, `CMD_BOOTI`,
     `CMD_BOOTM`, `CMD_BOOTZ`, `CMD_BOOTELF`, `CMD_GO`, `CMD_MEMORY`
     (or `CMDLINE=n` outright), every `ENV_IS_IN_*` and
     `ENV_IMPORT_*` option, `EFI_RT_VOLATILE_STORE`,
     `EFI_MM_COMM_TEE`;
   - `boot_targets` pinned to the shipping medium only; autoboot
     non-interruptible (`AUTOBOOT_KEYED` with `AUTOBOOT_ENCRYPTION`,
     `bootdelay=-2`, or no CLI); `fdtfile` empty so U-Boot's
     device-tree-from-medium lookup never runs.
   - The variable store is `EFI_VARIABLE_NO_STORE`.  The preseed
     works without the file store, LamaDist needs no persisted
     `Boot####`/`BootOrder` because systemd-boot lives at the
     removable-media path, and the file store would keep an
     attacker-writable file in U-Boot's pre-verification path.  A
     leaf may choose `EFI_VARIABLE_FILE_STORE` only with a written
     reason in its header.
   - The seed is a build artifact generated from the same PK/KEK/db
     the x86_64 gate enrolls (`files/sb-dev/` today, whose `.esl`
     files the `regen-dev-sb-keys.sh` script already produces;
     production custody stays M6), so both platforms share one key
     hierarchy; it is never a checked-in binary.  The generator
     (U-Boot's in-tree `tools/efivar.py`, GPL-2.0-only build tooling
     under the copyleft policy, or a dump from a U-Boot run) is the
     kill-switch spike's first task.
4. The trust statement for both boards is written with explicit
   actors, in its unfused form, for production keys, and nothing
   stronger is claimed:
   - An attacker who can only write the ESP or supply removable
     media is stopped: U-Boot starts no UKI that is not signed by the
     project db, and no other boot path exists in the shipped U-Boot.
   - An attacker with OS root in any domain that can open the
     whole-disk node -- today that includes the OTA writer -- is NOT
     stopped.  The preseeded db lives in the raw loader sectors of
     the same block device as the OS, with no write protection and
     no SELinux type separating the whole-disk node from its
     partitions, so such an attacker can replace U-Boot and with it
     db.  This is strictly weaker than x86_64, where PK/db live in
     firmware NVRAM the OS cannot rewrite.  Two corollaries are
     recorded as M6 items: a distinct SELinux type for the whole-disk
     node that no runtime domain may write, and the observation that
     on these boards the RAUC bundle-signing key has PK-equivalent
     power and needs PK-equivalent custody.
   - An attacker who holds the media or the board is not stopped:
     nothing verifies U-Boot, the DDR TPL, BL31, or BL32.
   - dbx is immutable (the preseed write-protects it) and key or
     image revocation is not available in the field on the first
     port: no OTA element can write the loader sectors, U-Boot has no
     A/B or torn-write story, and a bench reflash is undone by the
     same raw write the second bullet concedes.  Designing a U-Boot
     update path (loader regions as partitions, a RAUC raw slot, SPL
     backup-load behaviour, torn-write consequences) is an M6
     prerequisite for any production key rotation.
   - Runtime `SetVariable` is unsupported: `bootctl set-default` and
     `set-oneshot` do not work, and the `LoaderSystemToken` random
     seed does not persist.
   - Boards preseeded with the development keys in `files/sb-dev/`
     have no Secure Boot property at all, since the private keys are
     in the tree; they are functional test articles, mirroring
     SECURITY.md's existing development-keys section.
   - `SecureBoot=1` on these boards is the enforcement mechanism, not
     a root of trust.  The validator and the gate emit a per-platform
     anchor tag beside the assertion ("anchor: firmware NVRAM" on
     x86_64; "anchor: none, unfused loader" here), so a green board
     run never reads like a green x86_64 run.  ADR 0012 decision 3
     applies to the boards as it does to QEMU.
5. OTP fusing is out of scope for M5.  It needs a sacrificial RK3588
   board, an answer to whether the closed signing tool accepts a
   mainline-built loader, SPL FIT signature enforcement with an
   embedded key so that the signed `u-boot.itb` configuration covers
   U-Boot, BL31, and BL32, and an upstream OP-TEE platform port that
   RK3566 does not have.  Until a board is fused, no document, CI
   job, or validation check may cite `SecureBoot=1` as a root of
   trust.
6. The first port ships with no TPM and no OP-TEE dependency.  The
   fTPM is a separate, later spike pinned to the RK1, the only board
   with an upstream OP-TEE port, an OTP driver, and an open
   secure-boot path.  It is built as `TPM2_FTPM_TEE` beside the
   preseed, never as `EFI_MM_COMM_TEE`, which the preseed excludes.
   Its prerequisites are stated up front: a from-source OP-TEE in
   place of the rkbin BL32, eMMC RPMB provisioning (a one-way key
   write), and the OTP write of the hardware unique key that the
   upstream rk3588 port performs at first use -- so the spike is an
   OTP-writing spike, and "burns no fuse" holds for the first port
   only.  On an unfused board an fTPM cannot restore `/var`
   confidentiality against a device holder, because whoever can load
   their own U-Boot can extend the expected values into the real
   fTPM and unseal; its PCR policy is re-chosen for a chain whose
   first measured object is what U-Boot loads, and PCR 7 is not
   reused.  An RK3566 fTPM would be a new upstream OP-TEE port and is
   not planned.
7. `/var` on the boards is LUKS2 unlocked without a TPM, the state
   `vm --no-tpm` models, and the build gains the seam that state
   lacks today: the crypttab line becomes machine-conditional
   (`tpm2-device=auto` only on machines with the `tpm2` feature),
   `lamadist-luks-var` drops `tpm2` from its required features or
   splits the enrollment half out, and `lamadist-var-tpm2-enroll.service`
   and every other TPM-dependent unit are conditioned on TPM presence
   so a missing TPM never trips the health gate's degraded check.
   x86_64's TPM-only line is unchanged.  The fallback secret's shape
   is an owner decision (a per-device key generated at first boot
   into a plain partition; a recovery passphrase only; or the
   existing shipped development keyfile), and SECURITY.md states the
   honest consequence of the choice: with a shipped key, `/var` is
   not confidential against anyone who can read the storage or the
   image, not merely against a device holder.  The fallback is
   designed and tested against `vm --no-tpm` before the first board
   image.
8. Port order stays SOQuartz first, RK1 second.  The boot chain is
   the same fragment on both boards and depends on nothing RK1 has
   that RK3566 lacks; the fTPM spike, which does, is RK1-only and is
   not on the first port's critical path.  The owner accepts that
   SOQuartz has no planned fTPM at all and ships permanently in the
   `vm --no-tpm` state unless someone writes the upstream port.  A
   plain extlinux boot of the kernel and verity root may be used as
   a bring-up rung on either board, to separate SoC bring-up
   failures from EFI failures, but it is a rung and not a backend: it
   is a second, non-shipping U-Boot configuration and loader
   artifact, no RAUC integration, no env partition plumbing, and no
   shipping image is ever built from a U-Boot that has any non-EFI
   boot method compiled in.
9. Vendor and community UEFI firmware is adopted as a boot backend
   only when four tests hold: an upstream platform port we do not
   author, a recipe in a layer we already pin, an unattended firmware
   update path with a rollback story (capsule plus ESRT or
   equivalent), and documented variable custody that survives a
   firmware update.  Tegra's EDK2 meets the first three; edk2-rk3588
   meets only the fourth; quartz64_uefi meets only the first.
   Rockchip vendor UEFI is closed until an upstream Turing RK1
   platform lands in edk2-rk3588 with a tagged release and a capsule
   path.
10. The first machine leaf neutralises what meta-rockchip's SoC
    includes wire toward the competing boot path, explicitly rather
    than by omission: `KERNEL_IMAGETYPE = "Image"` and
    `KERNEL_CLASSES` without `kernel-fitimage` (a fitImage cannot be
    a UKI payload); `UBOOT_EXTLINUX = "0"` and `u-boot-extlinux` and
    `kernel-image` removed from `MACHINE_ESSENTIAL_EXTRA_RDEPENDS`;
    no `rk-u-boot-env` machine feature; `RK_RAUC_DEMO` unset; a
    LamaDist Rockchip WKS (fixed-sector prelude at the upstream
    offsets, the vendor-storage region left untouched, then the same
    ESP labelled `msdos`, A/B raw verity slots, and LUKS2 `var` the
    x86_64 WKS builds, with `--ondisk` re-targeted to the boot
    medium); `SERIAL_CONSOLES` and `LAMADIST_CONSOLES` set so that
    U-Boot's EFI console, systemd-boot's menu, the kernel command
    line, and the getty name one UART and baud; and a kernel
    configuration audit that the `remove-non-rockchip-arch-arm64.scc`
    feature and `alldefconfig` mode leave efivarfs, IMA, SELinux, and
    the other meta-lamadist fragments in the built `.config`.  The
    `virtual/bootloader` seam is an open decision: either the shared
    include weakens its provider assignment to `?=` and the leaf
    names `u-boot`, or U-Boot enters the image purely through the WKS
    rawcopy dependencies with `virtual/bootloader` left as
    systemd-boot.  The leaf header carries the decision 4 trust
    statement in one sentence.
11. The ESP is the one un-redundant element on these boards: both
    slots' entries, the keyless `boot.conf`, and the loader itself
    live on one FAT volume that U-Boot's FAT writer touches on every
    boot.  `loader.conf` sets `random-seed-mode off` to remove the
    per-boot write (the seed cannot persist without runtime
    `SetVariable` anyway); the counter rename is the only write left.
    SECURITY.md and docs/OTA.md record the ESP as the un-redundant
    element, and kill-switch check 15 soaks it.

## Alternatives considered

- (b) U-Boot extlinux/FIT with a U-Boot-env boot counter and RAUC's
  native `uboot` backend, the M5 review's design of record.  Keeps
  the bundle format and signing, the raw A/B slot layout, the health
  predicate, the `rauc-mark-good` mask, and the five-point contract.
  Loses the UKI trust pivot (the verity roothash rides an unsigned
  `extlinux.conf`, which is a dm-verity bypass surface and a standing
  violation of the Storage Immutability Spec that would need a dated
  exception), the five-verb backend, the ESP state machine and
  sort-key primary encoding, the bundle hook, efivarfs and with it
  the installer's trust gate and the validator's Secure Boot
  assertion, ADR 0006's single-signed-UKI installer and ADR 0007's
  enrollment, and PCR 7.  Costs a second backend class and machine
  include, the uboot_env partition, `libubootenv` on RAUC's path with
  `/etc/fw_env.config`, an SELinux grant for the rauc domain to write
  a raw block device, a boot script that must not copy
  `contrib/uboot.sh` (its exhaustion path resets both counters and
  loops), the deferred `rauc-conf` templating and pending-probe
  helper unfrozen as hard prerequisites, and a QEMU gate that does
  not exist, which ADR 0012 priced at an order of magnitude above
  estimate.  On an unfused board its trust claim equals option (a)'s,
  which is none below U-Boot, and its upgrade path to verified boot
  (FIT signing) still leaves the kernel command line outside the
  signature.  Rejected as the shipping backend; retained as the
  fallback named in decision 2 and as a bring-up rung.
- (c) A community EDK2 firmware.  No port exists for the RK1, the
  exit-criteria board; the SOQuartz port has no Secure Boot; neither
  has capsule or ESRT (firmware update is `sf updatefile` from a UEFI
  shell, with no rollback), a TPM stack, or a Yocto recipe, and both
  still consume the rkbin DDR and BL32 blobs.  Adopting it would mean
  two unrelated firmware upstreams, one of them untagged since
  2025-04, in the most trust-critical position of the stack,
  validated first on the board that does not have to prove it.
  Rejected under decision 9.  One idea carries over: edk2-rk3588
  keeps its variable store outside the flashed image so settings
  survive a firmware update; under the preseed a U-Boot update
  rewrites the trust anchors by design, which decision 4 records as
  the only revocation mechanism and as unavailable in the field.
- Preseed plus StandaloneMM in OP-TEE for a writable authenticated
  store: mutually exclusive in Kconfig, needs a from-source OP-TEE
  with dynamic shared memory and RPMB on both SoCs, and RK3566 has no
  upstream OP-TEE port.  Deferred with the fTPM spike; not a
  first-port option.
- `EFI_VARIABLE_FILE_STORE` as the default: keeps an
  attacker-writable `ubootefi.var` in U-Boot's pre-verification path
  and lets an ESP-only attacker pin boot to any db-signed image via
  `Boot####`/`BootOrder`, for no property the OTA needs.  Rejected as
  the default; allowed per leaf with a written reason.
- `EFI_RT_VOLATILE_STORE` to keep `bootctl set-default` working: buys
  nothing the OTA path needs, refuses authenticated variables, does
  not persist, and lets a compromised OS mutate the in-RAM variable
  view.  Rejected.
- A second QEMU profile member for U-Boot.  ADR 0012 decision 1 keys
  profiles to the backend and this decision keeps one backend, so no
  member is added.  A U-Boot `qemu_arm64` firmware payload under the
  existing `sdboot-uki` profile (a `vm --firmware u-boot` flag, AAVMF
  untouched) is the cheapest place to run the rename, preseed,
  tamper, and boot-path checks with no board; it proves U-Boot's EFI
  implementation at the pinned tag, never the SoC, and its results
  are never cited in SECURITY.md, the validator, or CI as a board
  property.  The `qemu_arm64` defconfig differs materially from the
  board fragment, so every check re-runs against the board `.config`
  before board work proceeds.  Recommended; needs an explicit go.

## Consequences

- What the boards inherit unchanged from x86_64: `lamadist-uki` and
  `lamadist-esp-slot-a`, the ESP layout and fstab entry, the
  five-verb backend, the health gate including its network guard,
  `system.conf` and the `bootloader=custom` handler, both
  slot-manager masks, the bundle hook and `bootfiles.tar`,
  `ota_test.py`, docs/OTA.md, efivarfs built in, the validator's
  Secure Boot assertion, and the deferred status of the `rauc-conf`
  templating and pending-detection rewrite, whose trigger is now
  Tegra alone.  What is new: a machine-scoped `u-boot` bbappend with
  the EFI fragment, a preseed generator, the device-tree plumbing in
  `lamadist-uki.bbclass`, two machine leaves that are thin only
  relative to a board with an upstream machine (each supplies the
  U-Boot defconfig name, `KERNEL_DEVICETREE`, `MACHINE_FEATURES`, the
  SoC include, `IMAGE_FSTYPES`, and `WKS_FILE`, plus the decision 10
  neutralisations), a Rockchip WKS, the no-TPM crypttab seam, and a
  flashing procedure (the first ARM deliverable is a flashed image;
  the board's existing loader and the USB maskrom recovery path are
  documented with it).  docs/PARTITIONING.md is corrected in both its
  Rockchip and x86_64 sections to the shipped layouts before it is
  cited again.
- What the boards lose relative to x86_64: runtime `SetVariable`
  (`bootctl set-default`, `set-oneshot`, a persistent
  `LoaderSystemToken`), an in-place dbx and any field revocation, a
  firmware-held trust anchor, `GetTime` without an RTC driver (an RK8xx
  PMIC RTC driver is an open item for EBBR conformance), any display
  before Linux (no GOP; systemd-boot is serial-only), PCR 7, and the
  TPM-sealed `/var`.  The installer's enrollment stage does not port:
  ADR 0007's efivarfs `.auth` writes are unsupported and unnecessary,
  since the keys ship inside U-Boot.  The stick's own boot path on
  Rockchip is undesigned; docs/PLAN.md's "enrollment is the only
  x86-specific piece" is corrected and the installer port is deferred
  past M5.
- Proprietary surface and fuses: the first port runs the rkbin DDR
  TPL, BL31, and BL32 if the SPL FIT configuration packs it (check
  10 decides; leaving it out is preferred), none of them auditable
  under the rkbin licence, and burns no fuse.  Replacing BL32 with a
  from-source OP-TEE for the fTPM improves that surface by one blob
  and is itself OTP-writing (decision 6).
- Threat-model items this ADR records but does not close:
  pre-verification parsing of attacker-controlled input (FAT metadata
  and PE headers remain after the fragment removes the rest); node
  serial consoles reachable through a cluster carrier's management
  controller, which makes an interruptible autoboot a
  network-reachable attack, hence the non-interruptible requirement;
  the USB maskrom path, which rewrites all storage on an unfused
  board; no anti-rollback for U-Boot or for previously signed UKIs;
  availability, where an ESP-only attacker can burn every counter and
  force the keyless `boot.conf` loop (parity with x86_64, reachable
  through more media here); and the health gate as a rollback oracle,
  so every x86_64 unit that a board cannot satisfy (TPM enrollment,
  efivars writers, `tee-supplicant` later) is conditioned rather than
  left to fail.
- Cost in layers, recipes, and CI: no new layer; meta-rockchip stays
  the vendor layer for SoC includes, kernel, and rkbin, and provides
  nothing for UEFI while actively wiring the competing path, which
  decision 10 undoes.  Recipes: one bbappend and fragment, one seed
  generator, two machine confs, one WKS, the crypttab seam, and the
  UKI device-tree plumbing.  CI: the qemuarm64 gate keeps covering
  the boards' actual backend logic; the two board targets build in
  CI and do not boot there; the optional U-Boot firmware payload
  under `vm` adds one U-Boot build and one job variant.  Option (b)
  would instead have opened three subsystems (image classes, RAUC
  runtime, installer) and deleted the fourth's coverage.
- Kill-switch checks, each of which voids or amends this ADR on the
  observation named.  Order: 11, then the leaves, then 1 and 2, then
  3 to 7 and 12 to 15 under the U-Boot QEMU payload, then 8 to 10 and
  every check again on the first board.
  1. The built U-Boot `.config` lacks `CONFIG_FAT_WRITE`,
     `CONFIG_FAT_RENAME`, `CONFIG_EFI_SECURE_BOOT`,
     `CONFIG_EFI_VARIABLES_PRESEED`, or `CONFIG_ENV_IS_NOWHERE`, shows
     any boot method or command from decision 3's off list, or
     shows a store other than `EFI_VARIABLE_NO_STORE` without the
     leaf's written reason.
  2. The EFI-enabled `u-boot.itb` or `u-boot-rockchip.bin` no longer
     fits the loader2 slot, or SPL reports a load or verify failure.
  3. U-Boot does not launch `EFI/BOOT/BOOTAA64.EFI` from the ESP on
     eMMC or SD and reach systemd-boot's menu on the serial console.
  4. After one boot of a fresh `lamadist-<slot>+3.conf` the entry is
     still `+3` (no rename, no rollback: stop here).
  5. A UKI with bytes zeroed starts instead of being refused, or the
     sort-key fallback does not then boot the untampered slot.
  6. `setenv -e ... PK` from the U-Boot shell, or a foreign db written
     from Linux, changes db after a reboot; with `NO_STORE`, any
     `ubootefi.var` on the ESP is read at all.
  7. efivarfs does not mount or `SecureBoot` does not read 1 in the
     guest, so the validator and the installer's trust gate lose their
     input (runtime `GetVariable` under `NO_STORE` is unverified).
  8. A full bundle install, forced-unhealthy trial, three burned
     tries, and fallback do not end with `rauc status` reporting the
     failed slot bad.
  9. A pending first boot reboot-loops on `/var` unlock without a
     TPM.
  10. `dumpimage -l u-boot.itb` shows a BL32 image the SPL FIT
      configuration requires: amends the blob-surface statement
      rather than voiding the decision.
  11. The meta-rockchip branch the leaves pin (wrynose, to be added to
      `soquartz.kas.yml`) ships a soquartz or rk1 machine, EFI wiring,
      or a from-source OP-TEE for these SoCs; every meta-rockchip fact
      above came from the scarthgap checkout and is re-verified first.
  12. With the shipping U-Boot, an `extlinux.conf` plus unsigned
      kernel on the ESP or a USB stick boots, a `boot.scr` runs, or
      autoboot can be stopped from the serial console.
  13. A crafted environment written at the upstream env offset, or a
      `uboot.env` on the ESP, changes any boot behaviour.
  14. A modified `dtb/<fdtfile>` on the ESP appears in
      `/proc/device-tree` after boot.
  15. N reboot cycles leave the ESP unclean under `fsck.vfat`, or a
      power cut during a trial boot's rename leaves it unmountable.
- docs/PLAN.md M5 review decisions 2 and 3 are annotated as
  superseded for Rockchip by this ADR; the `lamadist-boot-uboot.inc`
  and uboot_env checkboxes are rewritten; the Storage Immutability
  Spec's ARM clause changes from "the signed FIT on ARM" to "the
  signed UKI on Rockchip"; SECURITY.md gains the Rockchip chain, the
  decision 4 statement, the anchor-location table, and the new known
  gaps, and drops FIT signing from its portability paragraph; the
  header comments of `lamadist-boot-sdboot-uki.bbclass` and its
  machine include stop promising a second backend class per platform;
  `kas/bsp/soquartz.kas.yml` gains the meta-rockchip branch pin that
  review decision 4 requires.
- Tegra is untouched: its EDK2, L4TLauncher, and nvbootctrl design
  stays speced and gated as the M5 review left it, and decision 9 is
  the rule it is measured by.

## Open decisions for the owner

1. The variable store: `EFI_VARIABLE_NO_STORE` as decided, or the
   file store with its OS-rewritable boot options.
2. The `virtual/bootloader` seam on the Rockchip leaves (decision
   10): weaken the shared include, or pull U-Boot through the WKS
   dependencies only.
3. The no-TPM `/var` fallback secret (decision 7): per-device key,
   recovery passphrase, or the shipped development keyfile, and the
   SECURITY.md sentence that goes with it.
4. Whether unfused boards with `SecureBoot=1` as enforcement only
   satisfy the M5 exit criteria, and whether a sacrificial RK3588
   board is budgeted for the fuse experiment.
5. Revocation: accept "not available in the field" for the first
   port, or pull the U-Boot update path (decision 4) into M5.
6. The `vm --firmware u-boot` QEMU payload: go or no-go.
7. SOQuartz permanently without an fTPM (decision 8).
8. The first ARM deliverable as a flashed image only, with the
   installer port deferred past M5.
9. Console UART and baud per board, and whether to enable the RK8xx
   PMIC RTC driver on SOQuartz.
