# LamaDist USB Installer -- SPEC

**Status:** DRAFT, revision 2 -- reworked per the Fable security
review (`.local/state/agents/installer-spec-review.md`, verdict
REWORK: both blockers and all majors addressed in this revision).
Becomes CURRENT only after the targeted re-review passes and the
three AoAs land as ADRs.  Sections marked `[AoA: ...]` are
contractual slots filled by an ADR, not open questions.

**Scope of this pass:** ONE installer USB image artifact, built by
kas/bitbake and verified exclusively under QEMU+OVMF with Secure
Boot enforcing, plus Podman, static analysis, and unit tests.  No
physical flashing, no real-machine provisioning, no batch/fleet
tooling.  The at-scale secrets system is designed and written down
only (see `docs/installer/AT-SCALE.md`).

**Priority order when requirements tension:** non-destructiveness
> Secure Boot integrity > reproducibility > image size.

## 1. Definitions

- **Target**: the machine being installed; generic x86_64 UEFI
  firmware, Secure Boot capable.  No vendor-specific assumptions.
- **Stick**: the installer USB medium (this pass: its image
  artifact, boot-verified in QEMU).
- **Vault**: the encrypted volume on the stick holding the OS
  image payload and the manifest.  `[AoA: vault mechanism --
  LUKS2 container is the expected standard building block]`
- **Manifest**: one file inside the vault supplying every install
  setting, enabling headless installs.
- **Role A (provisioner)**: creates, flashes, labels, and ships
  sticks; writes the per-stick secret into the secrets manager.
- **Role B (technician)**: performs the install; obtains the
  stick's unlock password from the secrets manager (locally fnox;
  at scale, the portal).
- **Payload**: the unmodified current hardened x86_64 image
  (EROFS + dm-verity root, LUKS2 data, enforcing SELinux) as
  `.wic.xz` + `.wic.bmap`.

## 2. Hard requirements

1. The installed system boots with Secure Boot enforcing and the
   full chain validating.  The installer MUST verify this state
   (section 3.1 step 3) rather than assume it; an install can
   never complete with Secure Boot off or with a trust root other
   than the expected chain.  `[AoA: chain shape -- resolved by
   AOA-SIGNING: the existing custom PK/KEK/db chain, userland
   enrollment primary]`
2. The installer never writes any block device other than the one
   operator-selected target disk, with exactly two narrow
   exemptions on its own stick media: appending the install log
   and setting the install-consumed flag (both on the PUBLIC
   partition).  All ambiguity resolves to abort-without-writing
   (fail-closed).
3. The stick's OS image payload and manifest are encrypted at
   rest inside the vault; unlocking requires the per-stick
   password.
4. The per-stick password is unique to the stick, is issued and
   stored through the secrets manager, and serves ONE install:
   after a successful install the stick is consumed (section 6)
   and must be re-provisioned by Role A (fresh password, new
   vault) before it can install again.
5. Install-time input is minimal: hostname, network settings, and
   the unlock password.  Target-disk selection is input in
   interactive mode and manifest-supplied in headless mode.
6. Every setting is also expressible in the manifest; a complete
   manifest yields a fully headless install with zero interactive
   input.
7. The stick carries the operator manual.  The AUTHORITATIVE copy
   lives inside the vault; the PUBLIC partition carries a
   convenience copy explicitly marked as unverified (section 4
   and MAJOR-10 disposition).
8. Secure Boot key enrollment is performed by the signed
   installer userland (primary mechanism), automated where
   firmware state permits, with explicit confirmation in
   interactive mode; where automation is not possible the flow
   presents in-line technician instructions, and the same
   instructions ship in the on-stick manual.

## 3. User flow

The user flow is the primary deliverable; recipes serve it.

### 3.1 Interactive flow

1. **Boot.**  Technician selects the stick in the firmware boot
   menu.  The installer boots as a signed UKI (kernel + installer
   userland in the initramfs), so the entire installer
   environment is covered by one Secure Boot signature.  The UKI
   initramfs carries, covered by that signature: the expected
   PK/KEK/db digests, the `.auth` enrollment payloads' expected
   hashes, and the SELinux `file_contexts` used for install-time
   labeling.
