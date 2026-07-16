#!/bin/sh
# SPDX-License-Identifier: Apache-2.0
#
# Regenerates the LamaDist RAUC DEVELOPMENT-ONLY signing CA.  Never
# run this against a shipping product: the key it writes is
# committed to the repository and public to anyone with clone
# access.  See README.md in this directory.
set -eu
cd "$(dirname "$0")"

openssl req -x509 -newkey rsa:4096 -sha256 -days 7300 -noenc \
	-keyout dev-ca.key.pem -out dev-ca.cert.pem \
	-subj '/CN=LamaDist Development CA'
