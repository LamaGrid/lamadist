# SPDX-License-Identifier: Apache-2.0
# Goal 3: the security properties the M4 gate closed on still hold on
# the running system.  One scenario per property; each has a
# @negative twin that feeds the same matcher an input it must reject
# (ADR 0010 rule 4).  Gate references are in the scenario names.

@G3
Feature: Security properties on the live system

  @P1
  Scenario: P1 root integrity, the rootfs is the verity mapper on erofs (Stage-B exit, PLAN.md:412)
    When I run "cat /proc/cmdline"
    Then the output matches "root=/dev/mapper/rootfs"
    And the output matches "roothash=[0-9a-f]{64}"
    When I run "cat /proc/mounts"
    Then the output matches "^/dev/mapper/rootfs / erofs "

  @P1 @negative
  Scenario: P1 negative control
    Then the matcher "^/dev/mapper/rootfs / erofs " rejects "/dev/sda2 / ext4 rw,relatime 0 0"
    And the matcher "roothash=[0-9a-f]{64}" rejects "roothash= root=/dev/mapper/rootfs"

  @P5
  Scenario: P5 SELinux is enforcing (PLAN.md:412,416)
    When I run "cat /sys/fs/selinux/enforce"
    Then the output matches "^1$"
    When I run "cat /etc/selinux/config"
    Then the output matches "^SELINUX=enforcing$"

  @P5 @negative
  Scenario: P5 negative control
    Then the matcher "^1$" rejects "0"
    And the matcher "^SELINUX=enforcing$" rejects "SELINUX=permissive"

  @P2
  Scenario: P2 Secure Boot is enabled, read from the in-guest efivar (Stage-B exit, PLAN.md:412)
    When I run "od -An -tu1 -j4 -N1 /sys/firmware/efi/efivars/SecureBoot-8be4df61-93ca-11d2-aa0d-00e098032b8c"
    Then the output matches "^\s*1\s*$"

  @P2 @negative
  Scenario: P2 negative control
    Then the matcher "^\s*1\s*$" rejects "   0"

  @P8
  Scenario: P8 the /etc overlay is mounted read-write (PLAN.md:371,416)
    When I run "cat /proc/mounts"
    Then the output matches "^overlay /etc overlay rw,"

  @P8 @negative
  Scenario: P8 negative control
    Then the matcher "^overlay /etc overlay rw," rejects "overlay /etc overlay ro,relatime 0 0"

  @P9
  Scenario: P9 no plaintext swap is active (BLOCKER-1, PLAN.md:407)
    When I run "wc -l < /proc/swaps"
    Then the output matches "^1$"
    When I run "systemctl list-units --type=swap --no-legend --plain | wc -l"
    Then the output matches "^0$"

  @P9 @negative
  Scenario: P9 negative control
    Then the matcher "^1$" rejects "2"
    And the matcher "^0$" rejects "1"

  @P7 @root
  Scenario: P7 PID 1 runs in a real SELinux domain (Condition B, PLAN.md:416)
    When I run "cat /proc/1/attr/current" as root
    Then the output matches "^system_u:system_r:init_t:"
    And the output does not match "kernel_t"

  @P7 @negative
  Scenario: P7 negative control
    Then the matcher "^system_u:system_r:init_t:" rejects "system_u:system_r:kernel_t:s0"

  @P4 @root
  Scenario: P4 /var is LUKS2 with a TPM2 token (Stage-B TPM2, PLAN.md:412)
    When I run "dmsetup info -c --noheadings -o uuid $(awk '$2 == "/var" {print $1}' /proc/mounts)" as root
    Then the output matches "^CRYPT-LUKS2-"
    When I run "cryptsetup luksDump $(cryptsetup status $(basename $(awk '$2 == "/var" {print $1}' /proc/mounts)) | awk '/^ *device:/ {print $2}')" as root
    Then the output matches "^Version:\s+2$"
    And the output matches "systemd-tpm2"

  @P4 @negative
  Scenario: P4 negative control
    Then the matcher "^CRYPT-LUKS2-" rejects "CRYPT-PLAIN-var"
    And the matcher "^Version:\s+2$" rejects "Version:       1"

  @P14 @root
  Scenario: P14 IMA measures in log mode (Stage-B exit, PLAN.md:412)
    When I run "cat /proc/cmdline"
    Then the output matches "ima_policy=tcb"
    And the output matches "ima_appraise=log"
    When I run "wc -l < /sys/kernel/security/ima/ascii_runtime_measurements" as root
    Then the output matches "^[1-9][0-9]*$"

  @P14 @negative
  Scenario: P14 negative control
    Then the matcher "ima_appraise=log" rejects "ima_appraise=off"
    And the matcher "^[1-9][0-9]*$" rejects "0"

  @P15
  Scenario: P15 sshd refuses password authentication (policy: no password authentication over the network)
    Then the target offers only "publickey" authentication

  @P15 @negative
  Scenario: P15 negative control
    Then the authentication list "publickey,password" is not only "publickey"
