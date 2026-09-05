# AoA: Automated Live Validation Suite

**Status:** Accepted 2026-09-05.  Analysis of Alternatives (AoA) for
the Post-M4 automated validation suite, recorded as Architecture
Decision Record (ADR) 0010
(`docs/adr/0010-automated-live-validation-suite.md`).

**Scope:** how LamaDist asserts, on every build and on both the
emulated target and the live test device, that the image boots,
that nothing regressed (including across an over-the-air (OTA)
update), and that the security properties still hold.  Out of
scope: build-time checks (recipe linting, Software Package Data
Exchange (SPDX) manifests, scanners), which already run elsewhere.

**Decision priority** (set by this AoA; the validation pass has no
SPEC):

1. Trustworthy results.  A green run must mean the property holds.
2. Non-destructiveness.  A validation run must not change the image
   under test or the device state.
3. Two targets, one code path.  The emulated target and the live
   device run the same checks.
4. Small footprint.  Nothing new is added to the image to make
   validation possible.

## 1. Problem and goals

M4 is installed on the live test device (2026-08-30).  Validation
of that image is still manual: a person boots it, reads a console,
and signs off.  That proves one image once.  It does not run in
continuous integration (CI), it does not run again after an OTA
update, and it cannot say whether build N+1 kept what build N had.

Three goals drive the design, used as the scoring lenses in section
5 and as the label on every check in section 7.6:

- **G1, it works.**  The image boots to a usable system: units
  reach a healthy steady state, console and Secure Shell (SSH)
  logins succeed, and `/etc` is writable.
- **G2, nothing breaks, including after OTA.**  The same assertions
  pass before and after a RAUC update, the committed slot is the
  expected one, and a failed update rolls back to a good slot.
- **G3, security stays strong.**  The properties the M4 gate closed
  on -- verity-sealed root, Secure Boot, Security-Enhanced Linux
  (SELinux) enforcing with a real process identifier (PID) 1
  domain, Linux Unified Key Setup (LUKS) 2 `/var` with a Trusted
  Platform Module (TPM) 2 token, no plaintext swap, Integrity
  Measurement Architecture (IMA) in log mode -- are still true on
  the running system, not just in the recipes.

### 1.1 The M4 gate conditions this suite must keep closed

Each first-increment check in section 7.6 names the gate item it
guards:

| Gate item | Where | What it closed |
| --- | --- | --- |
| BLOCKER-1 | `docs/PLAN.md:407` | Plaintext swap partition removed (commit `77783ac`) |
| Stage-B exit | `docs/PLAN.md:412` | Both gate conditions folded in and closed 2026-07-19 |
| Condition B | `docs/PLAN.md:416` | dontaudit-disabled harvest on build 39 |
| Condition A | `docs/PLAN.md:423` | Reconciled into the Condition B fix |
| Read-write `/etc` overlay | `docs/PLAN.md:371` | Overlay was mounting read-only on every boot |

The `/etc` item is why this AoA exists in its present form.  A
dontaudit-hidden `mount_t var_t:dir` denial left `/etc` read-only on
every boot, breaking machine-id persistence, and the gate did not
notice (`.mise/lib/smoke_login.py:21-27`).  A check that only asks
"is the overlay mounted?" would have stayed green through it.  The
design in section 7 is built to catch that failure mode.

## 2. Constraints from the live-device probe

A probe of the running device fixes what any candidate may assume.
The probed image is stale relative to current builds; rows marked
*re-confirm* are true of the probed image and must be re-checked
against a current build before they are relied on.

| ID | Constraint | Consequence |
| --- | --- | --- |
| C1 | `package_db: NONE` -- no rpm, opkg, or dpkg binary and no database | Every candidate's `package` resource is dead weight.  Package-presence assertions are impossible and must not be written. |
| C2 | sudo requires a password: `%wheel ALL=(ALL:ALL) ALL`, no NOPASSWD (`meta-lamadist/classes/lamadist-image.bbclass`, `lamadist_sudoers_wheel()`) | Root is acquired by piping a password to `sudo -S -p ''`.  Any tool that assumes passwordless sudo or a root login fails. |
| C3 | No `sftp-server` on the probed image (*re-confirm*) | `scp` must be forced into legacy protocol mode with `-O`: without it, OpenSSH 9.0 and later negotiate SFTP and fail on a target that lacks `sftp-server`.  `.mise/lib/ota_test.py:132-137` builds its `scp` argv without `-O` today and has only been exercised against the emulated target; that is a latent gap to close (R7), not a precedent to copy.  Anything that hard-requires SFTP is out. |
| C4 | Read-only rootfs; only `/etc` (overlay), `/var`, `/tmp`, and `/var/tmp` are writable | No agent, profile bundle, or runner can be installed into the image.  Anything staged goes to `/tmp` and is removed. |
| C5 | SELinux enforcing, but the login path is `unconfined_t` | Checks run unconfined, so a check passing is not evidence that a confined service could do the same thing.  Do not read check success as policy coverage. |
| C6 | `python3` 3.14.5 is present only as a side effect of the SELinux tooling | On-image Python is not a contract.  No candidate may depend on it.  All Python runs host-side. |
| C7 | Root SSH login is refused: the image creates only the unprivileged `lama` user and root stays locked (`meta-lamadist/classes/lamadist-image.bbclass:17,29-34`) | Confirmed from the recipe, not from the probe.  Transport is always the unprivileged user plus C2. |
| C8 | `findmnt` and `lsblk` are in util-linux split packages that `packagegroup-lamadist-base` does not pull in (`.mise/lib/smoke_login.py:200-204`) | Mount assertions read `/proc/mounts` and `/proc/cmdline` with bash builtins and coreutils. |

Two targets, one code path.  The emulated Quick Emulator (QEMU)
target and the live device both authenticate with a password.
Every image carries the same built-in development password for the
`lama` user (`meta-lamadist/classes/lamadist-image.bbclass:15-17,
29-34`); the test SSH key is baked only into non-release builds
(`.mise/tasks/build:99-105`), so it is not a common denominator and
an installed device may lack it.  Password authentication on both
targets is deliberate: a single credential shape means one
transport implementation, not two.

