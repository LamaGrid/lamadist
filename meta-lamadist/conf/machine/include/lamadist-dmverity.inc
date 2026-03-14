# vi:ft=bitbake
# SPDX-License-Identifier: Apache-2.0
#
# Shared dm-verity machine defaults.
#
# Machine-specific dm-verity parameters: partition type GUIDs,
# block sizes, hash separation, and the target image for verity
# hashing.  Machines should require this file and override any
# values that need to differ.
#
# The distro-level dm-verity policy (IMAGE_CLASSES, KERNEL_FEATURES,
# INITRAMFS_IMAGE, INITRAMFS_FSTYPES) is set in lamadist-security.inc.

DM_VERITY_IMAGE ?= 'core-image-minimal'
DM_VERITY_IMAGE_TYPE ?= 'ext4'

DM_VERITY_SEPARATE_HASH ?= '1'

DM_VERITY_IMAGE_DATA_BLOCK_SIZE ?= '1024'
DM_VERITY_IMAGE_HASH_BLOCK_SIZE ?= '4096'
