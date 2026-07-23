# LamaDist At-Scale Secrets and Enrollment -- Design of Record

**STATUS: DESIGN ONLY -- NOT BUILT.**  This document records the
intended shape of the fleet-scale secrets and enrollment system so
that the local implementation does not paint it into a corner.
Nothing here is built this pass.  Local dev and test use `fnox`
(1.31.0, via mise) against the SAME object model described in
section 1; the portal and PKI are the at-scale substitution for
fnox, not a redesign.  The installer SPEC (`docs/installer/SPEC.md`)
is the contract this serves; where the two disagree, the SPEC wins
and this file is corrected.

Four external specifications are cited by structure from memory and
MUST be re-read against the published text before any
implementation: RFC 8628 (OAuth 2.0 Device Authorization Grant),
including its section 5 security considerations; RFC 7519 / RFC 8725
(JWT and JWT BCP); and RFC 7800 (`cnf` proof-of-possession claims,
section 4.4).  Every `[RECHECK]` tag below marks a point where the
real RFC governs and this summary may be imprecise.

## 1. Shared object model (fnox local, portal at scale)

The unit of secrecy is the **per-stick secret**: one high-entropy
vault-unlock password per installer USB, keyed by the stick's
printed serial/label.  Both backends implement one interface; only
the storage and the authorization surface differ.

- **Key:** `stick/<serial>` where `<serial>` is the human-readable
  label physically printed on the stick.  The key namespace is flat
  and opaque to the installer.
- **Value:** the vault-unlock password (SPEC section 6 "Issue"),
  plus issue metadata (created-at, issuer identity, rotation
  generation, install-consumed flag).
