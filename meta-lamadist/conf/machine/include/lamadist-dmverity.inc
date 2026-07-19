# vi:ft=bitbake
# SPDX-License-Identifier: Apache-2.0
#
# Shared dm-verity machine defaults.
#
# Machine-specific dm-verity parameters: partition type GUIDs,
# block sizes, and hash separation.  Machines should require
# this file and override any values that need to differ.
#
# The distro-level dm-verity policy (IMAGE_CLASSES, KERNEL_FEATURES,
# INITRAMFS_IMAGE, INITRAMFS_FSTYPES, DM_VERITY_IMAGE,
# DM_VERITY_IMAGE_TYPE) is set in lamadist-security.inc.

DM_VERITY_SEPARATE_HASH ?= '1'

# systemd Discoverable Partitions Specification type GUIDs for the
# A/B root and verity-hash slots, keyed on the target architecture
# (TRANSLATED_TARGET_ARCH override: x86-64, aarch64) so leaf
# machine confs and kas overlays carry no per-machine GUID lines
# (M5 abstraction review: thin-leaf machine pattern).  Slot
# DISCOVERY is by PARTLABEL + the UKI-embedded roothash, not these
# GUIDs; they make the partition table self-describing per the DPS.
# A machine needing different values overrides with :${MACHINE}
# (machine overrides outrank arch overrides).
DM_VERITY_ROOT_GUID:x86-64 ?= '4f68bce3-e8cd-4db1-96e7-fbcaf984b709'
DM_VERITY_RHASH_GUID:x86-64 ?= '2c7357ed-ebd2-46d9-aec1-23d437ec2bf5'
DM_VERITY_ROOT_GUID:aarch64 ?= 'b921b045-1df0-41c3-af44-4c6f280d3fae'
DM_VERITY_RHASH_GUID:aarch64 ?= 'df3300ce-d69f-4c92-978c-9bfb0f38d820'

DM_VERITY_IMAGE_DATA_BLOCK_SIZE ?= '1024'
DM_VERITY_IMAGE_HASH_BLOCK_SIZE ?= '4096'

# Fixed sizes for the A/B rootfs/hash slot partitions (see
# meta-lamadist/files/wic/lamadist-dmverity-bootdisk.wks.in).  RAUC
# writes raw partitions, so each slot must be pre-sized to fit the
# largest expected rootfs/hash artifact; bump these if a build's
# .verity or .vhash artifact no longer fits.  Measured on the
# 2026-07-16 W1 probe build: erofs-lz4hc rootfs 1.26G (down from
# ~2.8G ext4), vhash 40M (~3.1% of data); 3G/96M keeps ~2.4x
# headroom for the M7/M8 feature payloads.
DM_VERITY_ROOT_SIZE ?= '3G'
DM_VERITY_HASH_SIZE ?= '96M'
