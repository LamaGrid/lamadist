# vi:ft=bitbake
# SPDX-License-Identifier: Apache-2.0

FILESEXTRAPATHS:prepend := "${THISDIR}/linux-yocto:"

SRC_URI += "file://squashfs-xattr.cfg"