### 2.1 Native auditors already on the image

The image already carries the tools that answer every
first-increment question.  This is the finding that decides
build-versus-buy.

| Tool | Answers | Evidence |
| --- | --- | --- |
| `bash`, `cat`, `readlink`, `basename` | `/proc/mounts` and `/proc/cmdline` parsing | `.mise/lib/smoke_login.py:200-227` |
| `od`, `tr` | Secure Boot efivar byte | `.mise/lib/smoke_login.py:262-267` |
| `ss` | Listening sockets | `.mise/lib/smoke_login.py:182` |
| `rauc` | Slot and boot state, with `--output-format=json` | `.mise/lib/ota_test.py:236` |
| `sudo` | Root escalation, password on stdin | `.mise/lib/ota_test.py:118-127` |
| `getenforce`, `sestatus` | SELinux mode | probe (*re-confirm*) |
| `cryptsetup` | LUKS2 header and TPM2 token | probe (*re-confirm*); see [cryptsetup-dump] |
| `systemctl`, `journalctl`, `systemd-analyze` | Unit health, boot log, unit exposure | probe (*re-confirm*); see [systemd-analyze] |
| `ausearch` | SELinux access vector cache (AVC) denials | probe (*re-confirm*); see [ausearch] |

`veritysetup` is **not** in this list.  It appears nowhere on the
booted rootfs: every occurrence in `meta-lamadist/` is in the
initramfs or in a comment (`lamadist-uki.bbclass:128,134`,
`recipes-core/initrdscripts/initramfs-framework-dm/dmverity:63`,
`recipes-connectivity/openssh/files/10-genkeys-per-connection.
conf:5`).  It is in neither the probe's present nor its missing
list.  Root integrity is therefore asserted from `/proc/cmdline`
and `/proc/mounts` (section 7.6, check 1), not from `veritysetup
status`.

## 3. Options

| Key | Option | Shape |
| --- | --- | --- |
| A | Custom pytest suite in-repo (BUILD) | Host-side pytest driving the target over SSH; native auditors as check bodies |
| B | Cinc Auditor | Ruby compliance runner, InSpec-compatible domain-specific language (DSL) |
| C | bats-core | Bash test framework, host-side, shelling out |
| D | Point scanners and native auditors | ssh-audit, kernel-hardening-checker, plus the on-image tools |
| E | pytest-testinfra | pytest plugin with a host abstraction |
| F | goss / dgoss | Go binary, YAML Ain't Markup Language (YAML) specs, runs on target |
| G | labgrid | Python board-farm framework with drivers |
| H | tmt with the connect provisioner | Test management tool, Flexible Metadata Format plans |
| I | OpenSCAP plus ComplianceAsCode content | Security Content Automation Protocol (SCAP) scanner |
| J | Yocto oeqa runtime tests | The build system's own runtime test layer |

Option D is not a rival runner.  It is the vocabulary the check
bodies are written in, and every other option consumes it.  It is
scored for completeness in section 5.

## 4. Verified facts

License tiers use the repo ladder: Tier 1 permissive; Tier 2 weak
copyleft; Tier 3 strong copyleft, build tooling only, with a
standalone command-line tool that is never linked into the product
counting as Tier 1; Tier 4 network copyleft and any strong-copyleft
`-or-later` form.  An `-or-later` tag is judged at the strictest
license it can become, so LGPL `-or-later` stays Tier 2 and GPL
`-or-later` becomes Tier 4.  Source and binary tiers are listed
separately because they diverge for B.

| Key | Source license / tier | Binary license / tier | Last release | Execution model |
| --- | --- | --- | --- | --- |
| A | pytest MIT, Tier 1 [pytest-license] | same | pytest 9.1.1, 2026-06-19 [pytest-releases] | Host-side Python; target touched only by SSH command strings |
| B | Apache-2.0, Tier 1 [inspec-license] | **Cinc rebuild of InSpec: Apache-2.0 binaries, Tier 1 [cinc-about]; upstream Progress InSpec binaries carry a commercial end-user license agreement (EULA), not Tier 1 [inspec-license]** | Cinc Auditor images track upstream InSpec: v7.1.7 (image pushed 2026-05-17) and v5.24.24 on the 5.x long-term-support line (2026-06-25) [cinc-tags] | Ruby runner host-side; Train SSH transport opens a session per command [train-ssh] |
| C | MIT, Tier 1 [bats-license] | same | v1.14.0, 2026-07-21 [bats-releases] | Bash; each test is a subshell, no transport of its own [bats-usage] |
| D | ssh-audit MIT, Tier 1 [ssh-audit]; kernel-hardening-checker GPL-3.0-only, Tier 3 by text and Tier 1 as a standalone unlinked tool [khc]; on-image tools ship in the image already | same | ssh-audit v3.9.0, 2026-07-04 [ssh-audit-release]; kernel-hardening-checker v0.6.17.1 tag, 2025-11-01, no formal release [khc] | ssh-audit runs host-side against the target's SSH port; on-image tools run on target |
| E | Apache-2.0, Tier 1 | same | pytest-testinfra 10.2.2, 2025-03-30; upstream carries a maintainer notice that the project is not actively maintained [testinfra-pypi] | pytest plugin; SSH backend shells out to the `ssh` binary [testinfra-backends] |
| F | Apache-2.0, Tier 1 [goss-license] | same | v0.4.10, 2026-07-26, after a 22-month gap since v0.4.9 (2024-09-26) [goss-releases] | Static Go binary **copied onto the target** and executed there [goss-releases] |
| G | LGPL-2.1-or-later, Tier 2 (its upgrade path stays weak copyleft) [labgrid-license] | same | v26.0, 2026-06-22 [labgrid-releases] | Python framework; drivers for QEMU and SSH [labgrid-qemudriver], [labgrid-sshdriver] |
| H | MIT, Tier 1 [tmt-license] | same | tmt 1.78.0, 2026-08-31, roughly monthly releases [tmt-releases] | Python; connect provisioner drives an existing host over SSH [tmt-connect] |
| I | OpenSCAP LGPL-2.1-only, Tier 2 (`ext/meta-security/recipes-compliance/openscap/openscap_1.4.3.bb:7`); ComplianceAsCode content BSD-3-Clause, Tier 1 [cac-license] | same | OpenSCAP v1.4.4 and v1.3.14, both 2026-04-09 [openscap-releases]; ComplianceAsCode content v0.1.82, 2026-09-01 [cac-releases] | `oscap` binary **on the target**, or `oscap-ssh` wrapping it; consumes Extensible Configuration Checklist Description Format (XCCDF) and Open Vulnerability and Assessment Language (OVAL) content |
| J | MIT, Tier 1 (poky) | same | `yocto-6.0.1-118-gc2746a4a16`, HEAD 2026-06-29, wrynose [yocto-releases] | Runs inside the build system; needs a bitbake environment |

