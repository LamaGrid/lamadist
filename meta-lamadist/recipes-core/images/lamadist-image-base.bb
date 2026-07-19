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

# Builds the per-slot Unified Kernel Images (lamadist-a.efi,
# lamadist-b.efi) the RAUC bundle and ESP staging consume; see
# classes/lamadist-uki.bbclass.  Must be inherited before
# lamadist-esp-slot-a below: both append to do_image_wic[prefuncs],
# and bitbake runs that list in inherit order -- lamadist_uki_build
# has to run first so lamadist-a.efi exists in DEPLOY_DIR_IMAGE by
# the time lamadist_esp_slot_a_populate looks for it.
inherit lamadist-uki

# Seeds slot A's ESP boot content (kernel, initramfs, microcode,
# systemd-boot entry) at image build time; see
# classes/lamadist-esp-slot-a.bbclass.
inherit lamadist-esp-slot-a

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
