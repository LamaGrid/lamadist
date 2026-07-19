# SPDX-License-Identifier: Apache-2.0

# selinux-image inherits core-image and labels the rootfs at image
# build time (setfiles via IMAGE_PREPROCESS_COMMAND).  Build-time
# labeling is required because first-boot autorelabel cannot work
# on the read-only dm-verity root (FIRST_BOOT_RELABEL is '0' in
# lamadist-security.inc).
inherit selinux-image

IMAGE_FEATURES += "ssh-server-openssh"

CORE_IMAGE_BASE_INSTALL += "packagegroup-lamadist-base"
SYSTEMD_DEFAULT_TARGET = "multi-user.target"

# Administrator account: 'lama', wheel group, sudo via the wheel
# drop-in below.  The default password is 'lamadist' (fixed salt
# for reproducible builds).  Root login stays locked.
#
# No passwd-expire: /etc/shadow is on the read-only dm-verity
# root, so a forced first-login password change fails with
# "Authentication token manipulation error".  Revisit when /etc
# gains persistent state (credential provisioning milestone).
#
# The \$ escapes in the hash are load-bearing: useradd_base runs
# these commands through an extra shell eval, which strips the
# single quotes and expands unescaped $-words to empty strings,
# silently truncating the hash.
inherit extrausers
EXTRA_USERS_PARAMS = " \
    groupadd -r wheel; \
    useradd -m -G wheel -s /bin/bash \
        -p '\$6\$lamadist0\$NXM9PMLc/bVywi2Vg2ezUQpV5LVfLPBAkGX0araFFR9TuU4wL51EG9XxTApL4gi4u6.QSjMn3jNyfyeEoNlqf/' \
        lama; \
"

lamadist_sudoers_wheel() {
    install -d ${IMAGE_ROOTFS}${sysconfdir}/sudoers.d
    echo '%wheel ALL=(ALL:ALL) ALL' > ${IMAGE_ROOTFS}${sysconfdir}/sudoers.d/wheel
    chmod 0440 ${IMAGE_ROOTFS}${sysconfdir}/sudoers.d/wheel
}
ROOTFS_POSTPROCESS_COMMAND += "lamadist_sudoers_wheel; "

# The root filesystem is sealed by dm-verity, so declare it
# read-only (ro fstab root entry, ro kernel cmdline, volatile
# population) and mount a writable /var from the disk partition the
# WKS template creates (PARTLABEL 'var').
#
# ponytail: the var partition starts empty and services recreate
# what they need via tmpfiles/mkdir; factory population moves to
# the M3 data-partition design (PARTITIONING.md).
IMAGE_FEATURES += "read-only-rootfs"

# /var is LUKS2-encrypted (M4 plan decision 4): wic cannot format the
# partition as a LUKS container itself, so it still ships as the
# plain, empty ext4 filesystem wic built; lamadist-luks-var's
# lamadist-var-encrypt.service luksFormats it in place the first
# boot that finds no LUKS2 header there (a one-way migration -- see
# that recipe's files/lamadist-var-encrypt).
#
# Every boot after unlocks it via TPM2 (tpm2-device=auto, key field
# 'none'), not the keyfile: lamadist-var-tpm2-enroll.service (M4
# plan W11) enrolls a PCR7-sealed keyslot on first boot, ordered
# before this crypttab entry's systemd-cryptsetup@var.service ever
# runs (see that recipe's files/lamadist-var-tpm2-enroll.service).
# The DEVELOPMENT-ONLY keyfile at /etc/lamadist/dev-var.key (see
# recipes-core/luks/files/README.md) stays a live keyslot as a
# fallback -- it is DEV BEHAVIOR ONLY, pending security-owner
# sign-off on killing/gating it for non-dev builds (same README).
#
# A device with no TPM2 (or one whose PCR7 changed, e.g. Secure Boot
# state/keys changed since enrollment) has NO automatic fallback
# from this crypttab line: systemd-cryptsetup tries tpm2-device=auto,
# and with no interactive console (the QEMU CI/headless paths, and
# any unattended target boot) a failure here fails the 'var' mount,
# not a keyfile prompt.  This is intentional, not an oversight: every
# supported boot path currently has a TPM2 -- .mise/tasks/vm starts
# swtpm unconditionally (both plain and --secureboot runs, CI,
# headless, and interactive), and the only MACHINE this distro
# builds (intel.conf) requires DISTRO_FEATURES 'tpm2' via
# lamadist-tpm2.inc.  A future dev machine that legitimately lacks a
# TPM would need a crypttab drop-in (or a build-time toggle back to
# the keyfile field) rather than relying on this entry's absent
# fallback.
lamadist_crypttab_var() {
    echo 'var  PARTLABEL=var  none  luks,discard,tpm2-device=auto' >> ${IMAGE_ROOTFS}${sysconfdir}/crypttab
}
ROOTFS_POSTPROCESS_COMMAND += "lamadist_crypttab_var; "