Facts that decide the outcome, each traceable:

- **B's `package` resource is inert here.**  InSpec's package
  resource dispatches to rpm, dpkg, or a platform equivalent
  [inspec-package]; C1 says none exists.  The dev-sec baselines
  that make B attractive lean on it heavily [devsec-linux],
  [devsec-ssh].
- **B's transport opens a session per command** [train-ssh].  On
  the first increment that is roughly one SSH session per
  assertion, against a device reached over the network.
- **B's binaries are the tier question, not its source.**  Cinc
  exists precisely because upstream InSpec binaries are not freely
  redistributable [cinc-about], [inspec-license].  Using B means
  committing to the Cinc rebuild specifically, and tracking it.
- **F must write to the target.**  The goss binary is copied to the
  host under test.  C4 leaves `/tmp` as the only landing zone, and
  goss's own package resource has the same C1 problem
  [goss-package].
- **E's SSH backend shells out per command** [testinfra-base], and
  its backends are documented as command-oriented
  [testinfra-backends].  Its long-standing gap on non-package-
  managed systems is tracked upstream [testinfra-368].
- **I needs `oscap` on the target or over `oscap-ssh`.**  The
  recipe exists in `ext/meta-security` but nothing in
  `meta-lamadist` installs it.  Adopting I means adding a scanner,
  its Python bindings, and libxml2 to a read-only hardened image
  (C4).  There is no OpenEmbedded profile that matches LamaDist:
  the product exists upstream [cac-oe-product] but its profile set
  is thin [cac-oe-profiles].
- **J runs inside bitbake.**  It cannot be pointed at an installed
  device, which is the whole point of this suite.
- **A adds two runtime dependencies.**  pytest, MIT
  [pytest-license], and gherkin-official, MIT [gherkin-official].
  The repo already runs Python drivers (`.mise/lib/ota_test.py`,
  `.mise/lib/smoke_login.py`) and has no Python or Ruby linter
  configured: `.config/hk.pkl:9-33` defines eight linters
  (`trailing-whitespace`, `newlines`, `check-merge-conflict`,
  `shellcheck`, `yamllint`, `actionlint`, `hadolint`, and
  `kas-schema`), none of which touch Python or Ruby.  A adds no
  lint surface; B would add an unlinted Ruby surface.

## 5. Scoring

Three lenses scored the ten options independently.  Scores are
advisory: they rank options, they do not decide.  The merged column
is the unweighted mean of the three lens scores; per-lens rank is
in parentheses.

| Key | Option | Assurance | Simplicity | Operations | Mean | Rank |
| --- | --- | --- | --- | --- | --- | --- |
| A | Custom pytest | 3.97 (1) | 4.65 (2) | 4.24 (3) | **4.29** | 1 |
| C | bats-core | 3.74 (3) | 3.85 (3) | 4.33 (2) | 3.97 | 2 |
| D | Point tools | 3.37 (4) | 5.00 (1) | 3.19 (8) | 3.85 | 3 |
| B | Cinc Auditor | 3.92 (2) | 3.10 (6) | 4.51 (1) | 3.84 | 4 |
| G | labgrid | 2.98 (5) | 3.30 (5) | 3.50 (6) | 3.26 | 5 |
| E | pytest-testinfra | 2.51 (7) | 3.35 (4) | 3.83 (4) | 3.23 | 6 |
| F | goss | 2.79 (6) | 2.80 (7) | 3.50 (6) | 3.03 | 7 |
| H | tmt connect | 1.83 (9) | 2.80 (7) | 3.73 (5) | 2.79 | 8 |
| I | OpenSCAP | 2.08 (8) | 1.55 (10) | 2.39 (9) | 2.01 | 9 |
| J | oeqa | 0.96 (10) | 1.85 (9) | 2.03 (10) | 1.61 | 10 |

Option D is ranked and averaged with the rest for completeness, but
it is not a rival: it is the check vocabulary that A, B, C, E, and H
all call.  Its simplicity score of 5.00 says the on-image tools are
the simplest possible answer, which argues *for* A, not against it.

Where the lenses disagree:

- **Assurance** put A first (3.97) and B a close second (3.92).  A
  wins on the ability to write a negative control -- a check that
  proves the check can fail -- which B's declarative DSL makes
  awkward.
- **Simplicity** put A a distant second to D and ranked B sixth
  (3.10).  A Ruby runtime, a DSL, and a profile bundle to assert
  facts that `cat /proc/cmdline` already answers is the definition
  of a middleman.
- **Operations** put B **first** (4.51) and A third (4.24), and
  recommended Cinc Auditor as the primary tool.  Its reasoning is
  real: B gives reporting, waivers, and a profile format for free,
  and those are the parts a hand-rolled suite gets wrong.

## 6. Recommendation

**BUILD an in-repo pytest suite (Option A) whose checks are Gherkin
feature files.  BUY pytest (MIT) and gherkin-official (MIT), and
adopt ssh-audit from Option D as a separate host-side check.
Reject B as the runner.**

Build-versus-buy, stated plainly: the parts worth buying are a test
runner, a Gherkin parser, and an SSH posture scanner, and all three
are already available at Tier 1 with no image footprint.  The part
not worth buying is a compliance framework, because the compliance
framework's value is its resource library, and C1 through C8
disable most of it.  What is left after the resources are removed
is a Ruby runtime and a DSL wrapping `ssh <host> '<command>'`, which
is what `.mise/lib/ota_test.py:96` already does in twenty lines.

