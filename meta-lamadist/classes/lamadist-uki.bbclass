# SPDX-License-Identifier: Apache-2.0
#
# Builds the two per-slot Unified Kernel Images the RAUC A/B update
# carries: lamadist-a.efi and lamadist-b.efi, each the target
# kernel + microcode + dm-verity initramfs + a slot-specific
# .cmdline ("root=/dev/mapper/rootfs roothash=<this build's
# roothash> lamadist.slot=<a|b>"), via ukify (systemd-boot-native).
#
# Both UKIs are deployed to DEPLOY_DIR_IMAGE only.  They are
# deliberately NOT wired into IMAGE_EFI_BOOT_FILES/EFI/Linux: sd-boot
# 259.5 has no assessment-aware default/preferred key, so A/B primary
# selection and boot counting live entirely in the Type1 loader-entry
# sort-keys the RAUC backend maintains (lamadist-10/-20,
# lamadist-<slot>+<tries>.conf).  A UKI dropped into EFI/Linux
# becomes an auto-discovered Type2 entry whose sort-key/cmdline are
# baked into the (potentially signed) PE, which the backend could
# never flip without re-signing, and it would duplicate the boot
# menu.  Staging the UKIs under the ESP at
# lamadist/<slot>/lamadist.efi, referenced by a plain "linux" line
# in the existing Type1 entries, is a separate work item
# (esp-uki-layout); this class only builds and deploys the two
# files.
#
# roothash is read from STAGING_VERITY_DIR's .env file, the same
# source lamadist-esp-slot-a.bbclass and the bundle recipe
# (recipes-core/bundles/lamadist-bundle.bb) already use -- see those
# files for why the value only exists once dm-verity-img's verity
# conversion task has run.  This class resolves the same ordering
# problem the same way: the build runs as a do_image_wic prefunc.
# do_image_wic is a hard prerequisite of do_image_complete for this
# recipe (image.bbclass's addtask wiring), and dm-verity-img's own
# do_image_wic[depends] injection (added when 'wic' is in
# IMAGE_FSTYPES) orders it after the verity conversion, so by the
# time this prefunc runs the .env file is guaranteed to exist, and
# by the time do_image_complete finishes so are both UKIs -- visible
# to any recipe (e.g. the bundle) that depends on
# ${DM_VERITY_IMAGE}:do_image_complete.
#
# Stage A (M4.A) leaves UKI_SB_KEY/UKI_SB_CERT unset: ukify signs
# only when both are set, so the build stays unsigned here.  Stage B
# wires real values in via lamadist-security.inc.

DEPENDS += "\
    os-release \
    sbsigntool-native \
    systemd-boot \
    systemd-boot-native \
    virtual/cross-binutils \
    virtual/kernel \
"

require conf/image-uefi.conf

UKIFY_CMD ?= "ukify build"

# Secure Boot signing keys, stage B (see lamadist-security.inc).
# Unsigned build when unset, per plan D6/M4.A scope.
UKI_SB_KEY ?= ""
UKI_SB_CERT ?= ""

LAMADIST_UKI_SLOTS ?= "a b"

