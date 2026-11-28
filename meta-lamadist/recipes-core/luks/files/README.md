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
- `lamadist-var-notpm-key` / `lamadist-var-notpm-key.service` --
  machines WITHOUT the tpm2 DISTRO_FEATURE only (shipped by
  `../lamadist-var-notpm-key.bb`, which tpm2 machines skip; the gate
  is build time only, with no runtime TPM condition, because the
  crypttab line that names the key is build time too).  At first
  boot it generates a 32-byte per-device key from the kernel RNG at
  `/boot/lamadist-keys/var.key` on the ESP (mounted `umask=0077` on
  these machines), and puts it in LUKS2 keyslot 1 of `/var` with
  this dev keyfile as the unlock key, ordered after
  `lamadist-var-encrypt.service` and before
  `systemd-cryptsetup@var.service`.  `/etc/crypttab` on these
  machines unlocks with that key (`headless=true`, so a missing key
  fails at once instead of prompting), so a headless board boots
  with no TPM and no prompt.  A key that already unlocks `/var` is a
  no-op; any unlock-test failure other than "no key matches" fails
  the unit; otherwise a fresh key is generated and replaces keyslot
  1 (`luksKillSlot`, then `luksAddKey --key-slot 1`), so nothing
  found on the ESP is ever enrolled as is, and the slot count stays
  at two.  That recovery from a lost or damaged key works only while
  the dev keyfile slot exists: every kill and add is authorised with
  this dev keyfile, so killing the dev slot (one of the two options
  above) also means formatting with the per-device key and turning
  the loss of the ESP key into the loss of `/var`.  Without a TPM
  this key gives NO protection against physical access: it sits in
  the clear on the same disk as the volume it unlocks.  The dev
  keyfile slot above STILL EXISTS on these machines too (the
  per-device key is added alongside it, not in its place).  While
  the public development keyfile slot remains, a no-TPM /var opens
  with a public key, so the per-device key adds no protection at
  rest; that lasts until the pending owner decision to kill or gate
  the dev keyfile slot
  (meta-lamadist/recipes-core/luks/files/README.md).
- `regen-dev-var-key.sh` -- regenerates the keyfile in place.  Run it
  only to rotate the dev key (e.g. it leaks); commit the result like
  any other source file.  Rotating this file does NOT re-key any
  device already provisioned with the old one -- see the script's
  header comment.
