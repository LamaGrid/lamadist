#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
#
# Start the build's local iceccd as the current (non-root) user.
#
# Usage: start-iceccd.sh SCHEDULER [WORKDIR]
#   SCHEDULER  icecc scheduler address (127.0.0.1 keeps every job local)
#   WORKDIR    daemon log and environment cache (default /tmp/iceccd)
#
# Environment:
#   LAMADIST_MAX_LOCAL_JOBS  optional cap on the daemon's local slots
#   LAMADIST_ICECCD          daemon binary (default /usr/sbin/iceccd)
#   LAMADIST_ICECC_SOCKDIR   socket directory (default /var/run/icecc)
#
# A non-root iceccd binds $HOME/.iceccd.socket, and icecc clients try
# /var/run/icecc/iceccd.socket first.  BitBake gives every task a
# throwaway HOME, so the daemon runs with HOME set to the socket
# directory, where the builder image links iceccd.socket to
# .iceccd.socket.  The daemon runs with --no-remote, so it needs no
# chroot and no user switch.  Every failure is a warning, never an
# error: without a daemon, icecc clients compile locally.
#
# Exit status: always 0.

set -o errexit
set -o nounset
set -o pipefail

_scheduler="$1"
_workdir="${2:-/tmp/iceccd}"
_iceccd="${LAMADIST_ICECCD:-/usr/sbin/iceccd}"
_sockdir="${LAMADIST_ICECC_SOCKDIR:-/var/run/icecc}"

_local_only() {
	echo "==> WARNING: $*; icecc compiles stay local" >&2
	exit 0
}

# A fresh tmpfs over /run at container start would drop the directory
# and link the image created.
[[ -d "${_sockdir}" && -w "${_sockdir}" ]] || _local_only "${_sockdir} is missing or not writable"
[[ -L "${_sockdir}/iceccd.socket" ]] || _local_only "${_sockdir}/iceccd.socket link is missing"

mkdir -p "${_workdir}"
# shellcheck disable=SC2086 # the -m pair is either absent or two words
HOME="${_sockdir}" "${_iceccd}" -d --no-remote \
	${LAMADIST_MAX_LOCAL_JOBS:+-m ${LAMADIST_MAX_LOCAL_JOBS}} \
	-s "${_scheduler}" -b "${_workdir}/envs" -l "${_workdir}/iceccd.log" \
	|| _local_only 'iceccd failed to start'
