# AoA: Secrets Backend (per-stick unlock passwords)

**Status:** DRAFT -- fills the `[AoA: secrets manager]` slot the
installer SPEC references (SPEC sections 1, 6, and Definition of
Done stage 3).  Becomes an ADR on Fable security review.

**Decision scope (this pass):** the LOCAL dev/test secrets
backend, verified only under the QEMU+OVMF harness.  The at-scale
portal is design-only and authored separately (AT-SCALE.md); this
AoA's job is to pick the local shape AND pin the object model and
interface contract so the portal inherits them unchanged.

**What the backend must do:** hold one high-entropy password per
installer stick, keyed by the stick's printed serial/label, so
that Role A (provisioner) issues the password at stick creation
and Role B (technician) retrieves it at install time (SPEC
section 6).  The password opens the stick vault (LUKS2) and is
then enrolled as the target's LUKS2 recovery keyslot.


## Options

### A -- fnox (installed, 1.31.0)

Verified against the installed binary and the upstream jdx/fnox
docs, not from memory.

- **Storage model.**  A TOML file, `fnox.toml`.  Each secret is
  one table entry keyed by an env-var-style name:

  ```toml
  [providers.sticks]
  type = "age"
  recipients = ["age1ql3z7hjy54pw3hyww5ayyfg7zqgvc7w3j2el..."]

  [secrets]
  STICK_LD_0001_G2 = { provider = "sticks", value = "YWdlLW...", \
                    description = "issued 2026-07-23; label LD-0001; gen 2" }
  ```

  The `value` is the age ciphertext stored inline; the file is
  safe to commit.  Confirmed by observation: `fnox set` writes
  the entry, `fnox list` renders key + provider + description.
- **Encryption.**  Provider-pluggable.  For the local backend the
  `age` provider fits: recipients (age PUBLIC keys) live in
  `fnox.toml`; the age IDENTITY (private key) never does -- it is
  supplied out of band via `FNOX_AGE_KEY`, `FNOX_AGE_KEY_FILE`, an
  explicit `key_file`, or another provider (OS keychain).  This
  gives a genuine asymmetry for free: ENCRYPTING (issue) needs
  only the public recipients; DECRYPTING (lookup) needs the
  identity.
- **CLI ergonomics.**  `set` (issue, reads value from stdin or an
  interactive hidden prompt -- never argv), `get` (lookup),
  `remove`, `list` (inventory + descriptions), `reencrypt`
  (rotate the encryption to a changed recipient set),
  `import`/`export`.  Keys are env-var names; `-k/--key-name`
  maps to a different provider key when the label is not
  env-var-safe.
- **Multi-holder.**  `recipients` accepts multiple age public
  keys; each holder decrypts with their own identity.  Adding or
  removing a holder is `fnox reencrypt -p <provider>`.
- **Scale path.**  The SAME `fnox.toml` object model and the same
  five verbs work against 20-plus provider backends -- aws-kms,
  gcp-kms, azure-kms, HashiCorp Vault, 1Password, Bitwarden,
  fido2/yubikey, OS keychain.  Moving from the local age store to
  a server-backed portal store is a provider swap, not a data
  model change.
- **License.**  MIT (permissive; see License notes).

### B -- minimal custom backend (age/sops-encrypted YAML in a private repo)

A hand-built store: per-stick entries in a YAML/JSON file, each
value encrypted with age (or the file managed by sops), committed
to a private git repo, with a thin wrapper script for issue /
lookup / rotate / list.

- This is, structurally, what fnox already IS: age-encrypted
  values in a committable text file, plus a CLI, plus a provider
  abstraction, plus a documented scale path.  Choosing B means
  re-implementing fnox's issue/lookup/rotate/audit ergonomics and
  owning that code.
- To JUSTIFY B, fnox would have to LACK something we need.  It
  does not: it has the deterministic key->value map, encrypted-
  at-rest commit-safe storage, multi-recipient sharing,
  reencrypt-based rotation, and the KMS/Vault scale path.  The
  only real reasons to pick B would be (a) a hard requirement to
  ship zero third-party binaries in the loop, or (b) a key
  namespace that cannot be expressed as env-var names -- neither
  applies here.
