#!/bin/sh
# SPDX-License-Identifier: Apache-2.0
#
# Regenerates the LamaDist /var LUKS2 DEVELOPMENT-ONLY keyfile.
# Never run this against a shipping product: the key it writes is
# committed to the repository and public to anyone with clone
# access.  See README.md in this directory.
#
# Rotating this file does NOT rotate an already-provisioned device:
# lamadist-var-encrypt.service only ever luksFormats a 'var'
# partition once (the one-way migration in the M4 plan's decision
# 4), so a device that already has a LUKS2 header keeps using
# whatever key was baked into the image that formatted it.  Add a
# new keyslot with `cryptsetup luksAddKey` (and drop the old one)
# on any device that must move to a regenerated key.
set -eu
cd "$(dirname "$0")"

openssl rand -out dev-var.key 32
chmod 0600 dev-var.key