# fstab mounts the mapper device the crypttab entry above creates,
# not the raw PARTLABEL partition -- systemd's fstab-generator infers
# the ordering dependency on the /dev/mapper/var device unit itself,
# same as it did for the old LABEL=var raw-partition entry.
lamadist_fstab_var() {
    echo '/dev/mapper/var  /var  ext4  defaults  0  2' >> ${IMAGE_ROOTFS}${sysconfdir}/fstab
}
ROOTFS_POSTPROCESS_COMMAND += "lamadist_fstab_var; "

# Mask ldconfig.service.  The dynamic linker cache is baked complete
# at image build (glibc's do_rootfs ldconfig pass) and lives on the
# read-only dm-verity root, where it never goes stale -- libraries
# cannot change on an immutable root.  Left unmasked, oe-core's
# ldconfig.service regenerates /etc/ld.so.cache on every boot, and
# because /etc is an overlay whose upperdir sits on the LUKS /var
# (var_t), the freshly-created cache is a NEW file that inherits the
# upper's var_t rather than ld_so_cache_t.  Every dynamically-linked
# program then mmaps a var_t ld.so.cache at startup, which under
# enforcing SELinux denies ~every domain at once (the dominant
# cluster in the W12 AVC triage).  Masking the pointless regen keeps
# the correctly-labeled baked cache from the lower, fixing the storm
# at its source -- no runtime relabel, no local-policy relabel grant.
# Mirrors the systemd-bless-boot mask in rauc-conf.bbappend.
lamadist_mask_ldconfig_service() {
    install -d ${IMAGE_ROOTFS}${sysconfdir}/systemd/system
    ln -sf /dev/null \
        ${IMAGE_ROOTFS}${sysconfdir}/systemd/system/ldconfig.service
}
ROOTFS_POSTPROCESS_COMMAND += "lamadist_mask_ldconfig_service; "

