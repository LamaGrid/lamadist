# AoA: Secure Boot Signing and Key-Enrollment Model

**Status:** DRAFT analysis -- fills the `[AoA: chain shape --
shim+MOK vs. existing custom PK/KEK/db vs. sbctl-managed]` slot in
`docs/installer/SPEC.md` (section 2.1, 3.1 step 2, 8 stage 2).
Becomes an ADR on acceptance, then the SPEC leaves DRAFT.

**Decision owned:** how the installed system, and the installer
USB that provisions it, establish Secure Boot trust -- specifically
what fills the target firmware's PK/KEK/db (or MOK), how the
installer enrolls it, and how the installer itself boots before
that trust exists.

**Priority order inherited from the SPEC:** non-destructiveness >
Secure Boot integrity > reproducibility > image size.  This AoA is
the "Secure Boot integrity" fork; it must not compromise the
non-destructiveness invariant (an enrollment step must never be the
thing that writes an operator's disk) and it is graded on
reproducibility as the next tie-breaker.

## Methodology: deliberate two-angle self-consistency

This is the project's single riskiest fork, so each option is
evaluated twice, from two provisioning realities that pull in
different directions, and only then reconciled:

- **Fleet-provisioning angle.**  Role A images many sticks; targets
  are installed headless, possibly by a technician who never opens
  the firmware menu; someone owns firmware state at scale (the
  AT-SCALE portal).  This angle rewards zero-touch automation and
  punishes anything requiring per-machine physical presence in the
  firmware UI.
- **Single-device homelab angle.**  One operator, one board, full
  physical access to the firmware setup menu, and a strong
  preference for simple, reversible, self-hosted trust with no
  third-party dependency.  This angle rewards simplicity and
  reversibility and is indifferent to per-machine setup friction.

An option is only recommended if it survives BOTH angles; where the
angles disagree the disagreement is stated, not averaged away.

## Verified facts underpinning this analysis

Behavior below was checked against upstream sources rather than
asserted from memory (sources listed at the end):

1. **systemd-boot enrolls Secure Boot keys itself, in Setup Mode.**
   `loader.conf`'s `secure-boot-enroll` takes `off` / `manual` /
   `if-safe` (default) / `force`.  It acts only "if the system is
   in setup mode".  Key sets live on the ESP under
   `/loader/keys/NAME/` as `PK.auth`, `KEK.auth`, and `db.auth` --
   authenticated (signed) UEFI variable-update files, not raw ESLs.
   `force` always enrolls the set named `auto` (after a timed
   warning); `if-safe` enrolls `auto` only when it judges the
   enrollment safe.  This means the project's own loader can perform
   the entire Setup-Mode enrollment with no bespoke userland code --
   the installer only has to ship three `.auth` files on its ESP.

2. **A self-built shim is not Microsoft-signed.**  Microsoft's UEFI
   CA signature is gated by the rhboot-run shim-review board: SBAT
   currency, all known GRUB CVEs patched, kernel-lockdown
   enforcement, reproducible `docker build .`, legal-entity
   verification, and CA/vendor-cert disclosure, with a stated
   review wait of "2-3 months".  Nothing the project builds locally
   boots on stock (MS-key) firmware without either that signature or
   a prior enrollment step.

3. **systemd-boot can run under shim.**  Since shim 16.1 shim
   overrides the boot-services LoadImage/StartImage table, so
   systemd-boot and its UKIs are validated through shim's protocol
   (outer image against db/MOK, inner UKI sections allowlisted).  So
   Option A is not disqualified on "does sd-boot load under shim" --
   it is disqualified elsewhere.

4. **sbctl is MIT-licensed**, enrolls in Setup Mode, and also signs
   EFI binaries; it manages its own key store and JSON state.

5. **The existing harness already does offline custom-key
   enrollment.**  `.mise/tasks/ovmf-vars` uses `virt-fw-vars` to
   enroll the committed `sb-dev` PK/KEK/db into an OVMF varstore and
   turn Secure Boot on; `.mise/tasks/vm --secureboot` boots
   `OVMF_CODE.secboot.fd` against it and `smoke_login.py` asserts
   `SecureBoot=1` in-guest.  A blank (unenrolled) `OVMF_VARS.fd` with
   the same secboot CODE image is a Setup-Mode, SB-capable firmware
   -- exactly the state SPEC stage 2 wants to enroll from.

## The chicken-and-egg, stated once

Secure Boot's bootstrap problem is common to every option: a stick
signed by a key the target does not yet trust cannot boot with
Secure Boot enforcing until that key is trusted, but the thing that
would establish trust is on the stick that cannot boot.  There are
only three escapes, and every option below is just a different
choice among them:

- **(a) Firmware already trusts you.**  Real only with a
  Microsoft-signed shim (Option A) -- stock firmware trusts the MS
  UEFI CA, so an MS-signed shim boots unenrolled.  Self-built
  anything does not qualify.
- **(b) Firmware is opened first (Setup Mode).**  The target is put
  in Setup Mode (firmware "clear keys" / "custom mode"), where
  unauthenticated key writes are allowed; the installer enrolls,
  reboots, and thereafter boots enforcing.  This is Options B and C.
- **(c) Firmware is off (Secure Boot disabled).**  The installer
  boots with SB off, enrolls, and turns SB on at reboot.  A
  degenerate sub-case of (b); the SPEC treats "SB on, untrusted,
  refused to boot" as unreachable in-flow and pushes it to the
  manual's pre-boot section.

Note this interacts with the non-destructiveness invariant: the
enrollment escape must complete (and, for B/C, its reboot) BEFORE
the installer ever enumerates a target disk.  Enrollment touching
only EFI variables and never a block device is a property each
option is graded on.

## Option A: distro-signed shim + MOK enrollment

Ship a shim as the ESP's first-stage loader; shim chainloads the
signed systemd-boot, which loads the signed installer UKI.  The
project's signing cert is enrolled into shim's Machine Owner Key
(MOK) store via MokManager / `mokutil`, so shim trusts
project-signed binaries.

**Boot-before-trust (chicken-and-egg).**  The intended escape is
(a): a Microsoft-signed shim boots on stock firmware unenrolled.
But the project has no MS-signed shim and cannot self-produce one --
that is the shim-review board (fact 2), a 2-3 month process
requiring a legal entity, SBAT upkeep, kernel lockdown, and
reproducible builds, none of which a homelab-scale project realistically
carries.  A SELF-signed shim is no better than Option B: stock
firmware rejects it until its hash/cert is enrolled into db or MOK,
and that enrollment is the very step Option B does directly.  So on
stock firmware the shim layer buys nothing the project can actually
obtain.

**Enrollment automation depth.**  MOK enrollment is deliberately
NOT automatable: `mokutil --import` only queues a request; the
actual enroll happens in MokManager, a firmware-time UI shown on the
next reboot that requires a physically present human to confirm with
a firmware-generated password challenge.  This is by security design
(it blocks remote MOK injection) and it directly defeats the SPEC's
headless-install requirement (3.2) and the "automated where firmware
state permits" hard requirement (2.8).

**Irreversible firmware-state risk.**  Low-to-none at the firmware
level (MOK lives in shim's variable, clearable via MokManager /
`mokutil --delete`), but that is because it does not touch PK/KEK/db
at all -- which is also why it does not deliver a
project-controlled root of trust.

**Revocation / rotation.**  Split and awkward: binary revocation
rides SBAT (shim's mechanism, requires shim/SBAT version discipline
you now own forever) and MOKX; key rotation is per-machine MOK
re-enrollment (interactive again).  You do not control the db path
at all on stock firmware -- Microsoft does.

**Licenses.**  shim itself is permissive (BSD-2-Clause family) and
`mokutil` is GPL-2.0+ (copyleft -- would ship on the installer,
needs a note).  The disqualifier is not a license: it is the
dependency on Microsoft's UEFI CA signing service (a proprietary,
gated, third-party trust root) and the shim-review board as a
release prerequisite.

