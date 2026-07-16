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
# slot, so its content (kernel, initramfs, microcode, and the
# systemd-boot entry) travels as a plain bundle extra file and is
# unpacked by files/lamadist-bundle-hook.sh's post-install
# hook, keyed off whichever bootname RAUC just wrote to.
#
# The hook's entry file is templated from files/
# lamadist-boot-entry.conf.in at bundle-build time (do_lamadist_
# bootfiles, below): roothash/kernel/initrd are fixed for this
# build and filled in here, but the target slot (a/b) is only known
# at install time, so "@SLOT@" is left for the hook to substitute.

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

# dm-verity-img.bbclass scopes this default to recipes that inherit
# it; this recipe only reads the staged .env, so mirror the class
# default (keep in sync with ext/meta-security's dm-verity-img).
STAGING_VERITY_DIR ?= "${TMPDIR}/work-shared/${MACHINE}/dm-verity"

# Builds the ESP payload every RAUC update carries: kernel,
# initramfs, microcode, and a boot-entry file with this build's
# roothash already filled in (slot left as the literal "@SLOT@"
# placeholder for the install-time hook -- see files/
# lamadist-bundle-hook.sh).  Runs after do_unpack (SRC_URI content
# in WORKDIR) and before do_configure (which collects
# RAUC_BUNDLE_EXTRA_FILES into the bundle dir).  do_unpack already
# depends on ${DM_VERITY_IMAGE}:do_image_complete (added by
# bundle.bbclass's anonymous python for the rootfs/hash slots
# above), which is what guarantees STAGING_VERITY_DIR's .env file
# and DEPLOY_DIR_IMAGE's kernel/initramfs/microcode artifacts both
# exist by the time this task runs.
python do_lamadist_bootfiles () {
    import os
    import shutil
    import tarfile

    deploydir = d.getVar('DEPLOY_DIR_IMAGE')
    staging_verity_dir = d.getVar('STAGING_VERITY_DIR')
    verity_image = d.getVar('DM_VERITY_IMAGE')
    verity_type = d.getVar('DM_VERITY_IMAGE_TYPE')
    kernel = d.getVar('KERNEL_IMAGETYPE')
    initramfs_image = d.getVar('INITRAMFS_IMAGE')
    initramfs_fstypes = d.getVar('INITRAMFS_FSTYPES')
    machine = d.getVar('MACHINE')
    workdir = d.getVar('WORKDIR')
    template_path = d.getVar('LAMADIST_BOOT_ENTRY_TEMPLATE')

    env_path = os.path.join(staging_verity_dir,
                             '%s.%s.verity.env' % (verity_image, verity_type))
    roothash = None
    with open(env_path) as f:
        for line in f:
            key, sep, val = line.strip().partition('=')
            if sep and key == 'ROOT_HASH':
                roothash = val
                break
    if not roothash:
        bb.fatal("do_lamadist_bootfiles: ROOT_HASH not found in %s" % env_path)

    stage = os.path.join(workdir, 'bootfiles')
    bb.utils.remove(stage, recurse=True)
    bb.utils.mkdirhier(stage)

    initramfs_file = '%s-%s.%s' % (initramfs_image, machine, initramfs_fstypes)
    for name in (kernel, 'microcode.cpio', initramfs_file):
        src = os.path.join(deploydir, name)
        if not os.path.exists(src):
            bb.fatal("do_lamadist_bootfiles: missing %s in DEPLOY_DIR_IMAGE" % name)
        shutil.copy(src, os.path.join(stage, name))

    with open(template_path) as f:
        template = f.read()

    entry = (template
             .replace('@ROOTHASH@', roothash)
             .replace('@KERNEL@', kernel)
             .replace('@MICROCODE@', 'microcode.cpio')
             .replace('@INITRD@', initramfs_file))
    # @SLOT@ intentionally left unresolved; see the module comment.

    with open(os.path.join(stage, 'lamadist-boot-entry.conf'), 'w') as f:
        f.write(entry)

    tar_path = os.path.join(d.getVar('UNPACKDIR'), 'bootfiles.tar')
    with tarfile.open(tar_path, 'w') as tar:
        for name in sorted(os.listdir(stage)):
            tar.add(os.path.join(stage, name), arcname=name)
}
do_lamadist_bootfiles[dirs] = "${WORKDIR}"
do_lamadist_bootfiles[vardeps] += "LAMADIST_BOOT_ENTRY_TEMPLATE"
addtask lamadist_bootfiles after do_unpack before do_configure
