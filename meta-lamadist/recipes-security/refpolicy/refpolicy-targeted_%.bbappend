# SPDX-License-Identifier: Apache-2.0
#
# Link the LamaDist local SELinux policy module into refpolicy-targeted's
# monolithic policy at BUILD time (M4 stage B, W12).
#
# Why a refpolicy bbappend instead of a standalone module package:
# refpolicy uses semodule nowhere at rootfs time.  Its own build compiles
# every module (mount, ssh, lvm, ...) and links them into one policy store
# via prepare_policy_store + rebuild_policy in refpolicy_common.inc, whose
# rebuild_policy writes a semanage.conf pointing setfiles and
# sefcontext_compile at the recipe-sysroot-native tools before it runs
# `semodule -B`.  The previous approach shipped lamadist as its own package
# and ran an offline `semodule -i lamadist.cil` in a do_rootfs pkg_postinst;
# that ran with the target's stock semanage.conf, so semodule spawned the
# rootfs's own (target) setfiles with no native redirect and failed
# ("setfiles returned error code 1").  Each offline-tool fix only exposed
# the next relocation (HLL pp, then setfiles, next sefcontext_compile).
#
# Making lamadist just another refpolicy module makes it inherit that whole
# working pipeline: refpolicy's build compiles lamadist.pp, converts it to
# CIL, adds it to the policy store, and links it with `semodule -B` using
# the native tool paths -- so the module is in the store when
# selinux-image.bbclass's build-time setfiles pass labels the rootfs, and
# there is no rootfs-time semodule at all.  See lamadist.te for the FORM
# conversion (loadable-module -> policy_module/gen_require; rules verbatim).

FILESEXTRAPATHS:prepend := "${THISDIR}/files:"

SRC_URI += " \
    file://lamadist.te \
    file://lamadist.if \
    file://lamadist.fc \
"

# refpolicy layer to graft the module into.  `system` is refpolicy's home
# for mount, init, systemd, logging, lvm, udev and setrans -- the domains
# lamadist's rules mostly touch -- and it already carries a metadata.xml,
# so segenxml/gendoc treat lamadist like any other system module.  Grafting
# into an existing, known-good layer (rather than inventing a new one) keeps
# `make conf` from tripping over a missing layer metadata file.
LAMADIST_SELINUX_LAYER ?= "system"

# Drop the module into refpolicy's own module tree before do_compile's
# `oe_runmake conf` scans the layers (Makefile: detected_mods := find
# moddir).  do_compile:prepend keeps placement in the same task that
# consumes the files, so there is no cross-task ${S} state to reason about.
do_compile:prepend() {
    install -m 0644 ${UNPACKDIR}/lamadist.te \
        ${S}/policy/modules/${LAMADIST_SELINUX_LAYER}/lamadist.te
    install -m 0644 ${UNPACKDIR}/lamadist.if \
        ${S}/policy/modules/${LAMADIST_SELINUX_LAYER}/lamadist.if
    install -m 0644 ${UNPACKDIR}/lamadist.fc \
        ${S}/policy/modules/${LAMADIST_SELINUX_LAYER}/lamadist.fc
}

# Guarantee lamadist is enabled in modules.conf.  `oe_runmake conf`'s XML
# pass (support/sedoctool.py) already defaults a newly-detected, non-base
# module to "module", but this makes enablement explicit and independent of
# that pass.  It runs right after `oe_runmake conf` and before `oe_runmake
# policy` because refpolicy_common.inc calls disable_policy_modules exactly
# there; the idempotent guard means it is a no-op when conf already added
# the entry.  A module set to "module" is built as a loadable module and
# linked into the monolithic policy by rebuild_policy's `semodule -B`.
disable_policy_modules:append() {
    if ! grep -qE '^[[:space:]]*lamadist[[:space:]]*=' \
            ${S}/policy/modules.conf; then
        echo "lamadist = module" >> ${S}/policy/modules.conf
    fi
}

# Note on neverallow assertions: rebuild_policy's build-time `semodule -B`
# runs with expand-check=1 (its fresh semanage.conf omits the expand-check=0
# that meta-selinux's libsemanage patch sets elsewhere), so refpolicy's
# neverallow assertions ARE enforced at the policy link.  lamadist satisfies
# the one assertion its rules touch (authlogin's `neverallow
# ~can_read_shadow_passwords shadow_t:file read`) the sanctioned way:
# lamadist.te calls auth_can_read_shadow_passwords(mount_t), and the shadow
# read itself arrives through files_read_all_files(mount_t)'s file_type
# coverage (the earlier explicit bounded shadow allow was subsumed and
# removed).  No rebuild_policy override and no expand-check bend needed --
# and the active assertions remain a build-time regression guard for future
# policy edits.
