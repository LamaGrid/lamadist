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
# environment (boot_targets pinned, fdtfile empty).  The fragment turns
# the U-Boot prompt off (CMDLINE) and boots through BOOTSTD_PROG.

FILESEXTRAPATHS:prepend := "${THISDIR}/files:"

SRC_URI:append:soquartz-lamadist = " \
    file://lamadist-soquartz-efi.cfg \
    file://lamadist-soquartz.env \
    file://0001-efi_loader-link-bootm-for-ExitBootServices.patch \
"

# With CMDLINE off nothing builds boot/bootm.o, but the EFI loader's
# ExitBootServices calls two functions in it, so the final link fails.
# The patch builds bootm.o through LIB_BOOTM (ADR 0013 decision 3); it
# adds no command or boot method.  It rides the SRC_URI:append above, so
# no other machine's U-Boot is patched.

# U-Boot turns the env text file into a C header with xxd, which is not
# a HOSTTOOL.  oe-core's vim-native provides it (build-time only; Vim
# license; nothing of it reaches the image).
DEPENDS:append:soquartz-lamadist = " xxd-native"

# The EFI variable preseed (PK, KEK, db; ADR 0016) is generated at
# build time from the key hierarchy the x86_64 gate enrolls and is never
# checked in.  The class writes ${S}/${LAMADIST_EFI_VAR_SEED_FILE}
# between do_patch and do_configure; the fragment names the same file
# source-relative (lib/efi_loader/Makefile prefixes $(srctree)/).  The
# class is inherited for this machine only, so no other machine's U-Boot
# gains the task.  The default is empty so that inherit_defer expands to
# nothing and the file parses on every machine; an unset variable would
# stay a literal ${...} and fail the parse ("Could not inherit file").
LAMADIST_UBOOT_SEED_CLASS ??= ""
LAMADIST_UBOOT_SEED_CLASS:soquartz-lamadist = "lamadist-efi-var-seed"
inherit_defer ${LAMADIST_UBOOT_SEED_CLASS}

# U-Boot reaches the image through the WKS rawcopy dependencies only, and
# virtual/bootloader stays systemd-boot (ADR 0013 decision 10).  oe-core
# base.bbclass skips every other provider of a virtual/ name that has a
# PREFERRED_PROVIDER, so on this machine U-Boot stops providing
# virtual/bootloader; its other PROVIDES need no change.
PROVIDES:remove:soquartz-lamadist = "virtual/bootloader"

do_configure:prepend:soquartz-lamadist () {
	# The fragment names the environment file source-relative, because
	# u-boot-configure.inc merges the layer's copy of the fragment (an
	# edit to the ${UNPACKDIR} copy would never reach .config).  Put the
	# file where that name resolves.
	install -m 0644 "${UNPACKDIR}/lamadist-soquartz.env" "${S}/lamadist-soquartz.env"
	cfg="${UNPACKDIR}/lamadist-soquartz-efi.cfg"
	# Fail closed: a fragment and a class that disagree on the seed name,
	# or a missing seed, must stop the build rather than ship a U-Boot
	# with no Secure Boot variables.
	if ! grep -qx 'CONFIG_EFI_VAR_SEED_FILE="${LAMADIST_EFI_VAR_SEED_FILE}"' "$cfg"; then
		bbfatal "lamadist-soquartz-efi.cfg must set CONFIG_EFI_VAR_SEED_FILE=\"${LAMADIST_EFI_VAR_SEED_FILE}\" (ADR 0013 decision 3)"
	fi
	if [ ! -s "${S}/${LAMADIST_EFI_VAR_SEED_FILE}" ]; then
		bbfatal "no EFI variable seed at ${S}/${LAMADIST_EFI_VAR_SEED_FILE}: is lamadist-efi-var-seed inherited? (ADR 0013 decision 3)"
	fi
}

