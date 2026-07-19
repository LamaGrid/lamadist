# vi:ft=bitbake
# SPDX-License-Identifier: Apache-2.0
#
# Self-healing host-key generation for socket-activated sshd; see
# files/10-genkeys-per-connection.conf for the failure this closes.

FILESEXTRAPATHS:prepend := "${THISDIR}/files:"

SRC_URI += "file://10-genkeys-per-connection.conf"

do_install:append() {
	install -d ${D}${systemd_system_unitdir}/sshd@.service.d
	install -m 0644 ${UNPACKDIR}/10-genkeys-per-connection.conf \
		${D}${systemd_system_unitdir}/sshd@.service.d/
}

FILES:${PN}-sshd += "${systemd_system_unitdir}/sshd@.service.d"
