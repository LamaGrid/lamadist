#!/bin/sh
# SPDX-License-Identifier: Apache-2.0
#
# Regenerates the LamaDist Secure Boot DEVELOPMENT-ONLY PK/KEK/db
# chain.  Never run this against a shipping product: the keys it
# writes are committed to the repository and public to anyone with
# clone access.  See README.md in this directory.
#
# Each of PK, KEK, and db is a self-signed RSA-4096 cert (there is
# no PK-signs-KEK-signs-db chain here -- UEFI Secure Boot's PK/KEK/db
# are independent trust anchors enrolled directly into firmware
# variables, not an X.509 certificate chain).  For each key this
# script writes three forms: a PEM key+cert pair (sbsign, ukify --
# see ../../classes/lamadist-uki.bbclass UKI_SB_KEY/UKI_SB_CERT and
# the systemd-boot bbappend), a DER cert (tools that reject PEM),
# and an EFI Signature List (virt-firmware enrollment -- see
# .mise/tasks/ovmf-vars).
#
# GUID is the fixed (arbitrary, no special meaning) owner GUID
# efitools' cert-to-efi-sig-list stamps into each ESL's signature
# owner field.  It is a constant, not regenerated here, so re-running
# this script to rotate keys does not also change the owner GUID
# W10's enrollment tooling references.
set -eu
cd "$(dirname "$0")"

command -v cert-to-efi-sig-list >/dev/null || {
	echo "ERROR: efitools (cert-to-efi-sig-list) not found" >&2
	exit 1
}

GUID='0d648e51-9f2d-453a-bbc1-2200cf8ebe0e'

for _name in pk kek db; do
	case "${_name}" in
	pk) _cn='LamaDist Development PK' ;;
	kek) _cn='LamaDist Development KEK' ;;
	db) _cn='LamaDist Development db' ;;
	esac

	openssl req -x509 -newkey rsa:4096 -sha256 -days 7300 -noenc \
		-keyout "${_name}.key.pem" -out "${_name}.cert.pem" \
		-subj "/CN=${_cn}"

	openssl x509 -in "${_name}.cert.pem" -outform der \
		-out "${_name}.cert.der"

	cert-to-efi-sig-list -g "${GUID}" \
		"${_name}.cert.pem" "${_name}.esl"
done
unset _name _cn
