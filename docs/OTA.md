<!-- SPDX-License-Identifier: Apache-2.0 -->
# OTA Updates (M3 pass 1)

LamaDist updates are RAUC A/B bundles: the whole rootfs plus its
dm-verity hash tree, signed, written raw to the inactive slot.  A
systemd-boot boot-counting trial gates the new slot; a health check
commits it, and an unhealthy slot rolls back automatically after
three failed boots.  This document is the operator-facing
procedure; the design decisions live in the M3 plan and
[PARTITIONING.md](PARTITIONING.md).

## Building a bundle

The bundle recipe is `lamadist-bundle`
(`meta-lamadist/recipes-core/bundles/lamadist-bundle.bb`).  Build
the image first so the verity artifacts exist, then the bundle:

```sh
mise run build --bsp x86_64
mise run kas --bsp x86_64      # then, inside the container:
bitbake lamadist-bundle
```

The signed bundle lands in `deploy/images/<machine>/` as
`lamadist-bundle-<machine>-<timestamp>.raucb`.  Bundles are
`verity` format: RAUC verifies the signature and mounts the
squashfs payload through dm-verity before reading anything.

## Installing on a device

Spool the bundle somewhere on the writable `/var` partition --
NOT `/tmp` or `/var/tmp`, which are RAM-backed tmpfs (half the
machine's RAM) and cannot hold a multi-GB bundle:

```sh
sudo mkdir -p /var/cache/lamadist-ota
scp bundle.raucb <user>@<device>:/var/cache/lamadist-ota/
sudo rauc install /var/cache/lamadist-ota/bundle.raucb
sudo systemctl reboot
```

The install writes the inactive slot's `rootfs_<x>` and `hash_<x>`
partitions raw, stages the slot's kernel, initramfs, and microcode
under `ESP/lamadist/<x>/` (bundle hook), writes a boot-counting
loader entry `lamadist-<x>+3.conf`, and marks the slot primary.

## Commit and rollback

The freshly installed slot boots as a systemd-boot counted trial
(3 tries).  `lamadist-health.service` commits the boot by running
`rauc status mark-good` only when the system is healthy: systemd
`is-system-running` not degraded/failed and `sshd.socket` active.
Committing strips the entry's counter (renames it to the bare
`lamadist-<x>.conf`).

While the boot is still a pending trial, a failed health check
reboots the machine, burning one try.  After three failed trials
systemd-boot's boot assessment sorts the exhausted entry last and
the previous slot boots instead; `rauc status` then reports the
failed slot's boot status as `bad`.  Once a slot has been
committed, a later health failure only logs -- rebooting with no
counter left would loop, not degrade.

Primary-slot selection is encoded in the loader entries'
`sort-key` lines (`lamadist-10` primary, `lamadist-20` secondary),
NOT in a `loader.conf` `default` line: systemd-boot 259 matches
`default` without checking boot counting, which would pin a dead
slot forever.  See the header of
`meta-lamadist/recipes-core/rauc/files/systemd-boot-backend`.

## Signing keys

Bundles are dev-signed with the committed, intentionally public
development CA in `meta-lamadist/files/rauc-dev/` (CN "LamaDist
Development CA").  Every image built today trusts only that CA;
M6 owns real release signing.  `rauc-conf` also bakes a
DEVELOPMENT-ONLY forced-unhealthy hook
(`/var/lamadist-force-unhealthy`, gated on a rootfs marker) used
by the rollback test; release builds must set
`LAMADIST_OTA_TEST_HOOKS = "0"`.

## End-to-end test

```sh
mise run test-ota --bsp x86_64
```

Boots the newest WIC in QEMU (headless, snapshot), installs the
newest bundle twice: once cleanly (asserts the reboot lands on the
new slot and health commits it), then again with the
forced-unhealthy flag set (asserts the boot-counted trials burn
out and the machine rolls back to the previous slot, with the
failed slot marked bad).  Needs `sshpass` on the host.  On
failure the full serial transcript is preserved at
`.cache/agents/ota-serial-fail.log`.

## Known limitations (pass 1)

- Full-image bundles only; adaptive (casync) delta updates and
  CMS-encrypted bundles are M3 pass 2.
- Slots are written to raw partitions; LUKS-backed slots (writing
  through decrypted mapper devices) arrive with M4.
- If BOTH slots' entries are ever exhausted, the uncounted
  `boot.conf` entry (a copy of slot a's) is the last resort and
  the machine will loop rebooting unhealthy rather than degrade.
- The kernel console is not on ttyS0; boot messages are only
  visible on the VGA console (serial shows getty onward).