2. **Trust-state machine.**  The installer reads the
   `SecureBoot` and `SetupMode` EFI variables and dispatches on
   ALL four states:
   - `SetupMode=1`: enrollment is possible.  Verify the on-ESP
     `.auth` payloads against the in-UKI expected hashes (they
     are unsigned FAT32 files; this check is their integrity
     control), present the enrollment confirmation (interactive)
     or read the manifest's enrollment consent (headless, after
     step 4 -- see ordering note in 3.2), write PK/KEK/db via
     direct efivarfs `.auth` writes from the signed userland (no
     external enrollment binary), then reboot and continue.
   - `SecureBoot=1, SetupMode=0`: proceed to step 3 verification.
   - `SecureBoot=0, SetupMode=0` (Secure Boot disabled -- the
     common field configuration): HALT fail-closed with in-flow
     instructions ("enter firmware setup, enable Secure Boot or
     clear keys to Setup Mode, reboot the stick").  The install
     never proceeds SB-off.
   - Secure Boot on but our chain untrusted: unreachable in-flow
     (the installer would not have booted); covered by the
     manual's pre-boot section.
3. **Trust verification gate.**  Before ANY disk enumeration or
   write: assert `SecureBoot=1` AND that the live PK, KEK, and db
   variable contents match the in-UKI expected digests.  Any
   mismatch -- including an attacker PK with our db cert
   alongside -- halts fail-closed with a diagnostic naming the
   mismatched variable.  This gate is the single mechanism
   closing the SB-off silent install, the foreign-trust-root
   install, and the tampered-enrollment-payload cases.
4. **Unlock.**  Prompt for the per-stick password (obtained by
   Role B from the secrets manager).  Three attempts; on
   exhaustion, halt with a diagnostic.  Nothing has been written.
   If the stick's install-consumed flag is set, halt: the stick
   must be re-provisioned by Role A first.
5. **Settings.**  If the vault contains a manifest, it is parsed
   by the strict reader (section 5); it pre-fills all prompts and
   the technician confirms or overrides.  Otherwise prompt for:
   hostname, network mode (dhcp | static + address / gateway /
   DNS), and target disk.
6. **Disk selection.**  Enumerate fixed disks by stable ID
   (`/dev/disk/by-id`), excluding the stick itself and any medium
   holding an unlock keyfile.  Display ID, model, size.  The
   technician selects, then types an explicit confirmation phrase
   containing the disk ID.  Anything else aborts.
7. **Write.**  Decrypt-stream the payload to the selected disk;
   verify the vault-carried SHA-256 sums AFTER decrypt and BEFORE
   declaring the write good (the vault is
   confidentiality-only -- see section 4).  A write failure
   aborts loudly; partial writes are called out as leaving the
   target unbootable, but no OTHER disk is ever touched.
8. **Provision (full, install-time).**  The installer performs
   the complete data-volume provisioning on the target, in order:
   1. `luksFormat` the data partition (LUKS2).
   2. Enroll the per-stick password as the RECOVERY keyslot with
      argon2id KDF.  (KDF parameters are per-keyslot: argon2id
      here costs nothing at normal boot, which unlocks via TPM2;
      pbkdf2-1000 remains confined to keyfile/TPM-grade slots
      that only ever hold CSPRNG secrets.)
   3. Enroll the TPM2 keyslot (PCR7) using the target's TPM,
      unlocking against the just-enrolled recovery slot.  The
      provisioning boot's PCR7 matches the installed system's:
      both are validated by the same db certificate under the
      same enrolled variable state (asserted by step 3).
   4. `mkfs.ext4` and seed /var inside the opened volume,
      applying SELinux labels from the in-UKI `file_contexts`
      (setfiles).  Unlabeled files on an enforcing first boot
      are this project's known M1 failure class; every file the
      installer creates on the target is labeled at creation.
   No plaintext unlock secret is ever staged on the target, in
   the dev OR the M6 (no-keyfile) profile.  TPM2-enroll failure
   (absent/not-ready TPM): interactive mode offers retry or
   accept-recovery-only (recorded in the report; the system will
   halt at a console passphrase prompt on every boot until a TPM2
   slot exists); headless mode aborts and marks the install
   failed unless the manifest explicitly opts into
   recovery-only.  The existing first-boot units
   (`lamadist-var-encrypt`, `lamadist-var-tpm2-enroll`) gain an
   installer-provisioned guard: when the volume is already
   formatted and TPM2-enrolled they skip format/enroll and only
   verify; ssh host keys and machine-id remain first-boot
   (section 6).
9. **Configure.**  Hostname and network settings are written into
   the installed system's `/etc` overlay upper (the rw-by-design
   class), labeled via the same setfiles step.
