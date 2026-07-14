# SPDX-License-Identifier: Apache-2.0

# selinux-image inherits core-image and labels the rootfs at image
# build time (setfiles via IMAGE_PREPROCESS_COMMAND).  Build-time
# labeling is required because first-boot autorelabel cannot work
# on the read-only dm-verity root (FIRST_BOOT_RELABEL is '0' in
# lamadist-security.inc).
inherit selinux-image

IMAGE_FEATURES += "ssh-server-openssh"

CORE_IMAGE_BASE_INSTALL += "packagegroup-lamadist-base"
SYSTEMD_DEFAULT_TARGET = "multi-user.target"

LICENSE = "Apache-2.0"
