# ADR 0011: Quantum-Resistant Cryptography Policy

## Status

Accepted

## Context

The owner set a standing policy (2026-09-06): all cryptography in the
product must be quantum-resistant.  Post-quantum algorithms are used
wherever they are standardized and available in the product; any
algorithm known or suspected to be susceptible to a quantum attack
must not be used.  The policy was first applied to SSH, which the
automated validation suite (ADR 0010) depends on and which the image
exposes on both the emulated and live targets.

SSH is the current transport for validation and lab access.  Its
handshake has three cryptographic parts, each with a different quantum
threat model.  Key exchange is the "harvest now, decrypt later" risk:
a recorded session is broken retroactively once a quantum computer
exists.  Authentication signatures are only a live-impersonation risk:
a broken signature lets a future quantum adversary impersonate a host
or user in real time, never decrypt past traffic.  Symmetric ciphers
and message authentication codes face only Grover's quadratic
speedup, not a full break.

## Decision

Make every part of the SSH handshake quantum-resistant.

- **Key exchange: post-quantum only.**  Offer only the hybrid
  exchanges `sntrup761x25519-sha512@openssh.com` and
  `mlkem768x25519-sha256` (each a stabilized post-quantum key
  encapsulation mechanism -- Streamlined NTRU Prime, and ML-KEM-768
  from FIPS 203 -- combined with X25519).  The classical
  `curve25519-sha256` exchanges are removed.

- **Authentication: post-quantum only.**  The host key and the
  accepted user keys are `ssh-mldsa44-ed25519`, a hybrid of the
  ML-DSA-44 signature (FIPS 204) with Ed25519.  Classical Ed25519,
  ECDSA, and RSA signatures are no longer offered or accepted.  This
  requires OpenSSH 10.4, the first release to carry the algorithm;
  the pinned OpenEmbedded-core LTS ships 10.3p1, so 10.4p1 is
  backported into `meta-lamadist` (its upgrade is a verbatim recipe
  bump on master, hundreds of commits ahead of the pin).

- **Symmetric: conservative under Grover.**  Ciphers are 256-bit AEAD
  only (`chacha20-poly1305@openssh.com`, `aes256-gcm@openssh.com`),
  and message authentication codes are SHA-2 in encrypt-then-MAC form.
  AES-128-GCM is removed, its 64-bit post-Grover strength being the
  one borderline case a strict reading of the policy excludes.

The policy is enforced, not just documented: validation property P16
fails if any offered key exchange is classical or the host key is not
post-quantum.  These values live in
`meta-lamadist/recipes-connectivity/openssh/files/20-lamadist-crypto.conf`,
included ahead of every other sshd directive.

## Alternatives considered

- **Hold authentication classical until the LTS ships OpenSSH 10.4.**
  Rejected: it leaves authentication out of policy for an unbounded
  time.  The backport is small and yields automatically once the LTS
  catches up.

- **Bump the OpenEmbedded-core pin to master for 10.4.**  Rejected:
  the pin is 809 commits behind master, a full distribution's worth of
  upgrades and rebuild churn on an LTS base.

- **Keep AES-128-GCM.**  Rejected: 64-bit post-Grover strength is
  weaker than the policy's intent, and every reaching client supports
  the 256-bit AEADs.

## Consequences

- OpenSSH 10.4p1 is carried in the layer as a version override with no
  `PREFERRED_VERSION`, so it wins by being the higher version and is
  removed once the LTS ships 10.4 or newer.  Until then it tracks
  OpenEmbedded-core's recipe.

- OpenSSH 10.4 enables `ssh-mldsa44-ed25519` by default on neither side
  of the client handshake.  A client reaching these systems must opt
  in with both `HostKeyAlgorithms` (to accept the host key) and
  `PubkeyAcceptedAlgorithms` (to present its user key), or it fails
  with "no matching host key type" or a silent publickey denial.  The
  validation transport sets both.

- OpenEmbedded-core's `sshd_check_keys` generates host keys by
  filename and had no `mldsa44-ed25519` case, so the post-quantum host
  key was never created; the backported copy adds it.  This is a
  candidate upstream patch.

- ssh-audit cannot complete a post-quantum-only handshake, so it
  returns no host-key fingerprint; the posture check reads the offered
  host-key algorithm from the server's KEXINIT instead.

- Any host that builds the image needs `ssh-keygen` from OpenSSH 10.4+
  to generate the post-quantum test key.

- Authentication signatures are the lowest-priority quantum risk, so
  closing them last -- after key exchange -- was the right order; both
  are now closed.  A future MQTT-based job runner that replaces SSH
  should carry an ML-DSA signature on its signed manifest.
