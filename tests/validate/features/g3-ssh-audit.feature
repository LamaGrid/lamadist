# SPDX-License-Identifier: Apache-2.0
# The twelfth check (ADR 0010; AoA section 7.6): ssh-audit measures
# the target's SSH cryptographic posture host-side, over the same
# port the suite already reaches.  ssh-audit grades algorithms; rule 6
# forbids passing on a grade, so these scenarios assert concrete facts
# drawn from the report -- no algorithm ssh-audit rates as fail is
# offered, a modern (Edwards-curve) host key is advertised, and the
# key exchange is post-quantum only (policy: all cryptography must be
# quantum-resistant, so no classical key exchange may be offered).
# The negative twin runs the same predicates over a fixed sample
# report shaped like the stock image, with no target.

@G3
Feature: SSH cryptographic posture

  @P16
  Scenario: P16 sshd offers post-quantum crypto and a post-quantum host key (ADR 0010 rule 6)
    Then the SSH server offers no algorithm rated fail by ssh-audit
    And the SSH server offers a "ssh-mldsa44-ed25519@openssh.com" host key
    And the SSH server offers only post-quantum key exchange

  @P16 @negative
  Scenario: P16 negative control
    Then the sample ssh-audit report "stock-image" rates an algorithm as fail
    And the sample ssh-audit report "stock-image" offers no "ssh-mldsa44-ed25519@openssh.com" host key
    And the sample ssh-audit report "stock-image" offers a classical key exchange
