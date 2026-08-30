# SPDX-License-Identifier: Apache-2.0

DESCRIPTION = "LamaDist installer stick image (increment 1).  Produces \
a bootable USB stick .wic: an ESP carrying the signed installer UKI at \
EFI/BOOT/BOOTX64.EFI, and a payload partition carrying the hardened \
full-disk image, its checksum, the manifest, and the manual.  See \
docs/installer/SPEC.md and ADRs 0006-0008."
LICENSE = "Apache-2.0"

inherit core-image
require conf/image-uefi.conf

# This image is only a container for the ESP + payload partitions the
# prefunc stages; the rootfs itself is unused by the WKS.  Keep it
# minimal.
PACKAGE_INSTALL = "base-files"
IMAGE_FEATURES = ""
IMAGE_LINGUAS = ""
IMAGE_NAME_SUFFIX ?= ""

# Not a lamadist-image, so no selinux-image relabel and no refpolicy.
IMAGE_FSTYPES = "wic"
WKS_FILE = "lamadist-installer-stick.wks.in"

# Rebuild whenever the payload changes: the base image's deploy name
# is timestamped, so stamp-skip could otherwise ship a stale payload.
do_image_wic[nostamp] = "1"

# The signed installer UKI reuses the project Secure Boot keys wired
# in by lamadist-security.inc (stage B): a UKI signed with the db key
# boots under the enrolled OVMF variables the QEMU harness uses.
UKI_SB_KEY ?= ""
UKI_SB_CERT ?= ""

INSTALLER_INITRAMFS_IMAGE ?= "lamadist-installer-initramfs"
BASE_PAYLOAD_IMAGE ?= "lamadist-image-base"
# The LAST console= owns /dev/console (installer stdio).  The machine
# default LAMADIST_CONSOLES (intel.conf) is the QEMU order, serial
# last, which the serial install harness drives;
# kas/extras/hw-console.kas.yml flips it so prompts land on the
# screen of a physical machine.
INSTALLER_CMDLINE ?= "${LAMADIST_CONSOLES} lamadist.installer"

# Optional manifest baked onto the payload partition as manifest.env
# (path as seen in the build container).  Empty ships only the
# sample, yielding an interactive stick.  A HEADLESS=yes manifest
# makes the stick auto-install on boot -- see
# kas/extras/headless-auto.kas.yml for the canonical wiring and its
# warning.
INSTALLER_MANIFEST ?= ""

# Everything the staging prefunc consumes, ordered before do_image_wic.
do_image_wic[depends] += "\
    ${INSTALLER_INITRAMFS_IMAGE}:do_image_complete \
    ${BASE_PAYLOAD_IMAGE}:do_image_complete \
    virtual/kernel:do_deploy \
    systemd-boot:do_deploy \
    intel-microcode:do_deploy \
    systemd-boot-native:do_populate_sysroot \
    sbsigntool-native:do_populate_sysroot \
    mtools-native:do_populate_sysroot \
    dosfstools-native:do_populate_sysroot \
    e2fsprogs-native:do_populate_sysroot \
    coreutils-native:do_populate_sysroot \
    os-release:do_populate_sysroot \
"

# os-release must land in the recipe sysroot for ukify --os-release.
DEPENDS += "os-release"

# Manual + sample manifest shipped alongside the payload; single-
# sourced with the module in the installer recipe's files dir.
# Referenced directly (not via SRC_URI unpack, which image recipes do
# not run for these) -- safe because do_image_wic is nostamp.
INSTALLER_FILES_DIR := "${THISDIR}/../installer/files"

