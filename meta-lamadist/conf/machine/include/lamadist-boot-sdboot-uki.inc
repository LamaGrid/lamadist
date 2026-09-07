# SPDX-License-Identifier: Apache-2.0
#
# systemd-boot + UKI boot-backend policy, required by a machine leaf
# whose boot chain is systemd-boot with Unified Kernel Images (x86-64;
# intel today).  These choices used to live in the distro includes;
# they move here so the distro layer stays backend-neutral and a
# U-Boot or L4T machine can set its own boot chain without conflict.

LAMADIST_BOOT_BACKEND = "sdboot-uki"

# systemd-boot is both the bootloader and the EFI provider.  The RAUC
# systemd-boot backend (recipes-core/rauc/files/systemd-boot-backend)
# drives A/B selection and boot counting through the Type1 loader
# entries' sort-keys, because sd-boot 259.5 has no assessment-aware
# default key.
EFI_PROVIDER = "systemd-boot"
PREFERRED_PROVIDER_virtual/bootloader = "systemd-boot"

# Secure Boot signing keys (stage B, W9).
#
# DEVELOPMENT ONLY -- meta-lamadist/files/sb-dev/README.md.  db is the
# signature-database key/cert: lamadist-uki.bbclass's ukify call signs
# both per-slot UKIs with it whenever both variables are non-empty
# (stage A leaves them unset, so that build stays unsigned), and the
# systemd-boot bbappend (recipes-bsp/systemd-boot/systemd-boot_%.bbappend)
# sbsigns systemd-bootx64.efi with the identical pair, so every PE the
# firmware executes verifies against the one enrolled db entry.  M6
# replaces this pair with real, non-repository key material -- do NOT
# point these at production keys here.
UKI_SB_KEY  ?= "${@bb.utils.which(d.getVar('BBPATH'), 'files/sb-dev/db.key.pem')}"
UKI_SB_CERT ?= "${@bb.utils.which(d.getVar('BBPATH'), 'files/sb-dev/db.cert.pem')}"
