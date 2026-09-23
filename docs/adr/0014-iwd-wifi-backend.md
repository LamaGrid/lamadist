# ADR 0014: iwd as the WiFi Backend

## Status

Accepted (2026-09-23).  Proposed 2026-09-20; rolled out to the live
device 2026-09-22 per decision 7.

## Context

The live x86_64 test device is WiFi-only.  Its station came up on
wpa_supplicant, the daemon oe-core's `packagegroup-base-wifi` selects
by default (`WIRELESS_DAEMON ??= "wpa-supplicant"`), through an
`ExecStart` override that pointed the `wlan0` instance at a
configuration file on the encrypted `/var`, because the unit's `/etc`
path is unprovisionable on an image whose `/etc` is a write-locked
overlay.  systemd-networkd does the addressing.  NetworkManager is
not installed and was never a candidate.

A spike (2026-09-20) weighed iwd against keeping wpa_supplicant,
using this project's own Gentoo host (iwd plus systemd-networkd under
SELinux) as the model and the refpolicy sources as the evidence:

- refpolicy folds both daemons into its `networkmanager` module:
  `/usr/libexec/iwd` is `NetworkManager_exec_t` and
  `/var/lib/iwd(/.*)?` is `NetworkManager_var_lib_t` upstream, both
  already compiled into the image's `file_contexts`, so iwd runs in
  the same `NetworkManager_t` domain wpa_supplicant does, with the
  same manage rights on its state.  One permission is missing: iwd
  watches its state directory with inotify, and `NetworkManager_t`
  has `watch` on `NetworkManager_etc_t` but not on
  `NetworkManager_var_lib_t` (verified with `sesearch` on the built
  policy).  The model host runs permissive, so its clean audit log
  proved nothing on that point.
- iwd's state directory is `/var/lib/iwd` natively (`StateDirectory=`
  in the upstream unit), so the `ExecStart` rewrite goes away; the
  upstream unit is hardened (`ProtectSystem=strict`, a
  `CapabilityBoundingSet` of three capabilities, `DevicePolicy=closed`
  with `/dev/rfkill` only, `LimitNPROC=1`, `NoNewPrivileges`).
- iwd's `modules-load.d` requests `pkcs8_key_parser`; the kernel
  fragment for it is the one prerequisite in the tree.
- The recipe's default `PACKAGECONFIG` builds `iwctl` (a readline
  build dependency, GPL-3.0-or-later) and `iwmon` (a netlink
  sniffer); neither belongs on the base image.
- Footprint is not the argument: `iw` stays and keeps libnl in the
  image, so a daemon-only iwd saves roughly one to one and a half
  MiB.  What the port buys is one confined process with native `/var`
  state, the upstream hardening, and a unit that is not bound to a
  netdev (the wpa_supplicant instance's device dependency held
  `multi-user.target` for its 90 s job timeout on every radio-less
  QEMU boot).
- iwd 3.12 is `LGPL-2.1-only` with ELL bundled statically under the
  same licence: weak copyleft, consumed as an unmodified upstream
  daemon that systemd executes, with nothing of ours linked into it.
  Under the project's licence policy that tier is permitted and
  logged; readline, which would have been the only strong-copyleft
  pull, is not built.

## Decision

1. `WIRELESS_DAEMON = "iwd"` in the distro include; the
   wpa_supplicant bbappend and its files are removed.
2. iwd is built daemon-only (`PACKAGECONFIG = "systemd"`).  A field
   client, if ever wanted, enters through the debug overlay, never
   the base image.
3. Addressing stays with systemd-networkd:
   `EnableNetworkConfiguration` keeps its default (off), and the
   `wlan0` DHCP profile carries over unchanged.  iwd is ordered after
   `var.mount`, since its state lives there.
4. Network profiles are provisioned out of band into `/var/lib/iwd`
   as `[Security] Passphrase=` files, never baked; the same tmpfiles
   `d` + `Z` pair that served wpa_supplicant creates and relabels the
   directory every boot, because nothing else relabels the LUKS
   `/var`.  The passphrase form rather than the pre-shared key,
   because the lab access point offers SAE, which needs it.
5. The policy module gains one rule, `allow NetworkManager_t
   NetworkManager_var_lib_t:dir { watch watch_reads };`, and loses its
   only file-context entry, since upstream already labels
   `/var/lib/iwd`.
6. `/etc/iwd/main.conf` is baked into the read-only lower with
   `[General] UseDefaultInterface=true`: iwd keeps the kernel's
   netdev for every radio instead of destroying and recreating it at
   startup.  That keeps the `wlan0` name stable across a driver
   re-probe (a recreated netdev is named from the wiphy index), and
   it removes a race the recreate path has when two radios appear at
   once: the second `NEW_INTERFACE` fails on the name the netdev
   being deleted still holds, which is exactly how the QEMU test
   loads its two virtual radios.  The per-driver form,
   `[DriverQuirks] DefaultInterface=mt7921e`, is baked beside it for
   the day the global key is removed; it cannot replace it today,
   because iwd matches driver quirks on
   `/sys/class/ieee80211/<phy>/device/driver` and `mac80211_hwsim`
   radios have no driver link.  The global key is deprecated in name
   and logs one warning at startup; iwd 3.12 honours it.
7. Rollout to the WiFi-only device only after the RAUC health gate's
   network guard is in place, with the profile provisioned from the
   running wpa_supplicant slot first and the old configuration left
   until an iwd slot has been committed and survived an unrelated
   reboot.

## Alternatives considered

- Keep wpa_supplicant: works today, but through an `ExecStart`
  rewrite and a device-bound unit, with a larger multi-process daemon
  and helper packages.  Rejected; nothing is lost by the swap.
- iwd with the recipe defaults: ships a sniffer and a GPL-3 readline
  link on a hardened image for a client the field does not use.
  Rejected.
- iwd doing its own addressing (`EnableNetworkConfiguration=true`):
  duplicates what networkd already does for every other link and
  moves DHCP into the frame-parsing process.  Rejected.
- NetworkManager: never installed, and a much larger trusted surface
  than either supplicant.  Rejected.

## Consequences

- The confinement shape is unchanged: the same domain, the same state
  type, one added permission.  The QEMU proof runs enforcing against
  two virtual radios (`mac80211_hwsim`), with iwd as the station and
  the access point and networkd serving the lease, and asserts the
  daemon's domain, an association, a lease on `wlan0`, and zero new
  denials; the device validation suite gains the same checks against
  the real radio.
- iwd installs `80-iwd.link` (`NamePolicy=keep kernel` for wireless
  links), which shadows the image's `99-default.link` for `wlan0`;
  the hardware address is the card's own either way, and the first
  device boot confirmed it (2026-09-22: the hardware address and the
  leased IPv4 address were unchanged across the swap).
- `iwd.service` is `Type=dbus`, so the system bus is on the WiFi
  critical path; dbus is already enabled on the image.  The shipped
  D-Bus policy lets members of `wheel` talk to the daemon; on this
  image that is the administrator, who already has sudo.
- The validate suite's WiFi checks and the device rollout follow as
  their own increments.
