# vi:ft=bitbake
# SPDX-License-Identifier: Apache-2.0
#
# LamaDist base distro configuration.
#
# Core distribution policy: features, init system, package
# manager, kernel preferences, SDK settings, and optimization
# flags.  These settings define what LamaDist is as a product
# and apply to all machines and images.

MAINTAINER = 'Lucas Yamanishi <lamadist@lamawithonel.mozmail.com>'

SDK_VENDOR = '-lamadistsdk'
SDK_VERSION = "${@d.getVar('DISTRO_VERSION').split('+')[0]}"
SDK_VERSION[vardepvalue] = "${DISTRO_VERSION_BASE}"

TARGET_VENDOR = '-lamadist'

LOCALCONF_VERSION = '2'

SANITY_TESTED_DISTROS ?= " \
            ubuntu-18.04 \n \
            ubuntu-20.04 \n \
            ubuntu-22.04 \n \
            "

DISTRO_FEATURES ?= 'acl xattr ext2 ipv4 ipv6 pam pci seccomp security systemd usrmerge selinux luks ima'
DISTRO_FEATURES_NATIVE = 'acl xattr ipv4 ipv6 systemd selinux luks ima'

DISTRO_EXTRA_RDEPENDS += 'packagegroup-core-boot'
DISTRO_EXTRA_RRECOMMENDS += ''

PREFERRED_VERSION_linux-yocto ?= '6.6%'
PREFERRED_VERSION_linux-yocto-rt ?= '6.6%'

SDK_NAME = "${DISTRO}-${TCLIBC}-${SDKMACHINE}-${IMAGE_BASENAME}-${TUNE_PKGARCH}-${MACHINE}"
SDKPATHINSTALL = "/opt/${DISTRO}/${SDK_VERSION}"

PACKAGE_CLASSES = 'package_rpm'

# systemd
INIT_MANAGER = 'systemd'
EFI_PROVIDER = 'systemd-boot'
DISTRO_FEATURES_BACKFILL_CONSIDERED += 'sysvinit'
VIRTUAL-RUNTIME_init_manager = 'systemd'
VIRTUAL-RUNTIME_initscripts = ''
PREFERRED_PROVIDER_virtual/bootloader = 'systemd-boot'
PACKAGECONFIG:append:pn-systemd = ' cryptsetup'

# All image types any build stage might need; machines override
# IMAGE_FSTYPES to select their actual output formats
IMAGE_FSTYPES ?= 'ext4 wic wic.xz wic.zst wic.bmap'

# Release-quality xz compression; constrained machines can override
# in their machine config, and KAS overlays (debug, qa) override for
# faster dev builds
XZ_INTEGRITY_CHECK = 'sha256'
XZ_COMPRESSION_LEVEL = '-9e'

require conf/distro/include/gcsections.inc
require conf/distro/include/no-static-libs.inc
require conf/distro/include/security_flags.inc
require conf/distro/include/yocto-uninative.inc

INHERIT += 'uninative'

FULL_OPTIMIZATION="-Os -pipe ${DEBUG_FLAGS}"

# Save a little space by disabling wide character support in ncurses
ENABLE_WIDEC = 'false'

# Ensure wide character support is built in cross-tools where required
ENABLE_WIDEC:class-native = 'true'

# Don't install Native Language Support to save space and build time
USE_NLS='no'

# Don't install locales; they won't work without NLS
IMAGE_LINGUAS = ''