10. **Report, consume, reboot.**  The installer prints a summary
    (disk written, payload checksum, keyslots enrolled, trust
    gate result), appends it to the install log on the stick's
    PUBLIC partition (convenience telemetry ONLY -- the log has
    no integrity and is never an audit record), sets the
    install-consumed flag, and reboots into the installed system.

### 3.2 Headless flow

Identical pipeline, zero prompts.  Differences only:

- The manifest must be complete: hostname, network, target disk
  ID, a `CONFIRM` token that must exactly match the target disk
  ID, and explicit enrollment consent (`ENROLL=yes`) for the
  Setup-Mode branch.  Any missing, unknown, duplicate, or
  malformed field aborts before any write, with the reason on
  the console and in the stick log.
- Ordering note: because enrollment is userland-owned, manifest
  validation PRECEDES enrollment -- a garbage-manifest stick
  aborts before touching EFI variables.  (Under the demoted
  sd-boot auto-enroll fleet variant this ordering does not hold;
  that variant's ADR must state the firmware-state side effect.)
- The unlock password comes from a non-interactive source, in
  descending order of preference:
  1. `keyfile` on a second removable medium (the "key stick") --
     recommended.  The install stick alone remains inert.  The
     manual REQUIRES the two media to travel by separate
     transport/custody; shipped together they are equivalent to
     the inline downgrade below.
  2. `inline` password in a plaintext sidecar file on the stick's
     PUBLIC partition -- ACCEPTED DOWNGRADE: the stick becomes a
     self-unlocking secret-bearing item; a thief holding it gains
     the vault AND the recovery credential of the (single --
     requirement 2.4) target it installed.  The manual states
     this explicitly.  (The sidecar cannot live inside the
     vault -- it is what opens it.)
- Setup-Mode enrollment proceeds unattended only with manifest
  consent; any firmware state requiring manual action halts with
  instructions rather than guessing.

### 3.3 Failure semantics (both flows)

Every abort path satisfies: no block device other than the
selected target has been written (stick-media log/consumed-flag
exemption aside); the failure reason is on the console and
appended to the stick log; exit is to a shell only in interactive
mode (headless halts).  Distinct, individually tested abort
paths: wrong password; consumed stick; SB-off halt; trust-gate
digest mismatch (wrong-PK); tampered `.auth` payload; missing,
unknown-key, duplicate-key, and malformed manifest; disk-ID
mismatch; absent disk; payload checksum mismatch; TPM2-enroll
failure (headless, without the opt-in); write error.

## 4. Stick layout

| # | Partition   | FS     | Content and integrity model           |
|---|-------------|--------|---------------------------------------|
| 1 | ESP         | FAT32  | Signed installer UKI (integrity: SB   |
|   |             |        | signature) plus the UNSIGNED          |
|   |             |        | enrollment inputs (`.auth` payloads,  |
|   |             |        | loader config) whose integrity        |
|   |             |        | control is the in-UKI expected-hash   |
|   |             |        | check (3.1 steps 2-3)                 |
| 2 | PUBLIC      | FAT32  | Convenience manual copy (marked       |
|   |             |        | unverified), manifest schema + sample,|
|   |             |        | install log (forgeable telemetry),    |
|   |             |        | install-consumed flag, optional       |
|   |             |        | inline-password sidecar               |
| 3 | VAULT       | [AoA]  | OS image payload + SHA-256 sums +     |
|   |             |        | manifest + AUTHORITATIVE manual copy  |

Integrity chain (the vault is confidentiality-only -- LUKS2
aes-xts has no AEAD and ciphertext is malleable): payload SHA-256
sums ride inside the vault and are verified after decrypt, before
the write is declared good; a garbled manifest lands in the
strict-parse abort path; the installed system's durable integrity
is dm-verity anchored in its own signed UKI, independent of the
stick.  The PUBLIC manual copy is an unauthenticated instruction
channel and is treated as untrusted input to the human: portal
URLs and procedures are authoritative only in the vault copy and
pinned out-of-band (label/training); this is recorded in the
SECURITY.md extension.

The stick is provisioning media, not the appliance; Storage
Immutability Spec classes are applied by analogy for coherence,
not as compliance targets.  The installer userland lives entirely
in the signed UKI initramfs; there is no separate rootfs to
protect.  `[AoA: installer approach -- resolved by AOA-INSTALLER:
purpose-built initramfs in one signed UKI; size table includes
the tpm2, e2fsprogs, FAT, and SELinux-labeling tooling]`

## 5. Manifest schema (v1)

One line-oriented `manifest.env` file inside the vault.  The
YAML format of SPEC revision 1 is WITHDRAWN (review MAJOR-6): the
parser is a security boundary and must be trivially strict in the
installer's shell userland.  Rules, enforced by one named,
reviewed reader (`manifest-parse`):

- `KEY=VALUE`, one per line; `#` comments and blank lines only.
- Unknown key: abort.  Duplicate key: abort.  Value with
  characters outside its field's allowed set: abort.
- No line continuations, no quoting, no expansion of any kind.

```sh
MANIFEST_VERSION=1
HOSTNAME=node-01
NET_MODE=dhcp            # dhcp | static
NET_INTERFACE=auto       # auto | interface name
NET_ADDRESS=             # static only, CIDR
NET_GATEWAY=             # static only
NET_DNS=                 # static only, space-separated
TARGET_DISK=             # stable ID under /dev/disk/by-id
CONFIRM=                 # must equal TARGET_DISK exactly
UNLOCK_SOURCE=prompt     # prompt | keyfile | inline
UNLOCK_KEYFILE=          # keyfile: path on the key stick
ENROLL=                  # yes required for headless Setup-Mode
                         # enrollment
TPM_OPTIONAL=no          # yes = headless may complete
                         # recovery-only on TPM failure
HEADLESS=no              # yes requires TARGET_DISK, CONFIRM,
                         # and UNLOCK_SOURCE != prompt
```

The inline password, when used, lives NOT here but in the
public-partition sidecar (section 3.2); the manifest only selects
the source.  Interactive installs treat every manifest value as a
pre-fill the technician can override.

## 6. Secret model and provisioning windows

- **Issue:** Role A generates a >=128-bit CSPRNG per-stick
  password at stick creation and stores it in the secrets manager
  keyed by the stick's serial/label (collision-rejecting key
  normalization and retire-not-overwrite lifecycle per
  AOA-SECRETS).  The printed label on the stick matches the key.
  Locally the manager is fnox; the same object model scales to
  the portal (AT-SCALE.md).
