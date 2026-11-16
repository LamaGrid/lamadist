# SPDX-License-Identifier: Apache-2.0
#
# First-boot per-device /var key for machines WITHOUT a TPM (ADR 0013
# decision 7, owner decision 3).  lamadist-var-notpm-key.service
# generates a key on the ESP and adds it as a LUKS2 keyslot of /var,
# after lamadist-var-encrypt.service (lamadist-luks-var) formats it
# and before systemd-cryptsetup@var.service unlocks it with that key
# (crypttab, lamadist-image.bbclass).  See files/README.md.
#
# A separate recipe, not a conditional half of lamadist-luks-var: the
# tpm2 feature is set per MACHINE (lamadist-tpm2.inc), and an allarch
# package whose contents changed with it would differ between machines
# that share one deploy/ipk/all.  This recipe is all-or-nothing:
# CONFLICT_DISTRO_FEATURES skips it on tpm2 machines, and
# lamadist-image.bbclass installs it only when tpm2 is absent.
#
# No key ships: the key is made on the device at first boot.

DESCRIPTION = "LamaDist first-boot per-device /var key for machines without a TPM"
LICENSE = "Apache-2.0"
LIC_FILES_CHKSUM = "file://${COMMON_LICENSE_DIR}/Apache-2.0;md5=89aea4e17d99a7cacdbeed46a0096b10"

SRC_URI = " \
    file://lamadist-var-notpm-key \
    file://lamadist-var-notpm-key.service \
"

S = "${UNPACKDIR}"

inherit allarch systemd features_check

REQUIRED_DISTRO_FEATURES = "systemd luks"
CONFLICT_DISTRO_FEATURES = "tpm2"

SYSTEMD_SERVICE:${PN} = "lamadist-var-notpm-key.service"

# coreutils: head -c, stat -c, and sync FILE / sync -f (busybox sync
# does not fsync a single file).  cryptsetup: luksAddKey and the
# --test-passphrase idempotence check.  lamadist-luks-var: the unit
# Requires= its lamadist-var-encrypt.service and unlocks with its
# dev keyfile.
RDEPENDS:${PN} = " \
    coreutils \
    cryptsetup \
    lamadist-luks-var \
"

do_install() {
	install -d ${D}${nonarch_libdir}/lamadist
	install -m 0755 ${UNPACKDIR}/lamadist-var-notpm-key \
		${D}${nonarch_libdir}/lamadist/lamadist-var-notpm-key

	install -d ${D}${systemd_system_unitdir}
	install -m 0644 ${UNPACKDIR}/lamadist-var-notpm-key.service \
		${D}${systemd_system_unitdir}/
}

FILES:${PN} += " \
    ${nonarch_libdir}/lamadist/lamadist-var-notpm-key \
    ${systemd_system_unitdir}/lamadist-var-notpm-key.service \
"
