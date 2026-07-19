# /var LUKS2 development keyfile

**DEVELOPMENT ONLY.  This key is intentionally public.**  It is
committed to the repository so `bitbake lamadist-image-base` and
`mise run test` work out of the box for anyone with a clone.
`dev-var.key` must never unlock a `/var` partition on a real device
outside this dev/CI loop -- a LUKS keyslot holding a key committed to
the repository gives zero confidentiality, so it can never serve as
a production recovery fallback without defeating the /var encryption
this feature exists to provide.

`lamadist-var-tpm2-enroll.service` (W11 of the M4 plan) now adds a
TPM2 PCR7 keyslot via `systemd-cryptenroll` on every first boot,
**alongside** this keyfile slot -- it does not remove it.  This is
DEV BEHAVIOR ONLY, and deliberate: the decision on what a non-dev
build must do instead is still PENDING security-owner (Lucas)
sign-off (see `.cache/agents/m4-plan.md`, D7 and Open questions).
The two mechanisms under consideration remain:

- Kill the keyfile keyslot (`cryptsetup luksKillSlot`) once TPM2
  enrollment succeeds, on non-dev builds only.
- Gate installing the keyfile at all behind a dev/CI-only variable,
  so a non-dev build never has a keyfile keyslot to kill.

TODO(security-owner sign-off): until one of the above lands, treat
any non-dev image built from this recipe as carrying a public,
extractable `/var` decryption key -- the TPM2 keyslot narrows the
*normal* unlock path but does not revoke the keyfile one.  A real
release's recovery-fallback story is a milestone the M4 plan does
not yet scope.

- `dev-var.key` -- 32 bytes of random key material, installed on
  target as `/etc/lamadist/dev-var.key` (see
  `../lamadist-luks-var.bb`).  `lamadist-var-encrypt.service`
  `luksFormat`s the `PARTLABEL=var` partition with it the first time
  that partition has no LUKS2 header (a one-way migration -- see the
  module comment in `lamadist-var-encrypt`), and
  `lamadist-var-tpm2-enroll.service` uses it as the
  `--unlock-key-file` proving ownership when it enrolls the TPM2
  keyslot.  `/etc/crypttab`
  (`../../../classes/lamadist-image.bbclass`) unlocks the partition
  via `tpm2-device=auto` on every later boot, NOT via this file --
  the keyfile keyslot stays present as a fallback, but nothing in
  the normal boot path reads it once TPM2 enrollment has run.
- `lamadist-var-tpm2-enroll` / `lamadist-var-tpm2-enroll.service` --
  first-boot TPM2 PCR7 enrollment, ordered after
  `lamadist-var-encrypt.service` and idempotent via a `luksDump`
  token check.  See the script's header comment and the DEV
  BEHAVIOR note above.
- `regen-dev-var-key.sh` -- regenerates the keyfile in place.  Run it
  only to rotate the dev key (e.g. it leaks); commit the result like
  any other source file.  Rotating this file does NOT re-key any
  device already provisioned with the old one -- see the script's
  header comment.