**Fit with sb-dev keys + regen script.**  Poor.  The sb-dev chain is
a PK/KEK/db model; Option A uses none of PK/KEK/db on stock firmware
and instead needs a shim build, a MOK cert, and SBAT metadata -- a
parallel, largely disjoint trust apparatus.

**QEMU/OVMF testability.**  Weak.  The enrollment stage is
MokManager, a firmware-time interactive UI that the serial-console
harness cannot script without OVMF-specific hacks; and there is no
MS-signed shim to place in OVMF's db, so the "boots unenrolled on
stock firmware" property -- Option A's entire reason to exist --
cannot be demonstrated in the harness at all.

## Option B: existing custom PK/KEK/db + Setup-Mode enrollment

Keep the current chain unchanged: the committed `sb-dev` PK/KEK/db
sign systemd-boot and the UKIs (already true at M4 close).  The
installer enrolls those same PK/KEK/db into the target firmware
while it is in Setup Mode, reboots, and thereafter boots enforcing.
Two enrollment mechanisms, same key material:

- **B2 (primary): userland enrollment from the signed initramfs.**
  The installer reads `SecureBoot`/`SetupMode` (per SPEC 3.1 step
  2), applies the manifest-declared enrollment mode, owns the
  interactive confirmation UX, runs the in-UKI digest check (see
  "Trust verification gate" below), and writes the `.auth` files
  directly to `efivarfs` -- `chattr -i` on the target variable then
  a write of the `.auth` payload, with NO external enrollment
  binary -- before rebooting.  All enrollment policy (headless vs.
  interactive, confirmation, verification) lives in one signed,
  reviewed place that can read the manifest BEFORE it acts.