- Kept as the DEGRADED fallback: fnox's age format is age under
  the hood, so if fnox ever became unavailable the same
  ciphertexts are recoverable with the `age`/`rage` CLI directly.
  That interoperability is a point in fnox's favor, not a reason
  to build B now.

### C -- direct standard building blocks (OS keychain / pass / Vault)

- **OS keychain / `pass`:** single-operator local stores with no
  commitable audit artifact and a weaker scale story than the age
  file; fnox can front either of these as a provider if wanted,
  so they are not a competing choice so much as a fnox backend.
- **HashiCorp Vault:** the right shape for the PORTAL, wrong
  weight locally (server, unseal, TLS).  License caveat: Vault is
  BUSL-1.1 (source-available, "ask before adding" under our
  policy).  The permissive alternative for the portal is OpenBao
  (MPL-2.0 fork) or a cloud KMS.  Recorded here for the at-scale
  design; not adopted locally.


## AoA comparison table

| Criterion                     | A: fnox (age)        | B: custom age/sops YAML | C: Vault / keychain      |
|-------------------------------|----------------------|-------------------------|--------------------------|
| Already installed             | Yes (1.31.0)         | No (build wrapper)      | No (server / per-OS)     |
| Encrypted-at-rest, commitable | Yes (age inline)     | Yes (age/sops)          | No (external store)      |
| Issue without decrypt rights  | Yes (public recips)  | Yes (age recipients)    | Via IAM/policy           |
| Deterministic stick-id key    | Yes (env-var key)    | Yes (you define it)     | Yes (path/secret name)   |
| Rotation ergonomics           | new gen + `reencrypt`| Hand-rolled             | Native, richer           |
| Local audit artifact          | git history + `list` | git history             | Server audit log         |
| Role A/B crypto separation    | No (see gap)         | No (see gap)            | Yes (server RBAC)        |
| Scale path to portal          | Provider swap        | Rewrite to a server     | Is the portal            |
| Code we own/maintain          | None                 | The whole wrapper       | Server ops               |
| License                       | MIT (permissive)     | age BSD / sops MPL-2.0  | Vault BUSL-1.1 (ask)     |

**Selected: A -- fnox with the `age` provider.**  It is already
installed, needs zero code, stores commit-safe encrypted-at-rest
values keyed exactly the way the SPEC's secret model wants, gives
issue-without-decrypt asymmetry from age for free, and -- the
decisive property -- carries the identical object model and CLI
contract into the at-scale portal by swapping only the provider
backend.  B reinvents it; C is portal-weight or licence-flagged.


## Interface contract (inherited unchanged by the portal)

The at-scale system MUST implement this contract; the local fnox
backend is one implementation of it.  `stick-id` is derived from
the printed stick serial/label in two parts: a BASE key,
normalized env-var-safe (uppercase, `-` -> `_`, project prefix),
and a GENERATION suffix `_G<n>` appended per issuance, e.g. label
`LD-0001` generation 2 -> key `STICK_LD_0001_G2`.  The object
model is a flat map `stick-id -> { secret, metadata,
provider-ref }`, which maps one-to-one onto a portal database row
-- no schema change to scale.

- **Collision-rejecting normalization (review MAJOR-8).**  The
  base normalization is LOSSY: distinct labels `LD-0001` and
  `LD_0001` both collapse to base `STICK_LD_0001`.  Issuance MUST
  treat this as a hard error -- if a candidate base key already
  names a DIFFERENT printed label, abort and fail closed; it MUST
  NOT silently overwrite the colliding entry.  A `fnox set` that
  would land on an existing base owned by another label is
  forbidden; the operator picks a label that normalizes
  distinctly, or the project prefix scheme is widened.
- **issue(stick-id) -> password.**  Role A generates a
  high-entropy password with a CSPRNG and stores it under a FRESH
  generation key for the stick's base.  Issue is append-only: it
  allocates the next `_G<n>` and never overwrites a prior
  generation.  Local:

  ```sh
  # Verify the base is unclaimed OR owned by THIS label, and pick
  # the next free generation, before writing (collision check).
  pw=$(head -c 32 /dev/urandom | base64)     # CSPRNG, off-argv
  printf '%s' "$pw" | fnox set STICK_LD_0001_G2 \
      -p sticks -d "issued $(date -I); label LD-0001; gen 2"
  ```

  Issue is NOT idempotent-by-overwrite: re-provisioning a stick
  allocates a new generation (see one-stick-one-install below).
  The printed label MUST match the base key (SPEC section 6).
