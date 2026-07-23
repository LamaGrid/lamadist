# LamaDist USB Installer -- SPEC

**Status:** DRAFT -- becomes CURRENT only after the three AoAs land
as ADRs and the security-critical design (per-USB secret model,
signing/enrollment model, at-scale portal, device-enrollment flow)
passes its Fable security review.  Sections marked `[AoA: ...]`
are contractual slots filled by an ADR, not open questions.

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
   full chain validating.  `[AoA: chain shape -- shim+MOK vs.
   existing custom PK/KEK/db vs. sbctl-managed]`
2. The installer never writes any block device other than the one
   operator-selected target disk.  All ambiguity resolves to
   abort-without-writing (fail-closed).
3. The stick's OS image payload and manifest are encrypted at
   rest inside the vault; unlocking requires the per-stick
   password.
4. The per-stick password is unique to the stick and is issued
   and stored through the secrets manager.
5. Install-time input is minimal: hostname, network settings, and
   the unlock password.  Target-disk selection is input in
   interactive mode and manifest-supplied in headless mode.
6. Every setting is also expressible in the manifest; a complete
   manifest yields a fully headless install with zero interactive
   input.
7. The stick carries the operator manual, readable on any machine
   without unlocking the vault.
8. Secure Boot key enrollment is automated where firmware state
   permits; otherwise the flow presents in-line technician
   instructions, and the same instructions ship in the on-stick
   manual.

## 3. User flow

The user flow is the primary deliverable; recipes serve it.

### 3.1 Interactive flow

1. **Boot.**  Technician selects the stick in the firmware boot
   menu.  The installer boots as a signed UKI (kernel + installer
   userland in the initramfs), so the entire installer
   environment is covered by one Secure Boot signature.
2. **Enrollment stage.**  The installer inspects `SecureBoot` and
   `SetupMode` EFI variables:
   - Firmware already trusts the installer chain: skip ahead.
   - Firmware in Setup Mode: enroll the platform keys
     automatically (unauthenticated enrollment is permitted in
     Setup Mode), prompt for confirmation, reboot, continue.
   - Secure Boot on, chain untrusted (installer refused to boot):
     this state is unreachable in-flow by definition; it is
     covered by the manual's pre-boot section ("enter firmware
     setup, clear to Setup Mode or enroll keys, retry").
   `[AoA: chain shape determines whether this stage is MOK
   enrollment under shim or PK/KEK/db enrollment]`
3. **Unlock.**  Prompt for the per-stick password (obtained by
   Role B from the secrets manager).  Three attempts; on
   exhaustion, halt with a diagnostic.  Nothing has been written.
4. **Settings.**  If the vault contains a manifest, it pre-fills
   all prompts; the technician confirms or overrides.  Otherwise
   prompt for: hostname, network mode (dhcp | static + address /
   gateway / DNS), and target disk.
5. **Disk selection.**  Enumerate fixed disks by stable ID
   (`/dev/disk/by-id`), excluding the stick itself and any medium
   holding an unlock keyfile.  Display ID, model, size.  The
   technician selects, then types an explicit confirmation phrase
   containing the disk ID.  Anything else aborts.
6. **Write.**  Stream the payload to the selected disk
   (bmaptool-style sparse-aware write with checksum
   verification).  A write failure aborts loudly; partial writes
   are called out as leaving the target unbootable but no OTHER
   disk is ever touched.
7. **Provision.**  The installer performs the LUKS2 format of the
   data partition and enrolls the per-stick password as the
   recovery keyslot, then stamps the installed system's
   first-boot provisioning to add the TPM2-sealed keyslot on
   first boot (PCR7) while RETAINING the recovery keyslot.  See
   section 6 for the write-once window rationale.
8. **Configure.**  Hostname and network settings are written into
   the installed system's `/etc` overlay upper (the rw-by-design
   class), not into the immutable lower.
9. **Report and reboot.**  The installer prints a summary (disk
   written, payload checksum, keyslots enrolled, enrollment stage
   outcome), appends it to an install log on the stick's public
   partition, and reboots into the installed system.

