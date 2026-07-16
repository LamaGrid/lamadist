# SPDX-License-Identifier: Apache-2.0
#
# rauc-mark-good.service (rauc's own unconditional
# `rauc status mark-good` unit, shipped by the rauc-mark-good
# subpackage) is masked in favor of lamadist-health.service
# (recipes-core/rauc/rauc-conf.bbappend), which gates the same call
# on system health per decision 5 of the M3 plan.  Masking, not
# just disabling, stops a stray `systemctl enable` from
# resurrecting the unconditional behavior.
#
# SYSTEMD_AUTO_ENABLE = "mask" only skips the enable step in
# systemd_postinst (systemd.bbclass's systemd_populate_packages
# never writes a preset or mask symlink for action "mask" -- see
# ext/openembedded-core/meta/classes-recipe/systemd.bbclass); it
# does not, by itself, mask the unit.  The do_install:append below
# creates the actual mask: a symlink to /dev/null in
# /etc/systemd/system, which shadows the vendored unit and makes
# `systemctl enable`/`preset-all` no-ops against it.
SYSTEMD_AUTO_ENABLE:${PN}-mark-good = "mask"

do_install:append() {
	install -d ${D}${sysconfdir}/systemd/system
	ln -sf /dev/null ${D}${sysconfdir}/systemd/system/rauc-mark-good.service
}

FILES:${PN}-mark-good += "${sysconfdir}/systemd/system/rauc-mark-good.service"
CONFFILES:${PN}-mark-good += "${sysconfdir}/systemd/system/rauc-mark-good.service"