- **lookup(stick-id) -> password.**  Role B, holding the age
  identity, retrieves the value at install time:

  ```sh
  FNOX_AGE_KEY_FILE=/path/to/id fnox get STICK_LD_0001
  ```

- **One stick, one install (review MAJOR-1, SPEC req 2.4).**
  Issuance is per-install in practice: a stick installs exactly
  one target, so the generation issued for that stick is the
  recovery credential of exactly one machine, not a durable
  offline-unlock key shared across a fleet.  Re-provisioning a
  consumed stick MUST allocate a FRESH generation (a new `_G<n>`)
  and rebuild the vault, so every installed target's recovery
  credential is unique.  A stick's `install-consumed` flag
  (AT-SCALE) is the fail-closed guard that forces this: reuse
  without a fresh generation is an error, not a convenience.
- **rotate(stick-id) -- retire, never overwrite (review
  MAJOR-8).**  Bare `fnox set` on a live generation key is
  FORBIDDEN: it destroys the only copy of a credential that
  deployed state still depends on -- targets already installed
  from that stick keep the old generation as their LUKS2 recovery
  keyslot, and an in-flight stick's vault is sealed with it.
  Overwriting orphans both.  Rotation instead follows the
  AT-SCALE retire-not-delete semantics.  Two distinct operations
  the portal must keep distinct:
  1. SECRET rotation -- ISSUE a new generation (`_G<n+1>`) via the
     append-only `issue` above; MARK the prior generation retired
     in its `fnox` description (e.g. append `; retired
     $(date -I)`) but RETAIN it, so an in-flight stick or an
     already-installed target stays diagnosable and its still-
     enrolled keyslot stays recoverable.  The deployed target's
     LUKS2 recovery keyslot is then rotated by the manual
     operational procedure (`cryptsetup luksChangeKey` on the
     recovery slot, CSPRNG-only -- see Weak-KDF below); SPEC
     section 6 marks recovery-slot rotation a manual procedure
     this pass.
  2. ENCRYPTION rotation -- change WHO can decrypt without
     changing any password: edit `recipients`, then
     `fnox reencrypt -p sticks`.  Used to add/remove a holder or
     retire a compromised identity.
- **audit listing.**  Local inventory is `fnox list` (key,
  provider, description) and `fnox list --sources`; the durable
  event trail is the git history of `fnox.toml` (every issue and
  rotate is a commit).  There is NO local access log -- fnox does
  not record who ran `get` or when.  Access logging is a PORTAL
  responsibility (see gap below).


## Role A / Role B separation -- honest local posture

The SPEC separates Role A (provisioner, writes the secret) from
Role B (technician, reads it).  Assessed honestly for local fnox:

- **fnox profiles do NOT create a trust boundary.**  Profiles are
  configuration namespaces layered within the same file; they do
  not cryptographically isolate secrets.  "Two profiles" is not a
  security control and MUST NOT be presented as one.
- **What DOES separate the roles locally is age key
  distribution, not fnox.**  Because the age provider encrypts to
  PUBLIC recipients, Role A can `set` (issue) new per-stick
  secrets with only the recipients list and no ability to `get`
  them back.  Role B holds the age IDENTITY and can decrypt.  So
  a genuine write-only-vs-read split IS achievable locally IF the
  identity is withheld from the provisioning role and held only
  by the technician role.
- **Accepted local gap.**  In the single-operator homelab case
  one person holds both the recipients and the identity, so the
  separation collapses to a procedural, not enforced, boundary --
  and fnox provides NO access log to detect a Role-A holder who
  also reads.  This is an ACCEPTED LOCAL GAP for this pass.  The
  portal closes it: server-side RBAC grants issue and lookup as
  distinct capabilities to distinct principals, and the server
  audit log records every lookup with actor, stick-id, and time.
  The fnox object model and five-verb contract above are exactly
  what that portal exposes; only the enforcement and the audit
  log are added at the server tier.


