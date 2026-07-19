# SPDX-License-Identifier: Apache-2.0
#
# Populates the ESP's initial slot-A boot content at image build
# time: the slot-A UKI (kernel + initramfs + microcode + cmdline,
# all built and signed as one PE by W2's lamadist-uki.bbclass) plus
# a systemd-boot Type1 entry pointing at it.  First boot must
# discover its root the same way -- PARTLABEL + the roothash baked
# into the UKI's embedded .cmdline (see initramfs-framework-dm/
# dmverity and m4-plan.md D1/D2) -- that a RAUC update uses for slot
# B later, or slot A would be reachable only by a mechanism an
# update could never reproduce.
#
# Per m4-plan.md D1, the entry carries NO "initrd" and NO "options"
# line: sd-boot's Type1 "linux" here names a UKI, not a bare kernel,
# and passes no LoadOptions, so systemd-stub falls back to the
# .cmdline section ukify embedded in the PE (root=, roothash=,
# lamadist.slot= -- see lamadist-uki.bbclass).  This is also why
# this function no longer reads the dm-verity ROOT_HASH itself: the
# hash travels inside the UKI now, not in this entry.
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
# It needs DEPLOY_DIR_IMAGE's slot-A UKI artifact, which
# lamadist_uki_build (lamadist-uki.bbclass) produces as its OWN
# do_image_wic prefunc -- there is no separate "uki" task and no
# oe-core uki.bbclass addtask involved.  Ordering between the two
# prefuncs is decided purely by inherit order in
# lamadist-image-base.bb (bitbake runs prefuncs in the order they
# were appended); that recipe inherits lamadist-uki before
# lamadist-esp-slot-a specifically so lamadist_uki_build runs first.
# Cross-recipe artifact availability (systemd-boot/kernel/microcode)
# is separately guaranteed by image_types_wic.bbclass's
# "do_image_wic[recrdeptask] += 'do_deploy'" plus lamadist-uki.bbclass's
# own DEPENDS.
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

# The slot-A build artifact's name in DEPLOY_DIR_IMAGE, per
# lamadist-uki.bbclass (W2) and m4-plan.md D2's naming
# ("lamadist-a.efi"/"lamadist-b.efi").  Staged onto the ESP under
# its slot-generic name, lamadist.efi (see m4-plan.md D1), so the
# Type1 entry's "linux" path does not need to know the build's slot
# suffix.
LAMADIST_UKI_FILENAME_A ?= "lamadist-a.efi"

python lamadist_esp_slot_a_populate () {
    import os
    import shutil

    overlay = d.getVar('LAMADIST_ESP_SLOT_A_DIR')
    deploydir = d.getVar('DEPLOY_DIR_IMAGE')
    uki_filename = d.getVar('LAMADIST_UKI_FILENAME_A')
    timeout = d.getVar('LAMADIST_BOOT_ENTRY_TIMEOUT')

    entries_dir = os.path.join(overlay, 'loader', 'entries')
    slot_dir = os.path.join(overlay, 'lamadist', 'a')
    bb.utils.remove(overlay, recurse=True)
    bb.utils.mkdirhier(entries_dir)
    bb.utils.mkdirhier(slot_dir)

    uki_src = os.path.join(deploydir, uki_filename)
    if not os.path.exists(uki_src):
        bb.fatal("lamadist_esp_slot_a_populate: missing %s in "
                  "DEPLOY_DIR_IMAGE (did lamadist-uki.bbclass run?)"
                  % uki_filename)
    shutil.copy(uki_src, os.path.join(slot_dir, 'lamadist.efi'))

    entry = (
        "title   LamaDist (slot a)\n"
        "linux   /lamadist/a/lamadist.efi\n"
    )

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
    # discovery moved to PARTLABEL + the UKI's embedded roothash), so
    # creator.rootdev is None and that stock entry would render
    # "root=None" -- a dead menu entry.  --include-path's cp -r only
    # overwrites same-named files, so shipping our own boot.conf here
    # wins over wic's and removes the broken entry.  Deliberately NO
    # sort-key: keyless entries sort after keyed ones, so this
    # uncounted copy is the last resort (it can only be picked when
    # both slots' counted entries are exhausted).
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
do_image_wic[vardeps] += "LAMADIST_ESP_SLOT_A_DIR LAMADIST_BOOT_ENTRY_TIMEOUT LAMADIST_UKI_FILENAME_A"