- **Operations:**
  - `issue(serial) -> password` -- generate, store, return ONCE.
    Idempotency is by explicit generation, not by re-read (see
    Role A below).
  - `lookup(serial) -> password` -- authorized read of the current
    password (Role B, or the installer's non-interactive path).
  - `rotate(serial) -> password` -- supersede the current secret;
    the old value is retired, not deleted, so an in-flight stick
    remains diagnosable.  Rotation of the on-target LUKS recovery
    keyslot is a separate, manual operational procedure (SPEC 6).
  - `audit(serial | *) -> events` -- append-only log of issue,
    lookup, and rotate events with actor, timestamp, and outcome.

Locally, `fnox` provides this as a flat keystore; `audit` is the
fnox operation log.  At scale the same four operations become
portal API calls with the separation of duties of section 2
enforced server-side.  The installer and its tests bind to the
interface, never to fnox or the portal directly, so the local-to-
scale swap is a backend change with no installer change.

## 2. Separation of duties

Two roles, two disjoint capability sets, enforced by the backend --
not by convention and not by the installer.

- **Role A (provisioner):** creates, flashes, labels, and ships
  sticks.  Capability: `issue` and `rotate` (WRITE).  Role A can
  cause a secret to exist and can read it exactly once, in the
  `issue` response, to write it into the vault at stick-creation
  time.  Role A CANNOT read a secret back after issue: there is no
  `lookup` capability on the Role A credential.  A lost issue
  response is recovered by `rotate` (mint a new secret, re-flash),
  never by re-read.
- **Role B (technician):** performs the install.  Capability:
  `lookup` on EXACTLY the stick in hand (READ, scoped to one
  serial), via the portal flow of section 3.  Role B cannot
  enumerate the namespace, cannot issue, and cannot rotate.

What enforces each boundary:

- **Write-only-once for Role A:** the store returns the plaintext
  only in the `issue`/`rotate` response and never again; there is
  no read path on the Role A credential's grant.  This is a
  server-side authorization rule, so a compromised Role A station
  cannot harvest previously-shipped passwords.  Locally, fnox
  approximates this by policy convention only -- fnox has no role
  split -- and the gap is documented, not closed, in dev.
- **One-stick scope for Role B:** the portal issues a lookup token
  bound to a single serial, established by the operator-present
  authorization step (section 3).  A Role B credential is never a
  standing bearer of the namespace.
- **Audit as the backstop:** every `lookup` is logged with actor
  and serial (section 1).  Separation of duties bounds who CAN act;
  the audit log records who DID.  `[RECHECK]` the retention and
  tamper-evidence requirements for the audit log are a policy
  decision (append-only store vs. signed log) deferred to build.

### 2.1 Install-consumed flag policy (one-stick-one-install)

The norm is one install per stick.  On a successful install the
installer sets the `install-consumed` flag (section 1) and the portal
enforces its policy fail-closed:

- **Generation retirement.**  Consumption retires the current
  password generation (moved to retired-not-deleted per `rotate`, so
  an already-installed target stays diagnosable) -- it is no longer a
  live issue.
- **Re-provisioning uses a FRESH generation.**  Re-using a stick is a
  Role A `rotate`/`issue` that mints a NEW password, re-flashed; it is
  never a re-read of the consumed secret (SPEC MAJOR-1).  This re-arms
  `lookup` for the new generation only.
- **Consumed lookups refused to Role B.**  Once consumed, the portal
  denies any Role B `lookup` on that serial's retired generation, so
  the recovery credential of an already-installed target cannot be
  pulled back out of the portal; a genuine re-install must go through
  Role A for a fresh generation first.

This bounds the MAJOR-1 blast radius: a consumed stick's password
stops being a portal-retrievable credential, and the fresh-generation
rule prevents one password from becoming the durable offline-unlock
secret of every machine the stick ever touched.

## 3. Role B password-lookup portal (RFC 8628-shaped)

The technician-facing lookup is modeled on the OAuth 2.0 Device
Authorization Grant (RFC 8628), reused for a human-to-portal
handoff rather than device-to-authorization-server.  The mapping:

- The technician's install station (or the installer UI) plays the
  RFC 8628 **device**: it has a constrained UI and cannot run a
  full browser login.  It requests a lookup for a serial and
  receives a `user_code` and a `verification_uri`.
- The technician plays the RFC 8628 **user**: on a phone or laptop
  they open `verification_uri`, authenticate to the portal with
  their own Role B identity, enter the `user_code`, and confirm the
  stick serial shown.  This operator-present step is what scopes
  the resulting token to one serial.
- The station **polls** the portal token endpoint until the
  technician has approved, then receives the one-stick lookup
  result (the vault password), subject to the RFC 8628 poll states
  `authorization_pending`, `slow_down`, `access_denied`, and
  `expired_token`.  `[RECHECK]` exact error identifiers, the
  `interval` / `slow_down` backoff semantics (5 s increment), and
  the `verification_uri_complete` convenience form are governed by
  the RFC text.

Why RFC 8628 fits: the install station is a poor place to type
portal credentials, the technician already carries a second device,
and the grant gives an operator-present, per-transaction
authorization instead of a standing credential on the shop floor.
The one deliberate re-shaping is that the "resource" the flow
authorizes is a single-serial secret read, not an ongoing API
scope.

### 3.1 Security considerations (RFC 8628 section 5) [RECHECK]

Section 3 reproduced the grant mechanics; RFC 8628 section 5 governs
what keeps the flow off the phishing and brute-force surface, and it
bites harder here.  `[RECHECK]` each item against the published
section 5 text before build.

- **`user_code` entropy floor + brute-force rate limiting.**  The
  `user_code` is short and human-typed, hence guessable by
  construction; section 5 requires a large enough code space AND rate
  limiting (throttle or lockout) at the VERIFICATION endpoint so the
  code space cannot be walked within a code's lifetime.  The
  station-side poll backoff (`slow_down`) does not cover this; the
  human-facing verification side needs its own independent limit.
  Specify a minimum code entropy and a per-endpoint attempt budget.
- **Short `user_code` TTL.**  Keep the code lifetime short so both the
  brute-force and phishing windows stay small; it authorizes one
  pending transaction and expires with it.
- **Remote-phishing of approval -- AGGRAVATED here.**  The generic RFC
  8628 attack: an attacker starts a flow, then social-engineers a
  legitimate Role B holder into opening the verification URI and
  approving the ATTACKER's `user_code`, handing the attacker the
  approved result.  In the plain grant that result is an access token;
  HERE the token endpoint returns the RAW per-stick vault password
  (the section 3 deliberate re-shaping), so a successful phish yields
  the offline-unlock credential itself, not a revocable token --
  strictly worse.  Required mitigations: the approval screen MUST show
  the stick SERIAL and the requester context (who/where initiated the
  flow) so a Role B holder can see they are approving a read they did
  not start; the rate limits and short TTL above shrink the window;
  `[RECHECK]` binding approval to the same authenticated Role B
  session that will consume the result, closing the cross-actor gap
  the phish depends on.

## 4. Device self-enrollment (RFC 8628-shaped, JWT token)

The INSTALLED device enrolls itself to obtain a device certificate.
The flow is RFC 8628 in shape, with ONE change: the token returned
by the token endpoint is a **JWT** (RFC 7519), not an opaque
string, so relying parties validate it statelessly without a
portal round-trip.

Flow (RFC 8628 device grant, device-operated):

1. The device requests enrollment; the portal returns
   `device_code`, `user_code`, `verification_uri`, `expires_in`,
   and `interval`.  `[RECHECK]` field names/response shape.
2. An operator approves the enrollment at `verification_uri`
   (binding the device to a fleet/tenant), or an
   already-authorized manifest supplies the approval out of band
   for headless fleets -- a design choice deferred to build.
3. The device polls; on approval it receives an **enrollment JWT**.
4. The device presents the JWT to the PKI enrollment endpoint,
   which issues the device certificate.

### 4.1 JWT claims

- `iss` -- portal issuer URL (exact-match validated).
- `sub` -- device identity (the enrollment subject / serial).
- `aud` -- the PKI enrollment endpoint (exact-match validated).
- `exp`, `iat`, `nbf` -- short lifetime (see 4.3).
- `jti` -- unique token id, recorded for replay detection and
  revocation.
- `fleet` / `tenant` -- binding established at approval (step 2).

### 4.2 Signing algorithm policy

- **Allowlist only:** accept a single asymmetric family, `EdDSA`
  (Ed25519) preferred, `ES256` acceptable.  Reject everything else.
- **`alg: "none"` is rejected unconditionally** -- unsigned tokens
  are never accepted.
- **No alg-confusion:** the verifier selects the algorithm and key
  from its own trust configuration keyed by `kid`; it does NOT
  trust the token header's `alg` to choose a key type.  This blocks
  the RS256-key-as-HMAC-secret confusion.  `[RECHECK]` against
  RFC 8725 (JWT BCP) sections on algorithm verification and `kid`
  handling before implementation.
- Keys are asymmetric so relying parties verify with a public key
  and never hold a signing secret.

### 4.3 Expiry, renewal, and revocation

Stateless validation and revocation are in tension; state the
trade-off honestly.  A JWT is valid until `exp` by construction,
so a purely stateless verifier cannot know a token was revoked.
The chosen posture:

- **Short expiry.**  The enrollment JWT is single-use and
  short-lived (minutes); it exists only to bridge device-grant
  approval to certificate issuance.  Its blast radius on leak is
  one enrollment window.
- **Revocation checked at the boundary that already has state.**
  Certificate issuance (and any refresh) is an online step at the
  PKI, which consults a revocation list / `jti` denylist at that
  moment.  Long-lived trust lives in the device CERTIFICATE, whose
  revocation is the PKI's CRL/OCSP problem, not the JWT's.
- **Trade-off stated:** we do NOT get instant revocation of an
  issued JWT.  We accept that because (a) the JWT window is minutes,
  (b) `jti` single-use blocks replay, and (c) the durable
  credential is the certificate, where revocation is handled with
  established PKI machinery.  The alternative -- checking a
  revocation list on every stateless validation -- reintroduces the
  online dependency the JWT was meant to remove, so it is rejected
  for the short-lived enrollment token and kept only at issuance
  and refresh.

### 4.4 Proof-of-possession and subject attestation

Two [RECHECK]-class gaps in the section 4 enrollment JWT.

**Proof-of-possession -- the JWT must not stay a pure bearer token.**
As written, any holder can present the JWT to the PKI within its
minutes-window with their OWN keypair/CSR and be issued a certificate
for the victim `sub`.  Bind the JWT to the device key so only the
keyholder can redeem it:

- **`cnf` claim (preferred).**  At approval the portal binds the JWT
  to the public key the device will use in its CSR via a `cnf`
  (confirmation) claim -- a `jkt` thumbprint of that key.  The PKI
  issues only if the CSR is signed by the key the `cnf` names; a
  stolen JWT is useless without the device private key.  `[RECHECK]`
  RFC 7800 for `cnf` / `jkt` semantics and the thumbprint
  construction.
- **Fallback precondition (only if `cnf` is deferred).**  State the
  standing assumption explicitly: the JWT-to-PKI channel is mutually
  authenticated (client-cert TLS between the enrolling device and the
  PKI) so a third party cannot redeem the bearer token.  This is a
  precondition, not a mitigation; prefer the `cnf` binding, which
  does not depend on the channel.

**Who attests the device IS `sub`.**  `sub` (section 4.1) names the
enrollment subject/serial, but nothing yet states WHO vouches that the
device presenting the flow actually is that serial at approval time:

- **Operator verification (stronger).**  The human approving at
  `verification_uri` reads the device's claimed serial off the
  approval screen and confirms it against the physical device -- the
  same operator-present pattern as section 3.
- **Self-assertion (weaker).**  The device asserts its own `sub` and
  the portal binds it unchecked; a device that lies about its serial
  gets a certificate for that identity.  `[RECHECK]`-class residual
  risk: absent operator verification or a hardware-rooted identity
  (TPM EK / attestation), `sub` is self-declared and enrollment trusts
  the device's honesty.  A fleet MUST name which posture it uses;
  a headless fleet that skips the operator step inherits the
  self-assertion risk explicitly.

## 5. Forward design note: Clevis + Tang + TPM2 binding

Not built this pass; recorded so the keyslot layout (SPEC section 6)
leaves room.

- **Goal:** bind the target's LUKS2 `/var` to BOTH a network
  presence (Tang) and platform state (TPM2 PCR 7) via a Clevis
  `sss` (Shamir) pin, so unlock needs the device on its home
  network AND in a trusted boot state, while the SPEC recovery
  keyslot and the TPM2-only slot remain as fallbacks.
- **Pre-binding at install:** the Tang server public material is
  carried inside the stick vault and used to enroll the Clevis
  keyslot AT INSTALL TIME, offline, against the pre-fetched Tang
  advertisement.  This avoids a first-boot network dependency and
  matches the SPEC's window-shift (provision under the
  authenticated installer, not on the target's first boot).
  `[RECHECK]` that Clevis/Tang support enrolling from a
  pre-captured advertisement without live contact, and the trust
  model for verifying that advertisement offline, before relying on
  this.
- **Portal/PKI hosts Tang:** the same portal that issues passwords
  and enrollment JWTs also fronts the Tang key service, so a fleet
  has one trust origin.  Tang key rotation, per-fleet Tang key
  scoping, and the Clevis rebind procedure after rotation are
  portal responsibilities.  Tang's `adv` verification and DoS
  posture (Tang unreachable == cannot unlock via that pin, hence
  the retained fallback slots) are called out but not designed here.
- **License note:** Clevis and Tang are LGPL-2.1; adopting them as
  core target components triggers the copyleft-note requirement and
  a short ADR in the precedent format of `docs/adr/0002`-`0005`,
  the same as RAUC.  No strong-copyleft approval is needed.

## 6. Non-goals (this pass)

- No portal, PKI, or Tang service is built; local dev/test is fnox
  against the section 1 interface only.
- No Role A/Role B enforcement in dev: fnox has no role split, so
  the separation of duties (section 2) is documented policy locally,
  enforced server-side only at scale.
- No batch/fleet flashing, provisioning orchestration, or inventory
  system; one stick at a time (SPEC section 9).
- No JWT/certificate issuance code, no revocation-list service, no
  key-management/HSM design for the portal signing keys (M6 owns
  production key custody).
- No Clevis/Tang integration in the image; keyslot LAYOUT
  headroom only (SPEC section 6).
- No transport, session, or account-security design for the portal
  (TLS posture, Role B identity provider, rate limiting) beyond the
  RFC 8628 grant shape -- deferred to the build pass with its own
  security review.
