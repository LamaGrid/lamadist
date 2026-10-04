# SPDX-License-Identifier: Apache-2.0
"""Publish a CI build's new cache objects to the cluster's mirrors.

Trusted builds (main pushes in the ``yocto-publish`` environment) copy
the sstate archives, downloads, and buildstats they produced to every
mirror that has room, so later builds on any node find them.  The
mirrors serve http read-only on one port (8080) and accept writes over
webdav on another (8081).

``snapshot`` runs before the build and records what exists; ``publish``
runs after it, on success and on failure.  Per mirror, publish:

1. reads ``/.status/df.json`` and skips the mirror unless it is fresh
   and shows the upload size plus 5 GiB free;
2. HEADs every new object and every archive the build used, over 8080;
3. copies only the missing names into ``/.inflight-<run>/`` over
   webdav, then renames them into place with server-side MOVEs:
   sidecars before archives, because an archive's presence is what
   builds check for, and never over an existing name (first writer
   wins);
4. uploads the usage list (archives the build found on any mirror) and
   the downloads manifest (sha256) last, the same way, then purges the
   staging tree.

The step reports ``ok`` (2 or more mirrors), ``degraded`` (1), or
``failed`` (0, exit 1).  Nothing is lost on failure: the objects stay in
the job's own directories and the next build re-produces them.

Environment: SSTATE_DIR, DL_DIR, BUILDSTATS_BASE, GITHUB_RUN_ID,
GITHUB_RUN_ATTEMPT, LAMADIST_PUBLISH_MIRRORS (space-separated hosts),
LAMADIST_PUBLISH_USER, LAMADIST_PUBLISH_PASSWORD, and optionally
LAMADIST_PUBLISH_READ_PORT (8080), LAMADIST_PUBLISH_WRITE_PORT (8081),
LAMADIST_PUBLISH_DEADLINE (seconds, 1800), GITHUB_STEP_SUMMARY.
"""

from __future__ import annotations

import argparse
import concurrent.futures as cf
import datetime as dt
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final

SSTATE_SUFFIXES: Final = (".tar.zst", ".tar.zst.siginfo", ".tar.zst.sig")
SIDECAR_SUFFIXES: Final = (".tar.zst.siginfo", ".tar.zst.sig")
DOWNLOAD_SKIP_SUFFIXES: Final = (".done", ".lock")
# The CVE feeds (~8 GiB of git mirrors) stay out of the mirrors.
CVE_FEEDS: Final = (
    "github.com.CVEProject.cvelistV5",
    "github.com.fkie-cad.nvd-json-data-feeds",
)
FLOOR_BYTES: Final = 5 << 30
STATUS_MAX_AGE: Final = dt.timedelta(minutes=5)
HEAD_WORKERS: Final = 32
HTTP_TIMEOUT_S: Final = 10


class PublishError(Exception):
    """A mirror could not take this job's objects."""


# --- selection ---------------------------------------------------------


def is_sstate_object(rel: str) -> bool:
    """Whether an SSTATE_DIR-relative path is a publishable sstate file."""
    return rel.endswith(SSTATE_SUFFIXES)


def is_download_object(rel: str) -> bool:
    """Whether a DL_DIR-relative path is a publishable download."""
    if rel.startswith("CVE_CHECK/") or any(feed in rel for feed in CVE_FEEDS):
        return False
    if rel.endswith(DOWNLOAD_SKIP_SUFFIXES):
        return False
    return rel.startswith("uninative/") or "/" not in rel


def _walk(base: Path, keep_dir: bool) -> Iterator[str]:
    for dirpath, dirnames, filenames in os.walk(base):
        rel_dir = os.path.relpath(dirpath, base)
        if rel_dir == ".":
            rel_dir = ""
            if not keep_dir:
                dirnames[:] = [d for d in dirnames if d == "uninative"]
        for name in filenames:
            yield f"{rel_dir}/{name}" if rel_dir else name


def list_objects(sstate_dir: Path, dl_dir: Path) -> list[str]:
    """Publishable objects, named by their mirror path, sorted."""
    names = [f"sstate/{r}" for r in _walk(sstate_dir, True) if is_sstate_object(r)]
    names += [f"downloads/{r}" for r in _walk(dl_dir, False) if is_download_object(r)]
    return sorted(names)


