# SPDX-License-Identifier: Apache-2.0
#
# Boot backend: systemd-boot plus a Unified Kernel Image, the x86-64
# reference chain.  It bundles the two build-time pieces in the single
# order they must run: lamadist-uki builds the per-slot UKIs
# (lamadist-a.efi, lamadist-b.efi), then lamadist-esp-slot-a stages
# slot A's ESP content that references them.  Both classes append to
# do_image_wic[prefuncs] (lamadist_uki_build, then
# lamadist_esp_slot_a_populate); bitbake runs a prefunc list in append
# order and processes an inherit list left to right, so inheriting
# lamadist-uki before lamadist-esp-slot-a here reproduces exactly the
# ordering lamadist-image-base.bb used to spell out as two ordered
# inherits.
#
# A machine leaf selects this backend by setting LAMADIST_BOOT_BACKEND
# to "sdboot-uki" (see conf/machine/include/lamadist-boot-sdboot-uki.inc);
# lamadist-image-base.bb then inherits lamadist-boot-${LAMADIST_BOOT_BACKEND}.
# A second platform (U-Boot for Rockchip, L4T for Tegra) ships its own
# backend class beside this one and the image recipe is untouched.

inherit lamadist-uki lamadist-esp-slot-a
