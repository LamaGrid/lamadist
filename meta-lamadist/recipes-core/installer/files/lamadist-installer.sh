#!/bin/sh
# SPDX-License-Identifier: Apache-2.0
#
# Shared helpers for the LamaDist USB installer (initramfs).  Sourced
# by the 50-installer initramfs-framework module.  POSIX / busybox
# ash only.
#
# Increment 1 (the review installer): the payload is the complete
# hardened full-disk image (.wic.xz -- GPT + ESP + rootfs_a/b +
# hash_a/b + var).  "Install" writes it whole to the target disk; the
# installed system's own first-boot units then do LUKS2 format, TPM2
# enrollment, /var seed, and SELinux relabel exactly as they do in the
# QEMU smoke.  The SPEC's install-time provisioning and the encrypted
# vault are the security increment layered on top of this; see
# docs/installer/SPEC.md and the MANUAL on the payload partition.

# ---- output -------------------------------------------------------

_INST_TAG='lamadist-installer'

msg()  { printf '%s: %s\n'      "${_INST_TAG}" "$*"; }
warn() { printf '%s: WARN %s\n' "${_INST_TAG}" "$*" >&2; }
die()  { printf '%s: FATAL %s\n' "${_INST_TAG}" "$*" >&2; installer_halt 1; }

# Terminal action.  Interactive mode drops to a shell so the operator
# can inspect; headless halts the machine.  NEITHER path ever falls
# through to a rootfs pivot -- there is no rootfs in this initramfs.
installer_halt() {
	_rc="${1:-1}"
	if [ "${INSTALLER_HEADLESS:-no}" = yes ]; then
		msg "headless install halted (rc=${_rc})"
		# Poweroff so an automated harness sees a clean stop rather
		# than a hang; -f because there is no init to signal.
		poweroff -f 2>/dev/null || halt -f 2>/dev/null || exec sh
	else
		msg "dropping to a shell (rc=${_rc}); the target was not"
		msg "modified unless a write was explicitly reported above."
		exec sh
	fi
}

# ---- trust gate ---------------------------------------------------

EFIVARS=/sys/firmware/efi/efivars

# Increment-1 trust gate: assert Secure Boot is ON before any target
# write.  The full in-UKI PK/KEK/db digest match (SPEC 3.1 step 3) is
# a later increment; asserting SecureBoot=1 already refuses the
# SB-disabled silent-install path (BLOCKER-2 case 1), which is the
# one this dev harness can exercise.  Override for a deliberately
# insecure lab run only with `lamadist.installer.insecure` on the
# cmdline (bootparam_lamadist_installer_insecure set by the
# framework).
installer_trust_gate() {
	if [ "${bootparam_lamadist_installer_insecure:-}" = "1" ]; then
		warn "SECURE BOOT GATE BYPASSED (lamadist.installer.insecure)"
		return 0
	fi
	mkdir -p "${EFIVARS}"
	mount -t efivarfs efivarfs "${EFIVARS}" 2>/dev/null || true
	_sb="${EFIVARS}/SecureBoot-8be4df61-93ca-11d2-aa0d-00e098032b8c"
	[ -r "${_sb}" ] || die "SecureBoot EFI variable not readable; cannot verify trust state"
	# efivarfs prefixes 4 attribute bytes; the value byte follows.
	# Skip the 4 attributes, read 1 byte (same form smoke_login.py
	# uses), and trim whitespace.
	_val=$(od -An -tu1 -j4 -N1 "${_sb}" | tr -d ' ')
	if [ "${_val}" != "1" ]; then
		die "Secure Boot is not enabled (SecureBoot=${_val:-?}); refusing to install.  Enable Secure Boot in firmware, or pass lamadist.installer.insecure for a lab run."
	fi
	msg "trust gate: Secure Boot enabled"
}

# ---- payload discovery --------------------------------------------

PAYLOAD_LABEL=lamadist-payload
PAYLOAD_MNT=/run/lamadist-payload

