# LamaDist Installer -- Operator Manual

This manual ships on the installer stick's payload partition.  It is
a convenience copy; treat printed URLs and procedures as
authoritative only from an out-of-band source (SECURITY.md, installer
surface).

## What this stick does

Increment 1 (the review installer) writes the complete hardened
LamaDist disk image onto a target disk and reboots into it.  The
installed system provisions its own encrypted `/var` (LUKS2 + TPM2)
and relabels for SELinux on its first boot, exactly as the QEMU smoke
does.

## Before you boot (Secure Boot)

The installed system boots with UEFI Secure Boot enforcing, using the
LamaDist development keys.  The target firmware must trust those keys:

1. Enter firmware setup.
2. Either enroll the LamaDist PK/KEK/db (from the vault copy of these
   keys) via the firmware's key-management menu, or place the firmware
   in Setup Mode so the installer can enroll them.
3. If you cannot enroll keys, the installer refuses to proceed unless
   you pass `lamadist.installer.insecure` on its command line -- a lab
   escape hatch only.

Automated in-flow enrollment (userland `.auth` writes behind the
in-UKI digest gate) is the signing increment; increment 1 assumes the
keys are already enrolled (the review is done under QEMU with the
project's pre-enrolled OVMF variables).

## Interactive install

1. Select the stick in the firmware boot menu.
2. The installer verifies Secure Boot is on and checks the payload
   checksum.
3. It lists eligible target disks (the stick itself is excluded).
4. Type the device path (for example `/dev/sda`).  You will be asked
   to type it a second time to confirm.  THIS ERASES THE WHOLE DISK.
5. The image is written and verified; the installer creates a
   firmware boot entry for the installed disk, puts it first in the
   boot order, and sets it as the next boot, so a USB-first firmware
   does not re-enter the stick.  Remove the stick and press Enter to
   reboot.

## Headless install

Put a `manifest.env` on the payload partition (see
`manifest.env.sample`).  Set `HEADLESS=yes` and either an explicit
`TARGET_DISK=/dev/disk/by-id/...` with a matching `CONFIRM=`, or
`TARGET_DISK=auto` / `CONFIRM=auto` when the machine has exactly one
eligible disk.  A malformed, unknown-key, duplicate-key, or
CRLF manifest aborts before any write.

The headless reboot leaves the stick inserted.  The firmware
registration above makes the next boot (and the stored boot order)
point at the installed disk, but BootNext is one-shot and some
firmware re-prioritizes removable media on every boot -- remove the
stick promptly, or a later boot can re-enter the installer and
reinstall.  The install-consumed flag closing this durably is a
later increment.

## Recovery

The installed `/var` is unlocked by TPM2 on normal boots.  A stuck
first boot (slow or absent TPM) is recoverable only with console
access; see SECURITY.md.  The per-stick recovery-keyslot password and
the encrypted vault are the security increment and are not present in
increment 1.