def new_objects(start: Iterable[str], end: Iterable[str]) -> list[str]:
    """Objects present at the end but not at the start."""
    return sorted(set(end) - set(start))


def move_batches(names: Iterable[str]) -> list[list[str]]:
    """Group names into MOVE passes: sidecars, then archives, then the rest."""
    names = sorted(names)
    sidecars = [n for n in names if n.endswith(SIDECAR_SUFFIXES)]
    archives = [n for n in names if n.endswith(".tar.zst")]
    rest = [n for n in names if n not in set(sidecars) | set(archives)]
    return [b for b in (sidecars, archives, rest) if b]


# --- per-mirror decisions ----------------------------------------------


def has_room(df_json: str | None, need_bytes: int, now: dt.datetime) -> bool:
    """Whether a mirror's status file is fresh and shows enough free space."""
    if df_json is None:
        return False
    try:
        status = json.loads(df_json)
        free = int(status["free_bytes"])
        stamp = dt.datetime.fromisoformat(str(status["time"]).replace("Z", "+00:00"))
    except (ValueError, KeyError, TypeError):
        return False
    if stamp.tzinfo is None or now - stamp > STATUS_MAX_AGE:
        return False
    return free >= need_bytes + FLOOR_BYTES


def status(reached: int) -> str:
    """The step's verdict from the number of mirrors that took the upload."""
    return "ok" if reached >= 2 else "degraded" if reached == 1 else "failed"


def run_name(now: dt.datetime, run_id: str, attempt: str) -> str:
    """The shared name of this attempt's usage list and manifest."""
    return f"{now.strftime('%Y%m%dT%H%M%SZ')}-{run_id}-{attempt}"


def usage_lines(used: Iterable[str], present: Mapping[str, set[str]]) -> list[str]:
    """Archives the build used that at least one mirror already had."""
    return sorted(
        {
            u
            for u in used
            if u.endswith(".tar.zst") and any(u in p for p in present.values())
        }
    )


def _local_path(name: str, sstate_dir: Path, dl_dir: Path) -> Path:
    cls, _, rel = name.partition("/")
    return (sstate_dir if cls == "sstate" else dl_dir) / rel


def manifest_lines(names: Iterable[str], sstate_dir: Path, dl_dir: Path) -> list[str]:
    """``sha256sum`` lines for the downloads among the published names."""
    lines = []
    for name in sorted(n for n in names if n.startswith("downloads/")):
        digest = hashlib.sha256()
        with _local_path(name, sstate_dir, dl_dir).open("rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                digest.update(chunk)
        lines.append(f"{digest.hexdigest()}  {name}")
    return lines


# --- I/O -----------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Config:
    """Everything the step reads from its environment."""

    sstate_dir: Path
    dl_dir: Path
    buildstats_base: Path
    run_id: str
    attempt: str
    mirrors: tuple[str, ...]
    user: str
    password: str
    read_port: int
    write_port: int
    deadline_s: int
    summary: Path | None

    @classmethod
    def from_env(cls, env: Mapping[str, str]) -> Config:
        summary = env.get("GITHUB_STEP_SUMMARY")
        return cls(
            sstate_dir=Path(env["SSTATE_DIR"]),
            dl_dir=Path(env["DL_DIR"]),
            buildstats_base=Path(env["BUILDSTATS_BASE"]),
            run_id=env.get("GITHUB_RUN_ID", "local"),
            attempt=env.get("GITHUB_RUN_ATTEMPT", "1"),
            mirrors=tuple(env.get("LAMADIST_PUBLISH_MIRRORS", "").split()),
            user=env.get("LAMADIST_PUBLISH_USER", ""),
            password=env.get("LAMADIST_PUBLISH_PASSWORD", ""),
            read_port=int(env.get("LAMADIST_PUBLISH_READ_PORT", "8080")),
            write_port=int(env.get("LAMADIST_PUBLISH_WRITE_PORT", "8081")),
            deadline_s=int(env.get("LAMADIST_PUBLISH_DEADLINE", "1800")),
            summary=Path(summary) if summary else None,
        )


@dataclass(slots=True)
class Mirror:
    """One mirror's view of this job's objects."""

    host: str
    df_json: str | None = None
    present: set[str] = field(default_factory=set)
    error: str = ""


def _url(host: str, port: int, name: str) -> str:
    return f"http://{host}:{port}/{urllib.parse.quote(name, safe='/')}"


def _get(url: str) -> str | None:
    try:
        with urllib.request.urlopen(url, timeout=HTTP_TIMEOUT_S) as resp:
            return resp.read().decode()
    except (urllib.error.URLError, OSError):
        return None


def _exists(url: str) -> bool:
    req = urllib.request.Request(url, method="HEAD")
    try:
        with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT_S) as resp:
            return resp.status == 200
    except (urllib.error.URLError, OSError):
        return False


