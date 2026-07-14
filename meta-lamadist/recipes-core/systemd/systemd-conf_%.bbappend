# SPDX-License-Identifier: Apache-2.0

FILESEXTRAPATHS:prepend := "${THISDIR}/systemd-conf:"

SRC_URI += "file://10-lamadist-journald.conf"

do_install:append() {
	install -D -m0644 ${WORKDIR}/10-lamadist-journald.conf \
		${D}${systemd_unitdir}/journald.conf.d/10-lamadist.conf
}
