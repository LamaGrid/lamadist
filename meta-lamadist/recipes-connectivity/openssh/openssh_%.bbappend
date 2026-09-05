# vi:ft=bitbake
# SPDX-License-Identifier: Apache-2.0
#
# Self-healing host-key generation for socket-activated sshd; see
# files/10-genkeys-per-connection.conf for the failure this closes.
#
# Authentication policy drop-in: public-key only; see
# files/10-lamadist-auth.conf.  The stock sshd_config carries
# "Include /etc/ssh/sshd_config.d/*.conf" as its first directive and
# sshd_config_readonly is a copy of it, so the drop-in binds first
# on both the writable and the read-only-rootfs paths.

FILESEXTRAPATHS:prepend := "${THISDIR}/files:"

SRC_URI += "file://10-genkeys-per-connection.conf \
            file://10-lamadist-auth.conf"

do_install:append() {
	install -d ${D}${systemd_system_unitdir}/sshd@.service.d
	install -m 0644 ${UNPACKDIR}/10-genkeys-per-connection.conf \
		${D}${systemd_system_unitdir}/sshd@.service.d/
	install -d ${D}${sysconfdir}/ssh/sshd_config.d
	install -m 0644 ${UNPACKDIR}/10-lamadist-auth.conf \
		${D}${sysconfdir}/ssh/sshd_config.d/
}

FILES:${PN}-sshd += "${systemd_system_unitdir}/sshd@.service.d \
                     ${sysconfdir}/ssh/sshd_config.d"
