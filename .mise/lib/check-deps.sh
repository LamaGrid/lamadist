#!/usr/bin/env bash
# Container dependency freshness gate, run by `mise run check`.
#
# `mise run container:builder:verify` exits 5 when
# container/check_updates.sh finds available updates, 2 when the apt
# lockfile is stale, 3 when the builder image is missing, and 1 when
# no container runtime is found.  Updates warn; everything else
# fails the check.

set -o errexit
set -o nounset
set -o pipefail

# `$?` inside `if ! cmd; then` is the negated status (always 0), so
# capture the real status on the failure branch instead.
if output=$(mise run container:builder:verify 2>&1); then
	status=0
else
	status=$?
fi
echo "$output"

case "$status" in
	0) ;;
	5)
		echo "WARNING: Dependencies have available updates. Consider running 'mise run container:builder:lock'."
		;;
	2)
		echo "ERROR: Dependencies are stale (>7 days). Run 'mise run container:builder:lock'."
		exit 1
		;;
	*)
		exit "$status"
		;;
esac
