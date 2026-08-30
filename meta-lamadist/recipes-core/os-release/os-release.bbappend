# SPDX-License-Identifier: Apache-2.0
#
# The distro pins DISTRO_VERSION[vardepvalue] to the constant
# DISTRO_VERSION_BASE so package sstate stays valid across commits
# (lamadist-versioning.inc), but that pin also freezes THIS recipe's
# task hash: sstate then serves /etc/os-release from whichever
# commit first populated the cache, and VERSION goes stale.  Re-add
# the real version to the do_compile hash here; the immediate (:=)
# expansion captures the literal string at parse time, bypassing the
# vardepvalue indirection.  Cost: a commit that changes the version
# re-runs only this tiny recipe plus image rootfs assembly, while
# package-level sstate stays valid.
OS_RELEASE_REAL_VERSION := "${DISTRO_VERSION}"
do_compile[vardeps] += "OS_RELEASE_REAL_VERSION"
