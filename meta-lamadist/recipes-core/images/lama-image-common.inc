# SPDX-License-Identifier: Apache-2.0

IMAGE_FEATURES += "ssh-server-openssh"

LICENSE = "Apache-2.0"

inherit core-image

CORE_IMAGE_BASE_INSTALL += "packagegroup-lamadist-base"
SYSTEMD_DEFAULT_TARGET = "graphical.target"

inherit nopackages
