# SPDX-License-Identifier: Apache-2.0
SUMMARY = "Device-side collector for CI validation over a forced-command SSH key"
DESCRIPTION = "The single entrypoint the CI key's forced command runs and its \
scoped root helper, which gather the validation suite's check facts in one SSH \
connection.  The matching NOPASSWD sudoers rule is written by the image \
(lamadist-image.bbclass) so it does not co-own /etc/sudoers.d with sudo.  \
Test/CI images only; never install in a release image."
LICENSE = "Apache-2.0"
LIC_FILES_CHKSUM = "file://${COMMON_LICENSE_DIR}/Apache-2.0;md5=89aea4e17d99a7cacdbeed46a0096b10"

SRC_URI = "file://lamadist-validate-device \
           file://lamadist-validate-root \
"

S = "${UNPACKDIR}"

# python3 runs the collectors; sudo enforces the one scoped rule the
# image installs.
RDEPENDS:${PN} = "python3-core sudo"

do_install() {
    install -d ${D}${bindir}
    install -m 0755 ${UNPACKDIR}/lamadist-validate-device \
        ${D}${bindir}/lamadist-validate-device

    install -d ${D}${libexecdir}/lamadist
    install -m 0755 ${UNPACKDIR}/lamadist-validate-root \
        ${D}${libexecdir}/lamadist/lamadist-validate-root
}

FILES:${PN} = "${bindir}/lamadist-validate-device \
               ${libexecdir}/lamadist \
"
