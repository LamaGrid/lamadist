# vi:ft=bitbake
# SPDX-License-Identifier: Apache-2.0

FILESEXTRAPATHS:prepend := "${THISDIR}/linux-yocto:"

SRC_URI += "file://squashfs-xattr.cfg"
SRC_URI += "file://erofs.cfg"
SRC_URI += "file://overlay.cfg"
