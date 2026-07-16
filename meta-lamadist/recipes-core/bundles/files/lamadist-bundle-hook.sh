#!/bin/sh
# SPDX-License-Identifier: Apache-2.0
#
# RAUC bundle hook for LamaDist.  rauc invokes this script as
# "lamadist-bundle-hook.sh <hook-name>" with the RAUC_* environment
# documented under "Update Hooks" in the RAUC reference
# (https://rauc.readthedocs.io/en/latest/reference.html).  Two hook
# points are wired from lamadist-bundle.bb:
#
#   install-check      bundle-wide, RAUC_BUNDLE_HOOKS[hooks]
#   slot-post-install  rootfs slot only, RAUC_SLOT_rootfs[hooks]
#
# Note the asymmetry: the manifest registers the slot hook as
# hooks=post-install, but RAUC invokes the script with the argument
# "slot-post-install" (R_SLOT_HOOK_POST_INSTALL in the pinned
# 1.15.1 src/update_handler.c); bundle hooks are invoked with their
# manifest name verbatim ("install-check").
#
# The ESP is not a RAUC slot (single shared vfat, both slots' boot
# files live on it); this hook is how its per-slot content
# (ESP/lamadist/<slot>/ plus the systemd-boot entry) gets written
# after RAUC raw-writes the new rootfs, per the M3 plan's decision
# 5.  RAUC_UPDATE_SOURCE is only populated for the deprecated
# [handlers] preinstall/postinstall mechanism, not for [hooks]
# (confirmed against the pinned RAUC 1.15.1 source: run_bundle_hook()
# in src/install.c and run_slot_hook_extra_env() in
# src/update_handler.c never set it), so the bundle content
# directory is derived from this script's own invocation path
# instead -- RAUC always execs the hook by its absolute path inside
# the mounted bundle.

set -eu

# shellcheck disable=SC1007 # intentional: CDPATH= for this cd only
BUNDLE_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)

ESP=/boot
BOOTFILES_TAR="${BUNDLE_DIR}/bootfiles.tar"

hook="${1:-}"

case "${hook}" in
install-check)
    # post-install needs a writable ESP and the bootfiles
    # payload; fail before RAUC starts writing raw partitions rather
    # than partway through an update.
    if ! mountpoint -q "${ESP}"; then
        echo "lamadist-bundle-hook: ${ESP} is not a mount point" >&2
        exit 1
    fi
    if [ ! -f "${BOOTFILES_TAR}" ]; then
        echo "lamadist-bundle-hook: bootfiles.tar not found in bundle (${BOOTFILES_TAR})" >&2
        exit 1
    fi
    ;;
slot-post-install)
    # Only the rootfs slot carries this hook (see
    # RAUC_SLOT_rootfs[hooks] in lamadist-bundle.bb); the class
    # check below is defensive in case that ever changes.
    if [ "${RAUC_SLOT_CLASS:-}" != "rootfs" ]; then
        exit 0
    fi

    case "${RAUC_SLOT_BOOTNAME:-}" in
    a|b)
        slot="${RAUC_SLOT_BOOTNAME}"
        ;;
    *)
        echo "lamadist-bundle-hook: unexpected RAUC_SLOT_BOOTNAME '${RAUC_SLOT_BOOTNAME:-}'" >&2
        exit 1
        ;;
    esac

    slotdir="${ESP}/lamadist/${slot}"
    rm -rf "${slotdir}"
    mkdir -p "${slotdir}"

    tmpdir=$(mktemp -d)
    trap 'rm -rf "${tmpdir}"' EXIT
    tar -xf "${BOOTFILES_TAR}" -C "${tmpdir}"

    for f in "${tmpdir}"/*; do
        name=$(basename "${f}")
        [ "${name}" = "lamadist-boot-entry.conf" ] && continue
        mv "${f}" "${slotdir}/${name}"
    done

    mkdir -p "${ESP}/loader/entries"
    # Remove any existing entry for this slot first -- once a slot is
    # marked good, files/systemd-boot-backend's set-state renames its
    # entry to the bare, counter-less lamadist-<slot>.conf.  Leaving
    # that stale entry in place alongside the fresh +3 one written
    # below would make entry_for_slot() (which globs the bare name
    # first) keep resolving to the old, already-good entry instead of
    # the newly installed one.
    rm -f "${ESP}/loader/entries/lamadist-${slot}.conf" "${ESP}/loader/entries/lamadist-${slot}"+*.conf
    # @SLOT@ is the only placeholder still unresolved in the
    # bundle's copy of the template -- roothash/kernel/initrd were
    # already baked in at bundle-build time (see lamadist-bundle.bb)
    # since they are fixed for the build, but the target slot (a or
    # b) is only known here, at install time.
    sed "s/@SLOT@/${slot}/g" "${tmpdir}/lamadist-boot-entry.conf" \
        > "${ESP}/loader/entries/lamadist-${slot}+3.conf"

    # Leave the currently-booted slot's loader entry and
    # loader.conf 'default' alone; switching the boot target is the
    # bootloader backend's job (RAUC's systemd-boot backend or the
    # custom-backend script), not this hook's.
    ;;
*)
    # Fail loudly: RAUC only invokes hook names this bundle
    # registered, so an unmatched name is always a wiring bug --
    # a silent exit 0 here masked the post-install hook never
    # running at all.
    echo "lamadist-bundle-hook: unexpected hook '${hook}'" >&2
    exit 1
    ;;
esac
