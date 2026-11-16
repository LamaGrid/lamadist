<!-- SPDX-License-Identifier: Apache-2.0 -->
# RAUC A/B Partitioning with `dm-verity`, LUKS Encryption, and UAPI DPS

This document details the "Split" partitioning strategy for embedded Linux systems using **RAUC** with **adaptive updates**. It adheres to the **UAPI Group's Discoverable Partitions Specification (DPS)** and integrates **Full Disk Encryption (FDE)** for maximum security.

## The "Split" Architecture (RAUC Adaptive + FDE)

### Overview

This architecture leverages RAUC's ability to update distinct components (Kernel, Rootfs, Verity Hash) individually or as a bundle. By splitting the Root Filesystem from its Integrity Data (Verity Hash), the system can perform **adaptive updates**.

**Security Features:**

* **Full Disk Encryption (FDE):** All partitions (Rootfs A/B, Data) are encrypted using **LUKS2**. This protects Intellectual Property (IP) and user secrets at rest.

* **Secure Delivery:** RAUC updates are delivered as **`crypt` bundles** (CMS encrypted), protecting the firmware image during transport.

* **Integrity:** The underlying filesystem is read-only EROFS protected by **dm-verity**.

## Partitioning Strategy

This section details the GPT disk layout for each platform. The partitions are discovered by the OS via **GPT Type UUIDs** defined by the UAPI specification.

**Note on LUKS:** In this architecture, the partitions below contain **LUKS2 headers**. The OS maps them to decrypted block devices (e.g., `/dev/mapper/rootfs_a`) before mounting.

### A. x86_64 (UEFI)

**Platform:** Generic x86_64 (Intel/AMD)
**Storage:** NVMe / SSD / eMMC
**Boot Firmware:** UEFI (BIOS) on Motherboard SPI

```
[ GPT Partition Table ]
├── [ p1: EFI System Partition (ESP) ] ── UUID: c12a7328-f81f-11d2-ba4b-00a0c93ec93b
│   ├── /EFI/BOOT/BOOTX64.EFI
│   ├── /EFI/Linux/ (Unified Kernel Images - A & B)
│   └── /EFI/RAUC/  (Slot Status / State)
│
├── [ p2: Rootfs A (LUKS2) ] ──────────── UUID: 4f68bce3-e8cd-4db1-96e7-fbcaf984b709
│   └── [ LUKS Header ]
│       └── [ Decrypted: Read-Only EROFS ]
│
├── [ p3: Verity Hash A ] ─────────────── UUID: 2c7357ed-ebd2-46d9-aec1-23d437ec2bf5
│   └── (Merkle Tree for decrypted p2)
│
├── [ p4: Rootfs B (LUKS2) ] ──────────── UUID: 4f68bce3-e8cd-4db1-96e7-fbcaf984b709
│   └── (Inactive Target)
│
├── [ p5: Verity Hash B ] ─────────────── UUID: 2c7357ed-ebd2-46d9-aec1-23d437ec2bf5
│   └── (Merkle Tree for decrypted p4)
│
└── [ p6: Var / Data (LUKS2) ] ────────── UUID: 4d21b016-b534-45c2-a9fb-5c16e091fd2d
    └── [ LUKS Header ]
        └── [ Decrypted: Read-Write Ext4 / XFS ]
```

### B. Nvidia Jetson Orin NX

**Platform:** ARM64 (Tegra234)
**Storage:** External NVMe (Module has no eMMC)
**Boot Firmware:** BootROM, PSC, and UEFI are stored on internal **QSPI Flash**.

The external NVMe drive is dedicated entirely to the OS, resulting in a clean layout similar to x86 but with ARM64 UUIDs.

```
[ GPT Partition Table (NVMe) ]
├── [ p1: EFI System Partition (ESP) ] ── UUID: c12a7328-f81f-11d2-ba4b-00a0c93ec93b
│   ├── /EFI/BOOT/BOOTAA64.EFI           (Provided by JetPack/L4T or custom distro)
│   └── /EFI/Linux/                      (Kernel UKI)
│
├── [ p2: Rootfs A (LUKS2) ] ──────────── UUID: 69dad710-2ce4-4e3c-b16c-21a1d49abed3
│
├── [ p3: Verity Hash A ] ─────────────── UUID: df3300ce-69f5-4c93-a803-5a56c9202305
│
├── [ p4: Rootfs B (LUKS2) ] ──────────── UUID: 69dad710-2ce4-4e3c-b16c-21a1d49abed3
│
├── [ p5: Verity Hash B ] ─────────────── UUID: df3300ce-69f5-4c93-a803-5a56c9202305
│
└── [ p6: Var / Data (LUKS2) ] ────────── UUID: 4d21b016-b534-45c2-a9fb-5c16e091fd2d
```

