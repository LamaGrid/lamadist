#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
#
# Pre-push hook: warn if security scans have not been run on this branch.
# The build task writes the current HEAD SHA to .cache/last-scan-sha when
# --include-scans (or --release) is used. This hook compares that marker
# against the current HEAD and prompts the user to opt out if they differ.

set -euo pipefail

MARKER="${LAMADIST_PROJECT_DIR:-.}/.cache/last-scan-sha"

current_sha=$(git rev-parse HEAD 2>/dev/null || echo "unknown")

if [ -f "${MARKER}" ]; then
    scanned_sha=$(cat "${MARKER}")
    if [ "${scanned_sha}" = "${current_sha}" ]; then
        exit 0
    fi
fi

echo ""
echo "⚠  Security scans have not been run on this commit."
echo "   Run:  mise run build --include-scans"
echo ""

# Non-interactive environments (CI, piped input) should not block
if [ ! -t 0 ]; then
    exit 0
fi

read -r -p "Push without security scans? [y/N] " response
case "${response}" in
    [yY]|[yY][eE][sS])
        exit 0
        ;;
    *)
        echo "Push aborted. Run 'mise run build --include-scans' first."
        exit 1
        ;;
esac
