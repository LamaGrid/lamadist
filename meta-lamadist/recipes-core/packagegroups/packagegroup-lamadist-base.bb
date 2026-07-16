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
RDEPENDS:${PN} = " \
    bash \
    coreutils \
    haveged \
    iproute2 \
    iproute2-ss \
    procps \
    rauc \
    rauc-mark-good \
    sudo \
    systemd-conf \
    tzdata \
    util-linux \
"