### C. Rockchip (RK3566 SOQuartz first, RK3588 RK1 second)

**Platform:** ARM64
**Storage:** eMMC / SD Card.  The image never names the disk: every runtime
path finds a partition by its partition or filesystem label, PARTUUID, or
type GUID, and the WKS's `--ondisk mmcblk0` only names wic's output disk.
U-Boot calls the eMMC `mmc0` and the SD slot `mmc1`; under Linux, with the
board device tree, the eMMC is `mmcblk1` and an SD card is `mmcblk0`.
**Boot Firmware:** `idbloader.img` (DDR TPL and SPL) and `u-boot.itb` (U-Boot, BL31, and the device tree) at fixed raw sectors, with U-Boot acting as the UEFI provider (ADR 0013).

The BootROM and SPL expect the loaders at fixed sectors, so the WKS
(`meta-lamadist/files/wic/lamadist-rockchip-bootdisk.wks.in`) reproduces
meta-rockchip's `files/wic/rockchip.wks` prelude (lines 21-28) at its
offsets, leaves the vendor-storage and reserved regions untouched, and
then builds the same ESP, A/B raw verity slots, and LUKS2 `var` as the
x86_64 template.  Offsets are 512-byte sectors.

```
[ GPT Partition Table ]
├── [ p1:  loader1 ] ──────── sector 64     3552K  idbloader.img (DDR TPL + SPL), raw
├── [ p2:  v_storage ] ────── sector 7168   256K   vendor storage (untouched)
├── [ p3:  reserved ] ─────── sector 7680   192K   (untouched)
├── [ p4:  reserved1 ] ────── sector 8064   32K    (untouched)
├── [ p5:  uboot_env ] ────── sector 8128   32K    empty; U-Boot keeps no environment
├── [ p6:  reserved2 ] ────── sector 8192   4096K  (untouched)
├── [ p7:  loader2 ] ──────── sector 16384  4096K  u-boot.itb (U-Boot + BL31 + device tree), raw
├── [ p8:  atf ] ──────────── sector 24576  4096K  (untouched)
│
├── [ p9:  EFI System Partition (ESP) ] ── UUID: c12a7328-f81f-11d2-ba4b-00a0c93ec93b
│   └── /EFI/BOOT/BOOTAA64.EFI           (systemd-boot; U-Boot's EFI loader starts it)
│
├── [ p10: rootfs_a (EROFS + dm-verity) ]  UUID: b921b045-1df0-41c3-af44-4c6f280d3fae
├── [ p11: hash_a ] ────────────────────── UUID: df3300ce-d69f-4c92-978c-9bfb0f38d820
├── [ p12: rootfs_b ] ──────────────────── UUID: b921b045-1df0-41c3-af44-4c6f280d3fae
├── [ p13: hash_b ] ────────────────────── UUID: df3300ce-d69f-4c92-978c-9bfb0f38d820
│
└── [ p14: var (LUKS2) ] ──────────────── UUID: 4d21b016-b534-45c2-a9fb-5c16e091fd2d
```

The loaders sit in the same block device as the OS with no write
protection, so an attacker with OS root who can open the whole-disk
node can replace U-Boot; see ADR 0013 decision 4.

## Architectural Notes & Device Nodes

**General Notes:**

* **Root Filesystem:** Uses **EROFS** (Enhanced Read-Only File System) for high performance and compression. EROFS is supported by RAUC as a `raw` image type written into the decrypted container.

* **Adaptive Updates:** RAUC uses the `casync` chunker to download only changed chunks.

* **Unified Kernel Images (UKI):** The kernel, initrd, and cmdline are bundled into a single `.efi` file. This UKI contains the `dm-verity` root hash.

### Security Strategy: Full Disk Encryption (FDE)

To protect IP and data, this architecture uses LUKS2 on all OS and Data partitions.

1. **Boot Process:**

   * The UKI is loaded and verified (Secure Boot).

   * The Initramfs (systemd) unlocks the active Rootfs partition (`p2` or `p4`) using a key sealed in the TPM2.

   * The OS boots.

2. **Update Process (RAUC):**

   * RAUC downloads a **`crypt` bundle**. This bundle is encrypted (CMS) so the firmware image is never exposed in plaintext during transit.

   * **Crucial Step:** RAUC is configured to write to the **decrypted mapper device** of the *inactive* slot (e.g., `/dev/mapper/rootfs_b`).

   * *Why?* Writing to the mapper device preserves the LUKS header on the physical partition (`p4`). If RAUC wrote to `/dev/nvme0n1p4` directly, it would overwrite the encryption header and destroy the key.

3. **Filesystem Overlay:**

   * Since the rootfs is immutable (EROFS), overlays are used for `/etc` and `/greengrass` (hosted on the encrypted `/var`).

**1. Data Partition Mount**

