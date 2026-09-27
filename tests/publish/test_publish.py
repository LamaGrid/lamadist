# SPDX-License-Identifier: Apache-2.0
"""Tests for the CI mirror publish step (.mise/lib/publish.py).

Unit tests cover the selection rules and the per-mirror decisions.  The
integration test runs the whole step against two real rclone mirrors
(http read port plus webdav write port each) on loopback addresses.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import shutil
import socket
import subprocess
import sys
import time
from collections.abc import Iterator
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / ".mise" / "lib"))

import publish

NOW = dt.datetime(2026, 9, 27, 7, 0, 0, tzinfo=dt.UTC)
GIB = 1 << 30


def _touch(path: Path, data: bytes = b"x") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


# --- selection ---------------------------------------------------------


@pytest.mark.parametrize(
    ("rel", "wanted"),
    [
        ("ab/cd/sstate:zlib:x:1:r0:x:14:aa_populate_sysroot.tar.zst", True),
        ("ab/cd/sstate:zlib:x:1:r0:x:14:aa_populate_sysroot.tar.zst.siginfo", True),
        ("ab/cd/sstate:zlib:x:1:r0:x:14:aa_populate_sysroot.tar.zst.sig", True),
        ("universal/ab/sstate:x:::::aa_deploy.tar.zst", True),
        ("ab/cd/sstate:zlib:x:1:r0:x:14:aa_populate_sysroot.tar.zst.1234", False),
        ("ab/cd/sstate:zlib.tar.zst.lock", False),
    ],
)
def test_sstate_selection_uses_exact_suffixes(rel: str, wanted: bool) -> None:
    assert publish.is_sstate_object(rel) is wanted


@pytest.mark.parametrize(
    ("rel", "wanted"),
    [
        ("zlib-1.3.2.tar.xz", True),
        ("git2_github.com.madler.zlib.git.tar.gz", True),
        ("gitshallow_github.com.madler.zlib.git_1-2_main.tar.gz", True),
        ("uninative/abc/x86_64-nativesdk-libc.tar.xz", True),
        ("zlib-1.3.2.tar.xz.done", False),
        ("zlib-1.3.2.tar.xz.lock", False),
        ("git2/github.com.madler.zlib.git/HEAD", False),
        ("git2_github.com.CVEProject.cvelistV5.git.tar.gz", False),
        ("gitshallow_github.com.fkie-cad.nvd-json-data-feeds.git_x.tar.gz", False),
        ("CVE_CHECK/nvdcve_2-2.db", False),
        ("somedir/file.tar.gz", False),
    ],
)
def test_download_selection_skips_clones_markers_and_cve_feeds(
    rel: str, wanted: bool
) -> None:
    assert publish.is_download_object(rel) is wanted


def test_listing_names_objects_by_their_mirror_path(tmp_path: Path) -> None:
    sstate, dl = tmp_path / "sstate", tmp_path / "dl"
    _touch(sstate / "ab/cd/sstate:a.tar.zst")
    _touch(sstate / "ab/cd/sstate:a.tar.zst.siginfo")
    _touch(sstate / "ab/cd/sstate:a.tar.zst.tmp")
    _touch(dl / "a-1.tar.gz")
    _touch(dl / "a-1.tar.gz.done")
    _touch(dl / "git2/x.git/HEAD")
    assert publish.list_objects(sstate, dl) == [
        "downloads/a-1.tar.gz",
        "sstate/ab/cd/sstate:a.tar.zst",
        "sstate/ab/cd/sstate:a.tar.zst.siginfo",
    ]


def test_only_objects_absent_at_job_start_are_new() -> None:
    start = ["sstate/a.tar.zst", "downloads/x.tar.gz"]
    end = [
        "sstate/a.tar.zst",
        "sstate/b.tar.zst",
        "downloads/x.tar.gz",
        "downloads/y.tar.gz",
    ]
    assert publish.new_objects(start, end) == ["downloads/y.tar.gz", "sstate/b.tar.zst"]


def test_moves_put_sidecars_before_their_archives() -> None:
    names = [
        "sstate/a.tar.zst",
        "sstate/a.tar.zst.siginfo",
        "downloads/x.tar.gz",
        "sstate/a.tar.zst.sig",
    ]
    batches = publish.move_batches(names)
    flat = [n for batch in batches for n in batch]
    assert flat.index("sstate/a.tar.zst.siginfo") < flat.index("sstate/a.tar.zst")
    assert flat.index("sstate/a.tar.zst.sig") < flat.index("sstate/a.tar.zst")
    assert sorted(flat) == sorted(names)


# --- per-mirror decisions ----------------------------------------------


def _df(free: int, age_s: int, now: dt.datetime = NOW) -> str:
    stamp = (now - dt.timedelta(seconds=age_s)).strftime("%Y-%m-%dT%H:%M:%SZ")
    return json.dumps({"free_bytes": free, "time": stamp})


def _df_live(free: int) -> bytes:
    """A status file as a live mirror writes it: stamped with the real clock."""
    return _df(free, 0, dt.datetime.now(dt.UTC)).encode()


def test_room_needs_the_upload_plus_five_gib() -> None:
    assert publish.has_room(_df(6 * GIB, 30), GIB, NOW)
    assert not publish.has_room(_df(6 * GIB - 1, 30), GIB, NOW)


@pytest.mark.parametrize(
    "text",
    [
        None,
        "not json",
        json.dumps({"time": "2026-09-27T07:00:00Z"}),
        json.dumps({"free_bytes": 100 * GIB}),
        json.dumps({"free_bytes": 100 * GIB, "time": "yesterday"}),
    ],
)
def test_a_missing_or_malformed_status_file_means_no_room(text: str | None) -> None:
    assert not publish.has_room(text, 0, NOW)


def test_a_status_file_older_than_five_minutes_means_no_room() -> None:
    assert publish.has_room(_df(100 * GIB, 299), 0, NOW)
    assert not publish.has_room(_df(100 * GIB, 301), 0, NOW)


@pytest.mark.parametrize(
    ("reached", "status"), [(3, "ok"), (2, "ok"), (1, "degraded"), (0, "failed")]
)
def test_status_counts_the_mirrors_reached(reached: int, status: str) -> None:
    assert publish.status(reached) == status


def test_run_names_carry_the_start_time_run_and_attempt() -> None:
    assert publish.run_name(NOW, "123", "2") == "20260927T070000Z-123-2"


def test_usage_lists_used_archives_found_on_any_mirror() -> None:
    used = [
        "sstate/b.tar.zst",
        "sstate/a.tar.zst",
        "sstate/a.tar.zst.siginfo",
        "sstate/c.tar.zst",
    ]
    present = {"m0": {"sstate/a.tar.zst"}, "m1": {"sstate/b.tar.zst"}}
    assert publish.usage_lines(used, present) == [
        "sstate/a.tar.zst",
        "sstate/b.tar.zst",
    ]


def test_manifest_lines_are_sha256sum_format(tmp_path: Path) -> None:
    dl = tmp_path / "dl"
    _touch(dl / "a.tar.gz", b"abc")
    lines = publish.manifest_lines(["downloads/a.tar.gz"], tmp_path / "sstate", dl)
    assert lines == [
        "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad  downloads/a.tar.gz"
    ]


# --- integration: two real rclone mirrors ---------------------------------


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _wait_port(host: str, port: int) -> None:
    for _ in range(100):
        with socket.socket() as s:
            if s.connect_ex((host, port)) == 0:
                return
        time.sleep(0.05)
    raise RuntimeError(f"{host}:{port} did not open")


@pytest.fixture
def mirrors(tmp_path: Path) -> Iterator[tuple[list[Path], int, int]]:
    rclone = shutil.which("rclone")
    if rclone is None:
        pytest.skip("rclone not on PATH (mise install rclone)")
    read_port, write_port = _free_port(), _free_port()
    roots, procs = [], []
    for i, host in enumerate(("127.0.0.1", "127.0.0.2")):
        root = tmp_path / f"mirror{i}"
        _touch(root / ".status" / "df.json", _df_live(100 * GIB))
        roots.append(root)
        common = ["--dir-cache-time", "0s", "--vfs-cache-mode", "off"]
        procs.append(
            subprocess.Popen(
                [
                    rclone,
                    "serve",
                    "http",
                    str(root),
                    "--read-only",
                    "--addr",
                    f"{host}:{read_port}",
                ]
                + common
            )
        )
        procs.append(
            subprocess.Popen(
                [rclone, "serve", "webdav", str(root), "--addr", f"{host}:{write_port}"]
                + ["--user", "publish", "--pass", "secret"]
                + common
            )
        )
        _wait_port(host, read_port)
        _wait_port(host, write_port)
    try:
        yield roots, read_port, write_port
    finally:
        for p in procs:
            p.terminate()
        for p in procs:
            p.wait(timeout=10)


def test_publish_end_to_end(
    tmp_path: Path,
    mirrors: tuple[list[Path], int, int],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    roots, read_port, write_port = mirrors
    sstate, dl, bs = tmp_path / "sstate", tmp_path / "dl", tmp_path / "buildstats"
    old = _touch(sstate / "ab/sstate:old.tar.zst")
    _touch(dl / "old.tar.gz")
    _touch(bs / "20260926000000" / "zlib" / "do_compile")
    # The old archive is already on mirror 0, so the job's use of it is listed.
    _touch(roots[0] / "sstate/ab/sstate:old.tar.zst")
    for root in roots:
        _touch(root / "downloads/old.tar.gz")
    state = tmp_path / "state.json"
    env = {
        "SSTATE_DIR": str(sstate),
        "DL_DIR": str(dl),
        "BUILDSTATS_BASE": str(bs),
        "GITHUB_RUN_ID": "77",
        "GITHUB_RUN_ATTEMPT": "1",
        "LAMADIST_PUBLISH_MIRRORS": "127.0.0.1 127.0.0.2",
        "LAMADIST_PUBLISH_READ_PORT": str(read_port),
        "LAMADIST_PUBLISH_WRITE_PORT": str(write_port),
        "LAMADIST_PUBLISH_USER": "publish",
        "LAMADIST_PUBLISH_PASSWORD": "secret",
    }
    for k, v in env.items():
        monkeypatch.setenv(k, v)

    assert publish.main(["snapshot", "--state", str(state)]) == 0
    # The build: produce a new archive with sidecars, a new download, a new
    # buildstats run, and use (touch) the old archive.
    _touch(sstate / "ab/sstate:new.tar.zst", b"new")
    _touch(sstate / "ab/sstate:new.tar.zst.siginfo", b"sig")
    _touch(dl / "new-1.0.tar.gz", b"abc")
    _touch(dl / "git2_github.com.CVEProject.cvelistV5.git.tar.gz", b"cve")
    _touch(bs / "20260927070000" / "zlib" / "do_compile", b"stats")
    os.utime(old)

    assert publish.main(["publish", "--state", str(state)]) == 0

    for root in roots:
        assert (root / "sstate/ab/sstate:new.tar.zst").read_bytes() == b"new"
        assert (root / "sstate/ab/sstate:new.tar.zst.siginfo").read_bytes() == b"sig"
        assert (root / "downloads/new-1.0.tar.gz").read_bytes() == b"abc"
        assert not (
            root / "downloads/git2_github.com.CVEProject.cvelistV5.git.tar.gz"
        ).exists()
        runs = list((root / "buildstats").iterdir())
        assert [r.name for r in runs] == ["77-1"]
        assert (runs[0] / "20260927070000/zlib/do_compile").read_bytes() == b"stats"
        assert not (runs[0] / "20260926000000").exists()
        assert not list(root.glob(".inflight-*"))
        (usage,) = list((root / ".usage").iterdir())
        assert usage.name.endswith("-77-1.txt")
        assert usage.read_text() == "sstate/ab/sstate:old.tar.zst\n"
        (manifest,) = list((root / ".manifest").iterdir())
        assert manifest.name == usage.name.removesuffix(".txt") + ".sha256"
        assert "  downloads/new-1.0.tar.gz\n" in manifest.read_text()
    # The old download was already on both mirrors: not re-uploaded.
    assert "old.tar.gz" not in (roots[0] / ".manifest").iterdir().__next__().read_text()


def test_a_mirror_without_room_is_skipped_and_reported_degraded(
    tmp_path: Path,
    mirrors: tuple[list[Path], int, int],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    roots, read_port, write_port = mirrors
    _touch(roots[1] / ".status" / "df.json", _df_live(0))
    sstate, dl, bs = tmp_path / "sstate", tmp_path / "dl", tmp_path / "bs"
    for d in (sstate, dl, bs):
        d.mkdir()
    state = tmp_path / "state.json"
    summary = tmp_path / "summary.md"
    for k, v in {
        "SSTATE_DIR": str(sstate),
        "DL_DIR": str(dl),
        "BUILDSTATS_BASE": str(bs),
        "GITHUB_RUN_ID": "78",
        "GITHUB_RUN_ATTEMPT": "1",
        "GITHUB_STEP_SUMMARY": str(summary),
        "LAMADIST_PUBLISH_MIRRORS": "127.0.0.1 127.0.0.2",
        "LAMADIST_PUBLISH_READ_PORT": str(read_port),
        "LAMADIST_PUBLISH_WRITE_PORT": str(write_port),
        "LAMADIST_PUBLISH_USER": "publish",
        "LAMADIST_PUBLISH_PASSWORD": "secret",
    }.items():
        monkeypatch.setenv(k, v)
    assert publish.main(["snapshot", "--state", str(state)]) == 0
    _touch(sstate / "ab/sstate:n.tar.zst", b"n")
    assert publish.main(["publish", "--state", str(state)]) == 0
    assert (roots[0] / "sstate/ab/sstate:n.tar.zst").exists()
    assert not (roots[1] / "sstate/ab/sstate:n.tar.zst").exists()
    assert "degraded" in summary.read_text()
