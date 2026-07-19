# SPDX-License-Identifier: Apache-2.0
#
# RAUC update bundle for LamaDist A/B updates.
#
# RAUC_BUNDLE_FORMAT = "verity" is RAUC's own modern signed-bundle
# format (a squashfs payload sealed with its own dm-verity hash
# tree) -- unrelated to the OS's dm-verity rootfs slots this bundle
# updates.
#
# Slots: rootfs/hash mirror the [slot.rootfs.N]/[slot.hash.N]
# classes in system.conf (recipes-core/rauc/, W4) and are raw-copied
# straight from this build's dm-verity artifacts.  There is no
# "bootfiles" slot: the ESP is a single shared vfat, not an A/B
# slot, so its content (both slots' UKIs -- lamadist-a.efi,
# lamadist-b.efi, built by W2's lamadist-uki.bbclass -- plus the
# systemd-boot entry template) travels as a plain bundle extra file
# and is unpacked by files/lamadist-bundle-hook.sh's post-install
# hook, keyed off whichever bootname RAUC just wrote to.
#
# Per m4-plan.md D1/D2, roothash/kernel/initrd/microcode never
# appear in the entry: they are baked into each slot's UKI cmdline
# at UKI-build time.  files/lamadist-boot-entry.conf.in's only
# placeholder is "@SLOT@", which is fixed at install time (the
# target slot is not known here), so do_lamadist_bootfiles below
# copies the template verbatim -- no substitution happens in this
# recipe.

DESCRIPTION = "LamaDist RAUC A/B update bundle"
LICENSE = "Apache-2.0"
LIC_FILES_CHKSUM = "file://${COMMON_LICENSE_DIR}/Apache-2.0;md5=89aea4e17d99a7cacdbeed46a0096b10"

inherit bundle

RAUC_BUNDLE_COMPATIBLE = "lamadist-${MACHINE}"
RAUC_BUNDLE_FORMAT = "verity"

RAUC_BUNDLE_SLOTS = "rootfs hash"

# [file] is set explicitly rather than relying on bundle.bbclass's
# fallback naming (RAUC_SLOT_x + IMAGE_MACHINE_SUFFIX +
# IMAGE_NAME_SUFFIX + fstype) so this always matches the exact
# dateless artifact names dm-verity-img.bbclass's verity_hash()
# produces -- the same expression the WKS A/B layout rawcopies from
# (meta-lamadist/files/wic/lamadist-dmverity-bootdisk.wks.in, W2).
RAUC_SLOT_rootfs = "${DM_VERITY_IMAGE}"
RAUC_SLOT_rootfs[file] = "${DM_VERITY_IMAGE}-${MACHINE}${IMAGE_NAME_SUFFIX}.${DM_VERITY_IMAGE_TYPE}.verity"
RAUC_SLOT_rootfs[hooks] = "post-install"
# rauc cannot map the .verity/.vhash extensions to an image type;
# both are raw block images written verbatim to the slot device.
RAUC_SLOT_rootfs[imagetype] = "raw"

RAUC_SLOT_hash = "${DM_VERITY_IMAGE}"
RAUC_SLOT_hash[file] = "${DM_VERITY_IMAGE}-${MACHINE}${IMAGE_NAME_SUFFIX}.${DM_VERITY_IMAGE_TYPE}.vhash"
RAUC_SLOT_hash[imagetype] = "raw"

SRC_URI = " \
    file://lamadist-bundle-hook.sh \
    file://lamadist-boot-entry.conf.in \
"

RAUC_BUNDLE_HOOKS[file] = "lamadist-bundle-hook.sh"
RAUC_BUNDLE_HOOKS[hooks] = "install-check"

RAUC_BUNDLE_EXTRA_FILES += "bootfiles.tar"

# Development-only signing pair (never for release; see M6).
# Resolved via BBPATH rather than a hardcoded path so this recipe
# does not need to know where meta-lamadist's layer root ends up on
# disk; W4 owns creating these two files
# (meta-lamadist/files/rauc-dev/, M3 plan decision 4).  Weak
# defaults so a real signing setup can still override them.
RAUC_KEY_FILE  ??= "${@bb.utils.which(d.getVar('BBPATH'), 'files/rauc-dev/dev-ca.key.pem')}"
RAUC_CERT_FILE ??= "${@bb.utils.which(d.getVar('BBPATH'), 'files/rauc-dev/dev-ca.cert.pem')}"

LAMADIST_BOOT_ENTRY_TEMPLATE ?= "${UNPACKDIR}/lamadist-boot-entry.conf.in"

# The two per-slot UKI build artifacts in DEPLOY_DIR_IMAGE, per
# lamadist-uki.bbclass (W2) and m4-plan.md D2's naming.
LAMADIST_UKI_FILENAMES ?= "lamadist-a.efi lamadist-b.efi"

# Builds the ESP payload every RAUC update carries: both slots' UKIs
# and the boot-entry template, copied verbatim (slot substitution
# happens at install time -- see files/lamadist-bundle-hook.sh).
# Runs after do_unpack (SRC_URI content in WORKDIR) and before
# do_configure (which collects RAUC_BUNDLE_EXTRA_FILES into the
# bundle dir).  do_unpack already depends on
# ${DM_VERITY_IMAGE}:do_image_complete (added by bundle.bbclass's
# anonymous python for the rootfs/hash slots above); DM_VERITY_IMAGE
# is the same recipe (lamadist-image-base) that inherits
# lamadist-uki.bbclass, whose lamadist_uki_build runs as a
# do_image_wic prefunc (there is no separate oe-core uki.bbclass
# addtask involved).  do_image_wic is itself a hard prerequisite of
# that recipe's do_image_complete, so both UKI artifacts are
# guaranteed to exist in DEPLOY_DIR_IMAGE by the time this task
# runs.
python do_lamadist_bootfiles () {
    import os
    import shutil
    import tarfile

    deploydir = d.getVar('DEPLOY_DIR_IMAGE')
    workdir = d.getVar('WORKDIR')
    template_path = d.getVar('LAMADIST_BOOT_ENTRY_TEMPLATE')
    uki_filenames = d.getVar('LAMADIST_UKI_FILENAMES').split()

    stage = os.path.join(workdir, 'bootfiles')
    bb.utils.remove(stage, recurse=True)
    bb.utils.mkdirhier(stage)

    for name in uki_filenames:
        src = os.path.join(deploydir, name)
        if not os.path.exists(src):
            bb.fatal("do_lamadist_bootfiles: missing %s in DEPLOY_DIR_IMAGE "
                      "(did lamadist-uki.bbclass run?)" % name)
        shutil.copy(src, os.path.join(stage, name))

    shutil.copy(template_path, os.path.join(stage, 'lamadist-boot-entry.conf'))
    # @SLOT@ intentionally left unresolved; see the module comment.

    tar_path = os.path.join(d.getVar('UNPACKDIR'), 'bootfiles.tar')
    with tarfile.open(tar_path, 'w') as tar:
        for name in sorted(os.listdir(stage)):
            tar.add(os.path.join(stage, name), arcname=name)
}
do_lamadist_bootfiles[dirs] = "${WORKDIR}"
do_lamadist_bootfiles[vardeps] += "LAMADIST_BOOT_ENTRY_TEMPLATE LAMADIST_UKI_FILENAMES"
addtask lamadist_bootfiles after do_unpack before do_configure
