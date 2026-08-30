# ADR 0009: icecc Distributed Compiles

## Status

Accepted

## Context

The Post-M4 plan calls for lab machines to contribute compile power
to LamaDist builds, with icecream (icecc) preferred over distcc
(docs/PLAN.md, Post-M4 Checkpoint).  Two Ubuntu lab helpers
(`lamalab-75`, `lamalab-103`, 28 threads combined) now run `iceccd`,
with the scheduler on the bitbake host (172.16.0.1).

Yocto's icecc integration (`icecc.bbclass` plus the
`icecc-create-env` recipe) was dropped from openembedded-core on
2025-06-05 (`ecf8c386cf`, "Drop icecc from OE-Core") for lack of
maintainers, with the recommendation that users vendor it into a
dedicated layer.  No maintained community layer exists.

Licenses involved:

- `icecc.bbclass`: MIT (openembedded-core).
- `icecc-create-env` script and recipe: GPL-2.0-or-later, vendored
  unmodified from openembedded-core.  Built as a `-native` tool
  only; it packs host toolchain environments at build time and
  ships nothing into images.
- `icecc` and `patchelf` apt packages (GPL-2.0-or-later and
  GPL-3.0-or-later) added to the build container: standalone
  executables invoked as external tools, mere aggregation, nothing
  linked into or distributed with LamaDist artifacts.

Per our license policy (ADR 0001) copyleft build/test tooling is
allowed with a brief alternatives-and-obligations note and an ADR
-- the same shape as ADR 0003/0004/0005.

## Decision

Vendor `icecc.bbclass` and `icecc-create-env` into `meta-lamadist`
from the last in-tree openembedded-core revision (`ecf8c386cf^`),
with two local changes marked `LamaDist:` in the class (provenance
header; `ICECC_SDK_HOST_TASK` emptied because
`nativesdk-icecc-toolchain` is not vendored).  Enable per build via
`kas/extras/icecc.kas.yml` behind `mise run build --icecc`, which
also starts an in-container `iceccd --no-remote` pointed at the lab
scheduler (broadcast discovery does not cross the rootless-podman
network namespace).

## Alternatives considered

- **distcc**: still in oe-core, but requires matching cross
  toolchains installed on every helper; icecc ships self-contained
  toolchain chroots to helpers automatically, so helpers need only
  the daemon.  PLAN.md already prefers icecc.
- **A community icecc layer**: searched; none exists
  post-removal.
- **Do nothing (sstate only)**: sstate covers warm builds but does
  nothing for cold rebuilds, which are exactly the case the lab
  helpers target.

## Consequences

- Maintenance of the class falls on us; upstream reported it broken
  since mickledore, though it parses and runs against wrynose (the
  vendored copy was in-tree until one release before wrynose).
- Inheriting the class changes do_configure/do_compile/do_install
  task signatures, so `--icecc` and plain builds do not share task
  hashes.  Both variants stay cached in sstate; toggling costs a
  setscene pass, and the first `--icecc` build is effectively cold.
- All `ICECC_*` tuning variables are in `BB_BASEHASH_IGNORE_VARS`,
  so scheduler and parallelism changes do not invalidate caches.
