# SPDX-License-Identifier: Apache-2.0
#
# Generate U-Boot's EFI variable preseed (ADR 0013 decision 3, ADR
# 0016) from the PK/KEK/db signature lists the x86_64 gate enrolls
# (files/sb-dev/ -- DEVELOPMENT ONLY, see its README.md; M6 owns the
# production hierarchy).  Inherit it in the u-boot recipe of a machine
# whose boot chain is U-Boot's EFI loader:
#
#     inherit lamadist-efi-var-seed
#
# The task writes ${S}/${LAMADIST_EFI_VAR_SEED_FILE} between do_patch
# and do_configure, so the u-boot configuration fragment names the
# file with a source-tree-relative path, which is the only form
# lib/efi_loader/Makefile accepts (it prefixes $(srctree)/):
#
#     CONFIG_EFI_VARIABLES_PRESEED=y
#     CONFIG_EFI_VAR_SEED_FILE="lamadist-efivars.seed"
#
# do_deploy copies the seed next to the bootloader image so a build
# check can dump it.  Only the public .esl files are read; the seed is
# never tracked.  Nothing here touches the x86_64 enrollment path
# (.mise/tasks/ovmf-vars).

LAMADIST_EFI_VAR_SEED_FILE ?= "lamadist-efivars.seed"
LAMADIST_EFI_VAR_SEED_PK  ?= "${@bb.utils.which(d.getVar('BBPATH'), 'files/sb-dev/pk.esl')}"
LAMADIST_EFI_VAR_SEED_KEK ?= "${@bb.utils.which(d.getVar('BBPATH'), 'files/sb-dev/kek.esl')}"
LAMADIST_EFI_VAR_SEED_DB  ?= "${@bb.utils.which(d.getVar('BBPATH'), 'files/sb-dev/db.esl')}"
LAMADIST_EFI_VAR_SEED_GEN ?= "${@bb.utils.which(d.getVar('BBPATH'), 'lib/lamadist/efivarseed.py')}"

python do_lamadist_efi_var_seed () {
    from pathlib import Path

    from lamadist import efivarseed

    try:
        seed = efivarseed.build_seed(
            Path(d.getVar('LAMADIST_EFI_VAR_SEED_PK')),
            Path(d.getVar('LAMADIST_EFI_VAR_SEED_KEK')),
            Path(d.getVar('LAMADIST_EFI_VAR_SEED_DB')),
        )
    except efivarseed.SeedError as err:
        bb.fatal('lamadist-efi-var-seed: %s' % err)
    out = Path(d.getVar('S')) / d.getVar('LAMADIST_EFI_VAR_SEED_FILE')
    out.write_bytes(seed)
    bb.note('wrote %s (%d bytes)' % (out, len(seed)))
}
do_lamadist_efi_var_seed[file-checksums] = "\
    ${LAMADIST_EFI_VAR_SEED_PK}:True \
    ${LAMADIST_EFI_VAR_SEED_KEK}:True \
    ${LAMADIST_EFI_VAR_SEED_DB}:True \
    ${LAMADIST_EFI_VAR_SEED_GEN}:True"
do_lamadist_efi_var_seed[vardeps] += "LAMADIST_EFI_VAR_SEED_FILE"
addtask lamadist_efi_var_seed after do_patch before do_configure

do_deploy:append () {
    install -m 0644 ${S}/${LAMADIST_EFI_VAR_SEED_FILE} ${DEPLOYDIR}/${LAMADIST_EFI_VAR_SEED_FILE}
}
do_deploy[depends] += "${PN}:do_lamadist_efi_var_seed"
