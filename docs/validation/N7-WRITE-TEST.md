# N7 write test and its RED map

The N7 write test checks the claim in ADR 0013, decision 3: the
SetVariable API refuses writes to PK, KEK, and db, and nothing
persists.  It runs on the qemuarm64 guest with the U-Boot payload
(`kas/extras/uboot-vm.kas.yml`), the same U-Boot v2026.01 that the
boards ship.

## What runs

`mise run test-efivars` boots a scratch copy of the image, headless,
with `-snapshot`, and drives the serial console:

- **Part A**, in the guest as root, through efivarfs
  (`.mise/lib/efivar_part_a.sh`): the state of SecureBoot, SetupMode,
  PK, KEK, db, and dbx, the efivarfs mount, and `/dev/efi_test` (A0);
  a remount to read-write (A1); the eight payload rows; the state
  again.
- **Part B**, with `--probe`, before `ExitBootServices`: the probe
  (`meta-lamadist/recipes-test/lamadist-n7-probe`, ADR 0017), signed
  by the development db key, runs in place of `BOOTAA64.EFI`.  It
  reads PK, KEK, db, and dbx by CRC-32, sends the same eight rows
  through SetVariable, tries L1, reads the variables again, and
  chain-loads systemd-boot.
- **A reset**, then both parts read the state again.  With
  `--firmware u-boot`, `u-boot.bin` must have the given SHA-256
  before and after.

The eight rows (`.mise/lib/efivar_payloads.py`), in the probe's order:

| Row | Variable | Attributes | Data |
| --- | --- | --- | --- |
| U-PK, U-KEK, U-db | PK, KEK, db | 0x07 | the seeded list, unsigned |
| W-db | db | 0x27 | `kek.esl`, signed by the db key: the wrong key |
| X-PK | PK | 0x00 | none: an unauthenticated delete |
| S-db | db | 0x67 | `kek.esl` appended, signed by KEK |
| S-KEK | KEK | 0x67 | `db.esl` appended, signed by PK |
| S-PK | PK | 0x27 | an empty list signed by PK: a delete |

L1 runs between S-KEK and S-PK: `LoadImage` of `n7-target.efi`, the
probe signed by the KEK key only.  db trusts it only if S-db worked.

The verdict (`.mise/lib/efivar_write_test.py`) reads only the serial
transcript and prints one `N7 ROW <row> PASS|FAIL` line per row and
`N7 VERDICT`.  Its unit tests run it on transcripts built to the line
protocol, one per failure case.

## RED runs

A RED run shows that a row can fail.  Each is run with the same task
and the same verdict:

- **R1a**: `--firmware aavmf`, no probe.  edk2 with the development
  keys enrolled (`mise run ovmf-vars`) answers run-time writes and
  checks authenticated ones.  The Part A rows below give R1a.
- **R1b**: `--firmware aavmf --probe`.  The probe rows below give R1b.
  Its Part A rows are usable: in its one run they equal R1a's, because
  the probe's writes were all refused and it deleted nothing.
- **R2**: `--firmware u-boot --probe` on a U-Boot built from an
  untracked overlay that turns on a writable run-time store, with its
  own TMPDIR and deploy dir.  No tracked file holds that overlay, and
  the shipped U-Boot configuration does not change.

This document counts completed runs only: a completed run is one that
ended with no driver error.  Two earlier local runs of GREEN did not
finish.  One stalled and left no verdict.  The other stopped at a driver
error before Part A, and its verdict failed 45 rows for missing lines.
That shows that a missing line fails its row, and nothing about the
firmware.

**Finding: R1 shows no write that persists.**  edk2 refused every
authenticated write in every R1 run: the probe got SECURITY_VIOLATION
for S-db, S-KEK, and S-PK (R1b `probe.S-db`, `probe.S-KEK`,
`probe.S-PK`), and the Linux writes failed with rc 1 and "Permission
denied" (R1a `A.S-db`, `A.S-KEK`, `A.S-PK`).  No variable changed, so
every `post` and `reboot` row stayed green (R1a `A.post.PK`,
`A.post.KEK`, `A.post.db`, and the `reboot.*` rows; R1b the same, plus
`probe.post.*` and `probe.boot2.*`).  The enrolled KEK and db do hold
our certificates beside the template's, and the enrolled PK is ours
alone, so the refusal is not a missing key.  The signed payloads verify
offline against the enrolled certificates, so it is not the payload.

