# vi:ft=bitbake
# SPDX-License-Identifier: Apache-2.0
#
# U-Boot as the UEFI provider on the SOQuartz leaf (ADR 0013
# decisions 1 and 3).  Every addition is scoped to the
# soquartz-lamadist machine override, so no other machine's U-Boot
# changes; meta-rockchip's own u-boot_%.bbappend (BL31, rkbin DDR TPL,
# the rk-u-boot-env feature) still applies underneath.
#
# lamadist-soquartz-efi.cfg is merged over the board defconfig by
# u-boot-configure.inc; lamadist-soquartz.env is the whole default
# environment (boot_targets pinned, fdtfile empty, bootdelay=-2).

FILESEXTRAPATHS:prepend := "${THISDIR}/files:"

SRC_URI:append:soquartz-lamadist = " \
    file://lamadist-soquartz-efi.cfg \
    file://lamadist-soquartz.env \
"

# LAMADIST-SEED-HOOK: absolute path of the preseeded EFI variable file
# (PK, KEK, db, dbx), generated at build time from the key hierarchy the
# x86_64 gate enrolls; it is never checked in.  The preseed generator
# package sets this.  Empty stops the build rather than shipping a
# U-Boot with no Secure Boot variables.
LAMADIST_UBOOT_EFI_SEED ??= ""

# U-Boot reaches the image through the WKS rawcopy dependencies only, and
# virtual/bootloader stays systemd-boot (ADR 0013 decision 10).  oe-core
# base.bbclass skips every other provider of a virtual/ name that has a
# PREFERRED_PROVIDER, so on this machine U-Boot stops providing
# virtual/bootloader; its other PROVIDES need no change.
PROVIDES:remove:soquartz-lamadist = "virtual/bootloader"

do_configure:prepend:soquartz-lamadist () {
	# The fragment cannot name an absolute path, so fill in the
	# environment file's unpack location and the seed path.
	cfg="${UNPACKDIR}/lamadist-soquartz-efi.cfg"
	sed -i "s|@LAMADIST_UBOOT_ENV@|${UNPACKDIR}/lamadist-soquartz.env|" "$cfg"
	if [ -z "${LAMADIST_UBOOT_EFI_SEED}" ]; then
		bbfatal "LAMADIST_UBOOT_EFI_SEED is empty: no EFI variable seed for U-Boot (ADR 0013 decision 3)"
	fi
	if ! grep -q '^CONFIG_EFI_VAR_SEED_FILE=' "$cfg"; then
		echo 'CONFIG_EFI_VAR_SEED_FILE="${LAMADIST_UBOOT_EFI_SEED}"' >> "$cfg"
	fi
}
