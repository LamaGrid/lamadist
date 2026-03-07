# AGENTS.md

Instructions for AI coding agents working on this repository.

## Development Workflow

**Always test locally before pushing to CI.**

The GitHub Actions pipeline runs on self-hosted ARC runners with limited
feedback turnaround. Changes must be validated locally first using the same
container image and build tooling that CI uses.

### Local Build Workflow

1. **Build the container image** (if `container/` files changed):

   ```sh
   mise run container
   ```

   This builds `lamagrid/lamadist-builder:latest` with Podman (or Docker).
   The builder user UID matches your local UID via `$(id -u)`.

2. **Run the Yocto build**:

   ```sh
   mise run build --bsp x86_64
   ```

   This starts KAS inside the builder container. The project directory is
   bind-mounted at `/0` and the sstate cache at `/sstate`. Local builds
   include the `debug.kas.yml` overlay automatically.

   Verify KAS clones all repos, bitbake starts parsing, and no layer
   compatibility or permission errors occur. A full build takes many hours;
   confirming it starts correctly is usually sufficient for CI-related changes.

3. **Only push to CI once the local build succeeds.** Iterate locally until
   the build starts without errors.

### Key mise Tasks

| Task                          | Description                              |
| ----------------------------- | ---------------------------------------- |
| `mise run container`          | Build the builder container image        |
| `mise run build`              | Run the Yocto/KAS build                  |
| `mise run lint`               | Validate KAS configuration               |
| `mise run shell`              | Interactive KAS shell in container       |
| `mise run clean`              | Clean deploy artifacts                   |
| `mise run clean:all`          | Clean entire build directory             |
| `mise run clean:buildstats`   | Remove buildstats snapshots              |
| `mise run buildstats:list`    | List buildstats snapshots                |
| `mise run buildstats:summary` | Show build timing summary                |
| `mise run buildstats:diff`    | Compare two buildstats snapshots         |

All tasks support `--help` for usage details. Build tasks accept `--bsp`
to select target (x86_64, orin-nx, rk1, soquartz), `--ci` for CI mode,
`--qa` for QA/PR builds (zstd compression), `--release` for release builds
(machine-default xz compression + CVE scans), and `--include-scans` to
enable security scans independently.

### Environment Variables

Defined in `.mise.toml`, overridable via environment or `.mise.local.toml`:

| Variable                    | Default                    | Description                              |
| --------------------------- | -------------------------- | ---------------------------------------- |
| `LAMADIST_CONTAINER_IMAGE`  | `lamagrid/lamadist-builder:latest` | Builder container image name     |
| `LAMADIST_HOST_SSTATE_DIR`  | `<project>/.cache/sstate`  | Host path for sstate cache               |
| `LAMADIST_CONTAINER_CMD`    | auto-detected              | `podman` or `docker`                     |
| `KAS_WORK_DIR`              | `/0`                       | Workdir inside container                 |
| `SSTATE_DIR`                | `/sstate`                  | Sstate path inside container             |

In CI, `SSTATE_DIR` and `KAS_WORK_DIR` are overridden by the workflow
environment. The `.mise.toml` uses `exec()` templates to respect external
values.

## CI Pipeline

The CI workflow (`.github/workflows/ci.yml`) runs on ARC scaling sets:

- **`container-build-set`**: Builds the container image with Podman, pushes
  to the in-cluster OCI registry.
- **`yocto-runner-set`**: Runs the Yocto build inside the builder container
  as the workspace image.

The container is only rebuilt when files in `container/` change.

## Repository Structure

```
.mise.toml              # Environment variables (env-only, no inline tasks)
.mise/tasks/            # File-based mise tasks
container/              # Builder container Dockerfile and dependencies
kas/                    # KAS configuration files
  main.kas.yml          # Main KAS config with repo definitions
  bsp/                  # Per-target BSP overlays
  extras/               # Optional overlays (debug, demo, etc.)
meta-lamadist/          # Yocto distribution layer
docs/                   # Documentation
```

## Shell Script Style Guide

- Wrap comments at the first word extended beyond 72 characters, and do
  not exceed 80 characters.  Wrap before 72 characters if the last word
  would extend beyond 80 characters.  Exceptions: URLs, long paths, and
  code examples.
- Prefer POSIX syntax over Bash- or Zsh-specific syntax, except in the following
  cases:
    - Where shell-specific features are faster to execute, e.g.,
       `[[ "abc123" =~ c1 ]` instead of `echo abc123 | grep -q c1`.
    - Where shell-specific features are significantly more readable, e.g.,
       `<<-` heredocs with indented content and `source` insead of `.`.
- Use shell-specific features that add safety, e.g., `set -o pipefail`, `local`,
 `readonly`, `typeset`, etc.
- Quote strings with 'hard quotes' unless variable expansion is needed.
- Enclose all variables in curly braces when they are part of a larger string,
  e.g., `"this ${string}"`, but not when they are a standalone, e.g.,
  `"$solitary_variable"`.
- Use `UPPER_SNAKE_CASE` for variables intended to be used across multiple
  functions, e.g., configuration variables.
- Use `_underscore_lead_lower_snake_case` for file-local variables and
  functions, regardless of whether they are declared with `local` or not.
- Use `lower_snake_case` for functions intended to be used across multiple
  files, e.g., utility functions.
- Unset unneeded functions and variables not needed after use, e.g., temporary
  variables and helper functions.
- Batch `export` and `unset` calls as a micro-optimization-- speed matters!
- Use XDG Base Directory Specification wherever possible.
- Use tabs for indentation.  Spaces may be used after tabs for `<<-` heredoc
  content, e.g. to indent the output file with its native intendation, but
  the initial indentation must be tabs.

## Common Issues

- **`SHELL is not supported for OCI image format`**: The Dockerfile uses
  `SHELL` instruction. Local builds use `--format docker` to handle this.
  CI builds also pass `--format docker`.

- **SSTATE_DIR permission denied**: When the sstate host directory is owned
  by a different user/group, Podman's `--userns=keep-id` alone is
  insufficient. The tasks include `--group-add keep-groups` to pass through
  supplementary group membership.

- **Layer compatibility errors**: All KAS repos must target the same Yocto
  release series (currently `scarthgap`). Check `kas/main.kas.yml` branch
  settings if a layer reports incompatibility.