# Fail closed on the merged .config.  u-boot-configure.inc merges the
# fragments over the defconfig and runs oldconfig, which drops a symbol
# whose dependencies are not met and says nothing, so a Kconfig that moves
# under a branch-head layer could give a U-Boot with no Secure Boot or no
# seed while every check on the fragment text stays green.  The run-time
# write protection of PK, KEK, and db (ADR 0013 decision 3) rests on these
# symbols, so the task reads the built ${B}/.config.
#
# The caller names the fragments it merges, in merge order, and every
# line of them is checked; no symbol list is kept here.  An assignment
# line must appear in .config as written ("=y" lines and the file
# names alike).  An "is not set" line must have no "=y" line; absent
# counts as off, because a symbol hidden behind another
# (EFI_RT_VOLATILE_STORE behind EFI_VARIABLE_FILE_STORE) is not printed.
# When two fragments name one symbol, the later one wins, as in the
# merge.  The seed file must also be the one the seed class writes.  The
# function is shared with the QEMU payload (lamadist-uboot-vm.inc) so
# both builds check the same way; defining it changes no task that does
# not call it.
lamadist_uboot_check_config () {
	built_cfg="${B}/.config"
	if [ ! -s "$built_cfg" ]; then
		bbfatal "no merged U-Boot .config at $built_cfg (ADR 0013 decision 3)"
	fi
	if [ "$#" -eq 0 ]; then
		bbfatal "lamadist_uboot_check_config needs the merged fragments, in merge order (ADR 0013 decision 3)"
	fi
	want="${B}/lamadist-config.want"
	awk '
		/^CONFIG_[A-Za-z0-9_]+=/ {
			sym = $0
			sub(/=.*/, "", sym)
			want[sym] = "set " $0
		}
		/^# CONFIG_[A-Za-z0-9_]+ is not set$/ {
			want[$2] = "off " $2
		}
		END {
			for (sym in want) {
				print want[sym]
			}
		}
	' "$@" | LC_ALL=C sort > "$want"
	if ! grep -q '^set ' "$want"; then
		bbfatal "the merged fragments ($*) set no symbol (ADR 0013 decision 3)"
	fi
	while read -r state line; do
		case "$state" in
			set)
				if ! grep -qxF "$line" "$built_cfg"; then
					bbfatal "merged U-Boot .config lacks the fragment line $line: oldconfig dropped or changed it (ADR 0013 decision 3)"
				fi
				;;
			off)
				if grep -qx "$line=y" "$built_cfg"; then
					bbfatal "merged U-Boot .config turns $line on, which a fragment keeps off (ADR 0013 decision 3)"
				fi
				;;
		esac
	done < "$want"
	if ! grep -qx 'CONFIG_EFI_VAR_SEED_FILE="${LAMADIST_EFI_VAR_SEED_FILE}"' "$built_cfg"; then
		bbfatal "merged U-Boot .config does not set CONFIG_EFI_VAR_SEED_FILE=\"${LAMADIST_EFI_VAR_SEED_FILE}\" (ADR 0013 decision 3)"
	fi
}

do_configure:append:soquartz-lamadist () {
	lamadist_uboot_check_config "${UNPACKDIR}/lamadist-soquartz-efi.cfg"
}

# Fail closed on the default environment.  u-boot.inc's uboot_compile
# runs "make u-boot-initial-env" (no UBOOT_CONFIG on this machine), which
# leaves ${B}/u-boot-initial-env: the environment U-Boot really carries.
# It must equal the layer's env text, comments stripped, sorted, or a
# wrong environment (a stray bootcmd, a lost boot_targets pin) would
# ship silently.  An empty or missing file fails too.
do_compile:append:soquartz-lamadist () {
	built="${B}/u-boot-initial-env"
	if [ ! -s "$built" ]; then
		bbfatal "no built default environment at $built (ADR 0013 decision 3)"
	fi
	grep -v -e '^[[:space:]]*#' -e '^[[:space:]]*$' "${UNPACKDIR}/lamadist-soquartz.env" | LC_ALL=C sort > "${B}/lamadist-env.want"
	grep -v -e '^[[:space:]]*#' -e '^[[:space:]]*$' "$built" | LC_ALL=C sort > "${B}/lamadist-env.got"
	if [ ! -s "${B}/lamadist-env.want" ] || ! cmp -s "${B}/lamadist-env.want" "${B}/lamadist-env.got"; then
		diff "${B}/lamadist-env.want" "${B}/lamadist-env.got" || true
		bbfatal "built u-boot-initial-env differs from lamadist-soquartz.env (ADR 0013 decision 3)"
	fi
}

# The `vm --firmware u-boot` QEMU payload for qemuarm64-lamadist (ADR
# 0013 open question 6).  Off unless kas/extras/uboot-vm.kas.yml sets
# LAMADIST_UBOOT_VM = "1"; when off, nothing is included and no machine's
# U-Boot changes.  An empty require includes nothing.
LAMADIST_UBOOT_VM ??= "0"
require ${@'lamadist-uboot-vm.inc' if d.getVar('LAMADIST_UBOOT_VM') == '1' else ''}