### 6.1 Is Cinc Auditor still the best option?

**No.**

Cinc Auditor was a reasonable first choice: a mature, Apache-2.0,
Tier 1 compliance runner with baselines that look like exactly this
job [devsec-linux], [devsec-ssh].  The live-device probe is what
changed the answer:

1. **No package database (C1)** removes the largest slice of the
   resource library [inspec-package], which is the value being
   bought.
2. **A session per command** [train-ssh] is a poor fit for a device
   over the network when the alternative reuses one connection.
3. **The binary-tier split is real work.**  Only the Cinc rebuild
   is Tier 1 [cinc-about]; upstream binaries are not
   [inspec-license].  That is a supply-chain commitment to be
   tracked, renewed, and pinned.
4. **The Ruby surface is unlinted.**  `.config/hk.pkl:9-33` has no
   Ruby linter and no Python linter, but the repo already reads and
   reviews Python; Ruby would be a second unpoliced language.
5. **Two of three lenses rank it below A.**  Assurance ranks A
   above B, and simplicity ranks B sixth.

**Named dissent.**  The operations lens ranked B first (4.51) and
recommended it as primary.  This AoA overrides that lens, and the
reason is inside its own composition: even that lens's proposal
leaves every OTA transition and every serial-console transition to
the existing Python drivers, because Cinc cannot drive a reboot, a
slot switch, or a getty login.  A Cinc-primary design is therefore
not one runner; it is two, with the harder half still hand-written
in Python.  Buying B does not remove the Python; it adds Ruby
beside it.

The operations lens is right about what it valued.  Reporting,
waivers, and a stable profile format are the parts a hand-rolled
suite gets wrong, and section 7.5 answers each of them with a
concrete, small mechanism rather than by dismissing the concern.

### 6.2 The minimal variant, and why it is not enough

The laziest defensible option is: no new suite at all.  Extend
`.mise/lib/smoke_login.py` with more `expect()` assertions and add
more `ssh_run()` calls to `.mise/lib/ota_test.py`.  Cost: near
zero.  No new dependency, no new files, no new task.

It is rejected for three specific reasons, not on principle:

- **No negative controls.**  A serial `expect()` that never matches
  cannot be distinguished from a check that was never reached.  The
  read-only `/etc` defect is exactly this class.
- **No structure to diff.**  G2 needs the same assertions run
  before and after an OTA and compared.  A pass/fail exit code and
  a transcript cannot be diffed; a keyed snapshot can.
- **No selection.**  A single monolithic script cannot run one
  property, cannot skip the device-only checks on the emulated
  target, and cannot report which of fourteen properties failed.

The suite is the minimal thing that fixes those three, and no more:
one library module, the feature files, one step table, one
generator, one fixture file, and one task.

pytest rather than a hand-rolled runner, because the design uses
four of its features directly: markers generated from scenario
tags, `-k` and `-m` selection of a single property, `--junitxml`,
and the `conftest.py` hooks that enforce rules 1, 2, and 7 in
section 7.5.  Each would otherwise be hand-written.  It is
installed through the `uv` tool the mise configuration already pins
(`.mise.toml:17`), so it adds no new tool manager.

### 6.3 Executable specifications: the Gherkin layer

The project's development standard requires behavior-driven
development (BDD) at this layer; that requirement was one of the
original drivers toward Cinc Auditor.  It is met inside the pytest
suite: the properties are Gherkin feature files, and a generator
compiles them into pytest test functions, so the scenarios are the
specification and the sign-off document.

The survey covered behave, pytest-bdd, tursu, radish, Robot
Framework, Gauge, pytest-given, lettuce, freshen, and aloe.  It
also covered the Cucumber reference runners for Ruby, the Java
Virtual Machine (JVM), and JavaScript, which are not Python
runners and were carried no further.  Three candidates -- the
owned generator, pytest-bdd, and tursu -- were run by hand under
pytest 9.1.1 on Python 3.14.6 against one fixture of three
scenarios: a plain scenario, a scenario outline with two example
rows, and a scenario that skips.  Robot Framework was run under its
own runner against an equivalent Robot spec carrying the same three
scenarios.  behave was evaluated from its source.  The pass
criteria were the section 6.2 features and the section 7.5 hooks
the design depends on: tag selection, a skip that fails the
session, the scrub before JUnit output, a warning-free run, and
`-k` selection of one example row.

| Candidate | License, release | Tags select | Skip fails session | Scrub before JUnit | `-W error` clean | `-k` on an example row | Own code, spec excluded |
| --- | --- | --- | --- | --- | --- | --- | --- |
| gherkin-official 42.0.1 with an owned generator | MIT, 2026-08-05, twelve releases in the prior year [gherkin-official] | pass | pass | pass | pass | pass | 96 lines: 52 generator, 26 step table, and 18 conftest |
| pytest-bdd 8.1.0 | MIT, 2024-12-05 [pytest-bdd] | pass | pass | pass | fail: two `PytestRemovedIn10Warning` on pytest 9 [pytest-bdd-823], plus a `DeprecationWarning` from the pinned gherkin-official 29 on Python 3.14 | pass | two `filterwarnings` lines |
| tursu 1.1.0 | MIT, 2026-03-02, one maintainer [tursu] | pass | pass | fail: a `pytest_runtest_makereport` hookwrapper in `conftest.py` never fires for its generated items | pass | fail: identifiers carry the row index, not the values | package layout with `__init__.py` |
| Robot Framework 7.4.2 | Apache-2.0, 2026-03-03 [robot-releases] | pass, `--include` | pass, listener v3 | pass, `log_message` | pass, in its own process | no `-k` | 138 lines: 59 keywords, 45 listener, and 34 second-runner glue |
| behave 1.3.3 | BSD-2-Clause, 2025-09-04 [behave] | `--tags` | not built in: `--strict` is commented out [behave-config] | no report hook | not applicable | no `-k` | a second runner with every hook rewritten |

