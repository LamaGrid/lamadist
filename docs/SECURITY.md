# LamaDist Security Architecture and Threat Model

Status: CURRENT as of M4 close (2026-07-19).  The enforcing
Secure Boot + TPM2 + SELinux OTA gate is green on the shipped
policy, including a dontaudit-disabled certification pass with
zero findings.  This document covers the x86_64/QEMU development
profile.  Production
key management and per-platform hardware trust anchors are M6+
scope.  The Rockchip boards (the SOQuartz leaf) have a weaker
firmware trust model; "ARM boards: the Rockchip chain" states it.

## What this system defends against

LamaDist is an immutable, A/B-updated appliance OS for homelab
devices.  The composed stack is designed so that:

1. Offline modification of the ROOT FILESYSTEM (evil-maid, SD-card
   swap, compromised update server) is detected and refused at boot
   by dm-verity.  This covers the root only: /var (which backs the
   /etc overlay upper) is encrypted but NOT integrity-protected, and
   an old, validly-signed slot can still be booted (no anti-rollback
   -- see "Known gaps").
2. A compromised runtime service cannot silently persist across
   reboot or updates via the root filesystem, because it is
   read-only, cryptographically verified, and replaced wholesale by
   updates.  Persistence via /var-backed /etc config is bounded by
   SELinux, not by verity (see the overlay section).
3. Theft of the storage medium does not expose service state:
   everything mutable lives on an encrypted volume keyed to the
   device's TPM, and the image provisions no plaintext swap.
4. A bad update rolls back automatically while a known-good slot
   remains: boot counters and a health gate fall back to the
   previous slot.  This is not an absolute anti-brick guarantee --
   see the first-boot and both-slots-exhausted loops in "Known
   gaps".

It does NOT currently defend against: a compromised build host or
repo (the build signs with in-tree development keys), runtime
kernel exploits (no lockdown/IMA-appraisal enforcement yet), or
physical attackers with indefinite access to an unlocked, running
device.

## Boot chain of trust

UEFI firmware (OVMF with enrolled PK/KEK/db)
  -> systemd-boot (sbsign-signed, db key)
  -> per-slot UKI lamadist-a.efi / lamadist-b.efi
     (ukify-signed; kernel + initrd + cmdline are one signed
     object, so the dm-verity roothash on the cmdline is covered
     by the signature)
  -> dm-verity (erofs-lz4hc root, roothash pinned by the UKI)
  -> systemd + SELinux policy load (enforcing; the policy loads
     from the verity-covered lower before the /etc overlay mounts,
     so the boot policy is always the shipped one)

Design points:

- The UKI is the trust pivot: because cmdline is inside the
  signed PE, an attacker cannot point a signed kernel at an
  unsigned root or tamper with `systemd.verity` parameters
  without breaking the signature.
- Each slot has its own UKI; an update replaces the inactive
  slot's UKI and rootfs together, so a slot is always internally
  consistent (signature, roothash, filesystem).
- Boot counters live in systemd-boot loader entries.  A slot
  boots as a "trial" until the health gate marks it good; counter
  exhaustion falls back to the other slot (see docs/OTA.md).

### Development keys: what they do and do not protect

The Secure Boot keys (PK/KEK/db under `files/sb-dev/`) and the
RAUC bundle keyring (`rauc-dev/dev-ca.cert.pem`) are DEVELOPMENT
keys, committed to this repository on purpose:

- They DO exercise the full verification machinery end to end:
  enrollment, sbsign/ukify signing, bundle signature checks, and
  the failure paths (an unsigned UKI does not boot; an unsigned
  bundle does not install).
- They do NOT provide real-world authenticity: anyone with repo
  access can sign.  Every security property above must be read as
  "against attackers who do not have the repo".
- M6 (release engineering) owns the split: production signing
  with offline keys, dev profile keeps these keys.  Nothing in
  the image derives trust from key SECRECY today; the design only
  assumes the enrolled firmware db matches the signing keys.
- Baked test SSH key (2026-08-30): every test/dev installer build
  bakes the build host's cached test public key
  (`.local/share/lamadist/test-ssh/`, generated once, uncommitted,
  unencrypted) as an authorized key for the wheel user `lama`
  (`LAMADIST_SSH_AUTHORIZED_KEYS`, default-on in the installer
  task only).  Honest chain: whoever holds that host's private
  half gets SSH as `lama` on every lab install, and root via
  `sudo` with the PUBLIC fixed dev password.  Rotation: delete the
  directory and rebuild (the taskhash tracks key content, so
  sstate cannot serve a stale key).  Production builds leave the
  variable empty.
