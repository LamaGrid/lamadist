# SPDX-License-Identifier: Apache-2.0
#
# First-boot LUKS2 provisioning for the wic-built 'var' PARTLABEL
# partition (M4 plan decision 4).  Rootfs slots stay raw+verity in
# this pass; only /var gets LUKS2, and only via a first-boot service
# -- wic itself cannot create LUKS containers (see files/wic/
# lamadist-dmverity-bootdisk.wks.in).  lamadist-var-encrypt.service
# luksFormats the partition in place the first time it finds no
# LUKS2 header there, ordered before crypttab's own
# systemd-cryptsetup@var unit ever tries to open it (see
# files/lamadist-var-encrypt.service).  lamadist-var-tpm2-enroll.service
# (M4 plan W11, stage B) then adds a TPM2 PCR7 keyslot alongside the
# keyfile one, ordered between the two (see
# files/lamadist-var-tpm2-enroll.service).  /etc/crypttab and
# /etc/fstab are wired in lamadist-image.bbclass, not here.  See
# files/README.md for the DEVELOPMENT-ONLY keyfile this ships and the
# pending decision on its keyslot once TPM2 enrollment is live.

DESCRIPTION = "LamaDist first-boot LUKS2 provisioning for the /var partition"
LICENSE = "Apache-2.0"
LIC_FILES_CHKSUM = "file://${COMMON_LICENSE_DIR}/Apache-2.0;md5=89aea4e17d99a7cacdbeed46a0096b10"

SRC_URI = " \
    file://lamadist-var-encrypt \
    file://lamadist-var-encrypt.service \
    file://lamadist-var-tpm2-enroll \
    file://lamadist-var-tpm2-enroll.service \
    file://dev-var.key \
"

S = "${UNPACKDIR}"

inherit allarch systemd features_check

# tpm2: lamadist-var-tpm2-enroll.service needs systemd-cryptenroll's
# TPM2 support, which is gated by that same DISTRO_FEATURE across
# the layer stack (see meta-lamadist/conf/machine/include/
# lamadist-tpm2.inc and the systemd PACKAGECONFIG[tpm2] open
# question this recipe's README/commit notes).
REQUIRED_DISTRO_FEATURES = "systemd luks tpm2"

SYSTEMD_SERVICE:${PN} = " \
    lamadist-var-encrypt.service \
    lamadist-var-tpm2-enroll.service \
"

# cryptsetup: luksFormat/open/isLuks/close/luksDump.  e2fsprogs-mke2fs:
# mkfs.ext4 on the freshly formatted mapper device.  util-linux-blkid:
# confirms the mapper actually carries an ext4 filesystem (not just a
# LUKS2 header) before treating the migration as done, so an
# interrupted first boot can self-heal.  All three are always needed
# at boot, not just on the one boot that actually formats -- the
# blkid check in the script is what makes every later boot's run a
# no-op, not a missing dependency.  coreutils: the seed copy needs
# cp -a with xattr (SELinux label) preservation, which busybox cp
# does not guarantee.  systemd-crypt: ships systemd-cryptenroll and
# the libcryptsetup-token-systemd-tpm2 plugin systemd-cryptsetup@var
# needs to honor the crypttab tpm2-device= option -- oe-core's
# systemd recipe only RRECOMMENDS this package from the main
# systemd package, and a hard boot-time dependency should not rely
# on recommendations staying enabled.
RDEPENDS:${PN} = " \
    coreutils \
    cryptsetup \
    e2fsprogs-mke2fs \
    systemd-crypt \
    util-linux-blkid \
"

do_install() {
	install -d ${D}${nonarch_libdir}/lamadist
	install -m 0755 ${UNPACKDIR}/lamadist-var-encrypt \
		${D}${nonarch_libdir}/lamadist/lamadist-var-encrypt
	install -m 0755 ${UNPACKDIR}/lamadist-var-tpm2-enroll \
		${D}${nonarch_libdir}/lamadist/lamadist-var-tpm2-enroll

	install -d ${D}${systemd_system_unitdir}
	install -m 0644 ${UNPACKDIR}/lamadist-var-encrypt.service \
		${D}${systemd_system_unitdir}/
	install -m 0644 ${UNPACKDIR}/lamadist-var-tpm2-enroll.service \
		${D}${systemd_system_unitdir}/

	# DEVELOPMENT-ONLY keyfile; see files/README.md.  0600 matches
	# cryptsetup's own recommended keyfile permissions, even though
	# the read-only verity rootfs makes it moot in practice.
	install -d ${D}${sysconfdir}/lamadist
	install -m 0600 ${UNPACKDIR}/dev-var.key \
		${D}${sysconfdir}/lamadist/dev-var.key
}

FILES:${PN} += " \
    ${nonarch_libdir}/lamadist/lamadist-var-encrypt \
    ${nonarch_libdir}/lamadist/lamadist-var-tpm2-enroll \
    ${systemd_system_unitdir}/lamadist-var-encrypt.service \
    ${systemd_system_unitdir}/lamadist-var-tpm2-enroll.service \
    ${sysconfdir}/lamadist/dev-var.key \
"