Robot Framework and behave are standalone runners.  Their scenarios
run in a second process with a second exit code, outside every
`conftest.py` hook in section 7.5, and `mise run validate` becomes
two runners with two results to merge.  Robot Framework does not
parse Gherkin at all: Given, When, and Then are optional prefixes
that it ignores when matching keywords [robot-bdd].  Gauge
specifications are Markdown, not Gherkin, and Given/When/Then are
free-text step lines rather than parsed structure [gauge].  radish
is a standalone runner with its own parser.  pytest-given keeps
Given/When/Then inside Python with no feature file.  lettuce,
freshen, and aloe are unmaintained.

gherkin-official is the Cucumber project's reference Gherkin parser
for Python.  Its `Parser` returns the syntax tree, and its bundled
`Compiler` expands scenario outlines, prepends background steps,
and inherits tags into pickles [gherkin-compiler].  Everything the
suite needs after that is one loop: name the pickle, apply its tags
as markers, and dispatch each step text through a table of regular
expressions.  The measured cost is 52 lines of generator, 26 of
step table, and 18 of `conftest.py`, and the run is clean under
`-W error::DeprecationWarning`.  The package describes itself as "a
parser and compiler for the Gherkin language" [gherkin-readme], not
as a BDD tool.  The suite is BDD by construction, because the
scenarios are written first and are the specification.

## 7. Architecture

### 7.1 Repo layout

```text
.mise/lib/validate/
    target.py          # Target protocol, QemuTarget, DeviceTarget
tests/validate/
    features/
        *.feature      # the specification: one scenario per property
    steps.py           # step vocabulary: regex -> callable, no framework
    test_features.py   # generator: feature files -> pytest functions
    conftest.py        # target fixture, session guard, hooks, snapshot
.mise/tasks/validate   # mise task entry point
```

Six files, counting the feature directory as one.  There is no
`properties.py`, no `evidence.py`, and no `report.py`.  The check
registry is the feature files: each scenario carries its identifier,
goal, root requirement, and target restriction as tags, its gate
reference in its name, its command and matcher as steps, and its
negative control as a twin scenario.  Evidence is the `Result` tuple the
target already returns, and the report is pytest's own JavaScript Object
Notation (JSON) snapshot hook in `conftest.py` plus `--junitxml`.

`features/*.feature` is the design.  `test_features.py` parses each
file with gherkin-official's `Parser`, expands it with its
`Compiler`, and defines one pytest function per pickle: tags become
markers, example-row values go into the node identifier so `-k`
selects one row, and each step text is dispatched through the
regular-expression table in `steps.py`.  An unmatched step fails
the test.  Adding a check is writing a scenario, not writing a
test.

### 7.2 The Target abstraction

```python
class Target(Protocol):
    name: str
    def run(self, cmd: str) -> Result: ...       # unprivileged
    def run_root(self, cmd: str) -> Result: ...  # sudo -S -p ''
    def reboot(self) -> None: ...
    def wait_ready(self, timeout: float) -> None: ...
```

Four operations.  There is deliberately no `push`: nothing in the
first increment copies a file to the target, and C4 means nothing
should.  `push` is added when checks 11 and later need it -- the
post-OTA bundle staging path -- and not before.  When it is added
it wraps the existing `scp_to_guest()`
(`.mise/lib/ota_test.py:132-137`), which must gain `-O` before it
is reused (C3, R7).

`QemuTarget` and `DeviceTarget` differ in exactly two ways: how the
host and port are resolved, and whether `reboot()` can also drive a
serial console.  `SSH_HOST` is hardcoded at
`.mise/lib/ota_test.py:48` with no `--host` flag; the suite
parameterizes it, and the device's address comes from an untracked
local configuration file, never from the repo.

### 7.3 Root acquisition

C2 forbids passwordless sudo and C7 forbids root SSH.  `run_root()`
follows the existing pattern at `.mise/lib/ota_test.py:118-127`:

```python
f"sudo -S -p '' sh -c {shlex.quote('id -u; ' + command)}"
```

with the password written to stdin.  The `id -u` is inside the sudo
invocation, not beside it.  If the first line of output is not `0`,
the check errors -- it does not fail and it does not pass.  A sudo
prompt swallowed by `-p ''` and an empty stdout are then
distinguishable, which they are not today.

### 7.4 Design rules the layout enforces

- **Unprivileged first.**  Seven of the ten first-increment checks
  need no root.  They are ordered first so that a broken sudo path
  degrades to a partial pass with seven real results, not to a
  total error.
- **No package database.**  No check may ask what is installed
  (C1).  Presence is asserted by behavior -- the binary runs, the
  mount exists, the socket listens -- never by a package query.
- **Read-only rootfs.**  No check writes to the image.  Anything
  staged goes to `/tmp` and is removed in a fixture teardown (C4).
- **Structured over text.**  Prefer a parseable form where one
  exists.  `rauc status --output-format=json` is used with the
  caveat already recorded at `.mise/lib/ota_test.py:242`: the field
  names and nesting are unconfirmed against the shipped RAUC
  version, so the parser must fail loudly on an unexpected shape
  rather than defaulting a missing field to a pass.

### 7.5 Anti-false-green rules

These are the mechanisms answering the operations lens's concerns
about a hand-rolled suite.

1. **Session identity guard.**  A session-scoped fixture records
   the target's root hash and version and asserts they match the
   artifact under test.  A suite that silently validated
   yesterday's image is the worst possible failure.
2. **Skips are failures.**  Markers are generated from scenario
   tags.  The marker vocabulary is a fixed tuple that
   `pytest_configure` in `conftest.py` registers, and the task
   passes `--strict-markers`, so a tag outside the vocabulary is a
   collection error instead of a silently disabled check.  A
   `pytest_sessionfinish` hook in `conftest.py` fails the session
   when the skipped count is non-zero in a full run.  A property
   that could not be evaluated is not a property that holds.
3. **Empty is not pass.**  Every matcher must match non-empty
   output.  A regex over an empty string that happens not to find
   the bad pattern is an error, not a pass.
