# SPDX-License-Identifier: Apache-2.0
#
# LamaDist M3 pass 1 RAUC system configuration: overrides the
# upstream example system.conf (decision 5 of the M3 plan), installs
# the DEVELOPMENT-ONLY verification keyring under the path
# system.conf expects, and ships the custom systemd-boot bootchooser
# backend plus the health-gated mark-good service (decision 3/5).
#
# RAUC 1.15.1 has no native systemd-boot bootchooser backend
# (verified against the fetched upstream source's
# src/bootchooser.c supported_bootloaders list); system.conf below
# selects bootloader=custom and files/systemd-boot-backend
# implements the documented handler contract.

FILESEXTRAPATHS:prepend := "${THISDIR}/files:${THISDIR}/../../files/rauc-dev:"

SRC_URI += " \
    file://systemd-boot-backend \
    file://lamadist-health-check \
    file://lamadist-health.service \
    "

# DEVELOPMENT-ONLY keyring; see ../../files/rauc-dev/README.md.
# M6 owns the real release CA.  Pulled in via the base recipe's own
# RAUC_KEYRING_URI ??= "file://${RAUC_KEYRING_FILE}", so it is not
# repeated in SRC_URI above.
RAUC_KEYRING_FILE = "dev-ca.cert.pem"

# DEVELOPMENT-ONLY forced-unhealthy test hook (decision 5): gates
# lamadist-health-check's /var/lamadist-force-unhealthy check behind
# a marker file baked onto the read-only rootfs at build time, so a
# writable /var can never resurrect the hook on an image built with
# this unset.  Defaults on because every image built today is a
# dev/CI image signed with the dev keyring above; M6's release image
# build MUST set this to "0".  See ../../files/rauc-dev/README.md.
LAMADIST_OTA_TEST_HOOKS ??= "1"

inherit systemd

SYSTEMD_SERVICE:${PN} = "lamadist-health.service"

do_install:append() {
	# system.conf's [system] compatible= carries a literal
	# @MACHINE@ placeholder (bitbake does not variable-expand
	# installed files); substitute the real value here.
	sed -i -e 's!@MACHINE@!${MACHINE}!g' ${D}${sysconfdir}/rauc/system.conf

	# The base rauc-conf recipe installs the keyring under its
	# source basename (RAUC_KEYRING_FILE); system.conf's
	# [keyring] path expects /etc/rauc/keyring.pem.
	mv ${D}${sysconfdir}/rauc/${RAUC_KEYRING_FILE} ${D}${sysconfdir}/rauc/keyring.pem

	install -d ${D}${nonarch_libdir}/rauc
	install -m 0755 ${UNPACKDIR}/systemd-boot-backend ${D}${nonarch_libdir}/rauc/systemd-boot-backend
	install -m 0755 ${UNPACKDIR}/lamadist-health-check ${D}${nonarch_libdir}/rauc/lamadist-health-check

	install -d ${D}${systemd_system_unitdir}
	install -m 0644 ${UNPACKDIR}/lamadist-health.service ${D}${systemd_system_unitdir}/

	# system.conf's statusfile lives on the writable /var
	# partition, which starts empty; systemd-tmpfiles must create
	# the directory or every install fails writing the status file.
	install -d ${D}${nonarch_libdir}/tmpfiles.d
	echo 'd /var/lib/rauc 0700 root root -' \
		> ${D}${nonarch_libdir}/tmpfiles.d/rauc-statusdir.conf

	# systemd's bless-boot generator pulls systemd-bless-boot.service
	# into every counted boot and marks the entry good the moment
	# boot-complete.target is reached -- behind the health gate's
	# back, racing lamadist-health-check's reboot-on-unhealthy and
	# defeating the boot-counted rollback (observed: forced-unhealthy
	# trial boots getting blessed mid-cycle).  lamadist-health.service
	# is the ONLY thing allowed to bless a boot (via rauc status
	# mark-good), mirroring the rauc-mark-good.service mask in
	# rauc_%.bbappend.
	install -d ${D}${sysconfdir}/systemd/system
	ln -sf /dev/null ${D}${sysconfdir}/systemd/system/systemd-bless-boot.service

	if [ "${LAMADIST_OTA_TEST_HOOKS}" = "1" ]; then
		install -d ${D}${sysconfdir}/lamadist
		: > ${D}${sysconfdir}/lamadist/ota-test-hooks-enabled
	fi
}

FILES:${PN} += " \
    ${nonarch_libdir}/tmpfiles.d/rauc-statusdir.conf \
    ${sysconfdir}/systemd/system/systemd-bless-boot.service \
    ${nonarch_libdir}/rauc/systemd-boot-backend \
    ${nonarch_libdir}/rauc/lamadist-health-check \
    ${systemd_system_unitdir}/lamadist-health.service \
    ${sysconfdir}/lamadist/ota-test-hooks-enabled \
    "
