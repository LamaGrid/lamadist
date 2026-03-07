<!-- SPDX-License-Identifier: Apache-2.0 -->
# LamaDist Development Plan

This document outlines the phased development plan for the LamaDist project, a Yocto/OE distribution for homelab devices.

## Overview

LamaDist is designed to provide a secure, maintainable, and feature-rich Linux distribution for homelab hardware, including:
- x86_64 Intel-based systems
- ARM-based Single Board Computers (Orin NX, RK1, SOQuartz)

The development is organized into phases, with each phase building upon the previous to create a comprehensive distribution solution.

---

## Concept of Operations

- **Operator**: A single administrator managing a large number of nodes / devices.
- **Operational scenarios**: Unattended home server, NAS, edge compute node, or k3s
  cluster member. Devices run 24/7 with infrequent physical access; remote management
  is the norm.
- **Quality attribute priorities** (in order):
  1. Security
  2. Reliability
  3. Maintainability
  4. Performance
- **Deployment model**: Images are built on a development workstation (or CI runner),
  then flashed to target hardware (USB installer, network install) or deployed via OTA
  using RAUC. The target runs immutably; host-specific configuration is injected via
  kernel command line parameters and RAUC bundles. No configuration management tooling
  (Ansible, Puppet, etc.) is required on the target.

---

## Phase 0: Architecture Documentation + Tooling Baseline

**Status:** Complete  
**Goal:** Establish project documentation, architecture baseline, and development standards.

### Steps

#### 0.1 Core Documentation
- [x] Create master development plan (`docs/PLAN.md`)
- [x] Create architecture documentation (`docs/ARCHITECTURE.md`)
- [x] Create contribution guidelines (`docs/CONTRIBUTING.md`)
- [x] Create tooling baseline documentation (`docs/TOOLING.md`)
- [x] Update README with documentation links and quick start

**Acceptance Criteria:**
- All documentation files exist in the `docs/` directory
- Documentation includes SPDX license headers
- README provides clear entry point to the project
- Documentation is well-structured with clear Markdown formatting

#### 0.2 Development Standards
- [x] Define code review process and standards
- [x] Establish commit message conventions (Conventional Commits with git trailers)
- [x] Define branch naming strategy (JIT Flow)
- [x] Create PR templates
- [x] Create issue templates

**Acceptance Criteria:**
- Contribution guidelines document all development standards
- Standards are consistent with Yocto/OE best practices
- Clear examples provided for common scenarios
- JIT Flow branching strategy documented with examples and diagram
- Git trailer conventions documented with examples

#### 0.3 Tooling Setup
- [x] Document required tools and versions (mise + podman)
- [x] Create developer environment setup guide (mise-based workflow)
- [x] Document mise task runner usage
- [x] Add troubleshooting section for common setup issues
- [x] Implement mise task definitions (`.mise.toml`)
- [x] Migrate container Python dependencies to `uv` + `pyproject.toml`
- [ ] Validate QEMU launch from build container with SPICE/VNC viewer passthrough
- [x] Deprecate and remove `Makefile` and `Pipfile` once mise tasks are validated

**Acceptance Criteria:**
- New developers can set up environment from documentation using only `mise` and `podman`
- All mise tasks are documented with flags and autocompletion support
- Common issues have documented solutions
- QEMU images can be tested from the build container with graphical output via SPICE or VNC

> **Note:** QEMU launch validation with SPICE/VNC viewer passthrough requires a running build container with a built image and is deferred to Phase 2 (Recipe Testing, §2.4).

### Phase 0 Exit Criteria
- [x] All 0.x acceptance criteria met
- [x] All documentation reviewed and internally consistent across `docs/`
- [x] `.mise.toml` implemented and functional; Makefile fully deprecated
- [x] A new contributor can clone the repo, run `mise install`, and successfully execute `mise run build --bsp x86_64`
- [x] PR and issue templates exist in `.github/`
- [x] JIT Flow branching strategy documented with diagram and examples

---

## Phase 1: Core Distribution Foundation

**Status:** Not Started  
**Goal:** Establish the foundational Yocto distribution configuration and layer structure.

### Steps

#### 1.1 Distribution Configuration
- [ ] Review and refine `meta-lamadist/conf/distro/lamadist.conf`
- [ ] Define distro feature set (security, containers, etc.)
- [ ] Configure package management (RPM with mandatory signing)
- [ ] Set up init system (systemd)
- [ ] Define optimization and build flags
- [ ] Establish systemd-first tool preference policy