**Finding: no run on any firmware shows the test catching a key change
that persists.**  GREEN has no write.  R2 turns only the Linux rows red
(below), and it changes PK in RAM only.  R1 turns rows red by refusal
statuses, never by a changed key.  A row marked "RED not shown" below
has not been seen to fail for the reason it tests.

**Open: why edk2 refuses the signed writes.**  The map does not settle
it.  H1: the variable driver's runtime crypto (RSA-4096 and its fixed
memory pool) fails on these payloads.  H2: a check in edk2-stable202408
that the 202202 source lacks.  Separately, the S-db append would make
db 10368 bytes (9001 plus 1367), over the 10240-byte limit of
`PcdMaxAuthVariableSize` in edk2-stable202202, so S-db would then fail
with INVALID_PARAMETER; the 202408 value is not checked.  See
docs/PLAN.md, Future Work.

**Finding: R2 turns no Part B row red.**  The overlay opens U-Boot's
run-time write path, but the preseed still refuses every boot-time
write to PK, KEK, and db (`efi_variable.c:299-301`).  So R2 shows only
that the Linux rows catch a U-Boot that answers run-time writes.  Of
the completed runs, only R1b, on edk2, shows the probe rows red.

## RED map

Sources: U is U-Boot v2026.01 `lib/efi_loader/`, E is
edk2-stable202408 (`Variable.c` in `MdeModulePkg`, `AuthService.c` and
`AuthVariableLib.c` in `SecurityPkg`), E22 is edk2-stable202202 source
read in place of it (no 202408 tree was read, so an E22 line is not
checked against the firmware under test), K is Linux 6.18, and T is
this tree.  A run name and a row (`R1a A.X-PK`) cite an observation of
a local QEMU run of this task; the logs of those runs are not in the
tree.  The GREEN, R1, and R2 columns hold what those runs observed.
GREEN, R1a, and R2 ran with the guest script and the verdict code of
this tree.  R1b ran once, with an earlier guest script that kept only
dd's last stderr line, so its seven `dd` rows show rc 1 and no errno;
its probe and verdict code were the same as in the other runs.  An errno
is the strerror text in the logged error line ("Invalid argument" is
EINVAL, "Permission denied" is EACCES), not a number.  "inf" marks a
prediction that the source alone does not settle.  "RED not shown"
marks a row that no RED run turned red for the reason the row tests;
only its unit transcripts show it failing for that reason.  Such a row
with a "red" cell was turned red only by a refused write.  A refused
write turns a row red by status or errno, but only a write that takes,
and then persists, shows the row catching a key change.

