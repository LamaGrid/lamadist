<!-- SPDX-License-Identifier: Apache-2.0 -->
# LamaDist Tooling Guide

This document describes the tools required for LamaDist development, how to set up your environment, and how to use the build system.

## Table of Contents

- [Overview](#overview)
- [Required Tools](#required-tools)
- [Developer Environment Setup](#developer-environment-setup)
- [mise Task Reference](#mise-task-reference)
- [GitHub Actions CI](#github-actions-ci)
- [Container Python Dependencies](#container-python-dependencies)
- [KAS Configuration](#kas-configuration)
- [Troubleshooting](#troubleshooting)

---

## Overview

LamaDist uses a containerized build approach to ensure reproducible builds across different development environments. The core tools are:

- **mise**: Single CLI entrypoint — polyglot tool/runtime manager and task runner ([mise.jdx.dev](https://mise.jdx.dev/))
- **podman** (preferred) or Docker: Provides the isolated, reproducible KAS build container
- **KAS**: Declarative Yocto/OE project setup and build tool (runs inside the container)
- **uv** + `pyproject.toml`: Python dependency management inside the container
- **GitVersion**: Automatic semantic versioning

Host developers only need **`mise`**, **`podman`** (or Docker), and **`git`**. No Python, venv, or Make is required on the host — mise manages any needed tools.

---

## Required Tools

### Host System Requirements

**Operating System**: Linux (Ubuntu 22.04 LTS recommended) or WSL2

**Minimum Hardware**:
- CPU: 4+ cores (8+ recommended)
- RAM: 8 GB minimum (16+ GB recommended)
- Disk: 100+ GB free space (SSD strongly recommended)
- Internet: For downloading sources and dependencies

### Core Tools

#### 1. mise

**Purpose**: Polyglot tool manager and task runner — single CLI entrypoint for all development tasks

**Installation**: See the [mise Getting Started guide](https://mise.jdx.dev/getting-started.html) for the latest instructions.

```bash
# Install mise (one-liner)
curl https://mise.run | sh

# Add mise to your shell (follow the output instructions, e.g. for bash):
echo 'eval "$(~/.local/bin/mise activate bash)"' >> ~/.bashrc
source ~/.bashrc

# Verify installation
mise --version
```

#### 2. podman (preferred) or Docker

**Purpose**: Run the KAS build container for reproducible Yocto builds

**podman Installation (Ubuntu/Debian)**:
```bash
sudo apt-get update
sudo apt-get install -y podman

# Verify installation
podman --version
```

**Docker Alternative**: Docker 20.10+ with BuildKit is also supported. See [Docker documentation](https://docs.docker.com/) for installation.

#### 3. Git

**Required Version**: 2.25+

**Installation**:
```bash
sudo apt-get install -y git

# Configure Git (replace with your information)
git config --global user.name "Your Name"
git config --global user.email "your.email@example.com"
```

### Optional Tools

#### GitVersion

**Purpose**: Automatic semantic versioning from Git history

```bash
# GitVersion runs in a container, no local installation needed
mise run info
```

#### Development Tools

For enhanced development experience:

```bash
# Code editors
sudo snap install code --classic  # VS Code

# Useful utilities
sudo apt-get install -y \
  vim \
  tmux \
  htop \
  tree \
  jq
```

---

## Developer Environment Setup

### Quick Start

```bash
# Clone the repository
git clone https://github.com/LamaGrid/lamadist.git
cd lamadist

# Trust the mise config (required for MISE_PARANOID=1 users)
mise trust

# Install tools (mise manages everything)
mise install

# Build image (2-6 hours on first build)
mise run build --bsp x86_64

# Images will be in: build/tmp/deploy/images/genericx86-64/
```

### Detailed Setup

#### Environment Variables

LamaDist uses environment variables for build configuration:

**.kas.env**: Environment variables passed to KAS container
- See `.kas.env` file for available variables
- Contains container/CI environment passthrough

**.kas.env.local**: Local overrides (not committed to git)
```bash
# Create local environment overrides
cat > .kas.env.local << 'EOF'
# Example: Set download directory
DL_DIR=/path/to/shared/downloads

# Example: Set shared state mirror
SSTATE_MIRRORS=file://.* http://my-sstate-server/PATH;downloadfilename=PATH

# Example: Limit CPU usage
BB_NUMBER_THREADS=4
PARALLEL_MAKE=-j 4
EOF
```

#### Build Cache Configuration

**Shared State Cache**: Cache of built packages
```bash
# Default location: .cache/sstate/
# Override with environment variable
export LAMADIST_HOST_SSTATE_DIR=/path/to/sstate
```

**Download Directory**: Source tarballs
```bash
# Set in .kas.env.local
DL_DIR=/path/to/downloads
```

### Build Output Locations

After a successful build:

```
build/
├── downloads/              # Source tarballs
├── tmp/
│   ├── deploy/
│   │   ├── images/        # Final images (WIC, qcow2, etc.)
│   │   ├── rpm/           # RPM packages
│   │   └── licenses/      # License manifests
│   └── work/              # Build work directories
├── buildhistory/          # Build history tracking
└── buildstats/            # Build statistics
```

**Image files**:
- `build/tmp/deploy/images/<machine>/`
  - `*.wic.zst`: Compressed disk image
  - `*.ext4`: Root filesystem
  - `*.qcow2`: QEMU virtual machine image
  - `*.manifest`: Package list
  - `*.rootfs.json`: SPDX SBOM

---

## mise Task Reference

mise is the single CLI entrypoint for all LamaDist development tasks. Tasks are
defined as file tasks in `.mise/tasks/` and use [`usage`](https://usage.jdx.dev/)
specs for shell autocompletion of flags and arguments.

### Build Tasks

| Task | Description |
|------|-------------|
| `mise run build --bsp <bsp>` | Build images for specified BSP (default: x86_64) |
| `mise run build --bsp <bsp> --ci` | Build in CI mode (force checkout, no debug) |
| `mise run container:builder:build` | Build the KAS build container image |
| `mise run container:builder:build --ci` | Build container with podman (rootless, for CI) |

**Available BSPs**: `x86_64`, `orin-nx`, `rk1`, `soquartz`

**Examples**:
```bash
mise run build --bsp x86_64    # Build x86_64
mise run build --bsp rk1       # Build for RK1
mise run build --bsp x86_64 --ci  # CI-style build
mise run container:builder:build             # Rebuild container
```

### Validation & Testing Tasks

| Task | Description |
|------|-------------|
| `mise run check --bsp <bsp>` | Run static analysis and validate KAS configuration |
| `mise run test --bsp <bsp>` | Validate build artifacts exist and are well-formed |
| `mise run vm --bsp <bsp>` | Boot test build artifacts with QEMU |

All validation and testing tasks accept the `--ci` flag for non-interactive
operation in CI environments.

**Examples**:
```bash
mise run check --bsp x86_64     # Run linters and validate KAS config
mise run test --bsp x86_64     # Check build artifacts
mise run vm --bsp x86_64     # QEMU boot test
```

### Development Tasks

| Task | Description |
|------|-------------|
| `mise run kas --bsp <bsp>` | Interactive KAS shell for specified BSP |
| `mise run container:builder:shell` | Shell in container (without KAS) |
| `mise run inspect --bsp <bsp>` | Dump KAS configuration for specified BSP |

**Examples**:
```bash
# Start interactive KAS shell
mise run kas --bsp x86_64

# Dump configuration to review
mise run inspect --bsp x86_64
```

**In KAS shell**:
```bash
# You're in a BitBake environment
bitbake core-image-minimal          # Build an image
bitbake -c cleansstate <recipe>     # Clean a recipe
bitbake -e <recipe>                 # Show recipe environment
bitbake-layers show-layers          # List layers
bitbake-layers show-recipes         # List recipes
```

### Cleanup Tasks

| Task | Description |
|------|-------------|
| `mise run clean` | Remove build output artifacts |
| `mise run clean:all` | Remove entire build directory (with confirmation) |
| `mise run clean:builder` | Remove container image |

**Examples**:
```bash
# Clean outputs only (keep sstate)
mise run clean

# Full clean (will prompt for confirmation)
mise run clean:all
```

### Utility Tasks

| Task | Description |
|------|-------------|
| `mise run info` | Show build version (via GitVersion) |
| `mise tasks` | List all available tasks (built into mise) |

**Examples**:
```bash
# Get version
mise run info

# List all tasks
mise tasks
```

---

## GitHub Actions CI

CI uses a multi-stage GitHub Actions workflow on ARC (Actions Runner Controller)
scaling sets. The workflow is defined in `.github/workflows/ci.yml`.

### Runner Sets

| Runner | Purpose |
|--------|---------|
| `container-build-set` | Build the KAS build container image |
| `yocto-runner-set` | Run Yocto/KAS builds (persistent workspace + sstate) |

### Workflow Stages

1. **Build Container** (`container-build-set`): Conditionally builds the KAS
   build container with `mise run container:builder:build --ci` (uses podman) when files in
   `container/` have changed. Pushes the image to the in-cluster OCI registry
   for downstream jobs to pull as their workspace container.
2. **Build x86_64** (`yocto-runner-set`): Uses the builder image from the
   registry as its workspace container and runs
   `mise run build --bsp x86_64 --ci`. Runs automatically on push to `main`
   and on pull requests.
3. **Build other targets** (`yocto-runner-set`): Same pattern for `rk1`,
   `soquartz`, and `orin-nx`, but only triggered via `workflow_dispatch`.

### Workspace Management

- **Sstate cache** (`/__w/_sstate`): Always preserved across builds.
- **Build directory**: Cleaned on merges to `main`; reused on PR builds.

---

## Container Python Dependencies

Inside the build container, Python dependencies are managed with **`uv`** and **`container/pyproject.toml`**:

```mermaid
flowchart LR
    pyproject["container/pyproject.toml"] -- "mise run container:builder:lock" --> reqs["container/requirements.txt"]
    reqs --> container["Container"]
```

- **`container/pyproject.toml`**: High-level Python dependency specifications (PEP 621)
- **`container/requirements.txt`**: Locked, compiled dependencies generated by `mise run container:builder:lock` and committed to the repo.
- The **host does NOT need Python** — all Python tooling runs inside the container

---

## Dependency Management

LamaDist uses a "Manifest + Lockfile" strategy to ensure reproducible builds for all dependencies.

| Ecosystem | Manifest | Lockfile | Update Task |
| :--- | :--- | :--- | :--- |
| **APT** (Container) | `container/packages.txt` | `container/packages.lock` | `mise run container:builder:lock` |
| **Python** (Container) | `container/pyproject.toml` | `container/requirements.txt` | `mise run container:builder:lock` |
| **Mise** (Tools) | `.mise.toml` | `mise.lock` | `mise lock` |

### Updating Dependencies

To update all dependencies to their latest allowed versions:

```bash
# Update lockfiles
mise run container:builder:lock
mise lock

# Rebuild container with new dependencies
mise run container:builder:build
```

### Build Enforcement

The build system (`mise run build`) automatically checks dependency freshness:

- **Warning**: If updates are available, a warning is printed.
- **Error**: If lockfiles are stale (>7 days old), the build fails.

---

## KAS Configuration

### KAS Overview

KAS (Setup tool for bitbake based projects) provides declarative configuration for Yocto builds.

**Benefits**:
- Reproducible builds
- Version-controlled configuration
- Easy composition of features
- No manual setup of `bblayers.conf` or `local.conf`

### Configuration Structure

```
kas/
├── main.kas.yml              # Base configuration
├── bsp/                      # BSP-specific configs
│   ├── x86_64.kas.yml
│   ├── orin-nx.kas.yml
│   ├── rk1.kas.yml
│   └── soquartz.kas.yml
├── extras/                   # Optional features
│   └── debug.kas.yml
└── installer.kas.yml         # Installer image config
```

### KAS Configuration Composition

KAS configs can be layered using `:` separator:

```bash
# Base + BSP
kas build main.kas.yml:bsp/x86_64.kas.yml

# Base + BSP + Debug
kas build main.kas.yml:bsp/x86_64.kas.yml:extras/debug.kas.yml

# Via mise (automatically includes debug)
mise run build --bsp x86_64
```

### Key KAS Configuration Elements

#### main.kas.yml

- Defines repositories (layers)
- Sets distribution (`lamadist`)
- Configures shared `local_conf_header` settings
- Specifies default branch (`scarthgap`)

#### BSP configs (bsp/*.kas.yml)

- Set `machine` variable
- Add BSP-specific repositories
- Define build targets
- Add machine-specific `local_conf_header` settings

#### Extras (extras/*.kas.yml)

- Optional feature overlays
- Debug settings
- Development tools
- Testing configurations

### Customizing KAS Configuration

To add local customizations without modifying tracked files:

1. **Create local KAS config**:
   ```yaml
   # kas/local.kas.yml (add to .gitignore)
   header:
     version: 15

   local_conf_header:
     my_custom_config: |
       # Custom BitBake configuration
       BB_NUMBER_THREADS = "8"
       PARALLEL_MAKE = "-j 8"
   ```

2. **Use in builds**:
   ```bash
   # (The exact syntax will depend on mise task implementation)
   mise run kas --bsp x86_64
   kas build main.kas.yml:bsp/x86_64.kas.yml:kas/local.kas.yml
   ```

---

## Troubleshooting

### Common Issues and Solutions

#### Issue: podman permission denied

**Symptom**:
```
ERRO[0000] cannot find UID/GID for user ...
```

**Solution**:
```bash
# Ensure your user has a subuid/subgid mapping
grep $USER /etc/subuid || sudo usermod --add-subuids 100000-165535 $USER
grep $USER /etc/subgid || sudo usermod --add-subgids 100000-165535 $USER

# Reset podman storage if needed
podman system reset

# Verify
podman run --rm hello-world
```

#### Issue: KAS permission denied reading config files

**Symptom**:
```
PermissionError: [Errno 13] Permission denied: '/0/kas/main.kas.yml'
```

This occurs when rootless podman maps the host user's UID to a different UID
inside the container.  The build container runs as `builder` (UID 1000), and
without `--userns=keep-id` the mounted project files appear owned by a
different UID, making them unreadable.

LamaDist tasks pass `--userns=keep-id` to podman automatically, matching the
upstream `kas-container` behavior.  If you see this error, ensure you are
running the latest version of the tasks.

**Workaround** (if using a custom container command):
```bash
# For podman, always pass --userns=keep-id when mounting host volumes
podman run --userns=keep-id -v /my/project:/work ...
```

#### Issue: Docker permission denied (if using Docker)

**Symptom**:
```
docker: Got permission denied while trying to connect to the Docker daemon socket
```

**Solution**:
```bash
# Add user to docker group
sudo usermod -aG docker $USER

# Logout and login again, or:
newgrp docker

# Verify
docker ps
```

#### Issue: OCI permission denied with VirtualBox installed

**Symptom**:
```
Error: crun: creating `/dev/vboxusb/001/003`: openat2 `dev/vboxusb`: Permission denied: OCI permission denied
```

This occurs when a container bind-mounts the host `/dev` and VirtualBox USB
device nodes have restrictive permissions. LamaDist tasks do **not** mount
`/dev` (matching upstream kas-container behavior), so this should not happen.
If you see this error, ensure you are running the latest version of the
tasks.

**Workaround** (if using custom `--runtime-args`):
```bash
# Avoid mounting the entire /dev — use specific device mounts instead
# Bad:  -v /dev:/dev
# Good: --device /dev/loop-control (only when loop devices are needed)
```

#### Issue: mise install failures

**Symptom**:
```
mise ERROR tool not found or failed to install
```

**Solution**:
```bash
# Run mise doctor for diagnostics
mise doctor

# Clear mise cache and retry
mise cache clear
mise install

# Check mise version is up to date
mise self-update
```

#### Issue: BitBake server timeout

**Symptom**:
```
Timeout while waiting for a reply from the bitbake server (60s ...)
```

This occurs when BitBake's server process hangs during initialization. Common
causes inside a container:

- **Hash equivalence upstream unreachable** — if `BB_HASHSERVE_UPSTREAM` is
  set and the hostname cannot be resolved or the port is firewalled, DNS/TCP
  hangs block server startup for the full timeout period.
- **Insufficient memory** — BitBake needs several GB of RAM to parse recipes.
  Check `dmesg` or `journalctl` for OOM killer activity.
- **SSTATE_DIR mismatch** — if `local.conf` sets `SSTATE_DIR` to a path
  that is not writable, server initialization can fail silently.

**Solution**: Ensure the KAS configuration does **not** hardcode `SSTATE_DIR`
(the env var from the container mount should be used) and does not reference
unreachable external hash equivalence servers.

#### Issue: Out of disk space

**Symptom**:
```
ERROR: No space left on device
```

**Solution**:
```bash
# Check disk usage
df -h

# Clean old build artifacts
mise run clean

# Clean sstate cache (will cause full rebuild)
rm -rf .cache/sstate/

# Prune container images
podman system prune -a   # or: docker system prune -a
```

#### Issue: Build fails with hash mismatch

**Symptom**:
```
ERROR: Checksum mismatch!
```

**Solution**:
```bash
# Clear downloads and sstate
rm -rf build/downloads/<failing-package>*
rm -rf .cache/sstate/*<failing-package>*

# Retry build
mise run build --bsp x86_64
```

#### Issue: Container build fails

**Symptom**:
```
ERROR: failed to solve: failed to fetch...
```

**Solution**:
```bash
# Clear container build cache
podman system prune -a   # or: docker builder prune -a

# Rebuild container
mise run container:builder:build
```

#### Issue: KAS cannot find layer

**Symptom**:
```
ERROR: Layer 'meta-xxx' is not in the collection
```

**Solution**:
```bash
# Force checkout and rebuild all layers
mise run build --bsp x86_64

# Or manually in kas shell
mise run kas --bsp x86_64
bitbake-layers show-layers  # Verify all layers present
```

### Performance Optimization

#### Speed Up Builds

1. **Use SSD**: Store build directory on SSD
2. **Increase parallelism**:
   ```bash
   # In .kas.env.local
   BB_NUMBER_THREADS=<cpu_cores>
   PARALLEL_MAKE=-j <cpu_cores * 1.5>
   ```
3. **Use shared sstate cache**: Point to network sstate mirror
4. **Use shared download directory**: Reuse downloads across workspaces
5. **Enable Icecream** (distributed compilation):
   ```bash
   # In .kas.env.local
   ICECC_DISABLED=0
   ```

#### Reduce Disk Usage

1. **Clean old builds regularly**: `mise run clean`
2. **Limit sstate cache size**: Use `sstate-cache-management` script
3. **Share downloads**: Use `DL_DIR` on separate partition

### Getting More Information

#### Check BitBake logs

```bash
# Main BitBake log
less build/tmp/log/cooker/<machine>/<timestamp>.log

# Task logs
less build/tmp/work/<arch>/<recipe>/<version>/temp/log.do_<task>.<pid>
```

#### Debug in KAS shell

```bash
# Enter KAS shell
mise run kas --bsp x86_64

# Run BitBake with debugging
bitbake -D core-image-minimal

# Show dependencies
bitbake -g core-image-minimal
```

---

## Additional Resources

### Documentation
- [Yocto Project Documentation](https://docs.yoctoproject.org/)
- [KAS Documentation](https://kas.readthedocs.io/)
- [BitBake User Manual](https://docs.yoctoproject.org/bitbake/)
- [mise Documentation](https://mise.jdx.dev/)

### Community
- [Yocto Project Mailing Lists](https://lists.yoctoproject.org/)
- [Yocto Project Discord](https://discord.gg/yocto)

### Tools
- [mise](https://mise.jdx.dev/)
- [podman Documentation](https://docs.podman.io/)
- [uv Documentation](https://docs.astral.sh/uv/)
- [GitVersion Documentation](https://gitversion.net/)
