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
die() {
	printf '%s: FATAL %s\n' "${_INST_TAG}" "$*" >&2
	installer_halt 1
}

# Terminal action.  Interactive mode drops to a shell so the operator
# can inspect; headless halts the machine.  NEITHER path ever falls
# through to a rootfs pivot -- there is no rootfs in this initramfs.
installer_halt() {
	_rc="${1:-1}"
	if [ "${INSTALLER_HEADLESS:-no}" = yes ]; then
		msg "headless install halted (rc=${_rc})"
		# Poweroff so an automated harness sees a clean stop rather
		# than a hang; -f because there is no init to signal.
		poweroff -f 2> /dev/null || halt -f 2> /dev/null || exec sh
	else
		msg "dropping to a shell (rc=${_rc}); the target was not"
		msg "modified unless a write was explicitly reported above."
		# Canonical initramfs idiom: a fresh session plus a
		# controlling tty so job control and ^C work.  setsid -c
		# can fork under a process-group leader (fatal for a
		# would-be PID 1), so prefer cttyhack; guard each applet.
		if command -v setsid > /dev/null 2>&1; then
			if command -v cttyhack > /dev/null 2>&1; then
				exec setsid cttyhack sh
			fi
			exec setsid -c sh
		fi
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
	mount -t efivarfs efivarfs "${EFIVARS}" 2> /dev/null || true
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

# GUID of systemd-stub's loader EFI variables.
LOADER_VENDOR=4a67b082-0a4c-41cf-b6c7-440b29bb8c4f

# Print the boot ESP's PARTUUID from systemd-stub's
# LoaderDevicePartUUID variable (4 efivarfs attribute bytes, then
# UTF-16LE text).  Reads efivarfs directly, with no udev dependence,
# so its presence can be decided BEFORE any device races.  Caveat
# (accepted, documented): the variable names the LOADER'S ESP; on the
# supported direct-firmware boot that is the stick, while a UKI
# chainloaded from an internal loader would name the internal ESP --
# a clean internal disk then fails closed (no payload found there).
installer_loader_partuuid() {
	_lv="${EFIVARS}/LoaderDevicePartUUID-${LOADER_VENDOR}"
	[ -r "${_lv}" ] || return 1
	_u=$(tail -c +5 "${_lv}" 2> /dev/null | tr -d '\000\r\n' \
		| tr '[:upper:]' '[:lower:]')
	[ -n "${_u}" ] || return 1
	printf '%s\n' "${_u}"
}

# Resolve a PARTUUID to its whole-disk device once udev has created
# the by-partuuid symlink.  Prints /dev/<disk>.
installer_boot_disk_for() {
	_bp=$(readlink -f "/dev/disk/by-partuuid/$1" 2> /dev/null || true)
	[ -b "${_bp}" ] || return 1
	installer_part_to_disk "${_bp}"
}

# Count partitions whose GPT PARTUUID equals $1.  More than one means
# a cloned boot medium (a dd copy of the stick image on another disk)
# and the boot-device anchor is ambiguous.
installer_partuuid_claimants() {
	_n=0
	for _pb in /sys/class/block/*; do
		[ -e "${_pb}/partition" ] || continue
		_pdev="/dev/${_pb##*/}"
		[ -b "${_pdev}" ] || continue
		if [ "$(blkid -o value -s PARTUUID "${_pdev}" 2> /dev/null)" = "$1" ]; then
			_n=$((_n + 1))
		fi
	done
	printf '%s\n' "${_n}"
}

# Find the payload partition on ONE disk by filesystem label.
installer_find_payload_on() {
	_disk="${1##*/}"
	for _pd in "/sys/block/${_disk}/${_disk}"*; do
		[ -e "${_pd}" ] || continue
		_cand="/dev/${_pd##*/}"
		[ -b "${_cand}" ] || continue
		if [ "$(blkid -o value -s LABEL "${_cand}" 2> /dev/null)" = "${PAYLOAD_LABEL}" ]; then
			printf '%s\n' "${_cand}"
			return 0
		fi
	done
	return 1
}

