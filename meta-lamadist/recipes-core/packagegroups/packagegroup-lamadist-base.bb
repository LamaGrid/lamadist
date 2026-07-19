# SPDX-License-Identifier: Apache-2.0

DESCRIPTION = 'Base packagegroup'

LICENSE = 'Apache-2.0'

inherit packagegroup

# Administrator toolkit: full shell and core utilities instead of
# busybox stubs, network tooling, privilege escalation, timezone
# data, and the systemd machine config (DHCP ethernet, journald
# defaults) from systemd-conf.
#
# rauc / rauc-mark-good (M3): A/B OTA updates.  rauc-mark-good ships
# masked -- lamadist-health.service owns "good" semantics -- but is
# still installed so its unit exists to mask.
#
# lamadist-luks-var (M4 W4): ships the /etc/lamadist/dev-var.key
# keyfile and lamadist-var-encrypt.service that first-boot
# luksFormats the 'var' PARTLABEL partition.  lamadist-image.bbclass
# unconditionally writes crypttab/fstab entries pointing at
# /dev/mapper/var, so this package must be installed for that mapper
# device to ever exist.
RDEPENDS:${PN} = " \
    bash \
    coreutils \
    haveged \
    iproute2 \
    iproute2-ss \
    lamadist-luks-var \
    procps \
    rauc \
    rauc-mark-good \
    sudo \
    systemd-conf \
    tzdata \
    util-linux \
"
