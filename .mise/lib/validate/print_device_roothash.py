# SPDX-License-Identifier: Apache-2.0
"""Print the root hash the target device currently runs.

Reads ``/proc/cmdline`` through the same ``CollectorTarget`` the
validation suite builds from the environment, so the transport (the
post-quantum algorithms, the strict host-key pin, keepalive, and the
JSON/error handling) has a single definition.  CI uses this to pin
rule 1's expected hash to the running image when a run names none, and
it fails closed: an unreachable device, a broken collector, or a
command line without a root hash all exit non-zero.
"""

from __future__ import annotations

import re
import sys
from typing import Final

from validate.target import from_env

_ROOTHASH: Final[re.Pattern[str]] = re.compile(r"roothash=([0-9a-f]{64})")


def main() -> int:
    cmdline = from_env().run("cat /proc/cmdline").stdout
    found = _ROOTHASH.search(cmdline)
    if found is None:
        print("no roothash in the device kernel command line", file=sys.stderr)
        return 1
    print(found.group(1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
