# ADR 0010: Automated Live Validation Suite

## Status

Accepted

## Context

The M4 image is installed on the live test device (2026-08-30), but
validating it is still manual: a person boots it, reads a console,
and signs off.  That never runs in continuous integration (CI) or
after an over-the-air (OTA) update, and says nothing about the next
build.

A probe of the live device found no package database of any kind,
sudo requiring a password with no `NOPASSWD` rule, a read-only
rootfs with only `/etc`, `/var`, `/tmp`, and `/var/tmp` writable,
and root Secure Shell (SSH) login refused.  The project's
development standard requires behavior-driven development (BDD)
here: properties are written as executable Given/When/Then scenarios
before the check bodies exist.  Decided 2026-09-05.

The Analysis of Alternatives (AoA) -- candidates, license tiers,
probe detail -- is in `docs/validation/AOA-VALIDATION.md`.

## Decision

Build an in-repo pytest suite whose checks are Gherkin feature
files, parsed by gherkin-official and compiled to pytest functions
by a generator the repo owns.  Buy pytest, gherkin-official, and
ssh-audit (all MIT).  Reject Cinc Auditor as the runner.

Six files:

- `.mise/lib/validate/target.py` -- Quick Emulator (QEMU) and device
  `Target` implementations.
- `tests/validate/features/*.feature` -- the Gherkin specification.
- `tests/validate/steps.py` -- the step vocabulary.
- `tests/validate/test_features.py` -- the generator.
- `tests/validate/conftest.py` -- fixture, guard, hooks, snapshot.
- `.mise/tasks/validate` -- the entry point (default: emulated).

Root is acquired with `sudo -S -p ''` and the password on stdin,
`id -u` inside the same invocation, so a silently failed escalation
errors rather than reading as a pass.  Ten first-increment checks,
unprivileged first, cover root integrity, SELinux enforcing, Secure
Boot, the `/etc` overlay, no plaintext swap, a clean enforcing boot,
and the committed RAUC slot; then, with root, the process identifier
(PID) 1 SELinux domain, Linux Unified Key Setup (LUKS) 2 `/var` with
a Trusted Platform Module (TPM) 2 token, and Integrity Measurement
Architecture (IMA) in log mode.

Seven rules keep a green run honest: a session identity guard, skips
counted as failures, no matcher passing on empty output, a
negative-control twin scenario per property, `id -u` inside the root
helper, no check passing on a score, and no host or device
identifier in any report artifact.  CI runs the emulated target
only; the live device stays a local target, never reachable from CI.

## Alternatives considered

- **Cinc Auditor.**  Apache-2.0; the operations lens ranked it first
  (4.51 of 5) and dissented.  The probe voids its resource library
  (no package database), its transport opens an SSH session per
  command, and it cannot drive a reboot or a slot switch.  Rejected.
- **Extend the existing drivers.**  Cheapest option: more assertions
  in `smoke_login.py` and more `ssh_run()` calls in `ota_test.py`,
  but no negative control and no before/after OTA diff.  Rejected.
- **bats-core.**  MIT.  A second test paradigm beside the repo's
  existing Python drivers, for no offsetting gain.  Rejected.
- **pytest-testinfra.**  Apache-2.0.  Buys a host abstraction the
  repo already has; same package-resource gap as Cinc.  Rejected.
- **goss.**  Apache-2.0.  Requires copying a Go binary onto a target
  where only `/tmp` is writable.  Rejected.
- **labgrid.**  LGPL-2.1-or-later.  Solves board farms; overkill for
  one device and one emulated target.  Rejected.
- **tmt, with the connect provisioner.**  MIT.  A metadata format
  and provisioner abstraction around the same `ssh` call.  Rejected.
- **OpenSCAP with ComplianceAsCode.**  LGPL-2.1-only scanner,
  BSD-3-Clause content; needs the scanner, Python bindings, and
  libxml2 in a read-only image, and no OpenEmbedded profile matches.
  Rejected.
- **Yocto oeqa runtime tests.**  MIT.  Runs inside bitbake and
  cannot be pointed at an installed device.  Rejected.
- **pytest-bdd.**  MIT.  Passed every functional check but failed a
  clean run under `-W error::DeprecationWarning` on pytest 9 and its
  pinned gherkin-official.  Rejected.
- **tursu.**  MIT.  Generated items skip the conftest hookwrapper, so
  the scrub never runs and the target address leaks into the JUnit
  Extensible Markup Language (XML) report.  Rejected.
- **behave.**  BSD-2-Clause.  No pytest bridge: a skip does not fail
  a run, and there is no scrub hook.  Rejected.
- **Robot Framework.**  Apache-2.0.  Given/When/Then are optional
  prefixes it ignores, not parsed Gherkin; a second runner, no `-k`.
  Rejected.

Avocado, contest, robotframework-sshlibrary, Gauge, radish,
pytest-given, lettuce, freshen, and aloe were surveyed but not
scored: unmaintained, Tier 4 licensed, or no feature-file model.
kernel-hardening-checker audits the kernel `.config` at build time,
out of this decision's scope, and is a candidate follow-up.

## Consequences

- The M5 gate becomes the suite's result on both targets, not a
  person's reading of a console.
- Two new host-side dependencies, both MIT: pytest and
  gherkin-official.  No new image content -- every check body is a
  tool already on the image.
- Adding a check is writing a scenario, and a step function only
  when the vocabulary lacks one.
- Two tripwires: abstractions beyond the six files, or the
  generator past about one hundred lines, should revisit this.
- Goal 2 (OTA regression coverage) is only partly served here; the
  dynamic half stays in `.mise/lib/ota_test.py`, unchanged, and a
  green run is not an OTA guarantee.
- Checks run as `unconfined_t`; a pass is not evidence a confined
  service could do the same thing.
- `systemd-analyze security` stays advisory only: no check may pass
  on a score.
- Two facts stay unconfirmed until a fresh probe: the `rauc`
  JavaScript Object Notation (JSON) schema, and the auditor list,
  both from a prior probe.
- The `scp` helper omits `-O`; the device lacks `sftp-server`, so a
  future `push` must add it.
- `findmnt` and `lsblk` are absent from the base image; mount
  assertions read `/proc/mounts` directly.
