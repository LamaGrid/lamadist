# AoA: Installer Approach

**Status:** DRAFT -- fills the `[AoA: installer approach]` slots in
`docs/installer/SPEC.md` (sections 4 note, 7).  Becomes an ADR on
acceptance.  Decision here is a prerequisite for the SPEC leaving
DRAFT and for the mandated Fable security review.

**Scope:** One installer USB image artifact, built by kas/bitbake,
verified exclusively under QEMU+OVMF with Secure Boot enforcing
(SPEC section 8).  This AoA selects the mechanism that produces the
installer environment; it does not re-open the vault, secret, or
chain-shape AoAs.

**Decision priority (inherited from SPEC):** non-destructiveness >
Secure Boot integrity > reproducibility > image size.

## 1. Options

- **Option A -- meta-anaconda.**  The existing
  `kas/installer.kas.yml` scaffold: a separate `anaconda` distro
  and `core-image-anaconda` target driven by a kickstart file, with
  SELinux stripped and a `KICKSTART_FILE` TODO.
- **Option B -- meta-intel image installer.**  The
  `image-installer.wks.in` live-install path, which is a thin wic
  wrapper over oe-core's `initramfs-module-install-efi`
  (`init-install-efi.sh`).
- **Option C -- purpose-built initramfs in one signed UKI.**  A
  minimal installer userland (busybox + cryptsetup + a payload
  writer + sfdisk + a small TUI) carried in the initramfs of a
  single Secure-Boot-signed UKI, built with the same
  `lamadist-uki.bbclass` + `initramfs-framework` machinery the
  A/B boot path already uses.  This is the shape the SPEC presumes
  (sections 3.1 step 1, 4 note).

## 2. Verified starting facts

- `ext/meta-anaconda` is **not cloned**; the scaffold points at the
  `whinlatter` branch as a documented Wrynose-migration exception.
  meta-anaconda strips `selinux` from `DISTRO_FEATURES` (scaffold
  TODO) and expects a raw rootfs artifact
  (`INSTALLER_TARGET_BUILD = ...secure-core-image...ext4`), not the
  hardened `.wic.xz` + `.bmap` payload the SPEC ships.
- `ext/meta-intel` **is** cloned.  Its only installer asset is
  `files/wic/image-installer.wks.in`, which carries no logic; the
  behavior comes from oe-core's `init-install-efi.sh` (304 lines,
  MIT).  That script does a whole-disk `dd`/`cp` of a rootfs plus a
  GRUB/systemd-boot menu edit.  It knows nothing of vaults, LUKS
  provisioning, manifests, disk-ID confirm tokens, or SB key
  enrollment.
- The A/B boot path already builds a signed UKI whose initramfs is
  `initramfs-framework` (busybox) plus a custom dm-verity module
  (`lamadist-uki.bbclass`, `initramfs-framework-dm/dmverity`).
  `ukify build --initrd=... --sign-kernel` is already wired.  The
  target image already carries cryptsetup, device-mapper, systemd,
  and the TPM2 stack.
