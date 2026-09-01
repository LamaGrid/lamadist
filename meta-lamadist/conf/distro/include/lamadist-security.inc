# vi:ft=bitbake
# SPDX-License-Identifier: Apache-2.0
#
# LamaDist security stack configuration.
#
# Enables SELinux, IMA, LUKS, dm-verity, SPDX license
# manifests, and CVE scanning.  Security features are distro
# policy—they apply to all machines and images.

# meta-selinux
#
# Enforcing (M4 stage B, W12).  Stage A booted permissive to harvest
# the refpolicy gap against the real image; that AVC corpus is triaged
# into the local policy module (lamadist.te), which the
# refpolicy-targeted bbappend under recipes-security/refpolicy links
# into refpolicy's monolithic policy at build time, so the image now
# boots enforcing.  The forced-unhealthy rollback OTA test is the
# acceptance gate (D8): a denial that blocks mark-good surfaces there,
# not in the happy path.
#
# FIRST_BOOT_RELABEL stays '0': the dm-verity root is read-only, so a
# first-boot autorelabel cannot run; selinux-image.bbclass labels the
# rootfs at build time with setfiles instead.
DEFAULT_ENFORCING                     = 'enforcing'
FIRST_BOOT_RELABEL                    = '0'
IMAGE_INSTALL:append                  = ' packagegroup-core-selinux'
PREFERRED_PROVIDER_virtual/refpolicy  = 'refpolicy-targeted'
PREFERRED_VERSION_refpolicy           = '2.20240226'
PREFERRED_VERSION_refpolicy-minimum   = '2.20240226'

# meta-secure-core/meta-integrity
#
# IMA in LOG MODE (M4 plan D7): measurement + audit only, NOT
# appraisal enforcement.  The rootfs-signing half is already fully
# wired here -- DISTRO_FEATURES carries 'ima' (lamadist-base.inc),
# ima-evm-rootfs signs every rootfs file with the sample IMA key at
# build time, and packagegroup-ima installs the runtime.  EVM is off
# by construction: ima-evm-rootfs does IMA signing only ("EVM not
# supported at the moment" in the class), so no EVM HMAC key is ever
# applied.  The only remaining switch is the kernel cmdline
# 'ima_policy=tcb ima_appraise=log', which is NOT distro policy: on
# this image the cmdline is baked into the per-slot UKI from the
# machine's APPEND (conf/machine/intel.conf, consumed by
# lamadist-uki.bbclass).  See docs/PLAN.md D7 -- flagged for review at
# milestone close.
SECURE_CORE_IMAGE_EXTRA_INSTALL:append = ' packagegroup-ima'
INHERIT += "sign_rpm_ext ima-evm-rootfs"

# meta-secure-core/meta-encrypted-storage
SECURE_CORE_IMAGE_EXTRA_INSTALL += 'packagegroup-luks'

# meta-security/dm-verity
#
# dm-verity as a feature is distro policy.  The target image and
# filesystem type are distro-wide defaults; machines override the
# hardware-specific parameters (GUIDs, block sizes, WKS_FILE,
# IMAGE_FSTYPES) in machine.conf or machine includes.
IMAGE_CLASSES += 'dm-verity-img'
KERNEL_FEATURES:append = ' features/device-mapper/dm-verity.scc'

# Which image to apply dm-verity to, and the root filesystem type.
# erofs-lz4hc: read-only by design, ~2.4x smaller than the ext4 it
# replaced; lz4hc is the strongest compression oe-core's erofs
# image types offer (no zstd variant in wrynose).
DM_VERITY_IMAGE ?= 'lamadist-image-base'
DM_VERITY_IMAGE_TYPE ?= 'erofs-lz4hc'

INITRAMFS_IMAGE = 'dm-verity-image-initramfs'
INITRAMFS_FSTYPES = 'cpio'
INITRAMFS_IMAGE_BUNDLE = '0'

# Enable creation of SPDX manifests by default
INHERIT += 'create-spdx'
SPDX_INCLUDE_SOURCES ?= '0'

# We need debug symbols so that SPDX manifests for the kernel work
KERNEL_EXTRA_FEATURES:append = ' features/debug/debug-kernel.scc'

# CVE scanning runs against the image SBOM produced by create-spdx
# above, so it is opt-in only: enabling it here would run
# do_sbom_cve_check on every build.  --release and --include-scans
# add the sbom-cve-check overlay (kas/extras/cve.kas.yml) instead.

# Secure Boot signing keys (stage B, W9).
#
# DEVELOPMENT ONLY -- meta-lamadist/files/sb-dev/README.md.  db is
# the signature-database key/cert: lamadist-uki.bbclass's ukify call
# signs both per-slot UKIs with it whenever both variables are
# non-empty (stage A leaves them unset, so that build stays
# unsigned), and the systemd-boot bbappend
# (recipes-bsp/systemd-boot/systemd-boot_%.bbappend) sbsigns
# systemd-bootx64.efi with the identical pair, so every PE the
# firmware executes verifies against the one enrolled db entry.  M6
# replaces this pair with real, non-repository key material -- do
# NOT point these at production keys here.
UKI_SB_KEY  ?= "${@bb.utils.which(d.getVar('BBPATH'), 'files/sb-dev/db.key.pem')}"
UKI_SB_CERT ?= "${@bb.utils.which(d.getVar('BBPATH'), 'files/sb-dev/db.cert.pem')}"

# Include the Yocto CVE exclusion list for unfixable CVEs
include conf/distro/include/cve-extra-exclusions.inc
