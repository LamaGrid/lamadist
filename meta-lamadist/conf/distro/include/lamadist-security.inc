# vi:ft=bitbake
# SPDX-License-Identifier: Apache-2.0
#
# LamaDist security stack configuration.
#
# Enables SELinux, IMA, LUKS, dm-verity, SPDX license
# manifests, and CVE scanning.  Security features are distro
# policy—they apply to all machines and images.

# meta-selinux
FIRST_BOOT_RELABEL                    = '0'
IMAGE_INSTALL:append                  = ' packagegroup-core-selinux'
PREFERRED_PROVIDER_virtual/refpolicy  = 'refpolicy-targeted'
PREFERRED_VERSION_refpolicy           = '2.20240226'
PREFERRED_VERSION_refpolicy-minimum   = '2.20240226'

# meta-secure-core/meta-integrity
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

# Which image to apply dm-verity to, and the root filesystem type
DM_VERITY_IMAGE ?= 'core-image-minimal'
DM_VERITY_IMAGE_TYPE ?= 'ext4'

INITRAMFS_IMAGE = 'dm-verity-image-initramfs'
INITRAMFS_FSTYPES = 'cpio'
INITRAMFS_IMAGE_BUNDLE = '0'

# Enable creation of SPDX manifests by default
INHERIT += 'create-spdx'
SPDX_ARCHIVE_PACKAGED = '0'
SPDX_ARCHIVE_SOURCES  = '1'
SPDX_INCLUDE_SOURCES  = '1'

# We need debug symbols so that SPDX manifests for the kernel work
KERNEL_EXTRA_FEATURES:append = ' features/debug/debug-kernel.scc'

# Enable CVE checks and reporting (manifest generation is opt-in
# via --release or --include-scans to avoid the ~7 min/build
# recrdeptask overhead)
INHERIT += 'cve-check'
CVE_CHECK_CREATE_MANIFEST = '0'

# Include the Yocto CVE exclusion list for unfixable CVEs
include conf/distro/include/cve-extra-exclusions.inc
