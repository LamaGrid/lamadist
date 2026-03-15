# SPDX-License-Identifier: Apache-2.0

inherit core-image

IMAGE_FEATURES += "ssh-server-openssh"

CORE_IMAGE_BASE_INSTALL += "packagegroup-lamadist-base"
SYSTEMD_DEFAULT_TARGET = "graphical.target"

LICENSE = "Apache-2.0"
