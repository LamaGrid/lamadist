#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
# Hold the device Lease around a critical section.
#
# Usage:
#   ci-device-lease.sh acquire <holder> [timeout-seconds]
#   ci-device-lease.sh release <holder>
#   ci-device-lease.sh status
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

# Lease acquireTime/renewTime are MicroTime: the API server rejects a
# timestamp without exactly six fractional digits.
_now() {
	date -u +%Y-%m-%dT%H:%M:%S.%6NZ
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

# Try once; exit 0 if we now hold it, 1 if someone else does.  Any
# failure other than losing the race (RBAC, a missing Lease, a
# rejected body, no route to the API) is fatal on the spot: retrying
# it for the whole timeout would only report "lease is held".
_try_acquire() {
	local holder="$1" json rv state out
	json="$(_get)" || _fail "cannot read $LEASE_NS/$LEASE_NAME"
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
	out="$(kubectl -n "$LEASE_NS" patch lease "$LEASE_NAME" --type merge -p "$(jq -nc \
		--arg h "$holder" --arg t "$(_now)" --arg rv "$rv" \
		'{metadata: {resourceVersion: $rv}, spec: {holderIdentity: $h, acquireTime: $t, renewTime: $t}}')" 2>&1)" \
		&& return 0
	grep -q 'Operation cannot be fulfilled' <<< "$out" && return 1
	_fail "cannot acquire $LEASE_NS/$LEASE_NAME: $out"
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

# Same compare-and-swap as acquire: if the Lease changed hands after
# ours expired, the stale release is rejected instead of clearing the
# new holder.
_release() {
	local holder="$1" json current rv out
	json="$(_get)" || _fail "cannot read $LEASE_NS/$LEASE_NAME"
	current="$(jq -r '.spec.holderIdentity // ""' <<< "$json")"
	rv="$(jq -r .metadata.resourceVersion <<< "$json")"
	if [[ "$current" != "$holder" ]]; then
		echo "$SELF_NAME: not held by $holder (holder: '${current:-none}'); nothing to release" >&2
		return 0
	fi
	out="$(kubectl -n "$LEASE_NS" patch lease "$LEASE_NAME" --type merge -p "$(jq -nc --arg rv "$rv" \
		'{metadata: {resourceVersion: $rv}, spec: {holderIdentity: null, acquireTime: null, renewTime: null}}')" 2>&1)" \
		&& { echo "$SELF_NAME: released $LEASE_NS/$LEASE_NAME"; return 0; }
	grep -q 'Operation cannot be fulfilled' <<< "$out" && {
		echo "$SELF_NAME: lease changed hands during release; nothing to release" >&2
		return 0
	}
	_fail "cannot release $LEASE_NS/$LEASE_NAME: $out"
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
