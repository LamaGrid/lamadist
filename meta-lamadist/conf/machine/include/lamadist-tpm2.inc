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