- **One stick, one install (requirement 2.4):** a successful
  install consumes the stick; the flag is checked fail-closed at
  unlock.  Re-provisioning by Role A issues a FRESH password and
  rebuilds the vault, so each install's recovery credential is
  unique to that target.  At scale, install-consumed triggers
  rotation in the portal design.
- **Use at install:** the password opens the vault and is
  enrolled as the target's LUKS2 recovery keyslot (argon2id --
  section 3.1 step 8).
- **After install:** the recovery keyslot persists alongside the
  TPM2 keyslot.  Honest scope of this amendment (review MAJOR-2):
  it provides MANUAL recovery with console/physical access.  The
  crypttab MUST wire a console passphrase fallback so the
  recovery slot is actually reachable from the boot path; on a
  TPM failure an attended machine becomes console-recoverable
  instead of reboot-looping, but an UNATTENDED headless appliance
  still halts -- the W-b brick is narrowed, not closed.  Role B
  learns the password at install time and holds it until
  rotation; this exposure is recorded in the SECURITY.md
  extension.  Rotation (`cryptsetup luksChangeKey`) MUST use a
  fresh CSPRNG secret, never a human-chosen passphrase, and is a
  manual procedure in the operator manual.
- **Window model (Storage Immutability Spec class 2):** moved to
  the install window: LUKS2 format, recovery keyslot, TPM2
  keyslot, /var mkfs+seed.  Remaining first-boot: ssh host keys,
  machine-id.  First-boot units guard on installer-provisioned
  state (verify, don't re-format).  Footnote: on the very first
  install, "authenticated installer" is self-referential -- the
  authentication root is the enrollment the installer itself just
  performed; the custody/TOFU preconditions for that window are
  stated in the SECURITY.md extension (review MAJOR-7).
- **Forward compatibility:** the keyslot layout leaves room for a
  future Clevis+Tang+TPM2 binding with the Tang key pre-bound at
  install from vault-carried Tang public material (AT-SCALE.md;
  not built this pass).

## 7. Build definition

- New kas overlay producing `lamadist-installer-image` for the
  x86_64 target: installer UKI (kernel + initramfs userland,
  embedding expected-digest data and `file_contexts`), stick wic
  layout per section 4, vault creation and payload injection,
  manual rendering into the vault plus the PUBLIC convenience
  copy.
- The DEPLOYED image's loader configuration ships WITHOUT any
  enrollment directive and without a `\loader\keys\` payload: a
  deployed ESP can never re-enroll (review minor 4).
- The stick build consumes the ALREADY-BUILT hardened image
  artifact as its payload; it never rebuilds or modifies it
  (reproducibility boundary documented in the ADR: same payload
  in, byte-comparable stick out, modulo the unique vault key).
- One documented command builds the stick from a clean checkout.

## 8. Verification harness (Definition of Done)

Each item is a distinct, exit-0-checkable gate; the pass is done
when all are green in CI-style local runs.

1. Stage 1 (regression): the hardened base image still boots
   under QEMU+OVMF with SB enforcing (existing gate, reused).
2. Stage 2 (trust): `sbverify` passes against the installer UKI;
   the enrollment stage is exercised in QEMU across the full
   state machine: (a) blank-vars Setup Mode -> userland enroll ->
   reboot -> `SecureBoot=1` and digest-gate pass; (b) SB-off
   non-Setup-Mode varstore -> fail-closed halt; (c) wrong-PK
   varstore (attacker PK + our db cert) -> digest-gate halt;
   (d) tampered on-ESP `.auth` payload -> pre-enrollment halt.
3. Stage 3 (secrets): vault unlock succeeds with the fnox-issued
   password and fails closed (no target write) with a wrong
   password; after install, the target's LUKS2 data partition
   opens via the argon2id recovery slot AND the TPM2 path;
   `cryptsetup luksDump` shows the specified per-keyslot KDFs;
   dm-verity on the installed root is anchored in the signed UKI
   cmdline (existing assertion, re-run on the installed disk);
   installed files created by the installer carry correct SELinux
   labels (spot-check via `ls -Z` in the smoke).
4. Stage 4 (medium): the stick image boots in QEMU as USB
   mass-storage; the PUBLIC partition mounts on a host and
   contains the convenience manual, schema, and sample; the ESP
   contains the signed UKI plus ONLY the named unsigned
   enrollment inputs, each matching the in-UKI expected hashes.
5. Stage 5 (interactive): a scripted serial-console session
   drives the full prompt flow against a blank virtual disk; the
   machine reboots into the installed, signed, encrypted system
   and passes the existing hardened smoke.
6. Stage 5 (headless): the same result from a complete manifest +
   keyfile with zero console input; plus the full section 3.3
   abort matrix, each case fail-closed with the right diagnostic
   and an untouched second virtual disk; plus the consumed-stick
   re-run refusal.
7. Docs: SPEC.md (this file) CURRENT; three AoA tables; ADR(s)
   recorded; SECURITY.md extended with the installer attack
   surface (custody/TOFU preconditions, Role-B credential
   exposure, manual-as-untrusted-input, forgeable install log);
   AT-SCALE.md exists as design-only.

## 9. Out of scope (this pass)

Batch/fleet flashing; the at-scale portal and device-enrollment
implementation (design-only in AT-SCALE.md); real-hardware
provisioning; ARM installer (ports with M5 -- the enrollment
stage is the only x86-specific piece); Clevis+Tang enrollment
(design note only); rotation tooling for recovery keyslots
(manual procedure documented, tooling later); the sd-boot
auto-enroll fleet variant (named in the signing ADR, not built).
