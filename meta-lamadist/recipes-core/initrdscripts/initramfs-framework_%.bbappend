# SPDX-License-Identifier: Apache-2.0
#
# Shadow meta-security's dmverity initramfs module (see
# initramfs-framework-dm/dmverity) with a slot-aware version.
# meta-security's own initramfs-framework.inc still supplies the
# SRC_URI entry, do_install, and PACKAGES/FILES wiring; this
# FILESEXTRAPATHS entry only needs to win the search for
# file://dmverity, which it does because BBFILE_PRIORITY_lamadist
# outranks meta-security's and higher-priority layers' bbappends
# apply their :prepend last.

FILESEXTRAPATHS:prepend := "${THISDIR}/initramfs-framework-dm:"