# /etc is a writable overlayfs upper layer once /var (mounted above)
# is available (M4 plan D5).  oe-core's overlayfs-etc.bbclass cannot
# be used for this: its only mechanism is a preinit script that
# replaces /sbin/init and mounts the backing device BEFORE the real
# systemd starts -- but /dev/mapper/var is created by systemd itself
# (systemd-cryptsetup@var, generated from the crypttab entry above),
# so that device can never exist yet when such a preinit runs.  This
# unit does only the overlay mount -- not a second mount of
# /dev/mapper/var, the fstab entry above already owns that -- ordered
# After/Requires=var.mount and Before=sysinit.target, so /etc is
# overlaid before any user-facing service starts.  DefaultDependencies=no
# and the manual sysinit.target.wants symlink below mirror
# lamadist-luks-var's lamadist-var-encrypt.service, which has the
# same early, non-normal-shutdown-DAG shape.
lamadist_etc_overlay_unit() {
    install -d ${IMAGE_ROOTFS}${systemd_system_unitdir}
    cat > ${IMAGE_ROOTFS}${systemd_system_unitdir}/lamadist-etc-overlay.service <<-EOF
        [Unit]
        Description=LamaDist /etc overlay (writable upper on /var)
        DefaultDependencies=no
        Conflicts=shutdown.target
        Requires=var.mount
        After=var.mount
        Before=sysinit.target local-fs.target shutdown.target

        [Service]
        Type=oneshot
        RemainAfterExit=yes
        ExecStartPre=/bin/mkdir -p /var/overlay-etc/upper /var/overlay-etc/work
        # Drop any /etc/ld.so.cache a PRIOR boot's ldconfig.service left
        # in the upper before that service was masked.  /var survives
        # updates, so an in-place upgrade of an existing device would
        # otherwise keep serving the stale var_t cache from the upper,
        # shadowing the correctly-labeled lower and re-triggering the
        # ~every-domain mmap denial storm under enforcing.
        ExecStartPre=-/bin/rm -f /var/overlay-etc/upper/ld.so.cache
        ExecStart=/bin/mount -t overlay -o upperdir=/var/overlay-etc/upper,lowerdir=/etc,workdir=/var/overlay-etc/work,index=off,xino=off,redirect_dir=off,metacopy=off overlay /etc
        # Mounting over /etc hides submounts, and on this read-only
        # root PID 1 bind-mounts /run/machine-id onto /etc/machine-id
        # before any unit runs -- without the rebind, machine-id
        # reads go through the overlay to the baked empty file
        # (observed live as empty machineid= in shell-integration
        # frames).  '-' tolerates systems where PID 1 didn't need
        # the bind (writable /etc/machine-id baked in).
        ExecStartPost=-/bin/mount --bind /run/machine-id /etc/machine-id

        [Install]
        WantedBy=sysinit.target
	EOF

    install -d ${IMAGE_ROOTFS}${sysconfdir}/systemd/system/sysinit.target.wants
    ln -sf ${systemd_system_unitdir}/lamadist-etc-overlay.service \
        ${IMAGE_ROOTFS}${sysconfdir}/systemd/system/sysinit.target.wants/lamadist-etc-overlay.service
}
ROOTFS_POSTPROCESS_COMMAND += "lamadist_etc_overlay_unit; "

# The RAUC OTA commit/rollback chain (lamadist-health-check, the
# systemd-boot custom backend, and the bundle hook) all read/write
# ESP loader entries under /boot at runtime and require it mounted
# read-write.  Without an explicit fstab entry, whether /boot ends
# up mounted at all -- and at /boot rather than /efi -- depends on
# systemd-gpt-auto-generator guessing right, which is not reliable
# with a dm-verity mapper root.  Pin it the same way /var is pinned,
# using the filesystem label the WKS template gives the ESP
# partition (--label msdos on the /boot part in
# lamadist-dmverity-bootdisk.wks.in).
lamadist_fstab_boot() {
    echo 'LABEL=msdos  /boot  vfat  defaults,x-systemd.automount  0  2' >> ${IMAGE_ROOTFS}${sysconfdir}/fstab
}
ROOTFS_POSTPROCESS_COMMAND += "lamadist_fstab_boot; "

# read_only_rootfs_hook points sshd at volatile /var/run/ssh host
# keys, which would regenerate every boot and break known_hosts
# trust.  Persist them under /var/lib/ssh instead (sshdgenkeys
# creates the directory).
#
# IMAGE_PREPROCESS_COMMAND, not ROOTFS_POSTPROCESS_COMMAND:
# /etc/default/ssh is CREATED by read_only_rootfs_hook, itself a
# rootfs-postprocess command whose position in that list depends on
# bbclass parse order.  This function ran before it once and its
# existence guard silently skipped both files (observed live:
# /etc/default/ssh still said /var/run/ssh, keys volatile).
# IMAGE_PREPROCESS_COMMAND runs strictly after every rootfs
# postprocess, so the ordering can't regress.
lamadist_persist_ssh_hostkeys() {
    for _f in ${IMAGE_ROOTFS}${sysconfdir}/default/ssh \
              ${IMAGE_ROOTFS}${sysconfdir}/ssh/sshd_config_readonly; do
        if [ -e "$_f" ]; then
            sed -i 's|/var/run/ssh|/var/lib/ssh|g' "$_f"
        else
            bbwarn "lamadist_persist_ssh_hostkeys: $_f missing, skipped"
        fi
    done
}
IMAGE_PREPROCESS_COMMAND:append = " lamadist_persist_ssh_hostkeys; "

LICENSE = "Apache-2.0"