- **B1 (explicitly-chosen fleet variant, not built this pass):
  sd-boot native `secure-boot-enroll`.**  Ship `PK.auth` /
  `KEK.auth` / `db.auth` under `\loader\keys\auto\` on the installer
  ESP and set `secure-boot-enroll` in the installer's `loader.conf`.
  In Setup Mode the loader enrolls before the installer UKI even
  runs, reboots, and then verifies and boots the now-trusted
  installer; zero bespoke enrollment code.  This is deliberately NOT
  the primary mechanism, because three traps make it unsuitable as a
  default.  (i) `secure-boot-enroll force` auto-enrolls the fleet PK
  on ANY Setup-Mode machine that boots the stick -- an interactive
  install gets no confirmation prompt (violating SPEC 3.1 step 2),
  and a Setup-Mode bystander machine (a technician's own laptop)
  gets the fleet PK enrolled and Secure Boot flipped on.  (ii)
  `if-safe` judges enrollment "safe" only in virtualized
  environments, so the QEMU stage-2 gate would go green while real
  hardware silently never auto-enrolls -- the harness would validate
  a behavior the field does not have.  (iii) Under B1 the loader
  enrolls BEFORE the installer UKI runs, so enrollment precedes
  manifest validation and the in-UKI digest check entirely: keys are
  written and Secure Boot is flipped on (a firmware-state side
  effect) before any abort logic or trust verification can run.  B1
  is therefore built only when a fleet deliberately chooses
  zero-touch enrollment for machines it already controls and ships
  in Setup Mode; it is not built this pass.

**Trust verification gate (mandatory, in-UKI).**  The `.auth` files
and `loader.conf` on the ESP are UNSIGNED inputs -- plain FAT32
files covered by no signature (in Setup Mode the firmware verifies
nothing, and an `.auth` signature is self-referential to whatever
chain the file itself carries).  Their integrity control is a hash
check carried INSIDE the signed UKI: the installer initramfs embeds
the expected PK/KEK/db digests in a UKI section covered by the image
signature, and AFTER the enrollment stage but BEFORE any disk
enumeration or write it asserts (i) `SecureBoot=1` and (ii) that the
live PK/KEK/db efivar contents hash to the expected digests.  Any
mismatch halts fail-closed with diagnostics.  This single gate
closes the whole class of enrollment-trust holes: a swapped-`.auth`
stick tampered in transit enrolls an attacker root but fails the
digest match; an attacker who pre-enrolled attacker-PK-plus-our-db
in Setup Mode is caught because the live PK no longer matches; and
the `SecureBoot=0 && SetupMode=0` "operator simply disabled Secure
Boot" state fails the `SecureBoot=1` assertion instead of silently
provisioning SB-off.  Because B2 owns this check and runs it in the
same signed userland that reads the manifest, the check gates ALL
disk enumeration -- under B1 the loader has already enrolled and
rebooted before any such check could run, a further reason B1 cannot
be primary.

**Residual trust risk (Setup-Mode custody / TOFU).**  The real root
of trust for enrollment is whoever controls what boots first while
the target is in Setup Mode.  Physical custody of BOTH the stick and
the target during the Setup-Mode window is therefore a stated
precondition, and enrollment is trust-on-first-use on first install.
The in-UKI digest check above detects wrong-chain enrollment -- a
swapped or attacker-pre-enrolled PK/KEK/db -- but it CANNOT detect a
fully attacker-controlled first boot (an attacker who owns the whole
medium and the firmware window).  This precondition and the exact
detect / no-detect boundary are recorded in the SECURITY.md
installer extension (review MAJOR-7).

**Boot-before-trust.**  Escape (b): the target is in Setup Mode (or
SB off) for the first installer boot; the manual's pre-boot section
tells the operator how to reach Setup Mode ("clear keys" / "custom
mode") when it is not.  Enrollment touches only EFI variables and is
followed by a reboot -- no block device is written in the enrollment
stage, satisfying non-destructiveness.

**Enrollment automation depth.**  Full and unattended.  B2 reads
`SetupMode` and applies the manifest-declared mode from signed
userland -- headless installs enroll unattended, interactive
installs get the confirmation prompt -- so a single signed image
serves both flows.  The B1 fleet variant auto-enrolls headlessly (a
timed warning only) for machines a fleet owner ships in Setup Mode.
Either way this is the only option that meets hard requirement 2.8
(automate where firmware state permits, else in-line instructions)
for real.

**Irreversible firmware-state risk.**  Bounded and reversible.
Enrolling PK exits Setup Mode and turns Secure Boot on; a wrong or
unwanted key set can be cleared from the firmware setup menu
("restore factory keys" / "clear Secure Boot keys") on any standard
x86 UEFI.  The one genuinely-sticky UEFI action -- a monotonic `dbx`
update, which some firmware treats as append-only -- is NOT
performed: this option enrolls PK/KEK/db only and writes no
forbidden-signatures list.  The residual sharp edge is operational,
not irreversible: a headless/remote target enrolled with keys whose
private half is unavailable is unbootable until someone reaches its
firmware menu -- mitigated because the project holds all three
private keys and, for real deployments, M6 owns the production key
custody.

**Revocation / rotation.**  Clean and self-owned.  Because the
project holds PK and KEK, a new db (or a db entry removal) can be
pushed as a KEK-signed authenticated update WITHOUT returning to
Setup Mode; a full reset re-enrolls a fresh PK.  Rotation of the
signing key is: regenerate the chain (`regen-dev-sb-keys.sh`),
re-issue `.auth`, re-enroll.  The SPEC already carries a
recovery-keyslot rotation procedure in the manual; key rotation
slots beside it.

**Licenses.**  No new license exposure, and specifically no
enrollment binary on the shipped installer path.  B2 writes the
`.auth` files directly to `efivarfs` (`chattr -i` then write) using
only the kernel's efivarfs interface -- there is no `efi-updatevar`
/ `efitools` in the image.  This matters: efitools is GPL-3, and
shipping it in the initramfs would require explicit policy approval,
whereas a direct efivarfs write needs no such binary and no
approval.  `efitools`' `sign-efi-sig-list` stays BUILD-HOST-ONLY for
`.auth` generation (ADR 0005, GPL-2/GPL-3, build-container only,
already present); offline test enrollment uses `virt-firmware` (ADR
0004, GPL-2.0-only, build/test-only).  The enrolling loader used by
the B1 fleet variant is systemd-boot (LGPL-2.1-or-later, weak
copyleft), already the shipped loader -- note-only under policy, no
new approval.  Nothing new ships on the target that was not already
there.

**Fit with sb-dev keys + regen script.**  Best possible -- it IS the
current chain.  The single additive change: have
`regen-dev-sb-keys.sh` emit `pk.auth` / `kek.auth` / `db.auth`
alongside the existing `.pem` / `.der` / `.esl` forms, via
`sign-efi-sig-list -k <higher>.key.pem -c <higher>.cert.pem <VAR>
<var>.esl <var>.auth` (PK self-signs, KEK signed by PK, db signed by
KEK).  The tool is already a declared dependency; this is a handful
of lines in a script that already loops over `pk kek db`.

**QEMU/OVMF testability.**  Directly testable and the closest thing
to already-built.  Boot `OVMF_CODE.secboot.fd` against a fresh,
UNenrolled `OVMF_VARS.fd` (Setup Mode, SB-capable), let the installer
enroll, reboot, and assert `SecureBoot=1` in-guest with the existing
`smoke_login.py secureboot` check.  The harness delta is one new
`vm` mode (secboot CODE + blank vars, e.g. `--secureboot-setup`) and
a two-phase assertion; it reuses the exact enrollment machinery the
`ovmf-vars` task already proves works.

## Option C: sbctl-managed custom keys

sbctl (fact 4) as tooling over the same custom-key trust model as
Option B, or as its own key hierarchy.  Evaluated both ways.

**As its own model.**  sbctl would generate and own a fresh key set
in its store and enroll it in Setup Mode.  This is trust-model-
identical to Option B (custom PK/KEK/db, Setup-Mode escape) but
DISCARDS the committed `sb-dev` chain that already signs the shipped
loader and UKIs -- a regression in fit for no trust benefit.

**As tooling over Option B.**  sbctl can import externally-provided
keys and enroll/sign with them, so in principle it could drive
enrollment of the existing `sb-dev` chain.

**Boot-before-trust.**  Identical to Option B -- escape (b), Setup
Mode.  sbctl enrolls via `efivarfs` and turns SB on at reboot.

**Enrollment automation depth.**  Good (`sbctl enroll-keys` is
scriptable and reports status cleanly), but it is a runtime tool
that runs against a live `efivarfs` on the target from the installer
initramfs -- heavier than B1, which needs no userland tool at all.

**Irreversible firmware-state risk.**  Same as Option B (PK/KEK/db,
clearable from firmware setup; no dbx).  sbctl's optional
"also enroll Microsoft's keys" is a policy choice, not required.

**Revocation / rotation.**  Same as Option B when driving the same
keys; sbctl's `status` / `verify` give a nicer operational read-out,
which has genuine ergonomic value for a hands-on operator.

**Licenses.**  sbctl is MIT (permissive) -- the cleanest license of
any tool in this AoA -- but adopting it means shipping a NEW
userland Go binary in the installer image (size and supply-surface
cost the SPEC's image-size priority notes), duplicating enrollment
and signing capability the tree already gets from efitools +
sd-boot.

**Fit with sb-dev keys + regen script.**  Awkward.  sbctl is built
around managing its OWN key store and state DB; feeding it a fixed,
committed, externally-owned PK/KEK/db is the against-the-grain path
and couples the installer to sbctl's on-disk state model for no
capability the tree lacks.

**QEMU/OVMF testability.**  As testable as Option B (Setup-Mode
enroll, assert `SecureBoot=1`), but only after adding sbctl to the
installer image -- more moving parts to reach the same assertion.

## Two-angle evaluation and reconciliation

**Fleet angle.**  Option A is superficially the fleet dream (boot
anywhere SB-on, no firmware touch) but only with an MS-signed shim
the project cannot get, and MOK's mandatory interactivity breaks
headless install regardless -- it fails the angle on its own
premises.  Option B is fleet-workable: the friction is precisely
that each target must be in Setup Mode, which is the provisioner's
(Role A / the AT-SCALE portal's) job to guarantee -- machines that
ship in Setup Mode, or whose firmware config the fleet owner
controls, enroll zero-touch via B1 `force`.  Option C adds fleet-
friendly status reporting but no trust or automation B lacks.

**Homelab angle.**  Option A is pure overhead: a single operator
with firmware access gains nothing from an (unobtainable) MS shim
and inherits SBAT/shim maintenance forever.  Option B is the natural
fit: open firmware to Setup Mode from the menu once, boot the stick,
keys auto-enroll, done -- and everything is reversible from the same
menu.  Option C's `sbctl status`/`verify` ergonomics are a real,
if small, homelab nicety, but not worth a new image dependency and
the committed-key mismatch.

**Reconciliation.**  Both angles independently reject A (impractical
trust root under one, useless overhead under the other) and both
converge on the custom PK/KEK/db + Setup-Mode model.  They differ
only on Option C's tooling: the fleet angle is mildly warmed by
sbctl's reporting, the homelab angle mildly warmed by its UX, but
neither needs it and both are penalized by its new dependency and
poor fit with the committed chain.  The consistent choice is Option
B's trust model, implemented with the tools already in the tree,
with sbctl noted as a possible future ergonomics layer -- not
adopted now.

## Recommendation matrix

Wide table; scroll horizontally if needed.

| Option | Pros | Cons | SB-integrity + reproducibility trade-off | Recommendation |
|--------|------|------|------------------------------------------|----------------|
| A. shim + MOK | Boots unenrolled on stock MS-key firmware IF MS-signed; permissive shim license | No obtainable MS-signed shim (review board, 2-3 mo, legal entity, SBAT upkeep); MOK enrollment is interactive by design (breaks headless); mokutil GPL-2.0+; disjoint from sb-dev chain; not exercisable in harness | Strong integrity ONLY with the MS signature the project cannot get; reproducibility hurt by shim-review's ongoing SBAT/build burden and a proprietary signing dependency | Reject |
| B. custom PK/KEK/db + Setup-Mode enroll (B2 userland primary) | Reuses the exact M4 chain; B2 userland enrollment from the signed initramfs owns confirmation, reads the manifest mode, and runs the in-UKI PK/KEK/db digest + `SecureBoot=1` gate before any disk write; direct efivarfs `.auth` writes (no shipped enrollment binary, no GPL-3); reversible via firmware menu; self-owned revocation via held PK/KEK; directly QEMU-testable from blank-vars Setup Mode | Requires the target in Setup Mode first (per-machine firmware step; owned by provisioner at scale); Setup-Mode-window custody of stick and target is a stated precondition (TOFU on first install); a remote mis-enroll needs physical firmware access to clear | Highest self-owned integrity available without a third-party CA; best reproducibility -- same committed keys, `.esl`/`.auth` deterministic from the regen script, no external signing service | Adopt (B2 primary; B1 fleet-only, not built this pass) |
| C. sbctl over B | MIT (cleanest license); nice status/verify UX; scriptable enroll | Ships a new userland binary (size/supply cost); built around its own key store, awkward with a fixed committed chain; duplicates efitools + sd-boot capability | Same integrity as B; reproducibility slightly worse (extra binary + sbctl state model) | Note as optional future ergonomics; do not adopt now |

## Recommendation (prose)

Adopt **Option B**: keep the committed `sb-dev` PK/KEK/db chain as
the installed system's Secure Boot root, and have the installer
enroll that same chain into the target firmware from Setup Mode.
The PRIMARY mechanism is B2 -- userland enrollment from the signed
initramfs: it reads `SetupMode`, applies the manifest-declared mode,
owns the interactive confirmation, runs the in-UKI PK/KEK/db digest
plus `SecureBoot=1` gate before any disk enumeration, and writes the
`.auth` files directly to `efivarfs` (`chattr -i` then write) with no
external enrollment binary.  B1 -- sd-boot's native
`secure-boot-enroll` with `PK.auth`/`KEK.auth`/`db.auth` under
`\loader\keys\auto\` on the installer ESP -- is demoted to an
explicitly-chosen fleet variant (not built this pass): `force`
auto-enrolls interactive installs and any Setup-Mode bystander
machine, `if-safe` fires only in VMs (harness-green / field-broken),
and its enrollment precedes manifest validation and the trust gate.
Option B is still the only choice that satisfies the
headless-automation hard requirement (2.8, 3.2), reuses the existing
signing chain and the existing QEMU/OVMF enrollment harness end to
end, keeps revocation and rotation entirely self-owned through the
held PK/KEK, and -- with B2's direct efivarfs writes -- introduces no
new shipped binary and no new license exposure beyond the three ADRs
(0003-0005) M4 already accepted.  Option A is
rejected: its only advantage -- booting unenrolled on stock firmware
-- depends on a Microsoft-signed shim the project cannot obtain
without the shim-review board, its MOK enrollment is interactive by
design and defeats headless install, and it cannot be exercised in
the QEMU harness at all.  Option C is trust-identical to B but pays
a new-dependency and poor-fit cost for ergonomics the tree already
covers; note it for a possible future operator-UX layer, do not
build it now.

### Concrete follow-ups this decision implies

1. Extend `meta-lamadist/files/sb-dev/regen-dev-sb-keys.sh` to also
   emit `pk.auth` / `kek.auth` / `db.auth` via `sign-efi-sig-list`
   (efitools, already a dependency): PK self-signed, KEK signed by
   PK, db signed by KEK.  Commit the `.auth` forms beside the
   existing public dev key material.
2. Implement the B2 userland enrollment module in the installer
   initramfs: read `SecureBoot`/`SetupMode`, apply the
   manifest-declared mode, own the confirmation UX, run the in-UKI
   PK/KEK/db digest + `SecureBoot=1` gate, and write the `.auth`
   files via direct efivarfs (`chattr -i` then write) with no
   external enrollment binary; carry the expected PK/KEK/db digests
   in a signed UKI section (SPEC section 7 build definition).  Do
   NOT ship `secure-boot-enroll` or a `\loader\keys\auto\` payload
   on the DEPLOYED image -- the deployed `loader.conf` omits both so
   a deployed ESP can never re-enroll (the B1 fleet variant, if ever
   built, adds them only to the installer ESP).
3. Add a `vm` harness mode that boots `OVMF_CODE.secboot.fd` against
   a blank (Setup-Mode) `OVMF_VARS.fd`, plus negative varstores (a
   `SecureBoot=0 && SetupMode=0` "SB simply disabled" state and a
   wrong-PK enrolled store), and a two-phase assertion (Setup Mode
   -> installer enrolls -> in-UKI digest + `SecureBoot=1` gate
   passes -> reboot -> `SecureBoot=1`) that fail-closes on the
   negative cases, to satisfy SPEC stage 2.  This reuses
   `smoke_login.py`'s existing `secureboot` in-guest check.
4. Record the residual risk in the SECURITY.md installer extension:
   Setup-Mode-window custody of stick and target is a precondition
   and enrollment is TOFU on first install (the in-UKI digest check
   detects wrong-chain enrollment but not a fully attacker-
   controlled first boot); a target enrolled with unavailable keys
   is unbootable until its firmware menu is reached; the enrollment
   stage writes only EFI variables and no block device; the on-ESP
   `.auth` files and `loader.conf` are unsigned inputs whose sole
   integrity control is the in-UKI digest check; no `dbx` write is
   performed.

## Sources verified

- systemd-boot `secure-boot-enroll` values, `/loader/keys/NAME/`
  layout, `PK.auth`/`KEK.auth`/`db.auth` authenticated-variable
  requirement, and the Setup-Mode precondition: `loader.conf(5)`
  (systemd upstream man page).
- shim-review board as the prerequisite for a Microsoft UEFI CA
  signature (SBAT, reproducible build, legal entity, kernel
  lockdown, ~2-3 month wait): rhboot/shim-review.
- shim 16.1 overriding LoadImage/StartImage so systemd-boot and its
  UKIs validate through shim's protocol: rhboot/shim and the
  systemd-boot-under-shim discussion (systemd issue #41711).
- sbctl MIT license, Setup-Mode `enroll-keys`, and EFI-binary
  signing: Foxboron/sbctl.
- Existing offline custom-key enrollment and the `--secureboot`
  assertion path: in-tree `.mise/tasks/ovmf-vars`, `.mise/tasks/vm`,
  and `meta-lamadist/files/sb-dev/README.md`.
