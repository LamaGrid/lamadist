# SPDX-License-Identifier: Apache-2.0
# Goal 2: nothing breaks across an OTA update (AoA section 7.7).
# P11 is the static baseline and records the slot facts on every run.
# P17 (check 12) reads those facts back from a snapshot taken before an
# update (--baseline) and asserts the update moved the boot and left
# the slot it came from exactly as it was.  P18 (check 13) pushes a
# bundle signed by a certificate authority the image does not trust
# and asserts it is refused at signature verification with every slot
# unchanged.  P17 needs a baseline and is deselected without one, never
# skipped; P18 runs every time.  The dynamic install-and-rollback
# cycle itself stays in .mise/lib/ota_test.py.

@G2
Feature: OTA update integrity

  @P11
  Scenario: P11 the booted RAUC slot is good and committed (OTA baseline)
    When I run "rauc status --detailed --output-format=json"
    Then the RAUC status reports the booted slot as good
    And the RAUC slot facts are recorded

  @P11 @negative
  Scenario: P11 negative control
    Then the RAUC status "{"booted": "a", "slots": [{"rootfs.0": {"bootname": "a", "state": "booted", "boot_status": "bad"}}]}" is not reported as good

  @P17 @ota
  Scenario: P17 an update moves the boot and leaves the previous slot untouched (check 12)
    Given the baseline snapshot from before the update
    When I run "rauc status --detailed --output-format=json"
    Then the update moved the boot to the other slot
    And the slot booted in the baseline is inactive, good, and untouched

  @P17 @negative
  Scenario: P17 negative control
    Then the sample slot history "boot-did-not-move" did not move the boot
    And the sample slot history "rewritten-old-slot" rewrote the old slot

  @P18 @root
  Scenario: P18 a bundle signed by an untrusted certificate authority is refused (check 13)
    Given a bundle signed by a certificate authority the target does not trust
    When I install that bundle as root
    Then the installation is refused for its signature
    And the RAUC slots are unchanged by the attempt

  @P18 @negative
  Scenario: P18 negative control
    Then the sample install "accepted" is not a refusal
    And the sample slot history "install-bumped-a-slot" changed a slot
