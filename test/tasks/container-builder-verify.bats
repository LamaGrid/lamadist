#!/usr/bin/env bats
# SPDX-License-Identifier: Apache-2.0
#
# Lockfile staleness in .mise/tasks/container/builder/verify.  Age is
# the time since container/packages.lock last changed in git history,
# not the file's mtime, and a lockfile with uncommitted changes counts
# as fresh.
#
#   Given the lockfile was committed today, verify passes.
#   Given the lockfile was committed 10 days ago, verify exits 2.
#   Given a 10-day-old lockfile has uncommitted changes, verify passes.
#   Given the lockfile is missing, verify exits 2.

setup() {
	_verify="${BATS_TEST_DIRNAME}/../../.mise/tasks/container/builder/verify"
	_repo="${BATS_TEST_TMPDIR}/repo"
	_bin="${BATS_TEST_TMPDIR}/bin"
	mkdir -m 0700 "$_bin"
	# A container runtime that always finds the image and reports no
	# updates, so only the lockfile gate decides the outcome.
	cat > "${_bin}/podman" <<- 'EOF'
		#!/bin/sh
		exit 0
	EOF
	chmod 0700 "${_bin}/podman"
	PATH="${_bin}:${PATH}"
	export MISE_CONFIG_ROOT="$_repo"
	mkdir -m 0700 "$_repo"
	mkdir -m 0700 "${_repo}/container"
	git -C "$_repo" init -q
	git -C "$_repo" config user.email 'test@example.invalid'
	git -C "$_repo" config user.name 'test'
}

# Commit a lockfile with the given author and committer date.
_commit_lock() {
	echo '# Auto-generated lockfile. Do not edit.' > "${_repo}/container/packages.lock"
	git -C "$_repo" add container/packages.lock
	GIT_AUTHOR_DATE="$1" GIT_COMMITTER_DATE="$1" \
		git -C "$_repo" commit -q -m 'lock'
}

@test "lockfile committed today: verify passes" {
	_commit_lock "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
	run "$_verify"
	[ "$status" -eq 0 ]
}

@test "lockfile committed 10 days ago: verify exits 2 (stale)" {
	_commit_lock "$(date -u -d '10 days ago' +%Y-%m-%dT%H:%M:%SZ)"
	run "$_verify"
	[ "$status" -eq 2 ]
	[[ "$output" == *'stale'* ]]
}

@test "old lockfile with uncommitted changes: verify passes" {
	_commit_lock "$(date -u -d '10 days ago' +%Y-%m-%dT%H:%M:%SZ)"
	echo 'pkg=1.0' >> "${_repo}/container/packages.lock"
	run "$_verify"
	[ "$status" -eq 0 ]
}

@test "missing lockfile: verify exits 2" {
	run "$_verify"
	[ "$status" -eq 2 ]
	[[ "$output" == *'not found'* ]]
}
