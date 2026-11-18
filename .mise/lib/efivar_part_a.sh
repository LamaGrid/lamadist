#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
#
# N7 write test, Part A: runs as root in the qemuarm64 guest, sent over
# the serial console by efivar_write_test.py.  It tries every payload
# row through efivarfs and prints one N7A line per result; the host
# turns the lines into the verdict (docs/validation/N7-WRITE-TEST.md).
#
# usage: part_a.sh full|boot2
#   full   state, remount (A1), the eight rows, state again
#   boot2  state after the reset
#
# Each /run/n7/<row>.bin holds the efivarfs layout (4-byte attributes,
# then data), so one write(2) of the whole file is one SetVariable.
# The script never stops on a failed command: every failure is a
# result to print.
set -o nounset

readonly EFIVARS=/sys/firmware/efi/efivars
readonly GLOBAL=8be4df61-93ca-11d2-aa0d-00e098032b8c
readonly SECDB=d719b2cb-3d3a-4596-a3bc-dad00e67656f

var_file() {
	case "$1" in
		PK | KEK | SecureBoot | SetupMode) echo "${EFIVARS}/$1-${GLOBAL}" ;;
		db | dbx) echo "${EFIVARS}/$1-${SECDB}" ;;
	esac
}

# The data after the 4 attribute bytes, as a SHA-256 or "absent".
body_sha() {
	local f
	f=$(var_file "$1")
	if [[ -e "${f}" ]]; then
		tail -c +5 "${f}" | sha256sum | cut -d' ' -f1
	else
		echo absent
	fi
}

# A one-byte mode variable as a number, or "absent".
mode_byte() {
	local f
	f=$(var_file "$1")
	if [[ -e "${f}" ]]; then
		tail -c +5 "${f}" | od -An -tu1 | tr -d ' \n'
	else
		echo absent
	fi
}

mount_mode() {
	local m
	m=$(awk -v d="${EFIVARS}" '$2 == d { split($4, o, ","); print o[1] }' /proc/mounts)
	echo "${m:-none}"
}

state() {
	local test=absent
	[[ -e /dev/efi_test ]] && test=present
	echo "N7A STATE $1 secureboot=$(mode_byte SecureBoot)" \
		"setupmode=$(mode_byte SetupMode) PK=$(body_sha PK)" \
		"KEK=$(body_sha KEK) db=$(body_sha db) dbx=$(body_sha dbx)" \
		"mount=$(mount_mode) efi_test=${test}"
}

# Last error line, on one line, for the N7A record.
oneline() {
	tr '\n' ' ' | sed 's/ *$//; s/^$/-/'
}

# The error line of a failed command, read from stdin.  When open
# succeeds and write fails, dd prints "dd: error writing ...: <errno>"
# first and its record counts after, so the last line would drop the
# errno: take the first "dd: " or "rm: " line, else the last line.
error_line() {
	local all
	all=$(cat)
	printf '%s' "${all}" | grep -m 1 -E '^(dd|rm): ' \
		|| printf '%s' "${all}" | tail -n 1
}

info() {
	local ctx enforce chattr_path
	ctx=$(tr -d '\0' </proc/self/attr/current 2>/dev/null)
	enforce=$(cat /sys/fs/selinux/enforce 2>/dev/null)
	chattr_path=$(command -v chattr)
	echo "N7A INFO selinux=${ctx:-none} enforce=${enforce:-none}" \
		"chattr=${chattr_path:-missing}"
}

remount() {
	local err rc
	err=$(mount -o remount,rw "${EFIVARS}" 2>&1)
	rc=$?
	echo "N7A A1 rc=${rc} mount=$(mount_mode) err=$(printf '%s' "${err}" | oneline)"
}

row() {
	local tag=$1 var=$2 file payload err rc
	file=$(var_file "${var}")
	payload=/run/n7/${tag}.bin
	# PK, KEK, and db carry the immutable flag in efivarfs; clearing it
	# is part of the attempt and its failure is not the result.
	chattr -i "${file}" 2>/dev/null
	if [[ "${tag}" == X-PK ]]; then
		err=$(rm "${file}" 2>&1)
		rc=$?
	else
		err=$(dd if="${payload}" of="${file}" bs="$(stat -c %s "${payload}")" \
			count=1 conv=notrunc 2>&1 >/dev/null)
		rc=$?
		# On success dd prints only record counts.
		[[ ${rc} -eq 0 ]] && err=-
	fi
	echo "N7A ROW ${tag} rc=${rc} err=$(printf '%s' "${err}" | error_line | oneline)"
}

main() {
	# Kernel messages on the console would split N7A lines.
	dmesg -n 1 2>/dev/null

	case "${1:-}" in
		full)
			state pre
			info
			remount
			row U-PK PK
			row U-KEK KEK
			row U-db db
			row W-db db
			row X-PK PK
			row S-db db
			row S-KEK KEK
			row S-PK PK
			state post
			echo "N7A DONE full"
			;;
		boot2)
			state boot2
			echo "N7A DONE boot2"
			;;
		*)
			echo "usage: $0 full|boot2" >&2
			exit 2
			;;
	esac
}

# Run only as a script: a test sources this file to call row().
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
	main "$@"
fi