* **Source:** `/dev/mapper/data` (Decrypted LUKS device)

* **Target:** `/var`

* **Type:** `ext4` or `xfs` (Read-Write)

**2. /etc Overlay (Configuration)**

* **Mount Type:** `overlay`

* **LowerDir:** `/etc` (from Read-Only EROFS Root)

* **UpperDir:** `/var/overlay/etc/upper`

* **WorkDir:** `/var/overlay/etc/work`

**3. /greengrass Overlay (Application Data)**

* **Mount Type:** `overlay`

* **LowerDir:** `/greengrass` (from Read-Only EROFS Root)

* **UpperDir:** `/var/overlay/greengrass/upper`

* **WorkDir:** `/var/overlay/greengrass/work`

### Device Node Examples

**A. x86_64 (UEFI)**

* **Nodes:** `/dev/nvme0n1p2` (Physical Root A), `/dev/mapper/rootfs_a` (Decrypted Root A)

**B. Nvidia Jetson Orin NX**

* **Nodes:** `/dev/nvme0n1p2` (Physical Root A), `/dev/mapper/rootfs_a` (Decrypted Root A)

**C. Rockchip**

* **Nodes:** PARTLABEL `rootfs_a` (Physical Root A, dm-verity, partition 10)
  and PARTLABEL `var` (LUKS2, partition 14).  On the eMMC under Linux these
  are `/dev/mmcblk1p10` and `/dev/mmcblk1p14` (U-Boot: `mmc0`); on an SD
  card they are `/dev/mmcblk0p10` and `/dev/mmcblk0p14` (U-Boot: `mmc1`,
  which the pinned `boot_targets` never scans).

## Templates

Below are **Wic (.wks)** kickstart templates for Yocto.

### A. x86_64 (UEFI)

#### WKS Template

```
bootloader --ptable gpt --timeout=3 --append="rootwait"

# ESP -- sized for BOTH slots' boot payloads (kernel + initramfs +
# microcode, ~70 MB per slot today) plus growth; an OTA update
# stages the inactive slot's files here before switching, and an
# ESP can never realistically be resized on fielded A/B devices.
part /boot/efi --source bootimg-efi --sourceparams="loader=systemd-boot" --ondisk sda --label efi --active --align 1024 --fixed-size 512M --part-type c12a7328-f81f-11d2-ba4b-00a0c93ec93b

# Rootfs A (x86_64 UUID) - LUKS Container
part / --source rootfs --ondisk sda --fstype=erofs --label rootfs_a --align 1024 --fixed-size 3G --part-type 4f68bce3-e8cd-4db1-96e7-fbcaf984b709

# Verity A (x86_64 Verity UUID)
part --source rawcopy --sourceparams="file=rootfs.img.verity" --ondisk sda --label hash_a --align 1024 --fixed-size 96M --part-type 2c7357ed-ebd2-46d9-aec1-23d437ec2bf5

# Rootfs B (x86_64 UUID) - LUKS Container
part --source rootfs --ondisk sda --fstype=erofs --label rootfs_b --align 1024 --fixed-size 3G --part-type 4f68bce3-e8cd-4db1-96e7-fbcaf984b709

# Verity B (x86_64 Verity UUID)
part --source rawcopy --sourceparams="file=rootfs.img.verity" --ondisk sda --label hash_b --align 1024 --fixed-size 96M --part-type 2c7357ed-ebd2-46d9-aec1-23d437ec2bf5

# Data (LUKS Container)
part /var --ondisk sda --fstype=ext4 --label var --align 1024 --fixed-size 2G --part-type 4d21b016-b534-45c2-a9fb-5c16e091fd2d
```

#### Configuration

**Kernel Command Line:**
In a UKI/UAPI setup with LUKS, the `roothash` protects the inner filesystem, while `luks.uuid` (or auto-discovery) handles the container unlocking.

```
console=ttyS0,115200 rootwait roothash=
```

**/etc/fstab:**
Includes the `/greengrass` overlay.

```
#
PARTLABEL=var      /var            ext4     defaults,x-systemd.requires=/dev/mapper/data                                                       0       2
overlay            /greengrass     overlay  lowerdir=/greengrass,upperdir=/var/overlay/green/upper,workdir=/var/overlay/green/work,x-systemd.requires=/var  0       0
```

**Systemd Unit (`/lib/systemd/system/etc.mount`):**

```
[Unit]
Description=Overlay /etc
DefaultDependencies=no
Conflicts=umount.target
Before=local-fs.target umount.target
RequiresMountsFor=/var

[Mount]
What=overlay
Where=/etc
Type=overlay
Options=lowerdir=/etc,upperdir=/var/overlay/etc/upper,workdir=/var/overlay/etc/work

[Install]
WantedBy=local-fs.target
```

### B. Nvidia Jetson Orin NX