- Lab exception (operator-approved 2026-08-30): a dedicated
  lab/test machine counts as part of the dev/CI loop and MAY
  enroll the dev PK/KEK/db (`meta-lamadist/files/sb-dev/
  README.md`).  On such a machine every verified-boot property is
  exercise-only, and TPM2/PCR 7 sealing anchors to the public dev
  root; the machine may hold no production data or duties, and a
  role change requires clearing these keys from firmware and
  re-provisioning under the M6 chain.  The procedure is
  docs/installer/FLASHING-LAB.md.

## ARM boards: the Rockchip chain

The SOQuartz leaf boots through U-Boot as the UEFI provider (ADR
0013).  From systemd-boot on, the chain is the x86_64 chain:

```text
BootROM (mask ROM; on an unfused board it verifies nothing)
  -> rkbin DDR TPL (vendor binary, not auditable)
  -> U-Boot SPL
  -> BL31, and BL32 if the SPL FIT packs it (vendor binaries)
  -> U-Boot 2026.01 as the UEFI provider: EFI_LOADER,
     EFI_SECURE_BOOT, and PK/KEK/db from a build-time preseed
     (ADR 0016); no prompt, and the EFI loader is its only boot
     method
  -> systemd-boot at EFI/BOOT/BOOTAA64.EFI (sbsign-signed, db key)
  -> per-slot UKI (ukify-signed; also carries the board device tree)
  -> dm-verity, systemd, and SELinux, as on x86_64
```

The trust statement (ADR 0013 decision 4), for production keys.
With the development keys in `files/sb-dev/` the boards have no
Secure Boot property at all, as for x86_64 above.

- The trust anchor is a build-time seed inside an unverified U-Boot
  on writable storage.  PK, KEK, and db are compiled into the U-Boot
  binary, and U-Boot sits in the raw loader sectors of the boot
  medium.  The boards are not fused (ADR 0013 decision 5), so
  nothing verifies the DDR TPL, SPL, BL31, or U-Boot.
- Stopped: an attacker who can only write the ESP or supply
  removable media.  U-Boot starts no UKI that the project db does
  not sign, and the shipped U-Boot has no other boot path (no
  script, extlinux, or boot-manager method, and no prompt).
- NOT stopped: OS root in any domain that can open the whole-disk
  node; today that includes the OTA writer.  It can replace U-Boot,
  and with it db.  This is weaker than x86_64, where the OS cannot
  rewrite the firmware's PK and db.
- NOT stopped: an attacker who holds the medium or the board.
- PK, KEK, and db cannot change at run time: the variable store is
  `EFI_VARIABLE_NO_STORE`, and the build fails if the merged U-Boot
  configuration differs from its fragments.  dbx is not in the
  preseed and no write to it persists, so there is no revocation in
  the field.
- `SecureBoot=1` on these boards is the enforcement mechanism, not a
  root of trust.  No document, CI job, or check cites it as a root
  of trust until a board is fused.  Results from the QEMU U-Boot
  payload (`vm --firmware u-boot`) prove U-Boot's EFI code at the
  pinned tag, never a board property.

Where the Secure Boot anchor lives:

| Platform | PK, KEK, and db live in | Who can change them | Anchor |
| --- | --- | --- | --- |
| x86_64 (OVMF, lab UEFI) | Firmware NVRAM | Only a PK- or KEK-signed write | Firmware NVRAM |
| Rockchip (SOQuartz) | The U-Boot binary, in the raw loader sectors of the boot medium | Anyone who can write those sectors: OS root on the whole-disk node, or physical access | None: unfused loader |

ADR 0013 decision 4 asks the validator to print the anchor beside
its Secure Boot assertion; the validator does not print it yet.

## Data at rest: /var on LUKS2 + TPM2

All mutable state (logs, RAUC state, service data, the /etc
overlay upper) lives on a LUKS2 volume unlocked at boot:

- First boot: `lamadist-var-encrypt` formats /var, seeds it from
  the image, and `lamadist-var-tpm2-enroll` seals a key into the
  TPM against PCR 7 (Secure Boot state).  Later boots unseal via
  systemd-cryptsetup; the unlock path reads no keyfile (but a
  decryption keyfile IS baked into the dev image and enrolled as a
  standing slot -- see the dev-keyfile decision below).