# Locate the stick's payload partition, mount it read-only, and set
# STICK_DISK to the whole-disk device that carries it (so target
# enumeration can exclude the stick).  The stick is identified by
# the boot device (LoaderDevicePartUUID), NOT by a global by-label
# lookup: a label match on any other disk is stale or hostile data,
# never the medium the firmware verified and booted (observed in the
# field: a stale payload label on the internal NVMe captured the
# by-label symlink, so the installer excluded the internal disk as
# "the stick" and offered the real stick as the target).  Whether
# the variable exists is decided ONCE, straight from efivarfs and
# before any udev race, so a slow-enumerating stick can never
# demote discovery to the by-label path; that path survives only
# for the explicit insecure lab run.  A duplicate of the boot
# PARTUUID on another disk (a dd clone of the stick image) makes
# the anchor ambiguous and dies.
installer_mount_payload() {
	# The trust gate mounts efivarfs too, but not on the insecure
	# lab bypass; the loader variable is needed either way.
	mkdir -p "${EFIVARS}"
	mount -t efivarfs efivarfs "${EFIVARS}" 2> /dev/null || true
	_boot_uuid=$(installer_loader_partuuid || true)
	# Poll for the payload partition: USB mass-storage enumerates
	# asynchronously and a single settle can return before the stick
	# has even triggered udev (observed: the installer raced the
	# stick's SCSI attach).  Bounded at 40 rounds.
	STICK_DISK=""
	_part=""
	_c=0
	while [ "${_c}" -lt 40 ]; do
		udevadm settle --timeout=5 2> /dev/null || true
		if [ -n "${_boot_uuid}" ]; then
			STICK_DISK=$(installer_boot_disk_for "${_boot_uuid}" || true)
			[ -z "${STICK_DISK}" ] \
				|| _part=$(installer_find_payload_on "${STICK_DISK}" || true)
		else
			_part=$(readlink -f "/dev/disk/by-label/${PAYLOAD_LABEL}" 2> /dev/null || true)
		fi
		[ -b "${_part}" ] && break
		sleep 1
		_c=$((_c + 1))
	done
	if [ -n "${_boot_uuid}" ]; then
		[ -b "${_part}" ] || die "payload partition (LABEL=${PAYLOAD_LABEL}) not found on boot stick ${STICK_DISK:-unresolved} (timed out)"
		# Anti-clone recheck: the true stick has enumerated by now
		# (we booted from it and just found its payload), so a
		# second claimant of the boot PARTUUID is a dd copy and the
		# anchor is ambiguous.  Fail closed.
		udevadm settle --timeout=5 2> /dev/null || true
		_claims=$(installer_partuuid_claimants "${_boot_uuid}")
		[ "${_claims}" = "1" ] || die "boot PARTUUID ${_boot_uuid} found on ${_claims} partitions (cloned boot medium?); wipe or unplug the copy"
	else
		# A signed systemd-stub UKI always sets the loader
		# variable; its absence is anomalous, never routine.
		[ "${bootparam_lamadist_installer_insecure:-}" = "1" ] \
			|| die "LoaderDevicePartUUID absent; refusing the by-label fallback outside an insecure lab run"
		[ -b "${_part}" ] || die "payload partition (LABEL=${PAYLOAD_LABEL}) not found (timed out)"
		warn "LoaderDevicePartUUID unavailable; trusting the by-label scan for the stick disk (insecure lab run)"
		STICK_DISK=$(installer_part_to_disk "${_part}")
	fi
	[ -n "${STICK_DISK}" ] || die "cannot resolve stick disk for ${_part}"
	mkdir -p "${PAYLOAD_MNT}"
	mount -o ro "${_part}" "${PAYLOAD_MNT}" || die "cannot mount payload ${_part}"
	msg "payload on ${_part} (stick disk ${STICK_DISK})"
}

# Map a partition device (/dev/sda1) to its whole-disk device
# (/dev/sda) via sysfs, so it works for sd*, vd*, nvme*, mmcblk*.
installer_part_to_disk() {
	_p="${1##*/}"
	_sys=$(readlink -f "/sys/class/block/${_p}" 2> /dev/null || true)
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
	_want=$(cut -d' ' -f1 < "${_sum}")
	_have=$(sha256sum "${_img}" | cut -d' ' -f1)
	[ "${_want}" = "${_have}" ] || die "payload checksum mismatch (want ${_want}, have ${_have})"
	msg "payload checksum OK"
}

# ---- target enumeration -------------------------------------------

