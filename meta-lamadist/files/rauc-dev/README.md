# RAUC development signing keys

**DEVELOPMENT ONLY.  This key pair is intentionally public.**  It
is committed to the repository so `bitbake lamadist-bundle` and
`mise run test-ota` work out of the box for anyone with a clone.
`dev-ca.key.pem` must never sign a bundle destined for a real
device outside this dev/CI loop, and must never be reused as (or
mixed into the trust chain of) a release signing key.  M6 owns the
real release CA and its (offline, non-repository) key material.

- `dev-ca.cert.pem` / `dev-ca.key.pem` -- self-signed CA,
  CN "LamaDist Development CA", 20-year validity, RSA-4096.
  `dev-ca.cert.pem` is installed on target as
  `/etc/rauc/keyring.pem` (see `../../recipes-core/rauc/
  rauc-conf.bbappend`) and is what `rauc install` verifies bundles
  against.  `dev-ca.key.pem` signs bundles built by
  `lamadist-bundle.bb` (`RAUC_KEY_FILE`/`RAUC_CERT_FILE`).
- `regen-dev-ca.sh` -- regenerates both files in place.  Run it only
  to rotate the dev CA (e.g. it expires, or the key needs to
  change); commit the result like any other source file.

**DEVELOPMENT ONLY: forced-unhealthy test hook.**
`lamadist-health-check`'s `/var/lamadist-force-unhealthy` flag (the
negative-rollback test hook `mise run test-ota` uses) only takes
effect when `/etc/lamadist/ota-test-hooks-enabled` exists on the
rootfs, which `rauc-conf.bbappend`'s `LAMADIST_OTA_TEST_HOOKS`
switch installs at build time (`??= "1"` today, alongside this dev
keyring).  M6's release image build must set
`LAMADIST_OTA_TEST_HOOKS = "0"` so a writable `/var` can never be
used to suppress updates on a real device.