*Note: Uses ARM64 UUIDs. Requires NVMe target.*

#### WKS Template

```
bootloader --ptable gpt --timeout=3 --append="rootwait"

# ESP
part /boot/efi --source bootimg-efi --sourceparams="loader=systemd-boot" --ondisk nvme0n1 --label efi --active --align 1024 --fixed-size 512M --part-type c12a7328-f81f-11d2-ba4b-00a0c93ec93b

# Rootfs A (ARM64 UUID) - LUKS Container
part / --source rootfs --ondisk nvme0n1 --fstype=erofs --label rootfs_a --align 1024 --fixed-size 4G --part-type 69dad710-2ce4-4e3c-b16c-21a1d49abed3

# Verity A (ARM64 Verity UUID)
part --source rawcopy --sourceparams="file=rootfs.img.verity" --ondisk nvme0n1 --label hash_a --align 1024 --fixed-size 128M --part-type df3300ce-69f5-4c93-a803-5a56c9202305

# Rootfs B (ARM64 UUID) - LUKS Container
part --source rootfs --ondisk nvme0n1 --fstype=erofs --label rootfs_b --align 1024 --fixed-size 4G --part-type 69dad710-2ce4-4e3c-b16c-21a1d49abed3

# Verity B (ARM64 Verity UUID)
part --source rawcopy --sourceparams="file=rootfs.img.verity" --ondisk nvme0n1 --label hash_b --align 1024 --fixed-size 128M --part-type df3300ce-69f5-4c93-a803-5a56c9202305

# Data (LUKS Container)
part /var --ondisk nvme0n1 --fstype=ext4 --label var --align 1024 --fixed-size 2G --part-type 4d21b016-b534-45c2-a9fb-5c16e091fd2d
```

#### Configuration

**Kernel Command Line:**

```
console=ttyTCU0,115200 rootwait roothash=
```

**/etc/fstab:**

```
#
PARTLABEL=var      /var            ext4     defaults,x-systemd.requires=/dev/mapper/data                                                       0       2
overlay            /greengrass     overlay  lowerdir=/greengrass,upperdir=/var/overlay/green/upper,workdir=/var/overlay/green/work,x-systemd.requires=/var  0       0
```

### C. Rockchip

*Note: Includes raw loaders.*

#### WKS Template

The shipped template is
`meta-lamadist/files/wic/lamadist-rockchip-bootdisk.wks.in`.  Its
prelude is the part of meta-rockchip's `rockchip.wks` that the BootROM
dictates; everything after it is identical to the x86_64 template
except `--ondisk`.

```
part loader1   --ondisk mmcblk0 --offset 64s    --fixed-size 3552K --fstype=none --part-name loader1   --source rawcopy --sourceparams="file=${SPL_BINARY}"
part v_storage --ondisk mmcblk0 --offset 7168s  --fixed-size 256K  --fstype=none --part-name v_storage
part reserved  --ondisk mmcblk0 --offset 7680s  --fixed-size 192K  --fstype=none --part-name reserved
part reserved1 --ondisk mmcblk0 --offset 8064s  --fixed-size 32K   --fstype=none --part-name reserved1
part uboot_env --ondisk mmcblk0 --offset 8128s  --fixed-size 32K   --fstype=none --part-name uboot_env
part reserved2 --ondisk mmcblk0 --offset 8192s  --fixed-size 4096K --fstype=none --part-name reserved2
part loader2   --ondisk mmcblk0 --offset 16384s --fixed-size 4096K --fstype=none --part-name loader2   --source rawcopy --sourceparams="file=u-boot.${UBOOT_SUFFIX}"
part atf       --ondisk mmcblk0 --offset 24576s --fixed-size 4096K --fstype=none --part-name atf
# ESP, rootfs_a/hash_a, rootfs_b/hash_b, and var follow, as in the x86_64 WKS.
```

#### Configuration

**Kernel Command Line:**

```
console=tty0 console=ttyS2,1500000  (provisional console; see soquartz-lamadist.conf)
```

**/etc/fstab:**

```
#
PARTLABEL=var      /var            ext4     defaults,x-systemd.requires=/dev/mapper/data                                                       0       2
overlay            /greengrass     overlay  lowerdir=/greengrass,upperdir=/var/overlay/green/upper,workdir=/var/overlay/green/work,x-systemd.requires=/var  0       0
```

## References

* **UAPI Specification:**

  * **Spec:** [Discoverable Partitions Specification (DPS)](https://uapi-group.org/specifications/specs/discoverable_partitions_specification/)

  * **Reference:** Check the "Partition Type UUIDs" table for Architecture-specific IDs.

* **RAUC Adaptive Updates:**

  * **Docs:** [RAUC Adaptive Updates](https://rauc.readthedocs.io/en/latest/advanced.html#adaptive-updates)