**Acceptance Criteria:**
- Distro configuration is complete and well-documented
- All distro features have clear rationale
- Configuration follows Yocto best practices
- systemd tools are preferred over alternatives (systemd-timesyncd, systemd-networkd, etc.)
- RPM package format configured with signing requirements

#### 1.2 Layer Structure
- [ ] Organize `meta-lamadist` layer structure
- [ ] Define layer dependencies clearly
- [ ] Create layer documentation (README)
- [ ] Ensure layer compatibility with Yocto LTS releases

**Acceptance Criteria:**
- Layer structure follows OpenEmbedded standards
- Layer README documents purpose and usage
- Layer passes yocto-check-layer validation

#### 1.3 Machine Configurations
- [ ] Review and enhance machine configs for supported hardware
  - [ ] x86_64 Intel systems
  - [ ] Orin NX
  - [ ] RK1
  - [ ] SOQuartz
- [ ] Define bootloader configurations per machine
- [ ] Configure kernel selections per machine
- [ ] Set machine-specific features (TPM, UEFI, etc.)

**Acceptance Criteria:**
- Each supported machine has complete configuration
- Machine configs are modular and maintainable
- Hardware-specific features are properly enabled

#### 1.4 KAS Configuration Refinement
- [ ] Review and optimize KAS configurations
- [ ] Organize kas/bsp/ configurations
- [ ] Create kas/extras/ configurations for optional features
- [ ] Document KAS configuration layering approach

**Acceptance Criteria:**
- KAS configs are clean and well-organized
- BSP configs are minimal and focused
- Extras can be easily combined with base configs

### Phase 1 Exit Criteria
- [ ] All 1.x acceptance criteria met
- [ ] `meta-lamadist` layer passes `yocto-check-layer` validation
- [ ] `kas build` succeeds for at least one BSP (x86_64) producing a bootable image
- [ ] All KAS configurations are documented and composable
- [ ] Layer structure and dependencies fully documented in layer README

---

## Phase 2: Package & Recipe Development

**Status:** Not Started  
**Goal:** Develop custom recipes, package groups, and image definitions.

### Steps

#### 2.1 Custom Recipe Development
- [ ] Create custom recipes for homelab-specific software
- [ ] Develop bbappends for upstream recipe customization
- [ ] Ensure recipes follow Yocto recipe style guidelines
- [ ] Add recipe documentation and comments
- [ ] Configure RPM package signing for all recipes

**Acceptance Criteria:**
- Custom recipes build successfully
- Recipes include license information
- Recipes follow naming conventions
- Recipe functionality is documented
- All packages are signed with GPG signatures

#### 2.2 Package Groups
- [ ] Define core package group (base system)
- [ ] Create homelab package group (common services)
- [ ] Create development package group (debugging tools)
- [ ] Create security package group (hardening tools)

**Acceptance Criteria:**
- Package groups are logical and maintainable
- Dependencies are clearly defined
- Groups can be composed for different use cases

#### 2.3 Image Definitions
- [ ] Create minimal base image recipe
- [ ] Create full-featured homelab image recipe
- [ ] Create development/debug image recipe
- [ ] Define image features and customizations
- [ ] Configure zstd compression (level 11) for image artifacts

**Acceptance Criteria:**
- Images build successfully for all targets
- Images are appropriately sized
- Image manifests and licenses are generated
- Images include proper documentation
- Compressed image artifacts use zstd level 11

#### 2.4 Recipe Testing
- [ ] Set up recipe testing framework
- [ ] Create tests for custom recipes
- [ ] Validate package installations
- [ ] Test image boot and functionality
- [ ] Configure QEMU testing with SPICE/VNC viewer passthrough from build container

**Acceptance Criteria:**
- All custom recipes have basic tests
- Images can be tested in QEMU
- Test results are documented
- QEMU graphical output accessible from host via SPICE or VNC when testing from within the build container

### Phase 2 Exit Criteria
- [ ] All 2.x acceptance criteria met
- [ ] At least one image recipe builds and produces a bootable image for each supported BSP
- [ ] Package groups are defined and functional
- [ ] QEMU boot test passes for x86_64 image
- [ ] All custom recipes have license information and follow Yocto style guidelines