### 3.2 Headless flow

Identical pipeline, zero prompts.  Differences only:

- The manifest must be complete: hostname, network, target disk
  ID, and a `confirm` token that must exactly match the target
  disk ID.  Any missing or mismatched field aborts before any
  write, with the reason on the console and in the stick log.
- The unlock password comes from a non-interactive source, in
  descending order of preference:
  1. `keyfile` on a second removable medium (the "key stick") --
     recommended; the install stick alone remains inert.
  2. `inline` password in a plaintext sidecar file on the stick's
     public partition -- ACCEPTED DOWNGRADE: the stick becomes a
     self-unlocking secret-bearing item and must be handled as
     such.  The manual states this explicitly.  (The sidecar
     cannot live inside the vault -- it is what opens it.)
- Enrollment stage: Setup Mode auto-enrollment proceeds
  unattended; if the firmware state requires manual action the
  headless install halts with instructions rather than guessing.

### 3.3 Failure semantics (both flows)

Every abort path satisfies: no block device other than the
selected target has been written; the failure reason is on the
console and appended to the stick log; exit is to a shell only in
interactive mode (headless halts).  Wrong password, missing
manifest fields, disk-ID mismatch, absent disk, payload checksum
mismatch, and write errors are all distinct, tested abort paths.

## 4. Stick layout

| # | Partition   | FS     | Class (Storage Immutability Spec)     |
|---|-------------|--------|---------------------------------------|
| 1 | ESP         | FAT32  | Immutable-intent: sole content is the |
|   |             |        | signed installer UKI (+ shim/loader   |
|   |             |        | per AoA); integrity = SB signature    |
| 2 | PUBLIC      | FAT32  | rw-by-design: operator manual         |
|   |             |        | (HTML + Markdown + printable          |
|   |             |        | one-pager), manifest schema + sample, |
|   |             |        | install log (appended by installs),   |
|   |             |        | optional inline-password sidecar      |
| 3 | VAULT       | [AoA]  | Confidentiality layer: OS image       |
|   |             |        | payload (`.wic.xz` + `.bmap` +        |
|   |             |        | SHA-256 sums) and the manifest        |

Notes:

- The stick is provisioning media, not the appliance; classes are
  applied by analogy for coherence, not as compliance targets.
- The PUBLIC partition carries no secrets (except the documented
  inline-password downgrade) and no integrity guarantee; a
  tampered manual is a residual risk noted in the SECURITY.md
  extension.  The payload's integrity does not depend on the
  stick: checksums ride inside the vault, and the installed
  system self-verifies via dm-verity anchored in its signed UKI.
- The installer userland lives entirely in the signed UKI
  initramfs; there is no separate rootfs squashfs to protect.
  `[AoA: installer approach must confirm size feasibility]`

## 5. Manifest schema (v1)

One YAML file, `manifest.yaml`, inside the vault.  Unknown keys
are an error (fail-closed).

```yaml
version: 1
hostname: node-01
network:
  mode: dhcp            # dhcp | static
  interface: auto       # auto | explicit interface name
  address: null         # static only, CIDR
  gateway: null         # static only
  dns: []               # static only
target:
  disk: null            # stable ID under /dev/disk/by-id
  confirm: null         # must equal target.disk exactly
unlock:
  source: prompt        # prompt | keyfile | inline
  keyfile: null         # keyfile: path on the key stick
headless: false         # true requires target.* + unlock.source
                        # != prompt
```

The inline password, when used, lives NOT here but in the
public-partition sidecar (section 3.2); the manifest only selects
the source.  Interactive installs treat every manifest value as a
pre-fill the technician can override.

## 6. Secret model and provisioning windows

- **Issue:** Role A generates a high-entropy per-stick password at
  stick creation and stores it in the secrets manager keyed by
  the stick's serial/label; the printed label on the stick
  matches the key.  Locally the manager is fnox; the same object
  model scales to the portal (AT-SCALE.md).
- **Use at install:** the password opens the vault, and (section
  3.1 step 7) is enrolled as the LUKS2 recovery keyslot on the
  target's data partition.