4. **Negative controls.**  Each property scenario has a
   negative-control twin -- a scenario that feeds the same matcher
   an input it must reject, and passes only when the matcher
   rejects it.  The generator fails collection when a property
   scenario has no twin.  This is what catches the read-only
   `/etc` class: the matcher for check 4 must reject an options
   string beginning `ro,`.
5. **`id -u` inside the root helper.**  See 7.3.
6. **Scores are advisory.**  No check may pass on a numeric score
   or a grade.  A check asserts a specific fact or it is advisory
   and labeled so.
7. **No site details in any output.**  JUnit Extensible Markup
   Language (XML), the JSON snapshot, pytest node identifiers, and
   captured `ssh`/`scp` stderr must contain no hostname, address,
   media access control address, or serial number.  The target
   fixture substitutes the literal `device` or `qemu` for the
   resolved address in every identifier and every captured stream
   before pytest sees it.  This is enforced by a conftest hook, not
   by discipline, because CI artifacts are the leak path.

### 7.6 The first ten checks

Ordered unprivileged-first.  Every row names its goal and the gate
item it guards.

| # | Property | Goal | Assertion | Root | Guards |
| --- | --- | --- | --- | --- | --- |
| 1 | P1 Root integrity | G3 | `/proc/cmdline` has `root=/dev/mapper/rootfs` and a non-empty `roothash=`; `/proc/mounts` shows `/` as `erofs` on that mapper | no | Stage-B exit (`PLAN.md:412`) |
| 2 | P5 SELinux enforcing | G3 | `getenforce` is `Enforcing` **and** `sestatus` agrees on mode and policy name | no | `PLAN.md:412,416` |
| 3 | P2 Secure Boot | G3 | Byte 5 of the `SecureBoot` efivar is `1`, read in-guest | no | Stage-B exit (`PLAN.md:412`) |
| 4 | P8 `/etc` overlay | G1, G3 | `/proc/mounts` shows `/etc` as `overlay` **and** its options begin `rw,` | no | `PLAN.md:371,416` |
| 5 | P9 No plaintext swap | G3 | `/proc/swaps` has its header and no data lines; no swap unit is active | no | BLOCKER-1 (`PLAN.md:407`, commit `77783ac`) |
| 6 | P6 Clean enforcing boot | G1, G2 | `systemctl is-system-running` is `running`; `systemctl --failed` lists none | no | Health predicate for every other check |
| 7 | P11 Committed slot | G2 | `rauc status --output-format=json` reports the expected booted slot as good and committed | no | OTA baseline |
| 8 | P7 PID 1 domain | G3 | `/proc/1/attr/current` is a real domain, never `kernel_t` | yes | Condition B (`PLAN.md:416`) |
| 9 | P4 LUKS2 `/var` | G3 | `cryptsetup luksDump` on the `/var` backing device shows LUKS2 and a TPM2 token; the mapper's dm uuid contains `LUKS2` | yes | Stage-B TPM2 (`PLAN.md:412`) |
| 10 | P14 IMA log mode | G3 | `/proc/cmdline` has `ima_policy=tcb` and `ima_appraise=log`; the measurement list is non-empty | yes | Stage-B exit (`PLAN.md:412`) |

Check 3 is unprivileged.  `.mise/lib/smoke_login.py:258-269` already
reads that efivar as the `lama` user after login, so no elevation
is needed and none is taken.  An earlier draft marked it root; that
was wrong and it also broke the unprivileged-first ordering in 7.4.

Console and SSH login (G1) are not separate rows: checks 1 through
7 running at all is the proof, and the serial path stays covered by
the existing `.mise/lib/smoke_login.py`.

**`systemd-analyze security` is not in the ten.**  Its own manual
page states that a high exposure level proves neither absent
sandboxing nor an actual vulnerability [systemd-analyze].  It is a
score, and rule 6 in section 7.5 forbids passing on a score.  It
lands in a later increment as an explicitly advisory check whose
result is recorded and never gates.

**ssh-audit is the eleventh check, and it earns its place by need,
not by cost.**  No recipe in `meta-lamadist` touches `sshd_config`,
so the image's SSH posture -- key exchange, ciphers, host key
types, whether password authentication is on -- is asserted nowhere
today.  That is a gap, not a nice-to-have.  ssh-audit is MIT
[ssh-audit], runs host-side against the target's port, and adds
nothing to the image.  Its output is a graded report, so per rule 6
it is consumed as specific algorithm assertions, not as a grade.

**kernel-hardening-checker is not adopted here, and license is not
the reason.**  It is GPL-3.0-only by text, but as a standalone tool
that is never linked into the product it counts as Tier 1 under the
repo ladder (section 4).  It runs host-side against the build's
kernel `.config`, before any target exists, which makes it a
build-time check and out of this AoA's scope.  It is a candidate
follow-up beside the scanners overlay (`kas/scanners/`), not a
check in this suite.

### 7.7 Goal 2 coverage, stated plainly

The first increment does **not** fully exercise G2.  Check 6 and
check 7 give a static baseline: the system is healthy and the
expected slot is committed.  The dynamic half -- install, reboot,
mark-good, and rollback -- stays where it already works, in
`.mise/lib/ota_test.py`, unchanged by this increment.

What the suite adds for G2 arrives when the task is run twice
around an OTA and the two JSON snapshots are diffed.  That is a
small step because the snapshot is keyed by property id, but it is
a step, and it is not in the first increment.  Checks that are
genuinely new for G2 -- the untouched-good-slot assertion and the
refusal of a bundle signed by the wrong certificate authority (CA)
-- are checks 12 and 13.

Until those land, G2 rests on the existing OTA driver.  Nobody
should read a green first-increment run as an OTA guarantee.

### 7.8 The mise task

```text
mise run validate                  # emulated target, all checks
mise run validate --target device  # live device
mise run validate -m P8            # one property, by tag
mise run validate -m root          # only the checks that need root
```

The task resolves credentials through the existing secret
mechanism, never from the repo, and defaults to the emulated target
so that the safe thing is the default.

### 7.9 CI wiring

CI runs the emulated target only.  The live device is a local
target, run by hand or by a local runner; it is not reachable from
CI and must not be made reachable.  This matches the working
constraint in `docs/PLAN.md` that CI and test infrastructure use
Podman, QEMU, static analysis, and unit tests only.

