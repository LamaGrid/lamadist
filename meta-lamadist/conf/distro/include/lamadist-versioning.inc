# vi:ft=bitbake
# SPDX-License-Identifier: Apache-2.0
#
# LamaDist version computation.
#
# DISTRO_VERSION_BASE is the human-readable release number.
# DISTRO_VERSION appends the git metadata revision for
# traceability.  The vardepvalue pin ensures sstate hashes
# depend only on the base version, not the ever-changing
# METADATA_REVISION, so the sstate cache remains valid
# across commits within the same release series.

DISTRO_VERSION_BASE = '0.1'
DISTRO_VERSION ?= "${DISTRO_VERSION_BASE}+snapshot-${METADATA_REVISION}"
DISTRO_VERSION[vardepvalue] ?= "${DISTRO_VERSION_BASE}"
DISTRO_CODENAME = 'main'
