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

DM_VERITY_IMAGE_DATA_BLOCK_SIZE ?= '1024'
DM_VERITY_IMAGE_HASH_BLOCK_SIZE ?= '4096'

# Fixed sizes for the A/B rootfs/hash slot partitions (see
# meta-lamadist/files/wic/lamadist-dmverity-bootdisk.wks.in).  RAUC
# writes raw partitions, so each slot must be pre-sized to fit the
# largest expected rootfs/hash artifact; bump these if a build's
# .ext4.verity or .ext4.vhash no longer fits.  The current ext4
# rootfs lands at ~2.8G (1.2G of content plus the default
# IMAGE_OVERHEAD_FACTOR headroom); the M4 EROFS work is expected to
# shrink this substantially, at which point these can come back
# down.
DM_VERITY_ROOT_SIZE ?= '4G'
DM_VERITY_HASH_SIZE ?= '128M'
