#!/usr/bin/env bash
# Wrapper for check-deps in pre-push hook
# Allows exit code 1 (updates available) but fails on 2 (stale) or other errors

set -o errexit
set -o nounset
set -o pipefail

if ! output=$(mise run container:builder:verify 2>&1); then
	status=$?
	echo "$output"
	if [ "$status" -eq 1 ]; then
		# Updates available - warn but allow push
		echo "WARNING: Dependencies have available updates. Consider running 'mise run container:builder:lock'."
		exit 0
	elif [ "$status" -eq 2 ]; then
		# Stale - fail push
		echo "ERROR: Dependencies are stale (>7 days). You must run 'mise run container:builder:lock' before pushing."
		exit 1
	else
		# Other error
		exit "$status"
	fi
else
	echo "$output"
fi