Secrets are masked at the source: the development password is a
masked CI secret even though it is baked into the image, so that no
future change to that image quietly starts printing a real
credential.  Follow the masked-secret pattern the build job already
uses for its site-configuration values
(`.github/workflows/ci.yml:182-187`): repository secrets referenced
as scoped step environment variables, never plain workflow
variables, degrading gracefully when unset.  Combined with rule 7
in section 7.5, a published CI artifact contains property
identifiers, pass and fail states, and matcher output -- and no
address, no hostname, and no credential.

## 8. Rejected options

| Key | Reason |
| --- | --- |
| B Cinc Auditor | C1 removes the resource library that is the value being bought [inspec-package]; a session per command [train-ssh]; a Tier 1 binary story that holds only for the Cinc rebuild [cinc-about] versus a commercial EULA upstream [inspec-license]; and a second unlinted language (`.config/hk.pkl:9-33`).  See 6.1, including the operations-lens dissent. |
| C bats-core | Ranked second overall and is a genuinely good fit for shelling out.  Rejected because the repo's existing drivers are Python, the step vocabulary is Python functions, and adding bash tests beside Python drivers is a second paradigm for no gain. |
| E pytest-testinfra | Buys a host abstraction the repo already has in `.mise/lib/ota_test.py`, and its package resource has the C1 problem [testinfra-368].  The SSH backend shells out per command [testinfra-base]. |
| F goss | Must be copied onto the target.  C4 leaves only `/tmp`, and putting an executable there on a hardened read-only image to test that image is a bad trade [goss-releases], [goss-package]. |
| G labgrid | Solves board farms: power control, serial multiplexing, many boards.  There is one device and one emulated target.  The framework is bigger than the problem [labgrid-config]. |
| H tmt | The connect provisioner would work [tmt-connect], but Flexible Metadata Format plans plus a provisioner abstraction is machinery around the same `ssh` call. |
| I OpenSCAP | Requires putting a scanner, Python bindings, and libxml2 into a read-only hardened image (C4).  No OpenEmbedded profile matches LamaDist [cac-oe-product], [cac-oe-profiles].  Content is Tier 1 [cac-license] and OpenSCAP is Tier 2 (`openscap_1.4.3.bb:7`), so licensing is not the obstacle; footprint is. |
| J oeqa | Runs inside bitbake.  Cannot be pointed at an installed device, which is the requirement. |

Surveyed and not scored: Avocado is GPL-2.0-or-later and contest is
GPL-3.0-or-later, both Tier 4 under the repo ladder
[avocado-license], [contest]; robotframework-sshlibrary last
released 2021-11-18 [sshlibrary].  None reached the option list.
Also dispositioned in the long-tail survey: Serverspec, the
superseded predecessor of InSpec with issues disabled upstream;
Molecule and kitchen-ci, which manage an ephemeral instance
lifecycle that `mise run vm` already owns; Fuego, with no locatable
maintained canonical repository; KernelCI and Testing Farm,
board-farm federation and a hosted provisioning service, out of
proportion to one device plus an emulated target; ShellSpec,
redundant with bats-core; and Yocto ptest, per-recipe upstream unit
tests that answer a different question and inherit oeqa's bitbake
dependency.

The Gherkin toolchain candidates are dispositioned in section 6.3,
not here: pytest-bdd, tursu, behave, Robot Framework, radish,
Gauge, pytest-given, and the unmaintained lettuce, freshen, and
aloe.  Robot Framework and behave are the two that would have
displaced pytest as the runner, and both are rejected there for
running scenarios in a second process, outside every `conftest.py`
hook in section 7.5.

## 9. Risks and open questions

| ID | Risk | Mitigation |
| --- | --- | --- |
| R1 | The probe ran against a stale image.  Rows marked *re-confirm* in sections 2 and 2.1 may be wrong. | Re-probe against a current build before increment 1 merges.  Every check errors loudly on a missing binary rather than skipping. |
| R2 | The `rauc --output-format=json` schema is unconfirmed (`.mise/lib/ota_test.py:242`). | Check 7's parser fails on an unexpected shape.  No field defaults to a pass. |
| R3 | Checks run as `unconfined_t` (C5), so passing proves nothing about confined services. | Documented in C5 and repeated here.  Confined-domain assertions are a separate future property, not a variation on these checks. |
| R4 | Two targets drift: a check passes on the emulated target and fails on the device, or the reverse. | Both run the same feature files.  Any check that cannot run on both is tagged target-specific, and the count of target-specific checks is reported. |
| R5 | Credentials or site addresses leak into a CI artifact. | Section 7.5 rule 7 is a conftest hook, plus masked secrets (7.9). |
| R6 | The suite becomes the thing being maintained instead of the image. | Six files, two dependencies, and checks as scenarios.  If the suite needs its own abstractions, that is the signal to stop. |
| R7 | The existing `scp` path omits `-O` (C3) and has only run against the emulated target. | Add `-O` when `push` is introduced; it is harmless where `sftp-server` exists.  Re-confirm the absence of `sftp-server` on a current build (R1). |
| R8 | The feature-file generator is bespoke: 52 lines the repo maintains that a plugin would otherwise own (6.3). | It wraps the reference parser and does nothing a Cucumber pickle does not describe; ceiling about one hundred lines.  A maintained Gherkin-to-pytest plugin that runs warning-free on the pinned pytest is the trigger to swap it in, with the feature files and step vocabulary unchanged. |

Open questions:

- Does the current image carry `cryptsetup`, `ausearch`, and
  `sestatus`?  Check 9 and the later AVC checks depend on it (R1).
- Should the device target run in CI at all, ever?  This AoA says
  no.  If that changes, the network path and the secret handling
  need their own decision.
- Is password authentication acceptable long term, or should the
  suite move to the test key once every installed image bakes it?
  A split (key on one target, password on the other) would mean
  two transport paths (priority 3).

## 10. Decisions the owner must make

Decision 1 was taken on 2026-09-05.  Decisions 2 through 6 remain
open; none blocks the design of increment 1, and they are kept here
so that each acceptance is explicit.

