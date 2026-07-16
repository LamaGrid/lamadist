# SPDX-License-Identifier: Apache-2.0
#
# Populates the ESP's initial slot-A boot content at image build
# time: kernel, initramfs, microcode, plus a systemd-boot entry
# carrying this build's dm-verity roothash and lamadist.slot=a.
# First boot must discover its root the same way -- PARTLABEL +
# roothash + boot-counting entry (see initramfs-framework-dm/
# dmverity and the M3 plan's decisions 2/3) -- that a RAUC update
# uses for slot B later, or slot A would be reachable only by a
# mechanism an update could never reproduce.
#
# The rendered entry mirrors meta-lamadist/recipes-core/bundles/
# files/lamadist-boot-entry.conf.in (used for slot B by the RAUC
# bundle hook); keep the two in sync if the format changes.  They
# are not literally shared: the bundle recipe's copy is fetched via
# SRC_URI into its own WORKDIR, and threading that same file into
# an inherited class used by an unrelated image recipe would need a
# BBPATH-relative lookup for no real benefit at this size.
#
# Runs as a do_image_wic prefunc rather than a separate addtask.
# It needs STAGING_VERITY_DIR's .env (written by the dm-verity
# conversion task) and DEPLOY_DIR_IMAGE's kernel/initramfs/
# microcode artifacts; do_image_wic already depends on all of the
# above via do_image_complete and the existing kernel/initramfs
# deploy chain (bootimg-efi already consumes the same three files
# today), so running inside that task's own dependency envelope is
# simpler and safer than re-deriving an addtask ordering by hand.
#
# The populated directory is wired into the ESP partition via
# --include-path on the bootimg-efi line in
# meta-lamadist/files/wic/lamadist-dmverity-bootdisk.wks.in (the
# one line W5 may touch there); wic's bootimg-efi source plugin
# does a plain recursive copy of an --include-path directory into
# the partition root, so the trailing "/." in that wks line matters
# -- it copies this directory's *contents* (loader/, lamadist/)
# rather than nesting another directory level.

LAMADIST_ESP_SLOT_A_DIR ?= "${WORKDIR}/lamadist-esp-slot-a"

LAMADIST_BOOT_ENTRY_TIMEOUT ?= "5"

python lamadist_esp_slot_a_populate () {
    import os
    import shutil

    overlay = d.getVar('LAMADIST_ESP_SLOT_A_DIR')
    deploydir = d.getVar('DEPLOY_DIR_IMAGE')
    staging_verity_dir = d.getVar('STAGING_VERITY_DIR')
    verity_image = d.getVar('DM_VERITY_IMAGE')
    verity_type = d.getVar('DM_VERITY_IMAGE_TYPE')
    kernel = d.getVar('KERNEL_IMAGETYPE')
    initramfs_image = d.getVar('INITRAMFS_IMAGE')
    initramfs_fstypes = d.getVar('INITRAMFS_FSTYPES')
    machine = d.getVar('MACHINE')
    timeout = d.getVar('LAMADIST_BOOT_ENTRY_TIMEOUT')

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
        bb.fatal("lamadist_esp_slot_a_populate: ROOT_HASH not found in %s"
                  % env_path)

    entries_dir = os.path.join(overlay, 'loader', 'entries')
    slot_dir = os.path.join(overlay, 'lamadist', 'a')
    bb.utils.remove(overlay, recurse=True)
    bb.utils.mkdirhier(entries_dir)
    bb.utils.mkdirhier(slot_dir)

    initramfs_file = '%s-%s.%s' % (initramfs_image, machine, initramfs_fstypes)
    for name in (kernel, 'microcode.cpio', initramfs_file):
        src = os.path.join(deploydir, name)
        if not os.path.exists(src):
            bb.fatal("lamadist_esp_slot_a_populate: missing %s in "
                      "DEPLOY_DIR_IMAGE" % name)
        shutil.copy(src, os.path.join(slot_dir, name))

    entry = (
        "title   LamaDist (slot a)\n"
        "linux   /lamadist/a/%s\n"
        "initrd  /lamadist/a/microcode.cpio\n"
        "initrd  /lamadist/a/%s\n"
        "options root=/dev/mapper/rootfs roothash=%s lamadist.slot=a\n"
    ) % (kernel, initramfs_file, roothash)

    # sort-key lamadist-10 marks slot a as the primary: sd-boot
    # 259.5 has no assessment-aware default/preferred key, so the
    # RAUC backend encodes primary selection in the entries'
    # sort-keys (10 = primary, 20 = secondary; exhausted entries
    # sort last, which is the rollback).  See
    # recipes-core/rauc/files/systemd-boot-backend.
    with open(os.path.join(entries_dir, 'lamadist-a+3.conf'), 'w') as f:
        f.write("sort-key lamadist-10\n" + entry)

    # wic's bootimg-efi source plugin always writes its own stock
    # loader/entries/boot.conf with "root=%s" % creator.rootdev; none
    # of this WKS's partitions declare mountpoint "/" any more (root
    # discovery moved to PARTLABEL + roothash), so creator.rootdev is
    # None and that stock entry would render "root=None" -- a dead
    # menu entry that fails initramfs-framework-dm's dmverity module
    # if ever selected.  --include-path's cp -r only overwrites
    # same-named files, so shipping our own boot.conf here wins over
    # wic's and removes the broken entry.  Deliberately NO sort-key:
    # keyless entries sort after keyed ones, so this uncounted copy
    # is the last resort (it can only be picked when both slots'
    # counted entries are exhausted).
    with open(os.path.join(entries_dir, 'boot.conf'), 'w') as f:
        f.write(entry)

    # Overrides wic's own loader/loader.conf (do_configure_
    # systemdboot in bootimg-efi.py writes "default boot", pointing
    # at an entry with no root= now that root moved off the wks
    # bootloader --append -- see the wks file's own comment).  cp -r
    # in bootimg-efi.py overwrites same-named files, so this simply
    # wins.
    #
    # No "default" line, ever: sd-boot 259.5 matches it without any
    # boot-assessment check, so it boots a zero-tries entry forever
    # and defeats the A/B rollback.  Selection is left entirely to
    # the sorted entry list via the entries' sort-keys (see above).
    with open(os.path.join(overlay, 'loader', 'loader.conf'), 'w') as f:
        f.write('timeout %s\n' % timeout)
}

do_image_wic[prefuncs] += "lamadist_esp_slot_a_populate"
do_image_wic[vardeps] += "LAMADIST_ESP_SLOT_A_DIR LAMADIST_BOOT_ENTRY_TIMEOUT"