python lamadist_uki_build () {
    import os
    import bb.process

    deploydir = d.getVar('DEPLOY_DIR_IMAGE')
    staging_verity_dir = d.getVar('STAGING_VERITY_DIR')
    verity_image = d.getVar('DM_VERITY_IMAGE')
    verity_type = d.getVar('DM_VERITY_IMAGE_TYPE')

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
        bb.fatal("lamadist_uki_build: ROOT_HASH not found in %s" % env_path)

    target_arch = d.getVar('EFI_ARCH')
    stub = os.path.join(deploydir, 'linux%s.efi.stub' % target_arch)
    if not os.path.exists(stub):
        bb.fatal("lamadist_uki_build: cannot find %s" % stub)

    kernel_filename = d.getVar('KERNEL_IMAGETYPE')
    kernel = os.path.join(deploydir, kernel_filename)
    if not os.path.exists(kernel):
        bb.fatal("lamadist_uki_build: cannot find %s" % kernel)

    # Early microcode load, same ordering as the Type1 entries this
    # replaces (lamadist-esp-slot-a.bbclass, lamadist-boot-entry.conf.in):
    # the microcode initrd must precede the main initramfs.
    microcode = os.path.join(deploydir, 'microcode.cpio')
    if not os.path.exists(microcode):
        bb.fatal("lamadist_uki_build: cannot find %s" % microcode)

    initramfs_image = d.getVar('INITRAMFS_IMAGE')
    initramfs_fstype = d.getVar('INITRAMFS_FSTYPES').split()[0]
    machine = d.getVar('MACHINE')
    initramfs = os.path.join(deploydir, '%s-%s.%s' %
                              (initramfs_image, machine, initramfs_fstype))
    if not os.path.exists(initramfs):
        bb.fatal("lamadist_uki_build: cannot find %s" % initramfs)

    kernel_version = d.getVar('KERNEL_VERSION')
    tools_dir = "%s%s/lib/systemd/tools" % (d.getVar('RECIPE_SYSROOT_NATIVE'),
                                             d.getVar('prefix'))
    os_release = "%s%s/lib/os-release" % (d.getVar('RECIPE_SYSROOT'),
                                           d.getVar('prefix'))

    key = d.getVar('UKI_SB_KEY')
    cert = d.getVar('UKI_SB_CERT')

    # The machine's declared kernel arguments (intel.conf APPEND:
    # "console=ttyS0,115200 ro") ride along.  With no options line
    # in the Type1 entries and no LoadOptions from sd-boot, this
    # embedded .cmdline is the ONLY kernel cmdline there is -- the
    # first M4.A smoke ran blind (silent serial, invisible
    # emergency shell on tty0) because the console never made it
    # here.
    append = (d.getVar('APPEND') or '').strip()

    # systemd.verity=0: roothash= is consumed by OUR initramfs
    # dmverity module, but systemd's veritysetup-generator ALSO
    # reacts to it, synthesizing an "Integrity Protection Setup for
    # root" unit that waits for GPT data/hash partitions whose
    # partuuids are derived from the hash (the discoverable-
    # partitions convention).  Those partitions don't exist here, so
    # every boot stalled 90s on the device timeout and failed
    # veritysetup.target -- a dependency-fail cascade that (among
    # other things) swept the one-shot sshdgenkeys job.  The
    # explicit =0 keeps the generator inert while roothash= stays
    # available to the initramfs.
    for slot in d.getVar('LAMADIST_UKI_SLOTS').split():
        cmdline = ("root=/dev/mapper/rootfs roothash=%s lamadist.slot=%s "
                   "systemd.verity=0") % (roothash, slot)
        if append:
            cmdline += " " + append
        output = os.path.join(deploydir, 'lamadist-%s.efi' % slot)

        ukify_cmd = d.getVar('UKIFY_CMD')
        if target_arch:
            ukify_cmd += " --efi-arch %s" % target_arch
        ukify_cmd += " --stub %s" % stub
        ukify_cmd += " --initrd=%s" % microcode
        ukify_cmd += " --initrd=%s" % initramfs
        ukify_cmd += " --linux=%s" % kernel
        if kernel_version:
            ukify_cmd += " --uname %s" % kernel_version
        ukify_cmd += " --cmdline='%s'" % cmdline
        ukify_cmd += " --tools=%s" % tools_dir
        ukify_cmd += " --os-release=@%s" % os_release
        if key:
            ukify_cmd += " --sign-kernel --secureboot-private-key='%s'" % key
        if cert:
            ukify_cmd += " --secureboot-certificate='%s'" % cert
        ukify_cmd += " --output=%s" % output

        bb.note("lamadist-uki: building %s" % output)
        bb.debug(2, "lamadist-uki: running command: %s" % ukify_cmd)
        out, err = bb.process.run(ukify_cmd, shell=True)
        bb.debug(2, "%s\n%s" % (out, err))
}

do_image_wic[prefuncs] += "lamadist_uki_build"
do_image_wic[vardeps] += "\
    APPEND \
    LAMADIST_UKI_SLOTS \
    UKIFY_CMD \
    UKI_SB_CERT \
    UKI_SB_KEY \
"
