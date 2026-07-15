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

# 'x11' stays here even though the target has no display: this list
# governs build-host native/cross tool recipes only (never shipped to
# the target).  libsdl2.bb and libepoxy.bb both hardcode
# PACKAGECONFIG:class-native to include 'x11' unconditionally,
# regardless of DISTRO_FEATURES_NATIVE or qemu's own settings, so any
# native build that pulls them in (qemu-system-native, which
# oe-core's qemuboot.bbclass unconditionally adds to
# EXTRA_IMAGEDEPENDS -- enabled for this BSP by genericx86-64's
# machine chain via `IMAGE_CLASSES += "qemuboot"`) needs
# virtual/libx11-native to be resolvable.
#
# 'systemd' is deliberately absent: oe-core's systemd.bb has no
# native BBCLASSEXTEND, so "systemd-native" can never be provided.
# Recipes that unconditionally add "systemd-systemctl-native" to
# DEPENDS when 'systemd' is in DISTRO_FEATURES (e.g. util-linux via
# systemd.bbclass) close a hard dependency cycle with
# systemd-systemctl-native's own build if 'systemd' leaks into the
# native context.  Any BBCLASSEXTEND=native recipe with an unguarded
# `bb.utils.filter('DISTRO_FEATURES', 'systemd', d)` default (e.g.
# appstream) is a landmine for the same reason -- do not re-add
# 'systemd' here without first auditing for that pattern.
DISTRO_FEATURES_NATIVE = 'acl x11 xattr ipv4 ipv6 selinux luks ima'

DISTRO_EXTRA_RDEPENDS += 'packagegroup-core-boot'
DISTRO_EXTRA_RRECOMMENDS += ''

# Wrynose ships Linux 6.18 LTS; the 6.6 recipes left oe-core
PREFERRED_VERSION_linux-yocto ?= '6.18%'
PREFERRED_VERSION_linux-yocto-rt ?= '6.18%'

SDK_NAME = "${DISTRO}-${TCLIBC}-${SDKMACHINE}-${IMAGE_BASENAME}-${TUNE_PKGARCH}-${MACHINE}"
SDKPATHINSTALL = "/opt/${DISTRO}/${SDK_VERSION}"

PACKAGE_CLASSES = 'package_rpm'

# systemd
INIT_MANAGER = 'systemd'
EFI_PROVIDER = 'systemd-boot'
DISTRO_FEATURES_OPTED_OUT += 'sysvinit'
VIRTUAL-RUNTIME_init_manager = 'systemd'
VIRTUAL-RUNTIME_initscripts = ''
PREFERRED_PROVIDER_virtual/bootloader = 'systemd-boot'
PACKAGECONFIG:append:pn-systemd = ' cryptsetup'

# All image types any build stage might need; machines override
# IMAGE_FSTYPES to select their actual output formats
IMAGE_FSTYPES ?= 'ext4 wic wic.xz wic.zst wic.bmap'

# /var/log must be a real directory (not a link into volatile
# tmpfs) so the journal persists on the writable /var partition.
# Since 6.0 this is selected by dropping fs-perms-volatile-log.txt
# from the perms tables (VOLATILE_LOG_DIR is gone).
FILESYSTEM_PERMS_TABLES = "files/fs-perms.txt files/fs-perms-volatile-tmp.txt"

# Release-quality xz compression; constrained machines can override
# in their machine config, and KAS overlays (debug, qa) override for
# faster dev builds
XZ_INTEGRITY_CHECK = 'sha256'
XZ_COMPRESSION_LEVEL = '-9e'

require conf/distro/include/lamadist-gcsections.inc

# no-static-libs.inc, security_flags.inc, and yocto-uninative.inc are
# all required by oe-core's defaultsetup.conf since Wrynose; no need
# to require them again here.  defaultsetup.conf's INHERIT_DISTRO also
# inherits the uninative class by default, so no explicit INHERIT here
# either.

# -Os for flash-size budget; use ${DEBUG_LEVELFLAG} (not DEBUG_FLAGS
# -- renamed upstream).  Do not add ${DEBUG_PREFIX_MAP} here: oe-core's
# bitbake.conf already appends it in TARGET_CFLAGS, so re-adding it
# would duplicate the -ffile-prefix-map flags.  Same reasoning for
# '-pipe': bitbake.conf's TARGET_CFLAGS/BUILDSDK_CFLAGS append it
# unconditionally, so it no longer belongs in this override either.
FULL_OPTIMIZATION = "-Os ${DEBUG_LEVELFLAG}"

# Save a little space by disabling wide character support in ncurses
ENABLE_WIDEC = 'false'

# Ensure wide character support is built in cross-tools where required
ENABLE_WIDEC:class-native = 'true'

# Don't install Native Language Support to save space and build time
USE_NLS = 'no'

# Don't install locales; they won't work without NLS
IMAGE_LINGUAS = ''
