# SPDX-License-Identifier: Apache-2.0

DESCRIPTION = 'Base packagegroup'

LICENSE = 'Apache-2.0'

inherit packagegroup

# Administrator toolkit: full shell and core utilities instead of
# busybox stubs, network tooling, privilege escalation, timezone
# data, and the systemd machine config (DHCP ethernet, journald
# defaults) from systemd-conf.
RDEPENDS:${PN} = " \
    bash \
    coreutils \
    haveged \
    iproute2 \
    iproute2-ss \
    procps \
    sudo \
    systemd-conf \
    tzdata \
    util-linux \
"
