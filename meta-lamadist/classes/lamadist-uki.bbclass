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
# wires real values in via the machine's boot-backend include
# (conf/machine/include/lamadist-boot-sdboot-uki.inc).

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

# Smallest initramfs, in bytes, that a UKI may be built from; the
# build refuses a smaller file.  The value must be an integer.  The
# dm-verity initramfs is tens of MiB, and one packed from an emptied
# rootfs is 1536 bytes.  An overlay may raise or lower the floor, and
# 0 turns the size check off (the newc walk below still runs).
LAMADIST_UKI_INITRAMFS_MIN_BYTES ?= "1048576"

# The task that deploys microcode.cpio, which the UKI build reads when
# the machine sets LAMADIST_UKI_INCLUDE_MICROCODE = "1".  Nothing in
# DEPENDS reaches that recipe, so do_image_wic's recrdeptask on
# do_deploy does not order the UKI build after it; do_image_wic waits
# for this task instead.  A machine whose microcode comes from another
# recipe overrides it.
LAMADIST_UKI_MICROCODE_DEPLOY ?= "intel-microcode:do_deploy"
do_image_wic[depends] += "${@d.getVar('LAMADIST_UKI_MICROCODE_DEPLOY') if d.getVar('LAMADIST_UKI_INCLUDE_MICROCODE') == '1' else ''}"

python lamadist_uki_build () {
    import os
    import re
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

    # Early CPU-microcode load, same ordering as the Type1 entries this
    # replaces (lamadist-esp-slot-a.bbclass, lamadist-boot-entry.conf.in):
    # the microcode initrd must precede the main initramfs.  CPU
    # microcode is x86-specific, so a machine opts in with
    # LAMADIST_UKI_INCLUDE_MICROCODE = "1" (intel does).  An arch with no
    # CPU-microcode initrd, such as aarch64, leaves it unset and off.
    microcode = None
    if d.getVar('LAMADIST_UKI_INCLUDE_MICROCODE') == '1':
        microcode = os.path.join(deploydir, 'microcode.cpio')
        if not os.path.exists(microcode):
            bb.fatal("lamadist_uki_build: LAMADIST_UKI_INCLUDE_MICROCODE=1 "
                     "but %s is missing" % microcode)

    initramfs_image = d.getVar('INITRAMFS_IMAGE')
    initramfs_fstype = d.getVar('INITRAMFS_FSTYPES').split()[0]
    machine = d.getVar('MACHINE')
    initramfs = os.path.join(deploydir, '%s-%s.%s' %
                              (initramfs_image, machine, initramfs_fstype))
    if not os.path.exists(initramfs):
        bb.fatal("lamadist_uki_build: cannot find %s" % initramfs)
    # A re-packed, emptied initramfs rootfs yields a cpio of a few
    # blocks that boots to "No working init found"; never sign one.
    min_value = d.getVar('LAMADIST_UKI_INITRAMFS_MIN_BYTES')
    try:
        min_bytes = int(min_value)
    except (TypeError, ValueError):
        bb.fatal("lamadist_uki_build: LAMADIST_UKI_INITRAMFS_MIN_BYTES must "
                 "be an integer byte count, not %r" % (min_value,))
    size = os.path.getsize(initramfs)
    if size < min_bytes:
        bb.fatal("lamadist_uki_build: initramfs %s is %d bytes, under the "
                 "%d-byte floor (LAMADIST_UKI_INITRAMFS_MIN_BYTES); it was "
                 "likely packed from an empty rootfs.  An earlier invocation "
                 "left that tree empty and do_rootfs did not re-run: re-run "
                 "it with 'bitbake -c rootfs -f %s', or use a new TMPDIR"
                 % (initramfs, size, min_bytes, initramfs_image))

    # The size floor only proves "not nearly empty".  IMAGE_CMD:cpio
    # appends a zero-byte, mode-0644 init to a tree that has none, so
    # "init exists" proves nothing either.  Walk the newc headers (no
    # cpio tool, no extraction) and require a whole archive, ending in
    # TRAILER!!!, whose init is an executable non-empty regular file
    # or a symlink.  As in the kernel's unpacker, a name ends at its
    # first NUL, and the last entry of a name wins.  Every offset is
    # checked against the file size.
    def bad_cpio(why):
        bb.fatal("lamadist_uki_build: initramfs %s is not a whole newc "
                 "cpio archive: %s" % (initramfs, why))

    init_entry = None
    link_sizes = {}
    trailer = False
    with open(initramfs, 'rb') as f:
        pos = 0
        while not trailer:
            if pos + 110 > size:
                bad_cpio("it ends before its TRAILER!!! entry")
            f.seek(pos)
            header = f.read(110)
            if header[:6] != b'070701' or \
                    not re.fullmatch(rb'[0-9A-Fa-f]{104}', header[6:]):
                bad_cpio("bad header at offset %d" % pos)
            fields = [int(header[6 + 8 * i:14 + 8 * i], 16) for i in range(13)]
            ino, mode, nlink, filesize = fields[0], fields[1], fields[4], fields[6]
            devmajor, devminor, namesize = fields[7], fields[8], fields[11]
            if namesize < 1 or pos + 110 + namesize > size:
                bad_cpio("bad name length at offset %d" % pos)
            name = f.read(namesize)
            if not name.endswith(b'\0'):
                bad_cpio("unterminated name at offset %d" % pos)
            name = name.split(b'\0', 1)[0].decode('utf-8', 'replace')
            data = (pos + 110 + namesize + 3) & ~3
            if data + filesize > size:
                bad_cpio("entry %r at offset %d runs past the end of the "
                         "file" % (name, pos))
            pos = (data + filesize + 3) & ~3
            if name == 'TRAILER!!!':
                trailer = True
                continue
            # A hard link's data rides on its last link; earlier links
            # are empty, so remember each inode's largest size.
            inode = (devmajor, devminor, ino)
            link_sizes[inode] = max(link_sizes.get(inode, 0), filesize)
            while name.startswith('./'):
                name = name[2:]
            if name == 'init':
                init_entry = (mode, filesize, nlink, inode)
    if init_entry is None:
        bb.fatal("lamadist_uki_build: initramfs %s has no init entry" %
                 initramfs)
    mode, filesize, nlink, inode = init_entry
    if mode & 0o170000 == 0o120000:
        pass
    elif mode & 0o170000 != 0o100000 or not mode & 0o111:
        bb.fatal("lamadist_uki_build: initramfs %s has an init that is "
                 "not an executable file (mode %o)" % (initramfs, mode))
    elif not filesize and not (nlink > 1 and link_sizes[inode]):
        bb.fatal("lamadist_uki_build: initramfs %s has an empty init" % initramfs)

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
        if microcode:
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
    LAMADIST_UKI_INITRAMFS_MIN_BYTES \
    LAMADIST_UKI_SLOTS \
    UKIFY_CMD \
    UKI_SB_CERT \
    UKI_SB_KEY \
"
