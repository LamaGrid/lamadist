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

# Administrator account: 'lama', wheel group, sudo via the wheel
# drop-in below.  The default password is 'lamadist' (fixed salt
# for reproducible builds).  Root login stays locked.
#
# No passwd-expire: /etc/shadow is on the read-only dm-verity
# root, so a forced first-login password change fails with
# "Authentication token manipulation error".  Revisit when /etc
# gains persistent state (credential provisioning milestone).
#
# The \$ escapes in the hash are load-bearing: useradd_base runs
# these commands through an extra shell eval, which strips the
# single quotes and expands unescaped $-words to empty strings,
# silently truncating the hash.
inherit extrausers
EXTRA_USERS_PARAMS = " \
    groupadd -r wheel; \
    useradd -m -G wheel -s /bin/bash \
        -p '\$6\$lamadist0\$NXM9PMLc/bVywi2Vg2ezUQpV5LVfLPBAkGX0araFFR9TuU4wL51EG9XxTApL4gi4u6.QSjMn3jNyfyeEoNlqf/' \
        lama; \
"

lamadist_sudoers_wheel() {
    install -d ${IMAGE_ROOTFS}${sysconfdir}/sudoers.d
    echo '%wheel ALL=(ALL:ALL) ALL' > ${IMAGE_ROOTFS}${sysconfdir}/sudoers.d/wheel
    chmod 0440 ${IMAGE_ROOTFS}${sysconfdir}/sudoers.d/wheel
}
ROOTFS_POSTPROCESS_COMMAND += "lamadist_sudoers_wheel; "

LICENSE = "Apache-2.0"
