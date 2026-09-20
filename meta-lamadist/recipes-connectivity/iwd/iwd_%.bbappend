# SPDX-License-Identifier: Apache-2.0
#
# Persistent WiFi station on wlan0 with iwd.  Network profiles (SSID
# and passphrase) live only on the encrypted /var (/var/lib/iwd, iwd's
# native state directory, provisioned out of band and never baked into
# the image).  This bakes only the non-secret plumbing:
#   - iwd built daemon-only: no iwctl (a GPL-3 readline build
#     dependency) and no iwmon (a netlink sniffer) on a hardened image;
#     a field client can come back through the debug overlay;
#   - a drop-in ordering the daemon after the LUKS /var mount, since
#     its state directory lives there;
#   - a systemd-networkd DHCP profile for wlan0 (iwd leaves addressing
#     to networkd: EnableNetworkConfiguration stays off);
#   - a tmpfiles.d entry that creates and relabels /var/lib/iwd to
#     NetworkManager_var_lib_t so the confined daemon can read what an
#     operator copies in (nothing else relabels the LUKS /var; see
#     recipes-security/refpolicy/files/lamadist.{fc,te});
#   - a baked /etc/iwd/main.conf.
# The base recipe already installs and enables iwd.service.

FILESEXTRAPATHS:prepend := "${THISDIR}/files:"

PACKAGECONFIG = "systemd"

SRC_URI += " \
    file://10-var-mount.conf \
    file://25-wlan0.network \
    file://lamadist-wifi.conf \
    file://main.conf \
"

do_install:append() {
    install -d ${D}${systemd_system_unitdir}/iwd.service.d
    install -m 0644 ${UNPACKDIR}/10-var-mount.conf \
        ${D}${systemd_system_unitdir}/iwd.service.d/10-var-mount.conf

    install -d ${D}${systemd_unitdir}/network
    install -m 0644 ${UNPACKDIR}/25-wlan0.network \
        ${D}${systemd_unitdir}/network/25-wlan0.network

    install -d ${D}${nonarch_libdir}/tmpfiles.d
    install -m 0644 ${UNPACKDIR}/lamadist-wifi.conf \
        ${D}${nonarch_libdir}/tmpfiles.d/lamadist-wifi.conf

    install -d ${D}${sysconfdir}/iwd
    install -m 0644 ${UNPACKDIR}/main.conf ${D}${sysconfdir}/iwd/main.conf
}

FILES:${PN} += " \
    ${systemd_system_unitdir}/iwd.service.d/10-var-mount.conf \
    ${nonarch_libdir}/tmpfiles.d/lamadist-wifi.conf \
    ${sysconfdir}/iwd/main.conf \
"