1. **Accept the recommendation**: build Option A with Gherkin
   feature files as the checks (6.3), buy pytest, gherkin-official,
   and ssh-audit, reject Cinc as the runner -- knowing the
   operations lens dissented and recommended Cinc as primary (6.1).
   **Taken 2026-09-05.**
2. **Accept that goal 2 is only partly covered by increment 1**
   (7.7), with the dynamic OTA half staying in
   `.mise/lib/ota_test.py` until checks 12 and 13 land.
3. **Confirm the M5 gate is the suite's result**, not a person's
   reading of a console -- that is, that increment 1 green on both
   targets replaces the manual sign-off entirely.
4. **Confirm CI runs the emulated target only** and the live device
   stays local (7.9).
5. **Confirm the credential shape**: password authentication on
   both targets, one code path (section 2, open question 3), rather
   than the test key on the emulated target and a password on the
   device.
6. **Confirm `systemd-analyze security` is advisory forever**, not
   merely deferred (7.6).

## References

Link targets for the citations above.

[avocado-license]: https://raw.githubusercontent.com/avocado-framework/avocado/master/LICENSE
[ausearch]: https://manpages.debian.org/testing/auditd/ausearch.8.en.html
[bats-license]: https://raw.githubusercontent.com/bats-core/bats-core/master/LICENSE.md
[bats-releases]: https://api.github.com/repos/bats-core/bats-core/releases/latest
[bats-usage]: https://raw.githubusercontent.com/bats-core/bats-core/master/docs/source/usage.md
[behave]: https://pypi.org/project/behave/
[behave-config]: https://raw.githubusercontent.com/behave/behave/main/behave/configuration.py
[cac-license]: https://raw.githubusercontent.com/ComplianceAsCode/content/master/LICENSE
[cac-oe-product]: https://raw.githubusercontent.com/ComplianceAsCode/content/master/products/openembedded/product.yml
[cac-oe-profiles]: https://api.github.com/repos/ComplianceAsCode/content/contents/products/openembedded/profiles
[cac-releases]: https://github.com/ComplianceAsCode/content/releases
[cinc-about]: https://cinc.sh/about/
[cinc-tags]: https://hub.docker.com/r/cincproject/auditor/tags
[contest]: https://github.com/RHSecurityCompliance/contest
[cryptsetup-dump]: https://www.man7.org/linux/man-pages/man8/cryptsetup-luksDump.8.html
[devsec-linux]: https://github.com/dev-sec/linux-baseline
[devsec-ssh]: https://github.com/dev-sec/ssh-baseline
[gauge]: https://raw.githubusercontent.com/getgauge/gauge/master/README.md
[gherkin-compiler]: https://raw.githubusercontent.com/cucumber/gherkin/main/python/src/gherkin/pickles/compiler.py
[gherkin-official]: https://pypi.org/project/gherkin-official/
[gherkin-readme]: https://raw.githubusercontent.com/cucumber/gherkin/main/README.md
[goss-license]: https://raw.githubusercontent.com/goss-org/goss/master/LICENSE
[goss-package]: https://raw.githubusercontent.com/goss-org/goss/master/system/package.go
[goss-releases]: https://api.github.com/repos/goss-org/goss/releases
[inspec-license]: https://github.com/inspec/inspec/blob/main/docs-chef-io/content/inspec/license.md
[inspec-package]: https://raw.githubusercontent.com/inspec/inspec/main/lib/inspec/resources/package.rb
[khc]: https://github.com/a13xp0p0v/kernel-hardening-checker
[labgrid-config]: https://labgrid.readthedocs.io/en/latest/configuration.html
[labgrid-license]: https://github.com/labgrid-project/labgrid/blob/master/LICENSE
[labgrid-qemudriver]: https://raw.githubusercontent.com/labgrid-project/labgrid/master/labgrid/driver/qemudriver.py
[labgrid-releases]: https://api.github.com/repos/labgrid-project/labgrid/releases
[labgrid-sshdriver]: https://raw.githubusercontent.com/labgrid-project/labgrid/master/labgrid/driver/sshdriver.py
[openscap-releases]: https://api.github.com/repos/OpenSCAP/openscap/releases
[pytest-bdd]: https://pypi.org/project/pytest-bdd/
[pytest-bdd-823]: https://github.com/pytest-dev/pytest-bdd/issues/823
[pytest-license]: https://raw.githubusercontent.com/pytest-dev/pytest/main/LICENSE
[pytest-releases]: https://github.com/pytest-dev/pytest/releases
[robot-bdd]: https://raw.githubusercontent.com/robotframework/robotframework/master/doc/userguide/src/CreatingTestData/CreatingTestCases.rst
[robot-releases]: https://github.com/robotframework/robotframework/releases
[ssh-audit]: https://raw.githubusercontent.com/jtesta/ssh-audit/master/README.md
[ssh-audit-release]: https://api.github.com/repos/jtesta/ssh-audit/releases/latest
[sshlibrary]: https://pypi.org/project/robotframework-sshlibrary/
[systemd-analyze]: https://manpages.debian.org/testing/systemd/systemd-analyze.1.en.html
[testinfra-368]: https://github.com/pytest-dev/pytest-testinfra/issues/368
[testinfra-backends]: https://raw.githubusercontent.com/pytest-dev/pytest-testinfra/main/doc/source/backends.rst
[testinfra-base]: https://raw.githubusercontent.com/pytest-dev/pytest-testinfra/main/testinfra/backend/base.py
[testinfra-pypi]: https://pypi.org/pypi/pytest-testinfra/json
[tmt-connect]: https://raw.githubusercontent.com/teemtee/tmt/main/tmt/steps/provision/connect.py
[tmt-license]: https://raw.githubusercontent.com/teemtee/tmt/main/LICENSE
[tmt-releases]: https://api.github.com/repos/teemtee/tmt/releases
[train-ssh]: https://raw.githubusercontent.com/inspec/train/main/lib/train/transports/ssh_connection.rb
[tursu]: https://pypi.org/project/tursu/
[yocto-releases]: https://www.yoctoproject.org/development/releases/