# Print candidate target disks, one per line: "<dev> <size-bytes> <model>".
# Excludes the stick, loop/ram/zram, read-only, and removable devices.
installer_list_targets() {
	for _d in /sys/block/*; do
		_name=$(basename "${_d}")
		case "${_name}" in
			loop* | ram* | zram* | sr* | fd* | dm-*) continue ;;
		esac
		_dev="/dev/${_name}"
		[ "${_dev}" = "${STICK_DISK}" ] && continue
		# Skip read-only, removable, and zero-size media: targets
		# are fixed internal disks; the stick and any other USB
		# medium are never install targets.
		_ro=$(cat "${_d}/ro" 2> /dev/null || echo 1)
		[ "${_ro}" = "0" ] || continue
		_rm=$(cat "${_d}/removable" 2> /dev/null || echo 1)
		[ "${_rm}" = "0" ] || continue
		_sectors=$(cat "${_d}/size" 2> /dev/null || echo 0)
		[ "${_sectors}" -gt 0 ] 2> /dev/null || continue
		_bytes=$((_sectors * 512))
		_model=$(cat "${_d}/device/model" 2> /dev/null | tr -s ' ' | sed 's/ $//' || true)
		[ -n "${_model}" ] || _model='(unknown)'
		printf '%s %s %s\n' "${_dev}" "${_bytes}" "${_model}"
	done
}

# ---- boot order ---------------------------------------------------

BOOTNEXT_LABEL='LamaDist'

# Point the firmware at the freshly written target: create a boot
# entry for its ESP (partition 1, lamadist-dmverity-bootdisk wks,
# fallback loader path), prepend it to BootOrder, and set BootNext
# to it.  Without this, a USB-first boot order re-enters the stick
# after the final reboot -- and a headless manifest then reinstalls
# in a loop.  Honest scope: BootNext is one-shot and some firmware
# re-prioritizes removable media per boot regardless of BootOrder,
# so a stick left inserted can still re-enter at the boot after
# next; the SPEC's install-consumed flag (a later increment) is the
# durable closure.  Best-effort by design: every failure warns and
# falls through to the firmware's own order -- an availability
# concern, never an integrity one.
installer_set_bootnext() {
	_target="$1"
	if ! command -v efibootmgr > /dev/null 2>&1; then
		warn "efibootmgr missing; firmware boot order left unchanged"
		return 0
	fi
	# efibootmgr v18 prints "BootNNNN* Label<TAB>DevicePath" even
	# without -v, and inactive entries use two spaces after NNNN;
	# match the label bounded by blank-or-EOL, never anchored bare.
	_sed_num="s/^Boot\([0-9A-Fa-f]\{4\}\)[* ] ${BOOTNEXT_LABEL}\([[:blank:]].*\)\{0,1\}\$/\1/p"
	# Retire entries from previous installs so reinstalls do not
	# accumulate NVRAM clutter under our label.
	for _old in $(efibootmgr 2> /dev/null | sed -n "${_sed_num}"); do
		efibootmgr -q -b "${_old}" -B 2> /dev/null || true
	done
	# The loader path is the x86_64 removable fallback; the M5 ARM
	# port must switch this to \EFI\BOOT\BOOTAA64.EFI (derive from
	# the target EFI arch when that lands).
	_out=$(efibootmgr --create --disk "${_target}" --part 1 \
		--label "${BOOTNEXT_LABEL}" --loader '\EFI\BOOT\BOOTX64.EFI' 2>&1)
	_num=$(printf '%s\n' "${_out}" | sed -n "${_sed_num}" | tail -1)
	if [ -z "${_num}" ]; then
		warn "could not create a boot entry for ${_target} ($(printf '%s\n' "${_out}" | tail -1)); firmware boot order left unchanged"
		return 0
	fi
	if _err=$(efibootmgr -q --bootnext "${_num}" 2>&1); then
		msg "BootNext -> Boot${_num} (${BOOTNEXT_LABEL} on ${_target})"
	else
		warn "could not set BootNext (${_err}); firmware boot order left unchanged"
	fi
}

# ---- write --------------------------------------------------------

# Stream the compressed full-disk image onto the target and sync.
# busybox xz + dd: sparse-aware bmap writing is a later refinement.
installer_write_target() {
	_target="$1"
	_img="${PAYLOAD_MNT}/${PAYLOAD_IMAGE}"
	msg "writing ${PAYLOAD_IMAGE} to ${_target} (do not power off)..."
	case "${PAYLOAD_IMAGE}" in
		*.xz) xz -dc "${_img}" | dd of="${_target}" bs=4M conv=fsync 2> /dev/null ;;
		*) dd if="${_img}" of="${_target}" bs=4M conv=fsync 2> /dev/null ;;
	esac || die "write to ${_target} FAILED; the target is left unbootable (no other disk was touched)"
	sync
	# Re-read the partition table so the just-written GPT is visible.
	blockdev --rereadpt "${_target}" 2> /dev/null || true
	msg "write complete and synced"
}