| Row | GREEN (U-Boot) | R1 | R2 | Source |
| --- | --- | --- | --- | --- |
| `A0.secureboot` | 1 | pass | pass | U:efi_variable.c:600-605 (seed), efi_init_secure_state; RED not shown |
| `A0.setupmode` | 0 | pass | pass | as above; RED not shown |
| `A0.PK` | SHA-256 of `pk.esl` | pass (R1a, R1b: the enrolled PK is the test PK alone) | pass | T:lib/lamadist/efivarseed.py, T:.mise/tasks/ovmf-vars (`--set-pk` replaces the template PK); RED not shown |
| `A0.KEK` | SHA-256 of `kek.esl` | red: the template's Red Hat and two Microsoft KEKs stay beside ours | pass | T:.mise/tasks/ovmf-vars (`--add-kek` appends), R1a, R1b A0.KEK FAIL |
| `A0.db` | SHA-256 of `db.esl` | red: the template's five Microsoft CAs stay beside ours | pass | as above (`--add-db`), R1a, R1b A0.db FAIL |
| `A0.dbx` | absent | red: the template's dbx stays, 26 SHA-256 entries | pass | T:lib/lamadist/efivarseed.py (no dbx in the seed), R1a, R1b A0.dbx FAIL |
| `A0.mount` | ro | red: rw | red: rw | K:fs/efivarfs/super.c:378-379; U:efi_runtime.c:128-175 (SET_VARIABLE only with the run-time store); R1a, R1b, R2 A0.mount FAIL |
| `A0.efi_test` | absent | pass | pass | K:drivers/firmware/efi/Kconfig:137-140 (EFI_TEST off, inf); RED not shown |
| `A1.remount` | rc != 0, still ro | red: rc 0, rw | red: rc 0, rw | K:fs/efivarfs/super.c:407-409 (EINVAL); R1a, R1b, R2 A1.remount FAIL |
| `A.U-PK` | EROFS | red: EINVAL ("Invalid argument", R1a) | red: EINVAL ("Invalid argument") | GREEN K:fs/efivarfs/super.c:378-379; R1 probe INVALID_PARAMETER (R1b probe.U-PK), E:Variable.c:2872-2880, K:efi.c:1034-1035, R1a A.U-PK; R2 U:efi_variable.c:531-534 (seed attributes 0x27), R2 A.U-PK |
| `A.U-KEK` | EROFS | red: EINVAL (as `A.U-PK`) | red: EINVAL (as `A.U-PK`) | as `A.U-PK` |
| `A.U-db` | EROFS | red: EINVAL (as `A.U-PK`) | red: EINVAL (as `A.U-PK`) | as `A.U-PK` |
| `A.W-db` | EROFS | red: EACCES ("Permission denied", R1a; the probe got SECURITY_VIOLATION) | red: EINVAL ("Invalid argument") | R1 E:AuthService.c:2420-2421, K:efi.c:1046-1047 (SELinux can also give EACCES), R1a A.W-db; R2 U:efi_variable.c:508-509, R2 A.W-db |
| `A.X-PK` | EROFS | red: EINVAL | red: rc 0, PK deleted in RAM | R1 E:AuthService.c:705-712, K:fs/efivarfs/inode.c:126-127, R1a, R1b A.X-PK ("Invalid argument"); R2 U:efi_variable.c:545-547, 564, R2 A.X-PK rc 0 |
| `A.S-db` | EROFS | red: rc 1, EACCES ("Permission denied", R1a; refused, the write did not take) | red: EINVAL ("Invalid argument"; refused) | R1 E:AuthVariableLib.c:417-430 (db by KEK; inf: which check refused is open), R1b probe.S-db SECURITY_VIOLATION, R1a A.S-db; R2 U:efi_variable.c:508-509, R2 A.S-db; RED not shown (no run shows the write taking) |
| `A.S-KEK` | EROFS | red: rc 1, EACCES (as `A.S-db`) | red: EINVAL (as `A.S-db`) | R1 E:AuthVariableLib.c:417-430 (KEK by PK; inf, as `A.S-db`), R1b probe.S-KEK SECURITY_VIOLATION; R2 as `A.S-db`; RED not shown |
| `A.S-PK` | EROFS | red: rc 1, EACCES (as `A.S-db`) | red: EINVAL (as `A.S-db`) | R1 E:AuthService.c:784-790 (PK delete, setup mode; inf, as `A.S-db`), R1b probe.S-PK SECURITY_VIOLATION; R2 as `A.S-db`; RED not shown |
| `A.post.secureboot` | unchanged | pass | pass | E:AuthService.c:412-418 (not changed at run time); RED not shown |
| `A.post.setupmode` | unchanged | pass (inf: E:AuthService.c:396-400 changes it in place; the run-time cache was not traced) | pass | RED not shown |
| `A.post.PK` | unchanged | pass (R1a, R1b: no S-PK took, PK unchanged) | red: absent | R2 X-PK, R2 A.post.PK FAIL; R1 does not turn it red |
| `A.post.KEK` | unchanged | pass (R1a, R1b: S-KEK was refused, KEK unchanged) | pass | E:AuthVariableLib.c:417-430; RED not shown |
| `A.post.db` | unchanged | pass (R1a, R1b: S-db was refused, db unchanged) | pass | as above; RED not shown |
| `A.post.dbx` | unchanged | pass | pass | no row writes dbx; RED not shown |
| `reboot.secureboot` | as A0 | pass (R1a, R1b: no write took, so nothing persists) | pass | R1 the edk2 store persists, but no write reached it; R2 U:efi_variable.c:600-605 restores the seed; RED not shown |
| `reboot.setupmode` | as A0 | pass (as above) | pass | as above; RED not shown |
| `reboot.PK` | as A0 | pass (as above) | pass | as above; RED not shown |
| `reboot.KEK` | as A0 | pass (as above) | pass | as above; RED not shown |
| `reboot.db` | as A0 | pass (as above) | pass | as above; RED not shown |
| `reboot.dbx` | as A0 | pass | pass | RED not shown |
| `reboot.efi_test` | absent | pass | pass | RED not shown |
| `reboot.banners` | 2 U-Boot and 2 kernel banners | pass (kernel banners only) | pass | RED not shown (a reset loop is a unit transcript) |
| `uboot.sha256` | before = after = given | n/a | pass (R2 gives its own hash) | RED not shown |
| `probe.runs` | 2 runs, no error line | pass | pass | RED not shown |
| `probe.U-PK` | WRITE_PROTECTED | red: INVALID_PARAMETER | pass | GREEN and R2 U:efi_variable.c:299-301; R1 E22:Variable.c:2880-2887, R1b probe.U-PK |
| `probe.U-KEK` | WRITE_PROTECTED | red: INVALID_PARAMETER | pass | as `probe.U-PK`, R1b probe.U-KEK |
| `probe.U-db` | WRITE_PROTECTED | red: INVALID_PARAMETER | pass | as `probe.U-PK`, R1b probe.U-db |
| `probe.W-db` | WRITE_PROTECTED | red: SECURITY_VIOLATION | pass | R1 E:AuthService.c:2420-2421, R1b probe.W-db |
| `probe.X-PK` | WRITE_PROTECTED | red: INVALID_PARAMETER | pass | R1 E22:AuthService.c:592-600, R1b probe.X-PK |
| `probe.S-db` | WRITE_PROTECTED | red: SECURITY_VIOLATION (refused; the write did not take) | pass | R1 E:AuthVariableLib.c:417-430, R1b probe.S-db; open: H1, H2, and the S-db size limit; RED not shown |
| `probe.S-KEK` | WRITE_PROTECTED | red: SECURITY_VIOLATION (refused; the write did not take) | pass | R1b probe.S-KEK; open: H1 and H2; RED not shown |
| `probe.S-PK` | WRITE_PROTECTED | red: SECURITY_VIOLATION (refused; the write did not take) | pass | R1 E:AuthService.c:784-790, R1b probe.S-PK; open: H1 and H2; RED not shown |
| `probe.L1` | SECURITY_VIOLATION | red: ACCESS_DENIED on edk2; U-Boot gives SECURITY_VIOLATION | pass | GREEN U:efi_boottime.c:2082 (handle kept, probe unloads it); R1 E22:DxeImageVerificationLib.c:2042-2046 (policy 0x04, DENY_EXECUTE_ON_SECURITY_VIOLATION), R1b probe.L1 0x800000000000000f; red by status alone, because S-db did not take, so db never trusts KEK; RED not shown |
| `probe.pre.PK` | status 0, size and CRC of `pk.esl` | pass (R1b: the enrolled PK is the test PK alone) | pass | RED not shown |
| `probe.pre.KEK` | status 0, `kek.esl` | red: template KEKs and ours, 5409 bytes | pass | as `A0.KEK`, R1b probe.pre.KEK |
| `probe.pre.db` | status 0, `db.esl` | red: template CAs and ours, 9001 bytes | pass | as `A0.db`, R1b probe.pre.db |
| `probe.pre.dbx` | NOT_FOUND | red: 1276 bytes | pass | as `A0.dbx`, R1b probe.pre.dbx |
| `probe.post.PK` | as pre | pass (R1b: unchanged) | pass | R1 S-PK was refused; RED not shown |
| `probe.post.KEK` | as pre | pass (R1b: unchanged) | pass | R1 S-KEK was refused; RED not shown |
| `probe.post.db` | as pre | pass (R1b: unchanged) | pass | R1 S-db was refused; RED not shown |
| `probe.post.dbx` | as pre | pass | pass | RED not shown |
| `probe.boot2.PK` | as boot 1 pre | pass (R1b: unchanged) | pass | R1 the edk2 store persists, but no write reached it; R2 U:efi_variable.c:600-605; RED not shown |
| `probe.boot2.KEK` | as boot 1 pre | pass (R1b: unchanged) | pass | as above; RED not shown |
| `probe.boot2.db` | as boot 1 pre | pass (R1b: unchanged) | pass | as above; RED not shown |
| `probe.boot2.dbx` | as boot 1 pre | pass | pass | RED not shown |

## Known limits

- A kernel module that calls `efi.set_variable` directly is not
  exercised; that needs a test kernel with `CONFIG_EFI_TEST`.  U-Boot
  returns `EFI_UNSUPPORTED` (U:efi_variable.c:499-500), from the
  source only.  ADR 0013 decision 3 records it.
- The verdict's unit transcripts are built to the line protocol, one
  per failure case.  The driver's tests also replay recorded console
  logs of local runs (`tests/vm/fixtures/`).  The logs of the GREEN
  and RED runs themselves are not in the tree.
- The seven `dd` rows of R1b have no errno (see the Sources).  The E22
  citations are 202202 source, and the firmware under test is
  edk2-stable202408.
- R1 does not show why edk2 refuses the signed writes (H1 and H2), and
  it shows no write that takes.  Until a run does, the rows marked
  "RED not shown" stay unshown, and the claim that the test catches a
  persisting key change is untested.