- **After install:** the recovery keyslot persists alongside the
  TPM2-sealed keyslot.  This deliberately amends the M4
  TPM2-only posture: it closes the known first-boot brick path
  (slow/absent TPM with no fallback) and bounds exposure to one
  stick's fleet-unique password.  Rotation of the recovery slot
  is an operational procedure in the manual.
- **Window shift:** the LUKS format + recovery-slot enrollment
  moves from the target's first boot into the install step; first
  boot only ADDS the TPM2 keyslot.  Under the Storage
  Immutability Spec this narrows the write-once window (class 2)
  and avoids staging any plaintext secret on the target disk
  between install and first boot.  The Storage Immutability Spec
  wording gains "install-time provisioning by the authenticated
  installer" as part of the guarded write-once window.
- **Forward compatibility:** the keyslot layout must leave room
  for a future Clevis+Tang+TPM2 binding where the Tang key is
  bound ahead of time (a further keyslot enrolled at install from
  vault-carried Tang public material).  Design note in
  AT-SCALE.md; not built this pass.

This section is subject to the mandated Fable security review
before the SPEC leaves DRAFT.

## 7. Build definition

- New kas overlay producing `lamadist-installer-image` for the
  x86_64 target: installer UKI (kernel + initramfs userland),
  stick wic layout per section 4, vault creation and payload
  injection, manual rendering onto PUBLIC.
- `[AoA: installer approach -- meta-anaconda vs. meta-intel image
  installer vs. minimal initramfs + bmaptool/dd + systemd-repart]`
- The stick build consumes the ALREADY-BUILT hardened image
  artifact as its payload; it never rebuilds or modifies it
  (reproducibility: same payload in, byte-comparable stick out,
  modulo the unique vault key -- the reproducibility boundary is
  documented in the ADR).
- One documented command builds the stick from a clean checkout.

## 8. Verification harness (Definition of Done)

Each item is a distinct, exit-0-checkable gate; the pass is done
when all are green in CI-style local runs.

1. Stage 1 (regression): the hardened base image still boots
   under QEMU+OVMF with SB enforcing (existing gate, reused).
2. Stage 2: `sbverify` passes against the installer UKI (and
   loader/shim per AoA); the enrollment stage is exercised in
   QEMU by booting OVMF in Setup Mode with BLANK vars and
   asserting the installer enrolls keys, reboots, and continues
   with `SecureBoot=1`.
3. Stage 3: vault unlock succeeds with the fnox-issued password
   and fails closed (no target write) with a wrong password;
   after install, the target's LUKS2 data partition opens with
   the recovery password AND via the TPM2 path after first boot;
   dm-verity on the installed root is anchored in the signed UKI
   cmdline (existing assertion, re-run on the installed disk).
4. Stage 4: the stick image boots in QEMU as a USB mass-storage
   device; the PUBLIC partition mounts on a host and contains
   the manual and manifest schema; the ESP contains only signed
   artifacts.
5. Stage 5 (interactive): a scripted serial-console session
   drives the full prompt flow against a blank virtual disk;
   the machine reboots into the installed, signed, encrypted
   system and passes the existing hardened smoke.
6. Stage 5 (headless): the same result from a complete manifest
   + keyfile with zero console input; plus the abort matrix
   (wrong password, disk-ID mismatch, incomplete manifest,
   checksum mismatch) each abort fail-closed with the right
   diagnostic and an untouched second virtual disk.
7. Docs: SPEC.md (this file) CURRENT; three AoA tables; ADR(s)
   recorded; SECURITY.md extended with the installer attack
   surface; AT-SCALE.md exists as design-only.

## 9. Out of scope (this pass)

Batch/fleet flashing; the at-scale portal and device-enrollment
implementation (design-only in AT-SCALE.md); real-hardware
provisioning; ARM installer (ports with M5 -- the enrollment
stage is the only x86-specific piece); Clevis+Tang enrollment
(design note only); rotation tooling for recovery keyslots
(manual procedure documented, tooling later).
