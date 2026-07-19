# vi:ft=bitbake
# SPDX-License-Identifier: Apache-2.0
#
# TPM 2.0 machine configuration for LamaDist.
#
# Include this from machine configs that have TPM 2.0 hardware.
# Requires meta-secure-core/meta-tpm2 in the layer stack.

DISTRO_FEATURES_NATIVE:append = ' tpm2'
DISTRO_FEATURES:append = ' tpm2'
SECURE_CORE_IMAGE_EXTRA_INSTALL += 'packagegroup-tpm2'

# DISTRO_FEATURES 'tpm2' alone does not turn on systemd's own TPM2
# support: oe-core's systemd_259.5.bb only auto-maps a fixed
# DISTRO_FEATURES list (acl audit apparmor efi ldconfig pam
# pni-names selinux smack polkit seccomp) and 'tpm2' is not in it.
# Without PACKAGECONFIG[tpm2], systemd (and therefore
# systemd-cryptenroll and crypttab's tpm2-device=auto) builds with
# -Dtpm2=disabled, compiling out cryptsetup.c's HAVE_TPM2 codepath.
# PACKAGECONFIG[cryptsetup-plugins] is separately required to build
# libcryptsetup-token-systemd-tpm2.so, the plugin
# systemd-cryptsetup@var.service's tpm2-device=auto unlock loads at
# runtime (lamadist-image.bbclass's crypttab entry).
PACKAGECONFIG:append:pn-systemd = ' tpm2 cryptsetup-plugins'
