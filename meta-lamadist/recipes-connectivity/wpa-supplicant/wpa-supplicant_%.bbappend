# SPDX-License-Identifier: Apache-2.0
#
# Persistent WiFi station on wlan0.  The SSID and PSK live only on the
# encrypted /var (/var/lib/lamadist-wifi/wpa_supplicant-wlan0.conf,
# provisioned out of band, never baked into the image).  This recipe
# bakes only the non-secret plumbing:
#   - a drop-in pointing the wlan0 supplicant instance at that /var
#     config, ordered after the LUKS /var mount;
#   - a systemd-networkd DHCP profile for wlan0;
#   - a tmpfiles.d entry that relabels the provisioned /var dir to
#     NetworkManager_var_lib_t so the confined supplicant can read it
#     (nothing else relabels the LUKS /var; see the lamadist SELinux
#     module, recipes-security/refpolicy/files/lamadist.{fc,te});
#   - enablement of the wlan0 instance.
# Base wpa-supplicant leaves the unit disabled and pointed at
# /etc/wpa_supplicant.conf, neither of which fits a /var-config,
# overlay-locked-/etc image.
#
# The operator-provisioned /var config must NOT set a non-root
# `ctrl_interface` GROUP=: that would turn the wpa control socket into a
# PSK-adjacent management surface for that group.  Leave ctrl_interface
# root-owned (the default), or omit it.

FILESEXTRAPATHS:prepend := "${THISDIR}/files:"

SRC_URI += " \
    file://10-var-conf.conf \
    file://25-wlan0.network \
    file://lamadist-wifi.conf \
"

# Enable ONLY the wlan0 instance; base enables nothing
# (SYSTEMD_AUTO_ENABLE "disable").  This overrides the base
# SYSTEMD_SERVICE (wpa_supplicant.service, which reads the unused
# /etc/wpa_supplicant.conf) so the rootfs enable step wires up exactly
# the instance this image runs.
SYSTEMD_SERVICE:${PN} = "wpa_supplicant@wlan0.service"
SYSTEMD_AUTO_ENABLE:${PN} = "enable"

do_install:append() {
    install -d ${D}${systemd_system_unitdir}/wpa_supplicant@wlan0.service.d
    install -m 0644 ${UNPACKDIR}/10-var-conf.conf \
        ${D}${systemd_system_unitdir}/wpa_supplicant@wlan0.service.d/10-var-conf.conf

    install -d ${D}${systemd_unitdir}/network
    install -m 0644 ${UNPACKDIR}/25-wlan0.network \
        ${D}${systemd_unitdir}/network/25-wlan0.network

    install -d ${D}${nonarch_libdir}/tmpfiles.d
    install -m 0644 ${UNPACKDIR}/lamadist-wifi.conf \
        ${D}${nonarch_libdir}/tmpfiles.d/lamadist-wifi.conf
}

FILES:${PN} += " \
    ${systemd_system_unitdir}/wpa_supplicant@wlan0.service.d/10-var-conf.conf \
    ${systemd_unitdir}/network/25-wlan0.network \
    ${nonarch_libdir}/tmpfiles.d/lamadist-wifi.conf \
"