def _survey(cfg: Config, host: str, names: Sequence[str]) -> Mirror:
    mirror = Mirror(host, df_json=_get(_url(host, cfg.read_port, ".status/df.json")))
    if mirror.df_json is None:
        mirror.error = "no status file (unreachable or not ready)"
        return mirror
    with cf.ThreadPoolExecutor(HEAD_WORKERS) as pool:
        urls = [_url(host, cfg.read_port, n) for n in names]
        mirror.present = {n for n, ok in zip(names, pool.map(_exists, urls)) if ok}
    return mirror


class Rclone:
    """rclone against one mirror's webdav port, as remote ``m:``."""

    def __init__(self, cfg: Config, host: str, deadline: float) -> None:
        self.deadline = deadline
        obscured = subprocess.run(
            ["rclone", "obscure", "-"],
            input=cfg.password,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        self.env = {
            **os.environ,
            "RCLONE_CONFIG_M_TYPE": "webdav",
            "RCLONE_CONFIG_M_URL": f"http://{host}:{cfg.write_port}",
            "RCLONE_CONFIG_M_VENDOR": "rclone",
            "RCLONE_CONFIG_M_USER": cfg.user,
            "RCLONE_CONFIG_M_PASS": obscured,
        }

    def run(self, *args: str) -> None:
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise PublishError("publish deadline reached")
        try:
            subprocess.run(
                ["rclone", "--retries", "3", "--low-level-retries", "10", *args],
                env=self.env,
                check=True,
                timeout=remaining,
            )
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as err:
            raise PublishError(f"rclone {args[0]} failed: {err}") from err


def _write_list(directory: Path, name: str, lines: Iterable[str]) -> Path:
    path = directory / name
    path.write_text("".join(f"{line}\n" for line in lines))
    return path


def _publish_to(
    cfg: Config,
    mirror: Mirror,
    upload: Mapping[str, list[str]],
    extras: Mapping[str, Path],
    work: Path,
    deadline: float,
) -> None:
    """Stage and MOVE one mirror's missing objects, then the extras."""
    inflight = f".inflight-{cfg.run_id}-{cfg.attempt}"
    rc = Rclone(cfg, mirror.host, deadline)
    roots = {
        "sstate": cfg.sstate_dir,
        "downloads": cfg.dl_dir,
        "buildstats": cfg.buildstats_base,
    }
    moved: list[str] = []
    for cls, rels in upload.items():
        if not rels:
            continue
        files = _write_list(work, f"{mirror.host}-{cls}.lst", rels)
        dest = f"m:{inflight}/{cls}"
        if cls == "buildstats":
            dest += f"/{cfg.run_id}-{cfg.attempt}"
        rc.run(
            "copy",
            "--no-traverse",
            "--transfers",
            "16",
            "--files-from-raw",
            str(files),
            str(roots[cls]),
            dest,
        )
        prefix = (
            f"buildstats/{cfg.run_id}-{cfg.attempt}" if cls == "buildstats" else cls
        )
        moved += [f"{prefix}/{r}" for r in rels]
    for rel, local in extras.items():
        rc.run("copyto", str(local), f"m:{inflight}/{rel}")
    for i, batch in enumerate([*move_batches(moved), *[[r] for r in extras]]):
        files = _write_list(work, f"{mirror.host}-move{i}.lst", batch)
        rc.run(
            "move",
            "--no-traverse",
            "--ignore-existing",
            "--files-from-raw",
            str(files),
            f"m:{inflight}",
            "m:",
        )
    rc.run("purge", f"m:{inflight}")


def snapshot(cfg: Config, state: Path) -> None:
    """Record the objects and buildstats runs that exist before the build."""
    runs = (
        sorted(p.name for p in cfg.buildstats_base.iterdir() if p.is_dir())
        if cfg.buildstats_base.is_dir()
        else []
    )
    state.write_text(
        json.dumps(
            {
                "start": time.time(),
                "objects": list_objects(cfg.sstate_dir, cfg.dl_dir),
                "buildstats": runs,
            }
        )
    )


def _buildstats_files(cfg: Config, before: Iterable[str]) -> list[str]:
    if not cfg.buildstats_base.is_dir():
        return []
    new_runs = sorted(
        {p.name for p in cfg.buildstats_base.iterdir() if p.is_dir()} - set(before)
    )
    return [
        f"{run}/{rel}"
        for run in new_runs
        for rel in _walk(cfg.buildstats_base / run, True)
    ]


def _used_archives(cfg: Config, end: Iterable[str], start: float) -> list[str]:
    used = []
    for name in end:
        if name.endswith(".tar.zst"):
            try:
                if (
                    _local_path(name, cfg.sstate_dir, cfg.dl_dir).stat().st_mtime
                    >= start
                ):
                    used.append(name)
            except OSError:
                continue
    return used


def _size(paths: Iterable[Path]) -> int:
    total = 0
    for path in paths:
        try:
            total += path.stat().st_size
        except OSError:
            continue
    return total


def publish(cfg: Config, state: Path) -> str:
    """Publish this job's new objects; return the step's verdict."""
    deadline = time.monotonic() + cfg.deadline_s
    now = dt.datetime.now(dt.timezone.utc)
    before = json.loads(state.read_text())
    end = list_objects(cfg.sstate_dir, cfg.dl_dir)
    new = new_objects(before["objects"], end)
    used = _used_archives(cfg, end, float(before["start"]))
    stats = _buildstats_files(cfg, before["buildstats"])
    probe = sorted(set(new) | set(used))
    mirrors = [_survey(cfg, host, probe) for host in cfg.mirrors]
    name = run_name(now, cfg.run_id, cfg.attempt)
    usage = usage_lines(used, {m.host: m.present for m in mirrors})

    reached = 0
    report = []
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        for mirror in mirrors:
            if mirror.error:
                report.append(f"- {mirror.host}: skipped, {mirror.error}")
                continue
            missing = [n for n in new if n not in mirror.present]
            local = [_local_path(n, cfg.sstate_dir, cfg.dl_dir) for n in missing]
            local += [cfg.buildstats_base / s for s in stats]
            if not has_room(mirror.df_json, _size(local), now):
                report.append(f"- {mirror.host}: skipped, no room or stale status file")
                continue
            upload = {
                "sstate": [
                    n.removeprefix("sstate/")
                    for n in missing
                    if n.startswith("sstate/")
                ],
                "downloads": [
                    n.removeprefix("downloads/")
                    for n in missing
                    if n.startswith("downloads/")
                ],
                "buildstats": stats,
            }
            extras = {
                f".usage/{name}.txt": _write_list(
                    work, f"{mirror.host}-usage.txt", usage
                ),
                f".manifest/{name}.sha256": _write_list(
                    work,
                    f"{mirror.host}-manifest.sha256",
                    manifest_lines(missing, cfg.sstate_dir, cfg.dl_dir),
                ),
            }
            try:
                _publish_to(cfg, mirror, upload, extras, work, deadline)
            except PublishError as err:
                report.append(f"- {mirror.host}: failed, {err}")
                continue
            reached += 1
            report.append(
                f"- {mirror.host}: {len(missing)} objects, {len(stats)} buildstats files"
            )

    verdict = status(reached)
    lines = [
        f"### Mirror publish: {verdict} ({reached} of {len(cfg.mirrors)} mirrors)",
        "",
        *report,
    ]
    print("\n".join(lines))
    if cfg.summary:
        with cfg.summary.open("a") as f:
            f.write("\n".join(lines) + "\n")
    if verdict == "degraded":
        print("::warning::mirror publish reached only one mirror")
    return verdict


def main(argv: Sequence[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("action", choices=("snapshot", "publish"))
    parser.add_argument("--state", type=Path, required=True)
    args = parser.parse_args(argv)
    cfg = Config.from_env(os.environ)
    if args.action == "snapshot":
        snapshot(cfg, args.state)
        return 0
    return 1 if publish(cfg, args.state) == "failed" else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
