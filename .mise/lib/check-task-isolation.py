#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Fail when BitBake cannot cut a task off the network.

BitBake runs every task that has not asked for network access inside
a new user and network namespace (bb.utils.disable_network).  When the
kernel refuses an unprivileged user namespace, that function logs at
debug level and returns, so the task runs with network access and the
build stays green.  This check calls the same function in a child
process and fails unless the child ends up in a new network namespace
with only the loopback interface.

Usage: check-task-isolation.py BITBAKE_LIB_DIR
Exit status: 0 isolated, 1 not isolated, 2 usage error.
"""

from __future__ import annotations

import importlib
import os
import socket
import sys
from collections.abc import Sequence
from pathlib import Path


def main(argv: Sequence[str]) -> int:
    if len(argv) != 1:
        print(__doc__, file=sys.stderr)
        return 2
    lib = Path(argv[0])
    if not (lib / "bb" / "utils.py").is_file():
        print(f"error: no bitbake library at {lib}", file=sys.stderr)
        return 2
    sys.path.insert(0, str(lib))
    # The library path is only known at run time, from the kas checkout.
    bb_utils = importlib.import_module("bb.utils")

    before = os.readlink("/proc/self/ns/net")
    read_end, write_end = os.pipe()
    pid = os.fork()
    if pid == 0:
        os.close(read_end)
        bb_utils.disable_network(os.getuid(), os.getgid())
        isolated = os.readlink("/proc/self/ns/net") != before and [
            name for _, name in socket.if_nameindex()
        ] == ["lo"]
        os.write(write_end, b"1" if isolated else b"0")
        os._exit(0)
    os.close(write_end)
    os.waitpid(pid, 0)
    if os.read(read_end, 1) == b"1":
        print("task network isolation: ok")
        return 0
    print(
        "error: BitBake could not isolate a task from the network"
        " (are unprivileged user namespaces refused?)",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
