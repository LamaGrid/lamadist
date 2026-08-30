# Flashing LamaDist to a Lab Machine

**Scope: dedicated lab/test machines only.**  This procedure enrolls
the repository's public development Secure Boot keys into real
firmware, which is permitted only under the lab-machine exception in
`meta-lamadist/files/sb-dev/README.md` (operator-approved
2026-08-30).  Secure Boot on the resulting machine exercises the
verification machinery but authenticates nothing; the machine may
hold no production data or duties.

This is the increment 1 (raw-image) installer flow: the target
firmware must trust the LamaDist keys BEFORE the stick boots,
because in-flow enrollment is a later increment.  There is no
digest gate over the enrollment inputs in this increment either:
the certificate files you enroll by hand in step 3 ARE the root of
trust, so keep the stick and the target machine in your physical
custody from flashing through the end of first boot.  The full
operator manual ships on the stick's payload partition as
`MANUAL.md`.

The installer stick is self-contained: it carries its own live
userland (the full kernel module set with udev coldplug, so
Non-Volatile Memory Express (NVMe) targets, USB input, and display
are covered), the payload image, and -- after step 2 -- the
enrollment certificates.  No separate live Linux environment is
needed to install.  A generic live USB is still handy for two edge
cases: flashing the stick somewhere the build host is not, and the
Platform Configuration Register (PCR) 7 recovery in
troubleshooting.

## What you need

- The build host with this repository and a completed
  `mise run installer --hw-console` build (step 1).
- A USB stick, 2 GB or larger, for the installer.  Its contents
  are destroyed.
- The lab machine: Intel x86_64 with Unified Extensible Firmware
  Interface (UEFI) firmware, a Trusted Platform Module (TPM) 2.0,
  and an internal disk of 12 GiB or more (the payload decompresses
  to about 9 GiB).  Everything on that disk is destroyed.

## Step 1: build the hardware-console stick

The default installer build is the QEMU variant, whose prompts go
to the serial port.  Physical machines need the graphics-primary
variant:

```sh
mise run installer --hw-console
```

Add `--headless-auto` to bake the auto-target manifest onto the
stick: it then installs to the sole eligible internal disk with
ZERO prompts on boot -- label such a stick and treat it as the
destructive tool it is.

Test builds also bake a build-host-cached Secure Shell (SSH)
public key (`.local/share/lamadist/test-ssh/id_ed25519.pub`,
generated on first build, never committed) as an authorized key
for `lama`, so the installed system is reachable with
`ssh -i .local/share/lamadist/test-ssh/id_ed25519 lama@<host>`.
The rootfs is read-only; keys enter at build time only
(`LAMADIST_SSH_AUTHORIZED_KEYS`).

This applies `kas/extras/hw-console.kas.yml` and skips the QEMU
install test (the serial harness cannot drive a graphics-primary
stick).  Artifact, about 1.5 GB:

```text
deploy/images/intel/lamadist-installer-image-intel.wic
```

That path is a symlink to the newest timestamped build.  Flash
right after building, or resolve it first (`readlink -f`) and keep
the timestamped file: a later plain `mise run installer` run
repoints the symlink at a QEMU serial-console stick.

## Step 2: flash the stick

On the build host, with the stick plugged in:

```sh
# Identify the stick -- confirm by size/model before writing:
lsblk -o NAME,SIZE,MODEL,TRAN

# Write the image (DESTROYS the stick):
sudo dd if=deploy/images/intel/lamadist-installer-image-intel.wic \
        of=/dev/sdX bs=4M oflag=direct conv=fsync status=progress
sync

# Optional: move the backup GUID Partition Table (GPT) header to
# the end of the stick.
# Harmless to skip; some firmware complains about the mid-stick
# backup header.
sudo sgdisk -e /dev/sdX

# Re-read the new partition table:
sudo partprobe /dev/sdX
```

Then place the enrollment certificates on the stick's EFI system
partition (ESP, partition 1, FAT32) so the firmware file browser
can reach them in step 3:

```sh
sudo mount /dev/sdX1 /mnt
sudo mkdir -p /mnt/keys
sudo cp meta-lamadist/files/sb-dev/pk.cert.der \
        meta-lamadist/files/sb-dev/kek.cert.der \
        meta-lamadist/files/sb-dev/db.cert.der /mnt/keys/
sudo umount /mnt
```

Optional, for a headless install (skip when the stick was built
with `--headless-auto` -- the manifest is already baked in): mount
the payload partition (partition 2, ext4, label `lamadist-payload`)
and create a `manifest.env` from the `manifest.env.sample` beside
it.  Set `HEADLESS=yes` and either an explicit
`TARGET_DISK=/dev/disk/by-id/...` with a byte-identical `CONFIRM=`,
or `TARGET_DISK=auto` / `CONFIRM=auto` when the lab machine has
exactly one eligible disk.

## Step 3: configure the lab machine's firmware

Enter firmware setup on the lab machine, with the stick plugged in:

1. Disable legacy boot (Compatibility Support Module, CSM); the
   image is UEFI-only.
2. Enable the TPM 2.0 device.
3. Enroll the LamaDist keys with the firmware's Secure Boot key
   management.  WARNING, before clearing anything: if the machine
   boots through a discrete graphics processing unit (GPU) or an
   add-in storage controller, their option ROMs are likely signed
   only by the Microsoft UEFI certificate authority (CA); clearing
   that CA from db can kill all display output -- including the
   firmware setup UI on a discrete-GPU-only system -- and recovery
   is then a CMOS reset (clearing all firmware settings).  Locate
   the firmware's "restore factory keys" option first so you know
   the way back.  Then clear the existing keys (or switch to
   custom key management),
   and enroll from the stick's `keys/` directory in this order:
   `db.cert.der` as db, `kek.cert.der` as Key Exchange Key (KEK),
   and `pk.cert.der` as Platform Key (PK) LAST -- writing the PK
   is what leaves setup mode.
