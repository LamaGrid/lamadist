# SPDX-License-Identifier: Apache-2.0

DESCRIPTION = "LamaDist base image"

inherit lamadist-image

# Seeds slot A's ESP boot content (kernel, initramfs, microcode,
# systemd-boot entry) at image build time; see
# classes/lamadist-esp-slot-a.bbclass.
inherit lamadist-esp-slot-a