---

## Phase 3: Build Infrastructure & CI/CD

**Status:** Not Started  
**Goal:** Automate builds, implement testing pipelines, and manage artifacts.

### Steps

#### 3.1 Continuous Integration Setup
- [ ] Define GitHub Actions workflows
- [ ] Set up automated builds for all BSPs
- [ ] Configure build matrix (machine x image)
- [ ] Implement build caching strategies

**Acceptance Criteria:**
- Builds run automatically on PR and merge
- Build logs are accessible and clear
- Build times are optimized with caching
- Failed builds provide clear error messages

#### 3.2 Automated Testing
- [ ] Implement image boot tests
- [ ] Set up QEMU-based testing for supported machines
- [ ] Create smoke tests for critical functionality
- [ ] Implement security scanning in CI

**Acceptance Criteria:**
- Images are tested automatically
- Test results are reported in CI
- Security vulnerabilities are detected
- Test coverage meets minimum requirements

#### 3.3 Artifact Management
- [ ] Configure artifact storage (releases, containers)
- [ ] Set up sstate cache (if private)
- [ ] Implement download mirror
- [ ] Create artifact retention policies
- [ ] Generate SPDX 3.0.1 SBOM for all builds
- [ ] Configure zstd compression (level 11) for build artifacts
- [ ] Establish configuration baseline identification (link image version → GitVersion semver + KAS config pins + layer revisions + SPDX SBOM)

**Acceptance Criteria:**
- Build artifacts are stored reliably
- Artifacts are accessible to users
- Storage costs are managed
- Old artifacts are cleaned up automatically
- SPDX 3.0.1 SBOM generated for all images and packages
- Compressed artifacts use zstd level 11

#### 3.4 Build Reproducibility
- [ ] Implement fully reproducible builds
- [ ] Document build environment requirements
- [ ] Pin external dependencies
- [ ] Create build provenance documentation
- [ ] Verify build reproducibility in CI

**Acceptance Criteria:**
- Builds are fully reproducible given same inputs
- Build environment is documented
- Dependency versions are tracked
- Reproducibility is verified in automated testing

#### 3.5 Package Signing Infrastructure
- [ ] Set up GPG signing keys for RPM packages
- [ ] Configure TPM-backed key storage (where available)
- [ ] Implement automated package signing in build pipeline
- [ ] Establish key rotation and management procedures
- [ ] Configure signature verification in package manager

**Acceptance Criteria:**
- All RPM packages are automatically signed during build
- Signing keys are securely managed
- TPM integration configured for hardware-backed signing
- Signature verification is enforced on target systems
- Key management procedures are documented

### Phase 3 Exit Criteria
- [ ] All 3.x acceptance criteria met
- [ ] GitHub Actions CI builds and tests run on every PR to `main`
- [ ] SPDX 3.0.1 SBOM generated for all image builds
- [ ] Build artifacts are published with zstd level 11 compression
- [ ] Package signing infrastructure is operational
- [ ] Build reproducibility verified (two identical builds from same inputs)

---

## Phase 4: Device Integration & Testing

**Status:** Not Started  
**Goal:** Integrate with target hardware, establish deployment workflows, and implement OTA updates.

> **Verification focus**: Phase 4 is primarily concerned with *verification* — confirming the system was built correctly and meets its technical specifications. Verification activities include boot tests, hardware feature checks, update cycle tests, and security posture validation.

### Steps

#### 4.1 Hardware Testing
- [ ] Test images on physical x86_64 hardware
- [ ] Test images on Orin NX hardware
- [ ] Test images on RK1 hardware
- [ ] Test images on SOQuartz hardware
- [ ] Document hardware-specific issues and workarounds
- [ ] Establish QEMU-to-host display passthrough (SPICE/VNC) for graphical mode testing

**Acceptance Criteria:**
- Images boot successfully on target hardware
- All major hardware features are functional
- Issues are documented with workarounds
- Hardware-specific configurations are validated
- Graphical display modes can be tested via SPICE/VNC viewer from QEMU inside the build container