4. Enable Secure Boot.  Do NOT select any "Standard" mode or
   "restore default keys" option -- on common AMI firmware,
   "Standard" restores the factory keys and silently discards the
   step 3 enrollment.  The enrolled state is typically labeled
   "Custom", "User", or "Deployed" mode.
5. Save and exit.

Firmware menus differ; some accept only `.auth` payloads or want
the files at the stick root.  The `.esl` forms of the same keys are
in `meta-lamadist/files/sb-dev/` if your firmware prefers raw EFI
Signature Lists.

## Step 4: run the installer

1. Boot the lab machine and pick the stick in the firmware boot
   menu.
2. The installer verifies Secure Boot is enforcing and checks the
   payload checksum; prompts appear on the screen (the
   hardware-console build from step 1).
3. It lists eligible internal disks; the stick itself and removable
   media are excluded.
4. Type the target device path, then type it again to confirm.
   THIS ERASES THE WHOLE DISK.
5. The image is written and verified.  The installer registers the
   installed disk with the firmware (a "LamaDist" boot entry, first
   in the boot order and set as the next boot), so a USB-first boot
   order does not re-enter the stick.  Remove the stick and press
   Enter to reboot.

A headless manifest (a `--headless-auto` build, or step 2)
replaces all prompts, including the final one: the machine reboots
on its own three seconds after the write completes.  Pull the
stick during that pause or at the firmware splash.  A malformed
manifest aborts before any write.

## Step 5: first boot and verification

Leave the machine alone through its first boot: it formats `/var`
as a Linux Unified Key Setup (LUKS2) volume, seals the key into
the TPM against PCR 7, seeds `/var`, and relabels for SELinux.
Do not
change any firmware Secure Boot setting from now on, and treat
firmware (BIOS) updates as sealing-breaking events too: PCR 7
binds the volume to the step 3 configuration, and there is no
automatic fallback when it shifts (see troubleshooting).

Then log in on the console as `lama` (dev-image password
`lamadist`; sudo via the wheel group, root login is locked) and
verify:

```sh
bootctl status            # "Secure Boot: enabled"
getenforce                # "Enforcing"
lsblk --fs                # /var on a crypt device
systemctl --failed        # no failed units
```

The same checks work over the network with the baked test key
(step 1), once you know the machine's address:

```sh
ssh -i .local/share/lamadist/test-ssh/id_ed25519 lama@<address>
```

One caveat on what step 5 buys you: dev images carry a standing
LUKS keyslot for the in-repo keyfile
(`meta-lamadist/recipes-core/luks/files/dev-var.key`, baked at
`/etc/lamadist/dev-var.key`; SECURITY.md, W11), so `/var` on this
machine is offline-decryptable by anyone with a repo clone.
Stolen-disk protection does NOT hold; this is another reason the
no-production-data rule applies.

## Troubleshooting

- **"Secure Boot is not enabled ... refusing to install"**: step 3
  was incomplete.  Enable Secure Boot, or re-enroll the keys.  The
  `lamadist.installer.insecure` bypass exists but MUST NOT be used
  when the installed system is kept: sealing with Secure Boot off
  and enabling it later guarantees a PCR 7 unseal failure.
- **Installer prompts never appear on screen**: the stick is the
  QEMU serial-console build.  Rebuild with
  `mise run installer --hw-console` and reflash.
- **The stick does not boot at all**: the firmware does not trust
  the LamaDist db key (redo step 3), or CSM is still on.
- **No disks listed**: the installer only offers fixed, writable
  internal disks; check the disk is visible to the firmware and
  not connected via USB.
- **The internal disk is rejected as "not an eligible target
  disk"**: sticks built before 2026-08-30 identified themselves by
  a global filesystem-label lookup, and a stale `lamadist-payload`
  label on the internal disk could capture it, excluding the
  internal disk as "the stick".  Rebuild and reflash; current
  sticks identify themselves by the boot device
  (`LoaderDevicePartUUID`), which another disk cannot claim.
- **"cloned boot medium" abort**: a byte-for-byte copy of this
  exact stick image exists on another attached disk (same GPT
  partition UUIDs), so the boot-device anchor is ambiguous and the
  installer refuses to guess.  Wipe the copy's signatures
  (`wipefs -a /dev/<copy>`, available in the rescue shell) or
  unplug it, then reboot the stick.
- **The machine reboots back into the installer**: the stick is
  still inserted, the firmware boots USB first, and the stick
  predates the 2026-08-30 `BootNext` fix (or its
  `efibootmgr ... left unchanged` warning fired).  Remove the
  stick, or put the internal disk first in the firmware boot
  order; reflash with a current stick for the automatic fix.
- **First boot hangs or reboot-loops**: the TPM was slow or absent
  during provisioning (SECURITY.md, known gaps).  Recovery needs
  console access; check the TPM is enabled and retry a fresh
  install.
- **`/var` stops unlocking after a firmware (BIOS) update or a
  Secure Boot settings change**: PCR 7 moved and the TPM no longer
  unseals; there is no automatic fallback.  Recover data by
  unlocking with the dev keyfile from a live environment
  (`cryptsetup open --key-file dev-var.key /dev/<var-part> var`),
  or reinstall.
