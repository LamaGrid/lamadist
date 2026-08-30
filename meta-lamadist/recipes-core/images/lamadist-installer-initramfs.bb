# SPDX-License-Identifier: Apache-2.0

DESCRIPTION = "LamaDist installer initramfs: a live installer userland \
in one image, wrapped into a signed installer UKI (ADR 0006).  \
Increment 1 writes the hardened full-disk image to the target and \
reboots; the installed system's first-boot units do LUKS2/TPM2/relabel."
LICENSE = "Apache-2.0"

inherit core-image

# A live installer, not a rootfs-pivot initramfs: no dmverity, no
# rootfs/finish modules.  The 50-installer module is terminal (it
# reboots into the installed system).
#
# License note (project copyleft policy): efibootmgr is
# GPL-2.0-or-later and its efivar dependency LGPL-2.1-or-later --
# standalone exec'd tools, merely aggregated in an initramfs that
# already ships coreutils (GPL-3.0-or-later); no linking into
# project code.  Alternatives (hand-rolled efivar device-path
# writes, bootctl set-oneshot) need a booted systemd or invite
# binary-format bugs; efibootmgr is the standard tool.
PACKAGE_INSTALL = "\
    initramfs-framework-base \
    initramfs-module-udev \
    initramfs-module-lamadist-installer \
    ${VIRTUAL-RUNTIME_base-utils} \
    base-files \
    base-passwd \
    udev \
    kmod \
    kernel-modules \
    cryptsetup \
    e2fsprogs-mke2fs \
    efibootmgr \
    util-linux-blkid \
    util-linux-blockdev \
    coreutils \
    xz \
"

# Keep the installer image minimal; no distro rootfs features, no
# locales, and never let a kernel land inside the initramfs (the UKI
# supplies the kernel separately).
IMAGE_FEATURES = ""
IMAGE_LINGUAS = ""
PACKAGE_EXCLUDE = "kernel-image-*"

IMAGE_NAME_SUFFIX ?= ""
IMAGE_FSTYPES = "${INITRAMFS_FSTYPES}"

# The installer runs entirely from RAM; give it room for the tools.
IMAGE_ROOTFS_SIZE = "65536"
IMAGE_ROOTFS_EXTRA_SPACE = "0"

# The installer initramfs is deliberately unlabeled (ADR 0006,
# SECURITY.md installer surface -- its only protection is the UKI
# signature).  It inherits core-image, not lamadist-image, so it never
# pulls selinux-image's build-time relabel or the refpolicy package.

COMPATIBLE_HOST = "(x86_64.*|aarch64.*)-(linux.*)"