#### 4.2 Bootloader Integration
- [ ] Configure and test systemd-boot for x86_64 (fallback for non-UKI boot)
- [ ] Configure bootloaders for ARM targets
- [ ] Implement secure boot where applicable
- [ ] Configure Measured Boot with TPM PCR measurements
- [ ] Configure Trusted Boot with IMA/EVM integration
- [ ] Implement platform-specific boot integrity features
- [ ] Test boot failure recovery
- [ ] Configure kernel command line for host configuration (hostname, machine-id, network)
- [ ] Package boot artifacts into UKI (Unified Kernel Image) on supported systems
- [ ] Configure UEFI to boot UKI directly (bypass bootloader where supported)

**Acceptance Criteria:**
- Bootloaders are properly configured for systems requiring them
- UKI direct boot is configured on UEFI systems (x86_64)
- Secure boot works on supported hardware with signed binaries
- Measured Boot configured on TPM-enabled systems
- Trusted Boot integrated with IMA/EVM
- Full boot integrity protection enabled on platforms supporting it
- Boot process is documented
- Recovery mechanisms are in place
- Host configuration via kernel command line is functional
- UKI executable generated for UEFI systems (x86_64)

#### 4.3 Storage and Partitioning
- [ ] Implement WIC-based disk image generation with per-platform WKS templates (see [PARTITIONING.md](PARTITIONING.md))
- [ ] Configure EROFS root filesystem for immutable, compressed rootfs
- [ ] Implement split A/B partition layout: separate Rootfs and Verity Hash partitions per slot
- [ ] Configure dm-verity with separate Merkle tree partitions and `roothash` embedded in UKI
- [ ] Implement LUKS2 Full Disk Encryption on Rootfs A/B and Data partitions
- [ ] Configure TPM2-sealed key management for automated LUKS unlocking during boot
- [ ] Configure OverlayFS for mutable directories (`/etc`, application data) with upper layers on encrypted data partition
- [ ] Assign Discoverable Partitions Specification (DPS) type UUIDs to all GPT partitions (architecture-specific root, verity, ESP, `/var`)
- [ ] Enable `systemd-gpt-auto-generator` partition auto-discovery on supported platforms
- [ ] Implement platform-specific partition layouts (x86_64, Orin NX, Rockchip with raw sector bootloaders)
- [ ] Test partition resizing and management
- [ ] Verify rootfs immutability and write protection

**Acceptance Criteria:**
- Disk images are properly partitioned with split A/B layout (Rootfs + Verity Hash per slot)
- Root filesystem uses EROFS with dm-verity integrity verification via separate hash partition
- All Rootfs (A/B) and Data partitions are LUKS2-encrypted
- TPM2-sealed keys enable automated LUKS unlocking during boot (initramfs/systemd)
- All GPT partitions carry correct DPS type UUIDs (architecture-specific root, verity, ESP, `/var`, etc.)
- On platforms supporting DPS auto-discovery, partitions are mounted via `systemd-gpt-auto-generator` without `/etc/fstab` entries
- DPS type UUIDs are set on all platforms regardless of whether auto-discovery is used for mounting
- OverlayFS provides mutable `/etc` and application data directories on top of immutable EROFS root
- Platform-specific layouts implemented for x86_64, Orin NX, and Rockchip (including raw sector bootloader partitions)
- Rootfs is immutable and read-only (EROFS inside LUKS2 container)

#### 4.4 OTA Update System
- [ ] Integrate RAUC for OTA updates with adaptive update support (`casync` chunker)
- [ ] Configure RAUC `crypt` bundles for CMS-encrypted secure delivery
- [ ] Configure update bundles for split slot layout (rootfs + verity hash per slot)
- [ ] Configure RAUC slot definitions to target decrypted mapper devices (preserves LUKS headers)
- [ ] Configure RAUC slot definitions matching the split A/B partition scheme
- [ ] Implement update verification (bundle signature + dm-verity root hash)
- [ ] Test rollback mechanisms
- [ ] Create update documentation for users

**Acceptance Criteria:**
- OTA updates work reliably with adaptive (delta) updates via `casync`
- RAUC delivers updates as CMS-encrypted `crypt` bundles (firmware never exposed in plaintext during transit)
- RAUC writes to decrypted mapper devices (e.g., `/dev/mapper/rootfs_b`), preserving LUKS headers
- RAUC correctly targets split rootfs and verity hash partitions per slot
- Rollback is automatic on failure
- Update process is documented
- Updates preserve user data on the encrypted persistent data partition