## Key risks

- **No local access audit.**  fnox logs issue/rotate only via git
  history; it does not record `get`.  A local reader leaves no
  trace.  Mitigated at scale by the portal audit log; locally,
  accepted.
- **Role separation is procedural locally.**  Cryptographic
  separation exists only if the age identity is withheld from
  Role A; the single-operator case does not do this.  Accepted
  local gap, closed by the portal.
- **Overwrite destroys live credentials (review MAJOR-8).**  A
  bare `fnox set` on an existing generation key deletes the only
  copy of a password that deployed state still depends on -- an
  already-installed target's enrolled recovery keyslot, or an
  in-flight stick's sealed vault.  Mitigation is in the contract:
  generation-suffixed keys, append-only issue, and an explicit
  retire step (retain old generations, mark them retired) instead
  of overwrite; a base-key collision (`LD-0001` vs `LD_0001`)
  aborts issuance rather than clobbering.
- **Recovery-credential blast radius (review MAJOR-1).**  Because
  one stick installs one target and re-provisioning issues a
  fresh generation, each installed machine's recovery credential
  is unique; a leaked generation exposes at most that one
  target's offline-unlock slot, not a fleet.  The
  `install-consumed` fail-closed flag (AT-SCALE) enforces the
  one-stick-one-install norm this depends on.
- **Identity handling.**  The age identity is the whole ballgame
  for confidentiality -- if it leaks, every committed per-stick
  ciphertext is readable.  It MUST live outside `fnox.toml`
  (env/keychain/key file with tight perms), never be committed,
  and be enrollable as an age recipient set so it can be rotated
  via `reencrypt` without re-issuing passwords.
- **Password never on argv.**  `fnox set KEY value` would expose
  the secret in shell history and `ps`; the contract mandates
  stdin/interactive entry (fnox warns about this too).
- **Weak-KDF interaction (resolved -- review MAJOR-3).**  LUKS2
  KDF parameters are PER KEYSLOT, and the resolved policy uses
  that:
  - The RECOVERY keyslot the installer enrolls this password into
    uses **argon2id**, at zero boot-time cost (every normal boot
    unlocks via the TPM2 slot; the recovery slot is exercised
    rarely).  This holds even if a future rotation ever admitted a
    lower-entropy secret.
  - `pbkdf2 --pbkdf-force-iterations 1000` is CONFINED to the
    keyfile/TPM-grade slots that only ever hold CSPRNG,
    keyfile-grade secrets (the /var dev-keyfile / TPM path); it
    MUST NOT be used for the recovery slot.
  - The per-stick password remains CSPRNG-generated high-entropy
    (>= 128 bits), and **rotation is CSPRNG-only, never
    human-chosen** -- `cryptsetup luksChangeKey` on the recovery
    slot must take a fresh CSPRNG secret, closing the trap where a
    human-chosen passphrase under a weak KDF becomes offline-crack
    territory.
- **fnox is a third-party binary in the trust path.**  Supply-
  chain surface (installed via mise).  Fallback: the age
  ciphertexts are recoverable with the standalone `age`/`rage`
  CLI if fnox is ever unavailable.


## License notes

- **fnox: MIT.**  Permissive; the preferred class under the
  project license policy.  No copyleft note or approval needed;
  recorded here and to be captured in the SBOM if fnox ever
  enters a build recipe (it is dev/operator tooling, not shipped
  in the image, so it does not enter target licensing).
- **age (the crypto backend): permissive.**  Upstream
  FiloSottile/age is BSD-3-Clause; the Rust implementation fnox
  bundles is MIT/Apache-2.0.  No obligations of concern.
- **Fallback / portal building blocks flagged for later:**
  - sops (if ever used for option B): MPL-2.0 -- weak copyleft;
    would need a brief note under the policy, not approval.
  - HashiCorp Vault (a portal candidate): BUSL-1.1 --
    source-available "ask-before-adding" class; the permissive
    alternative is OpenBao (MPL-2.0) or a cloud KMS.  Deferred to
    the AT-SCALE design; NOT adopted in this local pass.
- No strong-copyleft or ask-first component enters the local
  secrets backend selected here.
