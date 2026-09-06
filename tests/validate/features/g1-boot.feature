# SPDX-License-Identifier: Apache-2.0
# Goal 1: the image works.  Console and SSH login are not separate
# rows: every scenario in this suite running at all is the proof.

@G1
Feature: The booted system is healthy

  @P6
  Scenario: P6 clean enforcing boot, no failed units (health predicate for every other check)
    When I run "systemctl is-system-running"
    Then the output matches "^running$"
    When I run "systemctl --failed --no-legend --plain | wc -l"
    Then the output matches "^0$"

  @P6 @negative
  Scenario: P6 negative control
    Then the matcher "^running$" rejects "degraded"
    And the matcher "^0$" rejects "1"
