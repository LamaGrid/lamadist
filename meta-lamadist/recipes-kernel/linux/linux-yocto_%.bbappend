# vi:ft=bitbake
# SPDX-License-Identifier: Apache-2.0

FILESEXTRAPATHS:prepend := "${THISDIR}/linux-yocto:"

SRC_URI += "file://squashfs-xattr.cfg"
SRC_URI += "file://erofs.cfg"
SRC_URI += "file://overlay.cfg"
SRC_URI += "file://efivarfs.cfg"
SRC_URI += "file://wifi-mt7922.cfg"
SRC_URI += "file://iwd-keys.cfg"

# Test-only virtual radio (mac80211_hwsim) for the QEMU WiFi test.  The
# QA and debug overlays switch it on; a release build carries no
# overlay and so no test-only driver.  Gating a config fragment forks
# the kernel between those two build profiles, which is the intent:
# the release kernel must not differ from what ships only by what was
# left out of it.
LAMADIST_TEST_HWSIM ??= "0"
SRC_URI += "${@'file://hwsim.cfg' if d.getVar('LAMADIST_TEST_HWSIM') == '1' else ''}"
