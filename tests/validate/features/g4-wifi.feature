# SPDX-License-Identifier: Apache-2.0
# Goal 4: the WiFi backend (ADR 0014).  iwd runs confined in the
# NetworkManager_t domain with its state on the encrypted /var, and the
# station path -- association, then a systemd-networkd lease on wlan0
# -- works.  The association check needs two radios that see each
# other: on the emulated target they are mac80211_hwsim radios (kernel
# fragment hwsim.cfg, QA builds only) with iwd itself as the access
# point and networkd serving the lease, which is why that scenario
# carries @hwsim and is deselected on the device, where the real radio
# is already associated through the provisioned profile.  The denial
# check counts kernel AVCs and the USER_AVC records dbus-daemon writes
# to the audit log, which never reach the kernel log.

@G4
Feature: The WiFi backend runs confined and takes a lease

  @P19 @root
  Scenario: P19 iwd runs in the NetworkManager_t domain (ADR 0014 decision 5)
    When I run "systemctl is-active iwd"
    Then the output matches "^active$"
    When I run "cat /proc/$(systemctl show iwd -p MainPID --value)/attr/current" as root
    Then the output matches "^system_u:system_r:NetworkManager_t:"

  @P19 @negative
  Scenario: P19 negative control
    Then the matcher "^system_u:system_r:NetworkManager_t:" rejects "system_u:system_r:unconfined_t:s0"
    And the matcher "^active$" rejects "inactive"

  @P20 @root
  Scenario: P20 the WiFi state and configuration carry their refpolicy types (ADR 0014 decisions 4 and 5)
    When I run "ls -Zd /var/lib/iwd" as root
    Then the output matches "NetworkManager_var_lib_t"
    When I run "ls -Z /etc/iwd/main.conf"
    Then the output matches "NetworkManager_etc_t"

  @P20 @negative
  Scenario: P20 negative control
    Then the matcher "NetworkManager_var_lib_t" rejects "system_u:object_r:var_lib_t:s0 /var/lib/iwd"
    And the matcher "NetworkManager_etc_t" rejects "system_u:object_r:etc_t:s0 /etc/iwd/main.conf"

  @P21 @root @hwsim
  Scenario: P21 the station associates and networkd takes a lease on wlan0 (ADR 0014 consequences)
    Given a virtual radio pair with iwd as the access point on wlan1 and the station on wlan0
    When I run "networkctl status wlan0"
    Then the output matches "State: routable"
    When I run "ip -4 route show dev wlan0"
    Then the output matches "^default via .* metric 2048"

  @P21 @negative
  Scenario: P21 negative control
    Then the matcher "State: routable" rejects "State: degraded (configuring)"
    And the matcher "^default via .* metric 2048" rejects "default via 10.0.2.2 proto dhcp src 10.0.2.15 metric 10"

  @P22 @root
  Scenario: P22 no SELinux denial this boot, kernel or D-Bus (ADR 0014 consequences)
    When I run "journalctl -k -b --no-pager | grep -c 'avc: '" as root
    Then the output matches "^0$"
    When I run "ausearch -m USER_AVC -ts boot 2>/dev/null | grep -c 'avc:'" as root
    Then the output matches "^0$"

  @P22 @negative
  Scenario: P22 negative control
    Then the matcher "^0$" rejects "3"
