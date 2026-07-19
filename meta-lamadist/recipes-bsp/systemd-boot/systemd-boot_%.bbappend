# SPDX-License-Identifier: Apache-2.0
#
# Secure Boot (stage B, W9): sbsign the sd-boot loader with the same
# db key/cert lamadist-security.inc points UKI_SB_KEY/UKI_SB_CERT at
# (meta-lamadist/files/sb-dev/db.key.pem / db.cert.pem --
# DEVELOPMENT ONLY, see that directory's README.md).  ukify signs
# the two per-slot UKIs with the identical pair
# (lamadist-uki.bbclass), so every PE the firmware executes on this
# machine -- loader and UKI alike -- verifies against the one
# enrolled db entry.  UKI_SB_KEY/UKI_SB_CERT default to empty in
# stage A, so this task is a no-op there and the loader stays
# unsigned, matching the M4.A gate.
#
# Two build outputs carry the loader binary and both are signed in
# place, under the names the rest of the build already expects:
#
#   - do_install's ${D}${EFI_FILES_PATH}/${SYSTEMD_BOOT_IMAGE}.  With
#     EFI_PROVIDER == "systemd-boot" (lamadist-base.inc),
#     SYSTEMD_BOOT_IMAGE == EFI_BOOT_IMAGE, unprefixed -- see this
#     recipe's own __anonymous python -- so this is the copy that
#     would land in any rootfs that installs the systemd-boot
#     package directly.
#   - do_deploy's ${DEPLOYDIR}/systemd-boot*.efi.  This is the copy
#     wic's bootimg-efi "systemd-boot" loader actually consumes: it
#     scans DEPLOY_DIR_IMAGE for files starting with "systemd-",
#     strips that 8-character prefix, and copies the rest onto the
#     ESP as EFI/BOOT/bootx64.efi (see
#     scripts/lib/wic/plugins/source/bootimg-efi.py in the poky
#     checkout).  This is the artifact that actually reaches a
#     booted image; signing only do_install's copy would leave the
#     ESP loader unsigned.
#
# sbsign (rather than systemd-sbsign/pesign) matches ukify's default
# tool inference when --secureboot-private-key/--secureboot-
# certificate are both given (src/ukify/ukify.py), so the loader and
# the UKIs are verified by firmware the same way.
DEPENDS += "sbsigntool-native"

lamadist_sbsign_file () {
	# $1: PE file to sign in place. No-op (stage A default) when
	# the key/cert pair is unset.
	if [ -z "${UKI_SB_KEY}" ] || [ -z "${UKI_SB_CERT}" ]; then
		bbnote "lamadist sb-signing: UKI_SB_KEY/UKI_SB_CERT unset, leaving $1 unsigned"
		return 0
	fi
	sbsign --key "${UKI_SB_KEY}" --cert "${UKI_SB_CERT}" \
		"$1" --output "$1.signed"
	mv -f "$1.signed" "$1"
}

do_install:append() {
	lamadist_sbsign_file "${D}${EFI_FILES_PATH}/${SYSTEMD_BOOT_IMAGE}"
}

do_deploy:append() {
	for f in "${DEPLOYDIR}"/systemd-boot*.efi; do
		[ -e "$f" ] || continue
		lamadist_sbsign_file "$f"
	done
}

do_install[vardeps] += "UKI_SB_CERT UKI_SB_KEY"
do_deploy[vardeps] += "UKI_SB_CERT UKI_SB_KEY"
