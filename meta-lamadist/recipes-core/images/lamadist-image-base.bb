# SPDX-License-Identifier: Apache-2.0

DESCRIPTION = "LamaDist base image"

inherit lamadist-image

# Local SELinux policy module (M4 stage B, W12): no IMAGE_INSTALL entry.
# lamadist is no longer a separate package with a rootfs-time `semodule
# -i` postinst (that offline chain kept failing on native-tool
# relocation -- HLL pp, then setfiles).  It is now built and linked into
# refpolicy-targeted's monolithic policy at refpolicy build time by the
# refpolicy-targeted bbappend (meta-lamadist/recipes-security/refpolicy),
# so it ships inside the refpolicy package the distro already installs
# (PREFERRED_PROVIDER_virtual/refpolicy + packagegroup-core-selinux in
# lamadist-security.inc) and is in the policy store before
# selinux-image.bbclass's build-time setfiles pass labels the rootfs --
# active from the very first (enforcing) boot.

# Boot backend.  The machine leaf selects LAMADIST_BOOT_BACKEND (x86
# = "sdboot-uki") and the backend class bundles the build-time pieces
# in order: the per-slot Unified Kernel Image build
# (lamadist-a.efi/-b.efi, consumed by the RAUC bundle and ESP staging)
# then slot A's ESP boot content.  A second platform sets a different
# backend without touching this recipe; the distro layer holds only
# boot-invariant policy.  See classes/lamadist-boot-sdboot-uki.bbclass
# and conf/machine/include/lamadist-boot-sdboot-uki.inc.
#
# No default backend: a machine leaf MUST select one in its
# boot-backend include.  Without it this inherit resolves to the
# missing class "lamadist-boot-" and fails at parse -- fail-closed on
# purpose, so a machine that forgets the include cannot silently build
# an unsigned image off the backend class's empty-key defaults.
inherit lamadist-boot-${LAMADIST_BOOT_BACKEND}

# /etc becomes a writable overlayfs upper layer backed by the
# LUKS-mapped /var partition, so runtime config changes persist
# across reboots while the erofs/dm-verity root stays sealed.  Per
# D5 (M4 plan): app-data overlays are a later milestone -- only /etc
# here.  This does NOT use oe-core's overlayfs-etc.bbclass: that
# class's only mechanism replaces /sbin/init with a preinit script
# that mounts OVERLAYFS_ETC_DEVICE and execs the real init
# afterward -- i.e. it runs BEFORE systemd ever starts.  But
# /dev/mapper/var is created BY systemd (systemd-cryptsetup@var,
# generated from lamadist-image.bbclass's crypttab entry, backed by
# lamadist-luks-var's first-boot format service), so that device can
# never exist yet when such a preinit runs; D4 also keeps /var's
# LUKS unlock out of the initramfs, the only place earlier than
# systemd.  See lamadist_etc_overlay_unit in lamadist-image.bbclass
# for the systemd-unit-based mount this class uses instead, ordered
# after the fstab /var mount rather than mounting the device a
# second time.
