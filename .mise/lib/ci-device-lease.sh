#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
# Hold the device Lease around a critical section.
#
# Usage:
#   acquire-lease.sh acquire <holder> [timeout-seconds]
#   acquire-lease.sh release <holder>
#   acquire-lease.sh status
#
# Works from a CI job pod (in-cluster ServiceAccount) and from the
# desktop (kubeconfig) alike; both sides use the same script so the
# protocol cannot drift.  The lamadist head runs `acquire` before a
# deploy and `release` after, exactly as CI does around validation.
#
# Acquire succeeds when the Lease is free (no holder) or expired
# (renewTime + leaseDurationSeconds is in the past), and it writes the
# new holder with a resourceVersion precondition so two acquirers
# racing for a free lease cannot both win.  It waits up to the
# timeout for a held lease, then fails.
#
# Environment: LEASE_NS (default arc-runners), LEASE_NAME (default
# lamadist-device).  Needs kubectl and jq.
set -o errexit
set -o nounset
set -o pipefail

LEASE_NS="${LEASE_NS:-arc-runners}"
LEASE_NAME="${LEASE_NAME:-lamadist-device}"
SELF_NAME="$(basename "$0")" && readonly SELF_NAME

_fail() {
	echo "$SELF_NAME: ERROR: $*" >&2
	exit "${2:-1}"
}

_get() {
	kubectl -n "$LEASE_NS" get lease "$LEASE_NAME" -o json
}

_now() {
	date -u +%Y-%m-%dT%H:%M:%SZ
}

# Prints "free" or "held <holder>" and whether it is expired.
_status() {
	_get | jq -r '
		.spec as $s
		| ($s.holderIdentity // "") as $h
		| ($s.renewTime // "1970-01-01T00:00:00Z" | sub("\\.[0-9]+"; "") | fromdateiso8601) as $t
		| ($s.leaseDurationSeconds // 0) as $d
		| if $h == "" then "free"
		  elif (now - $t) > $d then "expired \($h)"
		  else "held \($h)" end'
}

# Try once; exit 0 if we now hold it, 1 if someone else does.
_try_acquire() {
	local holder="$1" json rv state
	json="$(_get)"
	rv="$(jq -r .metadata.resourceVersion <<< "$json")"
	state="$(jq -r '
		.spec as $s
		| ($s.holderIdentity // "") as $h
		| ($s.renewTime // "1970-01-01T00:00:00Z" | sub("\\.[0-9]+"; "") | fromdateiso8601) as $t
		| ($s.leaseDurationSeconds // 0) as $d
		| if $h == "" or (now - $t) > $d then "takeable" else "held" end' <<< "$json")"
	[[ "$state" == takeable ]] || return 1
	# The resourceVersion precondition makes this a compare-and-swap:
	# if anyone touched the Lease since we read it, the patch is
	# rejected and we retry.
	kubectl -n "$LEASE_NS" patch lease "$LEASE_NAME" --type merge -p "$(jq -nc \
		--arg h "$holder" --arg t "$(_now)" --arg rv "$rv" \
		'{metadata: {resourceVersion: $rv}, spec: {holderIdentity: $h, acquireTime: $t, renewTime: $t}}')" \
		> /dev/null 2>&1
}

_acquire() {
	local holder="$1" timeout="${2:-600}" deadline
	deadline=$((SECONDS + timeout))
	while true; do
		if _try_acquire "$holder"; then
			echo "$SELF_NAME: acquired $LEASE_NS/$LEASE_NAME as $holder"
			return 0
		fi
		((SECONDS < deadline)) || _fail "timed out after ${timeout}s; lease is $(_status)"
		sleep 10
	done
}

_release() {
	local holder="$1" current
	current="$(_get | jq -r '.spec.holderIdentity // ""')"
	if [[ "$current" != "$holder" ]]; then
		echo "$SELF_NAME: not held by $holder (holder: '${current:-none}'); nothing to release" >&2
		return 0
	fi
	kubectl -n "$LEASE_NS" patch lease "$LEASE_NAME" --type merge \
		-p '{"spec":{"holderIdentity":null,"acquireTime":null,"renewTime":null}}' > /dev/null
	echo "$SELF_NAME: released $LEASE_NS/$LEASE_NAME"
}

case "${1:-}" in
	acquire)
		[[ $# -ge 2 ]] || _fail "usage: $SELF_NAME acquire <holder> [timeout]"
		_acquire "$2" "${3:-600}"
		;;
	release)
		[[ $# -ge 2 ]] || _fail "usage: $SELF_NAME release <holder>"
		_release "$2"
		;;
	status) _status ;;
	*) _fail "usage: $SELF_NAME acquire <holder> [timeout] | release <holder> | status" ;;
esac
