# SPDX-License-Identifier: Apache-2.0
SUMMARY = "N7 write probe: a test-only UEFI application"
DESCRIPTION = "Runs before ExitBootServices in place of the removable-media \
loader, tries every N7 payload row through SetVariable, reads PK, KEK, db, \
and dbx back by CRC-32, and chain-loads systemd-boot.  Test article for the \
N7 write test (.mise/tasks/test-efivars); never install it in an image."
LICENSE = "Apache-2.0"
LIC_FILES_CHKSUM = "file://${COMMON_LICENSE_DIR}/Apache-2.0;md5=89aea4e17d99a7cacdbeed46a0096b10"

# Built on demand only: the recipe is skipped unless
# kas/extras/n7-probe.kas.yml sets the gate, so no image, packagegroup,
# or world build can pull it in, and an accidental dependency fails the
# parse instead of building.  It has no packages and deploys no binary;
# do_n7_export copies the two signed binaries out of the work directory
# to LAMADIST_N7_PROBE_OUTDIR, which is outside every deploy directory.
LAMADIST_N7_PROBE ??= "0"
python () {
    if d.getVar('LAMADIST_N7_PROBE') != '1':
        raise bb.parse.SkipRecipe("test-only: build it with kas/extras/n7-probe.kas.yml")
}
EXCLUDE_FROM_WORLD = "1"
COMPATIBLE_HOST = "aarch64.*-linux"

SRC_URI = "file://n7-probe.c \
           file://n7-probe.lds \
           file://n7_elf2pe.py \
"
S = "${UNPACKDIR}"
B = "${WORKDIR}/build"

inherit nopackages

# The probe never ships, so it has no SPDX document to make.  nospdx
# (oe-core meta/classes-recipe/nospdx.bbclass) deletes only the SPDX
# tasks, which otherwise fail in a probe-only build.
inherit nospdx

DEPENDS = "sbsigntool-native"

# The public development keys only (meta-lamadist/files/sb-dev/README.md),
# read from this layer's own directory as lamadist-efi-var-seed does, so
# no other layer can shadow them.  The probe is signed by db, so the
# firmware runs it; n7-target.efi is the same binary signed by KEK alone,
# so db trusts it only after the S-db append.
N7_SIGN_DIR = "${LAMADIST_LAYERDIR}/files/sb-dev"
LAMADIST_N7_PROBE_OUTDIR ?= "${TOPDIR}/n7-probe"

# Freestanding, with no C library and no libgcc (ADR 0017).  Every
# address must resolve PC-relative, because the image has no base
# relocation table: no jump tables or switch-to-table conversion (both
# put addresses in static data), and no loop turned into a memset call.
# The link keeps its relocations so n7_elf2pe.py can refuse any that
# would need a load-time fix.
N7_CFLAGS = "-std=c11 -O2 -Wall -Wextra -Werror -ffreestanding -fno-builtin \
    -fno-stack-protector -fno-stack-clash-protection -fpie -fvisibility=hidden \
    -mgeneral-regs-only -fno-asynchronous-unwind-tables -fno-unwind-tables \
    -fno-jump-tables -fno-tree-switch-conversion \
    -fno-tree-loop-distribute-patterns -fno-common"
N7_LDFLAGS = "-nostdlib -static -no-pie -Wl,--no-dynamic-linker \
    -Wl,-T,${S}/n7-probe.lds -Wl,--emit-relocs -Wl,--build-id=none"

do_configure[noexec] = "1"

do_compile () {
	${CC} ${N7_CFLAGS} -c ${S}/n7-probe.c -o ${B}/n7-probe.o
	${CC} ${N7_LDFLAGS} -o ${B}/n7-probe.elf ${B}/n7-probe.o
	python3 ${S}/n7_elf2pe.py ${B}/n7-probe.elf ${B}/n7-probe.unsigned.efi
	sbsign --key ${N7_SIGN_DIR}/db.key.pem --cert ${N7_SIGN_DIR}/db.cert.pem --output ${B}/n7-probe.efi ${B}/n7-probe.unsigned.efi
	sbsign --key ${N7_SIGN_DIR}/kek.key.pem --cert ${N7_SIGN_DIR}/kek.cert.pem --output ${B}/n7-target.efi ${B}/n7-probe.unsigned.efi
}
# A key or certificate change must re-sign, as for lamadist-efi-var-seed:
# file-checksums carries the content of the four signing inputs, and the
# absolute path must not make the task signature checkout-dependent.
do_compile[file-checksums] += "\
    ${N7_SIGN_DIR}/db.key.pem:True \
    ${N7_SIGN_DIR}/db.cert.pem:True \
    ${N7_SIGN_DIR}/kek.key.pem:True \
    ${N7_SIGN_DIR}/kek.cert.pem:True"
do_compile[vardepsexclude] += "N7_SIGN_DIR"

do_install[noexec] = "1"

do_n7_export () {
	install -d ${LAMADIST_N7_PROBE_OUTDIR}
	install -m 0644 ${B}/n7-probe.efi ${B}/n7-target.efi ${LAMADIST_N7_PROBE_OUTDIR}/
	sha256sum ${B}/n7-probe.efi ${B}/n7-target.efi
}
addtask n7_export after do_compile before do_build
do_n7_export[nostamp] = "1"