- PCR 7 scope: sealing to PCR 7 means the volume only unseals
  while the Secure Boot configuration (db/KEK/PK, SB state) is
  unchanged.  Kernel/initrd updates do NOT re-seal (PCR 7 is
  stable across our A/B updates); firmware key rotation DOES
  require re-enrollment by design.  TWO SHARP EDGES the current
  code does not handle: (a) enrollment seals to whatever PCR 7
  reads on the enrolling boot with NO check that Secure Boot is
  actually on, so a first boot in setup/SB-off state seals to the
  wrong state and thereafter unseals whenever SB is off; and (b)
  crypttab unlocks TPM-only with no wired keyfile fallback, so a
  TPM that is slow to coldplug or a benign PCR 7 perturbation
  (firmware update) breaks unlock and, on a pending first boot,
  can reboot-loop.  Both are recorded in "Known gaps"; the
  SB-state assertion and a boot-path fallback are M6 decisions.
- The W11 dev-keyfile decision: the development profile keeps a
  keyfile slot (`/etc/lamadist/dev-var.key`, baked into the
  read-only root) alongside the TPM slot, so QEMU runs without
  swtpm state and image-rebuild loops stay debuggable.  BECAUSE
  this slot is a parallel unlock path and the keyfile is in-repo,
  TPM2/PCR 7 sealing provides ZERO marginal confidentiality on any
  dev-profile device: an attacker with the (public) keyfile
  unlocks /var offline regardless of TPM, Secure Boot, or PCR
  state.  It is a manual-recovery/first-boot-format slot, NOT an
  automatic boot fallback (crypttab does not reference it).  The
  M6 release profile drops the keyfile slot; only then does the
  PCR 7 sealing become a real at-rest control.
- KDF: `lamadist-var-encrypt` formats with `--pbkdf pbkdf2
  --pbkdf-force-iterations 1000` UNCONDITIONALLY (every image, not
  just the test profile).  This is acceptable ONLY because the
  slot passphrase is a high-entropy random keyfile, for which KDF
  hardening is near-irrelevant; the low iteration count also keeps
  QEMU first-boot inside the gate budget.  If a release ever adds
  a human-passphrase keyslot, this weak-KDF path MUST be revisited
  (argon2id).
- Machines without a TPM (no tpm2 DISTRO_FEATURE; ADR 0013
  decision 7): `lamadist-var-notpm-key` generates a per-device key
  at first boot, stores it on the ESP (`/boot/lamadist-keys/var.key`),
  and puts it in one fixed /var keyslot; crypttab unlocks with it, so
  a headless board needs no TPM and no prompt.  Without a TPM, this
  key gives no protection against physical access, and the exposure
  is wider than physical access: anyone who can read the storage or
  any copy of it (a disk image, a backup, a returned or discarded
  module) can read /var, because the key sits in the clear on the
  same disk as the volume it unlocks.  The ESP is mounted
  `umask=0077` on these machines; that is hygiene, not a control: it
  keeps unprivileged local users from reading the key and does
  nothing against anyone with the storage.  The key has no integrity
  and no revocation: nothing authenticates the ESP copy, so whoever
  can write the ESP can replace it (the unit then puts a fresh key in
  the slot rather than enrolling what it finds), and nothing rotates
  it, so a copied key stays valid until the ESP copy is lost or
  replaced.  The dev keyfile slot above still exists on these
  machines as well (the per-device key is added alongside it), so
  the public keyfile also unlocks /var, and the /var partition alone
  is enough: the ESP key is not even needed.  While the public
  development keyfile slot remains, a no-TPM /var opens with a
  public key, so the per-device key adds no protection at rest; that
  lasts until the pending owner decision to kill or gate the dev
  keyfile slot (meta-lamadist/recipes-core/luks/files/README.md).
  Known limit: fstab mounts the ESP at /boot by its filesystem label,
  `LABEL=msdos`, which is not unique to the boot disk.  A second FAT
  volume with that label (a USB stick or an SD card attached at boot)
  can take the label link.  The key unit then finds no working key
  there, replaces the fixed keyslot, and writes the new key to that
  removable medium, and the slot state that the RAUC backend writes
  to /boot goes there too.  The fix, mounting the ESP by a fixed
  PARTUUID from the WKS, is planned after M5 (docs/PLAN.md, Future
  Work).

## Runtime confinement: SELinux enforcing