lamadist_installer_stick_stage() {
	set -eu

	stage="${WORKDIR}/stick"
	rm -rf "${stage}"
	install -d "${stage}/esp/EFI/BOOT" "${stage}/payload"

	# --- 1. Build the signed installer UKI ---------------------------
	stub="${DEPLOY_DIR_IMAGE}/linux${EFI_ARCH}.efi.stub"
	kernel="${DEPLOY_DIR_IMAGE}/${KERNEL_IMAGETYPE}"
	microcode="${DEPLOY_DIR_IMAGE}/microcode.cpio"
	initrd="${DEPLOY_DIR_IMAGE}/${INSTALLER_INITRAMFS_IMAGE}-${MACHINE}.${INITRAMFS_FSTYPES}"
	tools="${RECIPE_SYSROOT_NATIVE}${prefix}/lib/systemd/tools"
	osrel="${RECIPE_SYSROOT}${prefix}/lib/os-release"
	uki="${stage}/esp/EFI/BOOT/BOOTX64.EFI"

	for f in "${stub}" "${kernel}" "${microcode}" "${initrd}" "${osrel}"; do
		[ -e "${f}" ] || bbfatal "installer-stick: missing UKI input ${f}"
	done

	sign_args=""
	if [ -n "${UKI_SB_KEY}" ] && [ -n "${UKI_SB_CERT}" ]; then
		sign_args="--sign-kernel --secureboot-private-key=${UKI_SB_KEY} --secureboot-certificate=${UKI_SB_CERT}"
		bbnote "installer-stick: signing UKI with project Secure Boot key"
	else
		bbwarn "installer-stick: UKI_SB_KEY/CERT unset; building UNSIGNED installer UKI (will not boot under Secure Boot)"
	fi

	ukify build \
		--efi-arch "${EFI_ARCH}" \
		--stub "${stub}" \
		--initrd="${microcode}" \
		--initrd="${initrd}" \
		--linux="${kernel}" \
		--cmdline="${INSTALLER_CMDLINE}" \
		--tools="${tools}" \
		--os-release=@"${osrel}" \
		${sign_args} \
		--output="${uki}"

	# --- 2. Stage the payload ---------------------------------------
	src="${DEPLOY_DIR_IMAGE}/${BASE_PAYLOAD_IMAGE}-${MACHINE}.rootfs.wic.xz"
	[ -e "${src}" ] || bbfatal "installer-stick: base payload ${src} not found (build ${BASE_PAYLOAD_IMAGE} first)"
	# Dereference the deploy symlink to the real timestamped artifact.
	realsrc="$(readlink -f "${src}")"
	cp "${realsrc}" "${stage}/payload/lamadist-payload.wic.xz"
	( cd "${stage}/payload" && sha256sum lamadist-payload.wic.xz > lamadist-payload.wic.xz.sha256 )
	cp "${INSTALLER_FILES_DIR}/manifest.env.sample" "${stage}/payload/manifest.env.sample"
	cp "${INSTALLER_FILES_DIR}/MANUAL.md" "${stage}/payload/MANUAL.md"
	if [ -n "${INSTALLER_MANIFEST}" ]; then
		[ -f "${INSTALLER_MANIFEST}" ] || bbfatal "installer-stick: INSTALLER_MANIFEST ${INSTALLER_MANIFEST} not found"
		cp "${INSTALLER_MANIFEST}" "${stage}/payload/manifest.env"
		bbnote "installer-stick: baked manifest.env from ${INSTALLER_MANIFEST} (headless-capable stick)"
	fi

	# --- 3. Build the ESP (vfat) and payload (ext4) fs images -------
	# Rootless: mkfs.vfat + mcopy (mtools), mkfs.ext4 -d.  Sized with
	# headroom for the ~80-120 MB UKI and the ~770 MB payload.
	esp_img="${stage}/esp.vfat"
	rm -f "${esp_img}"
	mkfs.vfat -C -n ESP "${esp_img}" 262144
	mcopy -s -i "${esp_img}" "${stage}/esp/EFI" ::

	pay_img="${stage}/payload.ext4"
	rm -f "${pay_img}"
	mkfs.ext4 -F -q -L lamadist-payload -d "${stage}/payload" "${pay_img}" 1200M

	bbnote "installer-stick: staged esp.vfat and payload.ext4"
}
do_image_wic[prefuncs] += "lamadist_installer_stick_stage"