- Tool availability (verified in the layer stack): `dialog`
  (LGPL-2.1-only), `bmaptool` 3.9.0 (GPL-2.0-only, Python),
  `bmap-writer` 1.0.4 (GPL-3.0-only, C++), `sfdisk`/`blkid`
  (util-linux), `efibootmgr`/`efivar`, and systemd-boot 259.5
  (which has a built-in `secure-boot-enroll` that reads signed
  `.auth` files -- PK self-signed, KEK signed by PK, db signed by
  KEK, NOT bare ESLs -- from the ESP `\loader\keys\` -- LGPL-2.1;
  this is the demoted fleet-variant path per AOA-SIGNING, not the
  rev-2 primary enrollment).

## 3. Assessment matrix

Scores: ++ strong fit, + adequate, o neutral/unknown, - friction,
-- disqualifying.  Weighted by the SPEC priority order.

| Criterion (SPEC ref)                | A meta-anaconda | B meta-intel | C initramfs UKI |
|-------------------------------------|-----------------|--------------|-----------------|
| Single-UKI size feasibility (4)     | -- (Python/NM)  | + (small)    | ++ (small)      |
| Non-destructive fail-closed (2, 3.3)| o (custom %pre) | - (dd-only)  | ++ (we own it)  |
| Secure Boot signing of installer (1)| - (many PEs)    | + (1 UKI)    | ++ (1 UKI)      |
| Vault/LUKS provisioning fit (3, 6)  | - (bolt-on)     | -- (none)    | ++ (native)     |
| Manifest flow fit (5, 6)            | - (kickstart)   | -- (none)    | ++ (env own)    |
| Minimal 3-input UI (3.1)            | - (anaconda UI) | o (none)     | ++ (dialog/read)|
| SELinux posture (context)           | -- (stripped)   | o            | + (SB+labeled)  |
| Buildability from kas/meta-lamadist | - (new distro)  | o (wks only) | ++ (reuse UKI)  |
| Section 8 harness testability       | - (fragile UI)  | + (scripted) | ++ (scripted)   |
| Maintenance burden                  | -- (track anac.)| + (stable)   | + (in-repo)     |
| License cleanliness                 | - (GPL+Python)  | ++ (MIT/GPL2)| + (weak+notes)  |

### 3.1 Option A -- meta-anaconda

- **Dependency weight.**  Anaconda is a full graphical/text OS
  installer: it pulls Python 3, `pykickstart`, `blivet`,
  NetworkManager, `libreport`, and a large support stack into the
  install environment.  That is tens of megabytes of runtime that
  do not fit the SPEC's "installer userland entirely in the signed
  UKI initramfs" note, and it cannot be a single self-contained UKI
  in any realistic size budget.  meta-anaconda's normal shape is a
  live rootfs the initramfs pivots into, i.e. a second protected
  filesystem -- exactly the "separate rootfs squashfs to protect"
  the SPEC says it does not want (section 4 note).
- **Kickstart vs. the manifest.**  Kickstart is anaconda's
  declarative language for traditional partition/package/user
  installs.  The SPEC's install is not that shape: it is "open a
  LUKS2 vault with a per-stick password, verify a checksum, write a
  pre-built signed `.wic.xz` to one confirmed disk, enroll a LUKS2
  recovery keyslot, stamp first-boot TPM2 provisioning."  Anaconda
  has no native primitive for any of that; it would all live in
  `%pre`/`%post` shell, making anaconda a heavyweight wrapper around
  the same shell logic Option C runs directly.  The SPEC manifest
  (a strict `KEY=VALUE` `manifest.env`, unknown-keys-fail-closed,
  disk-ID confirm token) would have to be translated into kickstart
  or bypassed -- either way the
  SPEC's own schema stops being the contract the installer reads.
- **SELinux friction.**  The scaffold does
  `DISTRO_FEATURES:remove = ' selinux'` because the anaconda install
  environment is not covered by the project's enforcing policy.
  That is a posture regression the whole M4 hardening line exists to
  avoid, and "create an SELinux policy for the installer" is an open
  TODO of unbounded size.
- **UI model.**  Anaconda's text UI (newt-based) cannot honor a
  "minimal three-input" flow without fighting the framework; driving
  it from a scripted serial console (SPEC section 8 stage 5) is
  brittle relative to a purpose-built prompt sequence.

**Verdict:** poor fit on the top three priorities.  The scaffold's
value was to prove the kas-overlay mechanics; it should be retired,
not grown.

### 3.2 Option B -- meta-intel image installer

- **What it actually is.**  Not an installer layer -- a single wks
  file (`image-installer.wks.in`) that composes oe-core's
  `initramfs-live-install-efi` (`init-install-efi.sh`).  meta-intel
  adds nothing installer-specific beyond that wks; the logic is
  oe-core's, and it is generic across BSPs.
- **Maintenance state.**  The oe-core live-install path is old and
  stable (MIT), but minimal: interactive `dd` of a rootfs to a
  chosen disk, then a bootloader menu rewrite.  It has no vault, no
  manifest, no checksum gate, no LUKS provisioning, and no SB key
  enrollment.
- **Fit.**  Meeting the SPEC means rewriting `init-install-efi.sh`
  substantially -- at which point the result is Option C with a
  meta-intel wks stapled on.  meta-intel also implies an
  Intel-specific BSP framing that the SPEC explicitly rejects
  ("generic x86_64 UEFI ... no vendor-specific assumptions",
  section 1).

**Verdict:** the reusable core (`init-install-efi.sh`) is a useful
*reference* for Option C's disk-write and confirm-prompt scaffolding,
but adopting meta-intel as the approach buys nothing the SPEC needs
and adds a vendor layer it does not want.

### 3.3 Option C -- purpose-built initramfs in one signed UKI

- **Shape.**  One `lamadist-installer.efi` UKI = kernel + microcode
  + an installer initramfs, signed by the same sb-dev chain and
  `ukify` invocation the A/B UKIs already use.  The initramfs
  carries only tooling; the OS image payload lives in the VAULT
  partition (SPEC section 4), so the initramfs stays small and the
  payload is never inside the signed PE.
- **Buildability.**  Highest reuse.  `lamadist-uki.bbclass` already
  turns `INITRAMFS_IMAGE` + kernel into a signed UKI; the installer
  is a second `INITRAMFS_IMAGE` recipe (busybox + an
  `initramfs-framework` "installer" module implementing the SPEC
  flow) plus a stick `.wks` for the three-partition layout.  No new
  distro, no new external installer layer to track.  The build
  consumes the already-built hardened `.wic.xz` as an opaque vault
  payload (SPEC section 7), preserving the reproducibility boundary.
- **Non-destructiveness.**  We own every write.  The disk
  enumeration (`/dev/disk/by-id`, exclude stick + keyfile media),
  the confirm-token check, and the abort-before-write matrix (SPEC
  3.3) are explicit shell in one module -- directly auditable, and
  the exact set section 8 stage 5-headless tests.
- **Testability.**  A single signed UKI makes `sbverify` (stage 2)
  trivial.  The prompt flow is busybox/`dialog` over the serial
  console, driven by `expect` for interactive runs (stage 5), and
  the same module reads `manifest.env` through the named
  `manifest-parse` reader for the zero-input headless run (stage
  5-headless).  `manifest-parse` is the strict line-oriented
  `KEY=VALUE` reader (unknown key => abort, duplicate key => abort,
  no quoting/expansion of any kind) mandated after the YAML format
  was withdrawn (review MAJOR-6); it is a reviewed security-boundary
  component because every headless abort property flows through it.
  QEMU boots the stick as USB mass storage (stage 4) with no special
  support.
- **SELinux.**  An initramfs runs before policy load by design (the
  running system loads policy at switch-root); the existing
  dm-verity boot initramfs already runs this way.  The installer
  never switch-roots into a running target -- it writes and reboots
  -- so running unlabeled inside a Secure-Boot-signed initramfs is
  consistent with the current posture, not a regression.  There is
  no "installer distro with selinux stripped."  What the initramfs
  running unlabeled does NOT excuse is the files it writes ONTO the
  target: those land on a filesystem whose first boot is enforcing,
  and an unlabeled file there is this project's own M1 brick class
  ("boots but unusable", every exec denied).  The installer
  therefore carries the policy's `file_contexts` inside the signed
  UKI and labels every target file it creates at creation time
  (`/var` seed, `/etc` overlay upper) with `setfiles`; see the
  labeling note under section 4 (review MAJOR-4).
- **Maintenance.**  All logic is small in-repo shell in
  `initramfs-framework` modules against stable tools (busybox,
  cryptsetup, util-linux, systemd-boot).  We carry it, but there is
  no upstream installer to chase.

**Verdict:** matches the SPEC's presumed shape on every top-priority
criterion.

## 4. Single-UKI size feasibility (confirming the SPEC note)

The SPEC (section 4 note) asserts the installer userland fits
entirely in the signed UKI initramfs.  **Confirmed.**  The payload
is NOT in the initramfs (it is in the vault); the initramfs carries
only tooling.  Estimate below is a glibc, busybox-based userland
reusing the existing `initramfs-framework` pattern (NOT a full
systemd-in-initramfs), installed size (uncompressed rootfs):

| Component (role)                          | Approx installed | New dep? |
|-------------------------------------------|------------------|----------|
| glibc runtime (libc/ld/libm/nss/resolv)   | ~9 MB            | no       |
| busybox (sh, dd, sha256sum, mount, etc.)  | ~1.0 MB          | no       |
| `initramfs-framework` + installer module  |                  |          |
| (incl. `manifest-parse` reader)           | ~90 KB           | no       |
| cryptsetup + libcryptsetup/devmapper/     |                  |          |
| json-c/argon2/popt (LUKS format+addkey)   | ~4 MB            | no*      |
| util-linux `sfdisk`/`blkid` + libblk/uuid | ~2 MB            | no*      |
| device-mapper `dmsetup`                    | ~0.5 MB          | no*      |
| liblzma/libzstd (decompress `.wic.xz`)    | ~0.3 MB          | no       |
| tpm2-tss + `systemd-cryptenroll`          |                  |          |
| (install-time TPM2 keyslot enroll)        | ~5 MB            | yes      |
| policycoreutils `setfiles` + libselinux/  |                  |          |
| libsepol/pcre2 + `file_contexts`          | ~2.5 MB          | yes      |
| e2fsprogs `mkfs.ext4` + libext2fs/libe2p/ |                  |          |
| libcom_err (/var seed filesystem)         | ~1.8 MB          | no*      |
| `efibootmgr` + `efivar`/libefivar         | ~0.4 MB          | maybe    |
| `dialog` + libncursesw (TUI; optional)    | ~0.7 MB          | yes      |
| **Total userland (excl. kernel)**          | **~27 MB**       |          |
| xz/zstd-compressed initramfs (~40%)       | **~11-13 MB**    |          |
| kernel + microcode (shared with A/B UKI)  | ~12-15 MB        | no       |
| **Signed UKI on ESP**                      | **~25-30 MB**    |          |

\* Present in the target image already; here they are pulled into
the installer initramfs recipe rather than shipped on target.  No
FAT userland is added: the PUBLIC log append (SPEC 3.1 step 10)
writes to the stick's already-formatted vfat PUBLIC partition
through the kernel's `vfat` write path, so it needs no `mkfs.vfat`
and avoids `dosfstools`/`mtools` entirely (see licenses).

Notes on the estimate:

- **glibc dominates.**  A musl variant would cut ~7-8 MB but the
  distro is glibc; not worth diverging for the installer alone.
- **TPM2 stack IS required in the installer (retraction).**  SPEC
  revision 1 said the installer enrolls only the LUKS2 recovery
  keyslot and left the TPM2-sealed keyslot for the target's first
  boot.  Review BLOCKER-1 showed that is unsolvable: enrolling a
  TPM2 keyslot on first boot needs an existing credential to prove,
  and staging no secret leaves first boot with nothing to unlock
  against (the M6 no-keyfile profile then bricks).  Rev 2 moves FULL
  provisioning into the installer, so the installer now formats the
  LUKS2 volume, enrolls the argon2id recovery keyslot, AND enrolls
  the TPM2 (PCR7) keyslot against the target's own TPM at install
  time (SPEC 3.1 step 8).  That REQUIRES the TPM2 stack in the
  initramfs; the earlier "no TPM2 stack needed" claim is withdrawn
  and the size table above now carries it (~5 MB).  Path chosen:
  **tpm2-tss + `systemd-cryptenroll`**, NOT tpm2-tools.  Rationale:
  the installed target unlocks `/var` via systemd-cryptsetup with
  `tpm2-device=auto`, which consumes a systemd-format LUKS2 TPM2
  token; only `systemd-cryptenroll` writes exactly that token, so it
  guarantees the enrolled slot is the one the target can open.  Its
  net weight is lighter than the tpm2-tools alternative once
  compatibility is accounted for: `systemd-cryptenroll` reuses the
  `libcryptsetup` already present and needs only tpm2-tss beneath
  it, whereas a tpm2-tools path would additionally have to ship
  Clevis or a hand-rolled token writer to produce a systemd-openable
  token.  (A small subset of systemd rides along with
  `systemd-cryptenroll`; this is the one systemd component the
  otherwise busybox initramfs pulls in, and it is scoped to the
  enroll step.)
- **No networking stack needed.**  The installer writes network
  config into the target's `/etc` overlay (SPEC 3.1 step 8); it does
  not bring up networking itself, so no dhcp client / NM.
- **Payload writer.**  busybox `dd` + `sha256sum` (a streaming
  decompress-and-write with checksum verify, SPEC 3.1 step 6) needs
  no new binary.  `bmap-writer` (~0.2 MB) would add sparse-aware
  speed but is a new GPL-3.0 shipped binary (see licenses).
- **SELinux labeling of target files (MAJOR-4).**  The installer
  initramfs runs unlabeled, but every file it CREATES on the target
  lands on a filesystem whose first boot is enforcing; unlabeled
  files there are the M1 brick class.  The signed UKI therefore
  carries the policy's `file_contexts`, and the installer labels
  each file it writes at creation.  Tool evaluated two ways:
  - **`setfiles` (policycoreutils) -- recommended.**  It is the
    canonical consumer of `file_contexts`, applying the same
    longest-match regex-spec semantics the on-target relabel uses,
    so the labels the installer stamps are bit-identical to what a
    first-boot `restorecon` would produce.  Cost is `setfiles` plus
    libselinux/libsepol/pcre2 (~2.5 MB, in the table).
  - **A minimal `setfattr`-based applier -- rejected.**  Writing
    `security.selinux` xattrs directly with `setfattr` (attr,
    ~0.1 MB) is far smaller, but it forces us to reimplement
    `file_contexts` longest-match resolution in busybox shell.  That
    reimplementation is itself a security boundary: a mismatched
    label is the same wrong-state failure MAJOR-4 is about, and the
    installer's write set is exactly the files whose labels matter.
    The ~2.4 MB saved is not worth hand-rolling context matching, so
    `setfiles` wins.
- **/var seed filesystem.**  The full provisioning now does
  `mkfs.ext4` for the target `/var` inside the opened LUKS2 volume
  (SPEC 3.1 step 8), so e2fsprogs (`mkfs.ext4` + libext2fs) joins
  the initramfs (~1.8 MB, in the table); the seed files are then
  `setfiles`-labeled as above.  No FAT userland is added for the
  PUBLIC install-log append -- that partition already exists and is
  written through the kernel `vfat` path (see the table note and
  licenses), so `dosfstools`/`mtools` stay out.
- **SB key enrollment.**  PRIMARY enrollment is userland from the
  signed initramfs (SPEC 3.1 step 2; AOA-SIGNING B2): the installer
  validates the manifest, owns the confirmation prompt, runs the
  in-UKI PK/KEK/db digest + `SecureBoot=1` gate, and writes the
  signed `.auth` payloads directly to efivarfs (`chattr -i` + write)
  -- **PK self-signed, KEK signed by PK, db signed by KEK**, never
  bare ESLs.  That path needs no new binary (`efivar`/`efibootmgr`
  cover variable and boot-entry work at low cost) and ships no GPL-3
  enrollment tool.  systemd-boot 259.5's built-in
  `secure-boot-enroll` -- which reads those same signed `.auth`
  files from the ESP `\loader\keys\` -- is now DEMOTED to an
  explicitly-chosen fleet variant (review MAJOR-5) and is NOT built
  this pass; when a fleet chooses it, it is governed by AOA-SIGNING.

The recommended shape stays busybox-based for continuity with the
existing boot initramfs; it pulls in `systemd-cryptenroll` (with its
tpm2-tss dependency) for the install-time TPM2 keyslot ONLY, not
full systemd.  Even so, the rev-2 provisioning move roughly halves
the earlier headroom: ~27 MB installed / ~11-13 MB compressed / a
~25-30 MB signed UKI, versus rev 1's ~18 MB / ~7-9 MB / ~20-24 MB.
A full-systemd-in-initramfs variant (adding the rest of systemd and
`systemd-repart`) would land around ~35-45 MB installed / ~18-22 MB
compressed / a ~35 MB UKI.  Both remain within a FAT32 ESP and
systemd-boot's UKI handling, so the SPEC section 4 single-UKI note
still holds -- but with materially less margin than rev 1 claimed,
which the size table above now reflects honestly.

## 5. License analysis

Per project policy (permissive preferred; copyleft needs a note;
strong copyleft needs explicit approval -- ADR 0002..0005 format):

- **Reused, already-precedented / already-shipped:** busybox
  (GPL-2.0), cryptsetup (GPL-2.0+ with OpenSSL exception),
  util-linux (GPL-2.0/LGPL), glibc (LGPL-2.1+), systemd/systemd-boot
  and `systemd-cryptenroll` (LGPL-2.1+), tpm2-tss (BSD-2-Clause).
  These already ship in the target or build; pulling them into the
  installer initramfs adds no new obligation.  `systemd-cryptenroll`
  + tpm2-tss are now in the installer (rev-2 install-time TPM2
  enroll, BLOCKER-1); tpm2-tss is permissive, `systemd-cryptenroll`
  is the same LGPL systemd already precedented.
- **New, weak copyleft -- note only:** `dialog` (LGPL-2.1-only) for
  the TUI.  LGPL, build/runtime, dynamically linked; a one-line note
  in the resulting ADR suffices.  Can be avoided entirely with plain
  busybox `read` prompts if a zero-new-dep installer is preferred.
- **New, weak/permissive copyleft -- note only (rev-2 tooling):**
  - e2fsprogs `mkfs.ext4` + libext2fs (GPL-2.0 tools / LGPL-2.0
    libs) for the `/var` seed filesystem (Minor 8, BLOCKER-1).
    Build/runtime; one-line note.
  - policycoreutils `setfiles` (GPL-2.0) with libselinux (public
    domain), libsepol (LGPL-2.1), and pcre2 (BSD) for install-time
    SELinux labeling (MAJOR-4).  The only GPL-2.0 piece is the
    `setfiles` tool; a one-line note in the ADR covers it.  This is
    a deliberate correctness-over-size choice (a `setfattr`/attr
    applier is smaller and non-copyleft but reimplements the
    label-matching boundary -- see section 4).
  - `manifest-parse` (MAJOR-6) is in-repo installer code under this
    project's own license; no third-party obligation, but it is
    called out as a reviewed security-boundary component, not a
    throwaway.
- **Deliberately AVOIDED -- strong copyleft, kept out:**
  `dosfstools`/`mtools` (GPL-3.0) for FAT handling of the PUBLIC
  log append.  Not needed: the PUBLIC partition is pre-formatted and
  the append rides the kernel `vfat` write path with no userland
  `mkfs.vfat`.  Flagged explicitly so the GPL-3.0 tool is not pulled
  in by reflex later; if a future need does require it, it takes the
  strong-copyleft approval step per policy.
- **Optional, strong copyleft -- would need explicit approval:**
  - `bmap-writer` 1.0.4 (GPL-3.0-only) shipped in the initramfs,
    OR `bmaptool` 3.9.0 (GPL-2.0-only, but drags in the Python
    runtime -- a large size hit).  Both are avoidable: busybox
    `dd` + `sha256sum` meets SPEC 3.1 step 6 with no new dependency.
    Adopt a bmap tool only if sparse-write speed proves necessary,
    and then via a fresh ADR (GPL-3.0 shipped binary => explicit
    approval; GPL-2.0+Python => size + note).
  - A GPL-3 SB-enrollment tool in the initramfs (`efi-updatevar`
    from efitools, or `sbkeysync` from sbsigntools) is **avoidable**.
    Rev-2 PRIMARY enrollment writes the signed `.auth` files to
    efivarfs directly from the installer module (`chattr -i` + write)
    with no external binary; the demoted fleet variant uses
    systemd-boot's LGPL `secure-boot-enroll`.  Either way no GPL-3
    enrollment tool is shipped -- a deliberate license (and attack
    surface) simplification worth stating in the ADR.

Net: Option C's rev-2 tooling adds `dialog` (LGPL, optional) plus
e2fsprogs and `setfiles`/policycoreutils (GPL-2.0 tools with LGPL/
public-domain libraries) and pulls `systemd-cryptenroll` + tpm2-tss
(LGPL + BSD, already precedented) into the initramfs -- all
weak-copyleft-or-permissive and each a one-line ADR note.  No new
strong-copyleft *shipped* binary is required, and the GPL-3.0 FAT
and bmap tools are deliberately kept out.  Option A, by contrast,
brings anaconda's GPL stack plus a Python runtime; Option B's
oe-core core is MIT but insufficient.

## 6. Recommendation

Adopt **Option C: a purpose-built installer userland in the
initramfs of one Secure-Boot-signed UKI**, built by extending
`lamadist-uki.bbclass` + `initramfs-framework` and a stick `.wks`
for the three-partition layout (ESP / PUBLIC / VAULT).  It is the
only option that satisfies the SPEC's top priorities
(non-destructiveness, SB integrity, single signed installer with no
second rootfs to protect) natively rather than by bolting custom
shell onto a heavyweight framework, it reuses the existing signed-UKI
and dm-verity-initramfs machinery for maximum buildability and
testability under the QEMU+OVMF harness, and it stays license-clean
(weak-copyleft-or-permissive tooling only, each a one-line ADR note;
the GPL-3.0 FAT and bmap tools kept out).  Retire the
`kas/installer.kas.yml` meta-anaconda scaffold; mine oe-core's
`init-install-efi.sh` and meta-intel's `image-installer.wks.in` as
*references* for the disk-write and wic scaffolding only.  Record the
decision as an ADR in the SPEC's `[AoA: installer approach]` slots.

## 7. Key risks

- **Owned installer code is security-critical.**  The fail-closed
  disk-selection and confirm-token logic (SPEC 2, 3.3) is now
  in-repo shell we maintain; a bug is a wrong-disk wipe.  Mitigation:
  the section 8 headless abort matrix must gate every path, and the
  module is in scope for the mandated Fable security review.
- **Payload writer choice.**  Choosing busybox `dd`+`sha256sum` keeps
  it license-clean and dependency-free but forgoes sparse-aware
  speed; a large `.wic.xz` streamed+verified may be slow.  Revisit
  `bmap-writer` (with the GPL-3 approval step) only if measured.
- **SB key enrollment portability.**  PRIMARY enrollment writes
  signed `.auth` files (PK self-signed, KEK-by-PK, db-by-KEK) to
  efivarfs from the initramfs after the in-UKI digest + `SecureBoot`
  gate (SPEC 3.1 step 2, section 8 stage 2); this must be proven
  under OVMF against blank vars, the SB-off-not-Setup-Mode state, and
  a wrong-PK varstore (BLOCKER-2 harness cases).  The demoted
  systemd-boot `secure-boot-enroll` fleet variant is not built or
  tested this pass.
- **Install-time labeling correctness.**  The installer runs
  unlabeled but now stamps labels on every target file via
  `setfiles` + the in-UKI `file_contexts`; a stale or mismatched
  `file_contexts` (drift from the policy the target actually loads)
  reproduces the M1 unlabeled-brick failure on first boot.
  Mitigation: the `file_contexts` shipped in the UKI must be built
  from the same policy revision as the target image, and stage 5
  should assert `restorecon -n` finds nothing to relabel on the
  provisioned volume.  The residual point still holds: the installer
  environment's OWN protection rests entirely on the Secure Boot
  signature over the UKI, stated in the SECURITY.md extension (SPEC
  section 8 item 7).
- **Size creep (rev-2 baseline reset).**  The TPM2 stack and full
  provisioning tooling are now IN by necessity (BLOCKER-1), so the
  baseline is ~27 MB installed, not rev 1's ~18 MB.  The ADR should
  fix THIS busybox+cryptenroll baseline and require a fresh note for
  any further addition (a Python tool, the rest of systemd, or a
  bmap/FAT tool), since the single-UKI margin is now materially
  thinner.
- **Scaffold retirement.**  Removing the meta-anaconda scaffold
  forfeits its (untested) mechanics; low risk since it was never
  wired to the SPEC flow, but the removal should land with the ADR
  so the kas overlay history is coherent.