- Policy: refpolicy-targeted plus a local module (`lamadist.te`)
  linked into the monolithic policy at BUILD time via a
  refpolicy bbappend.  There is no on-target policy store
  mutation; /etc/selinux is on the read-only root.
- The rootfs is labeled at image-build time (setfiles against the
  shipped file_contexts); there is no first-boot relabel, which
  closes the "boot once unlabeled, persist, relabel later"
  window an autorelabel design would open.
- Interactive and update paths are deliberately unconfined-ish on
  targeted policy (login users and init-driven services such as
  RAUC run unconfined); the confinement value today is for the
  long-running network-facing daemons and the audit trail.  The
  OTA acceptance gate requires a fully clean enforcing boot
  (zero failed units), so policy gaps surface as gate failures,
  not silent degradation.

### The /etc overlay and the mounter-credential posture

/etc is an overlayfs: read-only lower from the verified root,
upper on the encrypted /var.  Integrity boundary: dm-verity covers
the lower (the root), NOT the upper.  /var is LUKS2 aes-xts with no
AEAD/`--integrity`, so it gives confidentiality but not integrity;
its ciphertext is malleable.  Consequently the read-only-root
guarantee stops at the overlay: a late-loaded systemd unit or
drop-in written into the upper (by an attacker with the dev keyfile,
or via targeted ciphertext tampering) is honored by systemd for any
unit pulled in after the overlay mounts, which is a root-context
persistence path SELinux -- not verity -- must contain.  Early boot
is safe: generators and PID 1's initial unit load run from the
verity lower before the overlay mounts, so crypttab, /etc/selinux,
and the initial transaction are all verity-covered.

On this kernel (6.18) overlayfs performs ALL layer operations with
the MOUNTER's credentials (`override_creds=off` is rejected), which
has two consequences the policy must own honestly:

1. mount_t is the effective subject for /etc I/O that daemons do
   through the merged view -- as an ADDITIONAL check: the caller's
   own domain is still checked against the overlay inode, so
   mounter grants add no access for confined callers.  The local
   module grants mount_t bounded READ on all file types (read +
   directory list, symlink read, pipe/socket getattr, and map on
   file_contexts for the executor's labeling handle).  Broad by
   design: the /etc lower hosts any package's config type, and the
   Condition B dontaudit-disabled harvest proved per-type
   enumeration untenable -- 7 uncovered types on one image, with
   rauc's CA-certificate read and bluetoothd's config read failing
   silently.  Write-side mounter grants stay per-type and bounded
   (auditd rules backup, update-done stamping, overlay workdir
   setattr -- the last found by the same harvest as the silent
   cause of a read-only /etc on every enforcing boot).
2. Files CREATED through the merged /etc inherit the upper's
   var_t unless a tmpfiles rule labels them.  The one boot-time
   creator that mattered (ldconfig regenerating ld.so.cache) is
   masked; the linker cache ships complete on the immutable root.

Residual risk accepted: mount_t itself can read file content
across ALL file types, shadow included (via the sanctioned
can_read_shadow_passwords join).  This extends no OTHER domain's
access -- the caller-side check applies unchanged -- but it makes
the mount helper a higher-value target; mount_t runs only trusted
early-boot binaries from the verified read-only root, and
write-side mounter grants remain per-type.  This is the narrowest
posture that keeps an arbitrary package's config readable through
the overlay (allow_mount_anyfile stays off: runtime tunable,
broader); revisit if a future kernel restores
`override_creds=off`.

## Runtime integrity measurement: IMA (log mode)

`ima_policy=tcb ima_appraise=log` measures executables and
critical files into the IMA log (and TPM PCR 10) but does not
enforce appraisal.  Log mode is deliberate for now:

- Appraisal enforcement requires signing every executable at
  build time (EVM/IMA signatures over a busybox multi-call
  userland) and a stable xattr story through the overlay and
  RAUC updates; that machinery is not built yet.
- dm-verity already enforces immutability for everything on the
  root filesystem, which is where all executables live; IMA
  enforcement's marginal value today is /var-resident content,
  which SELinux already constrains.
- The measurement log still has forensic value and keeps PCR 10
  available for future attestation work.

## Update security

RAUC bundles are signed (dev CA above) and verified before
install; slots verify dm-verity roothashes end to end, and the
roothash rides inside the signed UKI `.cmdline` so a signed kernel
cannot be pointed at a different root.  The health gate
(`lamadist-health-check`) marks a trial slot good only after a
clean boot; forced-unhealthy testing exercises the rollback path in
the OTA gate.  A single bad update rolls back to the last-known-good
slot (counters are stripped on mark-good).  Note the bounds: there
is NO anti-rollback, so an old but validly-signed slot can be booted
by rewriting the plaintext, unauthenticated ESP loader entries; and
the "degrades rather than loops" property is only the single-bad-slot
case (both-slots-exhausted and a flaky first boot can loop -- see
Known gaps).  See docs/OTA.md for the full state machine.

## Installer surface (Installer Pass)

The USB installer (docs/installer/SPEC.md, ADRs 0006-0008) adds
an attack surface with its own trust model:

- **Setup-Mode custody / TOFU.**  The real root of trust for key
  enrollment is whoever boots first while the target is in Setup
  Mode.  Physical custody of BOTH the stick and the target during
  that window is a stated precondition; enrollment is
  trust-on-first-install.  The in-UKI digest gate (expected
  PK/KEK/db carried inside the signed installer UKI, asserted
  with `SecureBoot=1` before any disk access) detects wrong-chain
  enrollment and tampered on-ESP `.auth` payloads; it CANNOT
  detect a fully attacker-controlled first boot.  The gate checks
  PK/KEK/db only -- it makes no dbx claim.
- **Unsigned enrollment inputs.**  The `.auth` files and loader
  config on the installer ESP are unsigned FAT32 artifacts by
  construction; their sole integrity control is the in-UKI hash
  check above.
- **Unlabeled installer runtime.**  The installer initramfs runs
  without SELinux; its only protection is the Secure Boot
  signature over the UKI.  Files it creates on the target are
  labeled at creation from the in-UKI `file_contexts`.
- **Per-stick recovery credential exposure.**  The per-stick
  password becomes the target's LUKS2 recovery keyslot
  (argon2id).  Role B learns it at install time and holds it
  until rotated; rotation is a manual, CSPRNG-only procedure.
  The local install-consumed flag is a best-effort operational
  guard on a writable FAT32 partition, NOT a security control;
  enforced one-stick-one-install (fresh lookup, generation
  retirement) exists only at the portal tier (design-only, see
  docs/installer/AT-SCALE.md).  The inline-password sidecar
  downgrade makes a stolen stick self-unlocking: it yields the
  payload and the recovery credential of that stick's target.
- **The PUBLIC manual is untrusted input to the human.**  It is
  an unauthenticated instruction channel (portal-URL rewrite,
  "skip verification" phishing); the authoritative copy lives
  inside the vault, and portal identity is pinned out-of-band.
  The PUBLIC install log is forgeable convenience telemetry,
  never an audit record.
- **First-boot guard.**  Installer-provisioned volumes are
  accepted at first boot only when TPM2 unseal against the
  expected PCR7 succeeds; existence checks are forbidden
  (adopting an attacker-preformatted volume) and unseal failure
  fails closed to the console recovery path.

## Known gaps and accepted risks

- Development keys in-tree (by design until M6; see above).
- Dev-keyfile slot nullifies TPM2/PCR 7 confidentiality on dev
  images (see the /var section); real at-rest protection begins
  when M6 drops the slot.
- No-TPM machines: /var at rest is unprotected against anyone who
  can read the storage or a copy of it, by design (the per-device
  key is in the clear on the ESP; see the /var section).  The dev
  keyfile slot is live there too, so the public key alone opens
  /var.  The per-device key has no integrity and no revocation
  without a TPM, and recovering a lost key depends on the dev slot.
  The ESP is mounted by the label `msdos`, which is not unique, so a
  removable FAT volume with that label can receive the key (see the
  /var section); a fixed PARTUUID is planned after M5.
- IMA is log-only (by design for now; see above).
- /var has NO integrity protection (LUKS2 aes-xts, no AEAD): the
  /etc overlay upper is confidential but malleable, and late-boot
  units/config read through it are a persistence path bounded by
  SELinux, not verity.  A /var `--integrity` mode is deferred
  (performance cost, format-path re-key).
- The ESP is the one element with no A/B copy.  systemd-boot, both
  slots' UKIs and loader entries, and the keyless `boot.conf` live on
  one FAT volume, so a corrupt or lost ESP stops both slots.  The
  firmware writes it during boot: the counter rename on a trial boot
  (U-Boot's FAT writer on the Rockchip boards), and
  `\loader\random-seed` on every boot if that file exists, which is
  open (ADR 0013 decision 11).  The OTA install writes it too.
- Rockchip boards: the anchor is unverified U-Boot on writable
  storage, and there is no TPM, no field revocation, no
  anti-rollback for U-Boot, and no runtime `SetVariable`
  (`bootctl set-default` and `set-oneshot` fail).  On an unfused
  board the USB maskrom path can rewrite all storage.  See "ARM
  boards: the Rockchip chain".
- No anti-rollback / unauthenticated ESP: an old validly-signed
  slot can be forced by rewriting the plaintext loader entries;
  ESP entry deletion/corruption is also a DoS.  A monotonic
  version counter / retired-roothash dbx is M6 scope.
- TPM2 sealing precondition unverified: enrollment does not check
  Secure Boot is on before sealing to PCR 7, and there is no
  boot-time keyfile fallback, so a first boot in the wrong SB
  state or a slow/absent TPM can misseal or reboot-loop.  M6
  should add an SB-state assertion before enroll and decide the
  boot-path fallback; a slow TPM coldplug past the 30 s settle is
  a real brick path today.
- PCR 7 brittleness: any firmware change that perturbs PCR 7 (not
  just key rotation) breaks unlock with no automatic fallback.
- First-boot health-gate fragility: the factory image ships slot
  A as a counted trial, so a transient degrade during the fragile
  first-boot one-shots (LUKS format, seed, TPM enroll) can burn
  all tries and loop.  Exempting the never-yet-good first boot
  from reboot-on-unhealthy is the tracked fix.
- Enforcing SELinux gate: green on build 40 (smoke + full OTA +
  rollback), and the dontaudit-disabled certification pass on the
  same build returned zero findings (13 documented-accepted noise
  rows only).  Certification scope note: the dontaudit-disabled
  exercise is structurally post-boot only (PID 1 loads the stock
  policy from the verity lower before the overlay exists), so
  MOUNT-TIME mount_t operations are certified behaviorally
  instead -- the smoke test's /etc read-write assertion plus an
  enforcing=0 differential boot.  Every policy rule in
  `lamadist.te` cites its triggering evidence.
- /etc is rw-mounted but not arbitrarily writable: the
  mounter-cred WRITE layer only covers the granted system writers
  (tmpfiles, augenrules, update-done, the overlay/workdir and
  machine-id paths).  A naive interactive edit of an arbitrary
  /etc file under enforcing can still be refused at that layer
  (e.g. copy-up of a net_conf_t file).  All product flows work
  and are gate-verified; interactive /etc editing is not a
  supported flow on the immutable profile.  If it ever becomes
  one, the write side needs a broad grant mirroring the read
  consolidation.
- mount_t content reads are broad by design (see the overlay
  section): the former per-type "insurance" reads, shadow
  included, were re-audited under Condition A and reclassified as
  permanent mounter-cred double-checks, then subsumed by the
  broad read grant rather than dropped.
- machine-id volatility: TWO stacked causes -- the read-only /etc
  bug (fixed: overlay workdir setattr) and the W11 tmpfs bind
  that shadows the persistent commit (still open, tracked as M6
  first-boot-robustness work); impact is log correlation, not
  confidentiality.
- Audit coverage: refpolicy dontaudit rules hide mounter-cred
  denials; that cost three debugging rounds AND masked a
  read-only /etc on every enforcing boot (the workdir setattr
  denial).  The M4 exit therefore ran the dontaudit-disabled
  harvest (Condition B, done -- 23 genuinely-missing rows, all
  triaged) and the smoke test now asserts /etc mounts
  read-write.
- QEMU/OVMF is the only validated platform; hardware-specific
  trust anchors (real UEFI implementations, discrete TPMs) are
  unvalidated until the post-M4 hardware checkpoint.

## Portability boundaries

The OS-level stack (erofs and dm-verity, LUKS /var, RAUC, SELinux,
and IMA) ports as-is.  The Rockchip leaf also keeps the boot path:
it ships UEFI Secure Boot (provided by U-Boot), systemd-boot, and
the signed UKI, and it does not use U-Boot FIT signing (ADR 0013).
What changes is the anchor (see "ARM boards: the Rockchip chain"):
no firmware-held root of trust until a board is fused, and no TPM2,
so no PCR 7 sealing (/var uses the per-device key).  An OP-TEE
fTPM on the RK1 is a later spike.  Tegra keeps its own EDK2 design,
not yet built.  Every other claim in this document holds for the
x86_64 profile only.
