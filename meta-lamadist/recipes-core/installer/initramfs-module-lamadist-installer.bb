# SPDX-License-Identifier: Apache-2.0

SUMMARY = "LamaDist USB installer initramfs-framework module"
DESCRIPTION = "The 50-installer module (SPEC section 3 flow), its \
shared helper library, and the strict manifest reader.  Runs the \
raw full-disk-image install (increment 1) from a signed installer \
UKI initramfs."
LICENSE = "Apache-2.0"
LIC_FILES_CHKSUM = "file://${COMMON_LICENSE_DIR}/Apache-2.0;md5=89aea4e17d99a7cacdbeed46a0096b10"

inherit allarch

SRC_URI = "\
    file://installer \
    file://lamadist-installer.sh \
    file://manifest-parse \
"

S = "${UNPACKDIR}"

# The flow needs a real block-tool userland; RDEPENDS documents it and
# pulls it into any image that installs this module.
RDEPENDS:${PN} = "\
    busybox \
    coreutils \
    udev \
    util-linux-blkid \
    util-linux-blockdev \
    xz \
"

do_install() {
    install -d ${D}/init.d
    install -m 0755 ${S}/installer ${D}/init.d/50-installer

    install -d ${D}${libexecdir}
    install -m 0755 ${S}/lamadist-installer.sh ${D}${libexecdir}/lamadist-installer.sh

    install -d ${D}${bindir}
    install -m 0755 ${S}/manifest-parse ${D}${bindir}/manifest-parse
}

FILES:${PN} = "\
    /init.d/50-installer \
    ${libexecdir}/lamadist-installer.sh \
    ${bindir}/manifest-parse \
"
