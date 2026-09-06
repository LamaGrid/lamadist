# SPDX-License-Identifier: Apache-2.0
# Goal 2: nothing breaks across an OTA update.  Increment 1 gives the
# static baseline only; the dynamic install and rollback cycle stays
# in .mise/lib/ota_test.py until checks 12 and 13 land.

@G2
Feature: OTA baseline

  @P11
  Scenario: P11 the booted RAUC slot is good and committed (OTA baseline)
    When I run "rauc status --output-format=json"
    Then the RAUC status reports the booted slot as good

  @P11 @negative
  Scenario: P11 negative control
    Then the RAUC status "{"booted": "a", "slots": [{"rootfs.0": {"bootname": "a", "state": "booted", "boot_status": "bad"}}]}" is not reported as good
