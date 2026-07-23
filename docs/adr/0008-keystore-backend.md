# ADR 0008: Per-Stick Keystore Backend

## Status

Accepted

## Context

Each installer stick carries a unique >=128-bit CSPRNG unlock
password (SPEC section 6) that Role A issues at stick creation
and Role B looks up at install time.  Locally (this pass) the
store must be simple and already-toolable; at scale the same
object model must back the RFC 8628-modeled portal
(docs/installer/AT-SCALE.md, design-only).  Full analysis:
docs/installer/AOA-KEYSTORE.md, reviewed through two Fable
security-review rounds.

## Decision

Use fnox (1.31.0, mise-installed) with the age provider as the
local keystore.  Per-stick entries are inline age ciphertexts in
a commit-safe fnox.toml, keyed by the stick's serial/label.
Lifecycle rules from the review: generation-suffixed keys with an
explicit retire step -- bare `fnox set` overwrite is FORBIDDEN as
re-issue/rotate (it would destroy the only copy of a credential
still enrolled as deployed targets' recovery keyslot and
permanently seal in-flight vaults); label normalization must
REJECT collisions (e.g. LD-0001 vs LD_0001), never silently
merge.  The five-verb contract (issue, lookup, rotate, retire,
audit) is the interface the at-scale portal inherits unchanged.

## Alternatives considered

- Custom age/sops-encrypted YAML in a private repo: reinvents
  what fnox already is, with code we then own.  Rejected.
- Vault/OS-keychain class backends: portal-weight infrastructure
  or license-flagged for a local dev/test need.  Rejected
  locally; the portal tier is where server-enforced RBAC lives.

## Consequences

- Role A / Role B separation is PROCEDURAL locally: fnox profiles
  are namespaces, not a trust boundary, and fnox does not log
  reads.  Accepted local gap, closed at the portal tier
  (server-side RBAC, per-serial scoping, audit log,
  consumed-generation retirement).  One-stick-one-install is
  likewise best-effort locally (forgeable PUBLIC-partition flag)
  and enforced only by the portal.
- The age identity is the whole confidentiality boundary: kept
  out of fnox.toml (env/key file, tight permissions), rotatable
  via re-encrypt.  Ciphertexts remain recoverable with the
  standalone age/rage CLI if fnox disappears (supply-chain
  hedge).
- Passwords are CSPRNG-only, entered via stdin/prompt (never
  argv), and rotation of a deployed recovery keyslot must also
  be CSPRNG-only -- the argon2id recovery-slot KDF (SPEC 3.1
  step 8) does not make human passphrases acceptable.
- fnox is MIT-licensed; age is BSD-3-Clause.  No copyleft
  exposure.