#### 4.5 Deployment Workflows
- [ ] Create USB installer images
- [ ] Document network-based installation
- [ ] Create first-boot configuration scripts
- [ ] Document backup and restore procedures

**Acceptance Criteria:**
- Multiple deployment methods available
- Installation is well-documented
- First-boot setup is smooth
- Backup/restore is reliable

### Phase 4 Exit Criteria
- [ ] All 4.x acceptance criteria met
- [ ] Images boot and pass smoke tests on all supported physical hardware
- [ ] OTA update (RAUC) cycle verified end-to-end (install → reboot → health check → commit)
- [ ] Rollback mechanism verified (failed update → automatic rollback to previous slot)
- [ ] Deployment documentation complete for at least USB installer and network install methods

---

## Phase 5: Release Management & Maintenance

**Status:** Not Started  
**Goal:** Establish versioning, release processes, and ongoing maintenance procedures.

### Steps

#### 5.1 Versioning Strategy
- [ ] Define semantic versioning approach
- [ ] Set up GitVersion or equivalent
- [ ] Configure version tagging workflow
- [ ] Document version numbering scheme
- [ ] Define how GitVersion semver is propagated into Yocto `DISTRO_VERSION` and image filenames

**Acceptance Criteria:**
- Version numbers are consistent
- Versions are automatically generated
- Versioning scheme is documented
- Tags are properly created
- Built image filenames and metadata contain the GitVersion-derived version string

#### 5.2 Release Process
- [ ] Define release criteria and checklist
- [ ] Create release branch strategy
- [ ] Automate release artifact generation via tag-triggered CI workflow
- [ ] Generate release notes automatically
- [ ] Create release announcement templates
- [ ] Build all platforms on tag push (x86_64, orin-nx, rk1, soquartz)
- [ ] Upload artifacts as GitHub Release

**Acceptance Criteria:**
- Release process is documented
- Releases are consistent and repeatable
- Release artifacts are complete
- Release notes are comprehensive

#### 5.3 Security Updates
- [ ] Set up CVE monitoring
- [ ] Define security update SLA
- [ ] Create security advisory process
- [ ] Implement expedited security releases

**Acceptance Criteria:**
- CVEs are monitored continuously
- Security updates are timely
- Security process is documented
- Users are notified of security issues

#### 5.4 Long-term Maintenance
- [ ] Define LTS and standard release tracks
- [ ] Create backport policy
- [ ] Establish deprecation process
- [ ] Document end-of-life procedures

**Acceptance Criteria:**
- Maintenance policy is clear
- LTS releases are supported long-term
- Deprecations are well-communicated
- EOL process is defined

#### 5.5 Community and Support
- [ ] Create issue templates
- [ ] Set up discussion forums or mailing list
- [ ] Define support channels
- [ ] Create FAQ and troubleshooting guides

**Acceptance Criteria:**
- Users can easily get help
- Common issues are documented
- Community can contribute
- Support expectations are clear

### Phase 5 Exit Criteria
- [ ] All 5.x acceptance criteria met
- [ ] At least one tagged release published on `main` following JIT Flow
- [ ] GitVersion-based versioning operational and producing correct semver tags
- [ ] Security update process documented and tested with at least one simulated CVE patch
- [ ] Release notes generated automatically from Conventional Commits

---

## Future Phases (TBD)

Additional phases may be defined as the project matures:

- **Phase 6:** Advanced Features (clustering, orchestration, advanced security)
- **Phase 7:** Ecosystem Integration (cloud services, monitoring, logging)
- **Phase 8:** Performance Optimization (profiling, tuning, benchmarking)

---

## Success Metrics

### Phase 0
- Complete, well-structured documentation in place
- Development standards documented and adopted

### Phase 1
- Successful builds for all target machines
- Clean layer structure passing validation

### Phase 2
- Custom images building successfully
- All package groups defined and functional

### Phase 3
- Automated CI/CD pipeline operational
- Build times under target thresholds

### Phase 4
- Images successfully deployed to all target hardware
- OTA updates working reliably

### Phase 5
- Regular releases published
- Security updates delivered promptly
- Community engagement established

---

## Notes

- This plan is a living document and will be updated as the project evolves
- Each phase should be completed before moving to the next, but some overlap is acceptable
- Phases may be adjusted based on priorities, resources, and community feedback
- Security and quality should never be compromised for speed