# Locate the stick's payload partition by filesystem label, mount it
# read-only, and set STICK_DISK to the whole-disk device that carries
# it (so target enumeration can exclude the stick).  Use udev's
# by-label symlink (robust across busybox/util-linux blkid flag
# differences); settle first so it exists.
installer_mount_payload() {
	udevadm settle --timeout=15 2>/dev/null || true
	_part=$(readlink -f "/dev/disk/by-label/${PAYLOAD_LABEL}" 2>/dev/null || true)
	[ -b "${_part}" ] || die "payload partition (LABEL=${PAYLOAD_LABEL}) not found"
	mkdir -p "${PAYLOAD_MNT}"
	mount -o ro "${_part}" "${PAYLOAD_MNT}" || die "cannot mount payload ${_part}"
	STICK_DISK=$(installer_part_to_disk "${_part}")
	[ -n "${STICK_DISK}" ] || die "cannot resolve stick disk for ${_part}"
	msg "payload on ${_part} (stick disk ${STICK_DISK})"
}

# Map a partition device (/dev/sda1) to its whole-disk device
# (/dev/sda) via sysfs, so it works for sd*, vd*, nvme*, mmcblk*.
installer_part_to_disk() {
	_p="${1##*/}"
	_sys=$(readlink -f "/sys/class/block/${_p}" 2>/dev/null || true)
	[ -n "${_sys}" ] || return 1
	_diskname=$(basename "$(dirname "${_sys}")")
	[ -e "/sys/block/${_diskname}" ] || return 1
	printf '/dev/%s\n' "${_diskname}"
}

# Verify the payload image against its shipped SHA-256 sum.
installer_verify_payload() {
	_img="${PAYLOAD_MNT}/${PAYLOAD_IMAGE}"
	_sum="${PAYLOAD_MNT}/${PAYLOAD_IMAGE}.sha256"
	[ -f "${_img}" ] || die "payload image ${PAYLOAD_IMAGE} missing"
	[ -f "${_sum}" ] || die "payload checksum ${PAYLOAD_IMAGE}.sha256 missing"
	msg "verifying payload checksum (this reads the whole image)..."
	_want=$(cut -d' ' -f1 <"${_sum}")
	_have=$(sha256sum "${_img}" | cut -d' ' -f1)
	[ "${_want}" = "${_have}" ] || die "payload checksum mismatch (want ${_want}, have ${_have})"
	msg "payload checksum OK"
}

# ---- target enumeration -------------------------------------------

# Print candidate target disks, one per line: "<dev> <size-bytes> <model>".
# Excludes the stick, loop/ram/zram, and read-only devices.
installer_list_targets() {
	for _d in /sys/block/*; do
		_name=$(basename "${_d}")
		case "${_name}" in
		loop*|ram*|zram*|sr*|fd*|dm-*) continue ;;
		esac
		_dev="/dev/${_name}"
		[ "${_dev}" = "${STICK_DISK}" ] && continue
		# Skip removable/zero-size and read-only.
		_ro=$(cat "${_d}/ro" 2>/dev/null || echo 1)
		[ "${_ro}" = "0" ] || continue
		_sectors=$(cat "${_d}/size" 2>/dev/null || echo 0)
		[ "${_sectors}" -gt 0 ] 2>/dev/null || continue
		_bytes=$(( _sectors * 512 ))
		_model=$(cat "${_d}/device/model" 2>/dev/null | tr -s ' ' | sed 's/ $//' || true)
		[ -n "${_model}" ] || _model='(unknown)'
		printf '%s %s %s\n' "${_dev}" "${_bytes}" "${_model}"
	done
}

# ---- write --------------------------------------------------------

# Stream the compressed full-disk image onto the target and sync.
# busybox xz + dd: sparse-aware bmap writing is a later refinement.
installer_write_target() {
	_target="$1"
	_img="${PAYLOAD_MNT}/${PAYLOAD_IMAGE}"
	msg "writing ${PAYLOAD_IMAGE} to ${_target} (do not power off)..."
	case "${PAYLOAD_IMAGE}" in
	*.xz)  xz -dc "${_img}" | dd of="${_target}" bs=4M conv=fsync 2>/dev/null ;;
	*)     dd if="${_img}" of="${_target}" bs=4M conv=fsync 2>/dev/null ;;
	esac || die "write to ${_target} FAILED; the target is left unbootable (no other disk was touched)"
	sync
	# Re-read the partition table so the just-written GPT is visible.
	blockdev --rereadpt "${_target}" 2>/dev/null || true
	msg "write complete and synced"
}
