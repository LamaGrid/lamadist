# Secure Boot development key chain

**DEVELOPMENT ONLY.  This key chain is intentionally public.**  It
is committed to the repository so `bitbake lamadist-image-base` and
`mise run test -- --secureboot` work out of the box for anyone with
a clone.  None of these keys may enroll into, or sign anything that
boots on, a real device outside this dev/CI loop -- a Secure Boot
trust anchor whose private key is committed to the repository gives
zero protection against a malicious image, so it can never serve as
a production root of trust.  M6 owns the real PK/KEK/db and their
(offline, non-repository) key material.

**Lab-machine exception (operator-approved 2026-08-30).**  A
dedicated lab or test machine counts as part of this dev/CI loop:
enrolling the dev PK/KEK/db into its firmware is allowed.  The
consequences carry over unchanged -- Secure Boot on that machine
authenticates nothing (anyone with a repo clone can sign a bootable
image), and its TPM2/PCR 7 sealing anchors to this public root.
Such a machine may hold no production data or duties, and moving it
to any other role requires clearing these keys from its firmware
and re-provisioning under the M6 chain.  Production devices remain
prohibited.  The lab flash procedure is
`docs/installer/FLASHING-LAB.md`.

- `pk.key.pem` / `pk.cert.pem` -- Platform Key.  Self-signed CA,
  CN "LamaDist Development PK", 20-year validity, RSA-4096.  The PK
  is the Secure Boot root of trust: whoever holds `pk.key.pem` can
  re-enroll KEK.  `.mise/tasks/ovmf-vars` (W10) enrolls
  `pk.cert.pem`/`pk.esl` into the `ovmf-vars-enrolled.fd` deploy
  artifact the `--secureboot` vm task consumes.
- `kek.key.pem` / `kek.cert.pem` -- Key Exchange Key.  Same shape as
  PK (self-signed, CN "LamaDist Development KEK", RSA-4096,
  20-year).  Authorizes updates to db (and dbx, not shipped here --
  M4 pass 1 enrolls no forbidden-signatures list).  Enrolled by
  `.mise/tasks/ovmf-vars` alongside PK.
- `db.key.pem` / `db.cert.pem` -- signature database entry.  Same
  shape again (CN "LamaDist Development db").  `db.key.pem` is what
  actually signs boot binaries: the systemd-boot bbappend (W9)
  sbsigns `systemd-bootx64.efi` with it, and
  `lamadist-security.inc` (W9) points `UKI_SB_KEY`/`UKI_SB_CERT`
  (`../../classes/lamadist-uki.bbclass`) at `db.key.pem`/
  `db.cert.pem` so ukify signs both per-slot UKIs the same way.
  `db.cert.pem`/`db.esl` is what firmware checks signatures against
  once enrolled.
- `*.cert.der` -- DER form of each cert above, for tooling that
  rejects PEM.
- `*.esl` -- EFI Signature List form of each cert above (built with
  efitools' `cert-to-efi-sig-list`), for virt-firmware enrollment
  (`.mise/tasks/ovmf-vars`, W10) and any other tool that consumes
  raw ESLs instead of PEM/DER.  All three share the same fixed
  owner GUID, `0d648e51-9f2d-453a-bbc1-2200cf8ebe0e`
  -- see `regen-dev-sb-keys.sh`'s header comment for why it is a
  constant rather than regenerated.
- `regen-dev-sb-keys.sh` -- regenerates all nine key/cert files (and
  derived DER/ESL forms) in place.  Run it only to rotate the dev
  chain (e.g. a key leaks, or the 20-year validity nears expiry);
  commit the result like any other source file.  PK, KEK, and db
  are independent self-signed certs, not a signing chain -- UEFI
  Secure Boot enrolls each directly into its own firmware variable
  rather than validating one against another.  Requires `openssl`
  and `efitools` (for `cert-to-efi-sig-list`); the builder container
  has both (`container/packages.txt`).

**Not a chain of trust in the X.509 sense.**  Unlike the RAUC dev CA
(`../rauc-dev/`), where `dev-ca.cert.pem` signs bundle certs, PK/KEK/
db here are three unrelated self-signed certs.  UEFI Secure Boot's
PK -> KEK -> db authorization model is enforced by firmware variable
write permissions (PK authorizes writing KEK, KEK authorizes writing
db), not by certificate signing relationships, so there is no
`openssl verify` chain to check across the three -- only that each
cert is internally self-consistent (self-signed, and its embedded
public key matches its own private key).
