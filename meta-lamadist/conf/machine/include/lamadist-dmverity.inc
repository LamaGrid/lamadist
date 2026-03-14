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
