#!/usr/bin/env bats
# SPDX-License-Identifier: Apache-2.0
#
# Behaviour of .mise/lib/check-deps.sh, the dependency freshness gate
# that `mise run check` runs around `mise run container:builder:verify`.  The verify task exits
# 5 when container/check_updates.sh finds updates, 2 when the apt
# lockfile is stale, and 3 when the builder image is missing.
#
#   Given verify exits 0, the check passes and the output is echoed.
#   Given verify exits 5, the check passes with a WARNING.
#   Given verify exits 2, the check fails with an ERROR.
#   Given verify exits 3, the check fails and the status passes
#   through.

setup() {
	_hook="${BATS_TEST_DIRNAME}/../../.mise/lib/check-deps.sh"
	_bin="${BATS_TEST_TMPDIR}/bin"
	mkdir -m 0700 "$_bin"
	cat > "${_bin}/mise" <<- 'EOF'
		#!/bin/sh
		echo 'verify output line'
		exit "${FAKE_VERIFY_STATUS:-0}"
	EOF
	chmod 0700 "${_bin}/mise"
	PATH="${_bin}:${PATH}"
}

@test "verify exit 0: check passes and output echoed" {
	FAKE_VERIFY_STATUS=0 run "$_hook"
	[ "$status" -eq 0 ]
	[[ "$output" == *'verify output line'* ]]
}

@test "verify exit 5 (updates available): check passes with a warning" {
	FAKE_VERIFY_STATUS=5 run "$_hook"
	[ "$status" -eq 0 ]
	[[ "$output" == *'verify output line'* ]]
	[[ "$output" == *'WARNING: Dependencies have available updates'* ]]
}

@test "verify exit 2 (stale lockfile): check fails with an error" {
	FAKE_VERIFY_STATUS=2 run "$_hook"
	[ "$status" -eq 1 ]
	[[ "$output" == *'ERROR: Dependencies are stale'* ]]
}

@test "verify exit 3 (builder image missing): status passed through" {
	FAKE_VERIFY_STATUS=3 run "$_hook"
	[ "$status" -eq 3 ]
}
