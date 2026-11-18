# vi:ft=bitbake
# SPDX-License-Identifier: Apache-2.0
#
# The `vm --firmware u-boot` QEMU payload (ADR 0013 open question 6,
# answered go 2026-11-15): U-Boot qemu_arm64 as the UEFI provider for
# the qemuarm64-lamadist image, under the existing sdboot-uki profile.
# AAVMF stays the vm task's default and the image does not change; this
# builds only u-boot.bin for `vm --firmware u-boot`.
#
# u-boot_%.bbappend requires this file only when LAMADIST_UBOOT_VM is
# "1", which kas/extras/uboot-vm.kas.yml sets.  Every statement is
# scoped to qemuarm64-lamadist, so stacking the overlay on another BSP
# changes nothing.  The SOQuartz U-Boot is not touched.
#
# The payload mirrors the board: the same EFI fragment
# (lamadist-soquartz-efi.cfg, merged first), the same link patch, and
# the same build-time variable seed.  lamadist-qemu-arm64-efi.cfg,
# merged after it, holds the QEMU-only delta, and lamadist-qemu-arm64.env
# is the default environment.  A QEMU result proves U-Boot's EFI code
# at the pinned tag, never the SoC; it is never cited as a board
# property, and every check re-runs on the board .config.

# oe-core qemuarm64.conf already defaults this; pin it so the payload
# never follows a changed default.
UBOOT_MACHINE:qemuarm64-lamadist = "qemu_arm64_defconfig"

SRC_URI:append:qemuarm64-lamadist = " \
    file://lamadist-soquartz-efi.cfg \
    file://lamadist-qemu-arm64-efi.cfg \
    file://lamadist-qemu-arm64.env \
    file://0001-efi_loader-link-bootm-for-ExitBootServices.patch \
"

# U-Boot turns the env text file into a C header with xxd (see the
# bbappend's note for the board).
DEPENDS:append:qemuarm64-lamadist = " xxd-native"

# The same PK/KEK/db seed the board gets, generated at build time and
# never checked in.  The bbappend's inherit_defer picks the class up.
LAMADIST_UBOOT_SEED_CLASS:qemuarm64-lamadist = "lamadist-efi-var-seed"

# virtual/bootloader stays systemd-boot (lamadist-boot-sdboot-uki.inc),
# and base.bbclass skips every other provider; drop the claim so the
# recipe parses for this machine.
PROVIDES:remove:qemuarm64-lamadist = "virtual/bootloader"

do_configure:prepend:qemuarm64-lamadist () {
	# The QEMU fragment names the env file source-relative, as the board
	# fragment does; put the file where that name resolves.
	install -m 0644 "${UNPACKDIR}/lamadist-qemu-arm64.env" "${S}/lamadist-qemu-arm64.env"
	cfg="${UNPACKDIR}/lamadist-soquartz-efi.cfg"
	if ! grep -qx 'CONFIG_EFI_VAR_SEED_FILE="${LAMADIST_EFI_VAR_SEED_FILE}"' "$cfg"; then
		bbfatal "lamadist-soquartz-efi.cfg must set CONFIG_EFI_VAR_SEED_FILE=\"${LAMADIST_EFI_VAR_SEED_FILE}\" (ADR 0013 decision 3)"
	fi
	if [ ! -s "${S}/${LAMADIST_EFI_VAR_SEED_FILE}" ]; then
		bbfatal "no EFI variable seed at ${S}/${LAMADIST_EFI_VAR_SEED_FILE}: is lamadist-efi-var-seed inherited? (ADR 0013 decision 3)"
	fi
}

# Fail closed on the merged .config, as the board does (the function is
# defined in u-boot_%.bbappend): every line of both fragments must
# survive oldconfig, or the QEMU result would describe a different U-Boot
# than the one the board runs.  The fragments are named in the order
# SRC_URI merges them, so the QEMU delta wins where it differs.
do_configure:append:qemuarm64-lamadist () {
	lamadist_uboot_check_config "${UNPACKDIR}/lamadist-soquartz-efi.cfg" "${UNPACKDIR}/lamadist-qemu-arm64-efi.cfg"
}

# Fail closed on the default environment, as the board does: the built
# u-boot-initial-env must equal the layer's env text.
do_compile:append:qemuarm64-lamadist () {
	built="${B}/u-boot-initial-env"
	if [ ! -s "$built" ]; then
		bbfatal "no built default environment at $built (ADR 0013 open question 6)"
	fi
	grep -v -e '^[[:space:]]*#' -e '^[[:space:]]*$' "${UNPACKDIR}/lamadist-qemu-arm64.env" | LC_ALL=C sort > "${B}/lamadist-env.want"
	grep -v -e '^[[:space:]]*#' -e '^[[:space:]]*$' "$built" | LC_ALL=C sort > "${B}/lamadist-env.got"
	if [ ! -s "${B}/lamadist-env.want" ] || ! cmp -s "${B}/lamadist-env.want" "${B}/lamadist-env.got"; then
		diff "${B}/lamadist-env.want" "${B}/lamadist-env.got" || true
		bbfatal "built u-boot-initial-env differs from lamadist-qemu-arm64.env (ADR 0013 open question 6)"
	fi
}
