#!/usr/bin/bash
# SPDX-License-Identifier: Apache-2.0
#
# Build the KAS builder image in CI and push it when the run holds a
# registry push credential.
#
# This script runs in the job that holds the registry push credential.
# It pins PATH to the system directories, takes podman from its first
# argument or from /usr/bin/podman, and runs its other tools through the
# pinned PATH.  CI runs it directly as
# `exec /usr/bin/bash -p .mise/lib/builder-ci.sh`, not through mise; the
# build task's CI branch runs it for local use.
# The -p flag makes bash skip BASH_ENV, which bash would otherwise read
# before this script's first line runs, and ignore shell functions
# exported in the environment.
#
# The login writes the credential to an auth file in a directory made
# by mktemp -d, not to podman's default auth file.  The pushes read that
# file, and an EXIT trap removes the directory.
#
# The script copies the registry password into an unexported shell
# variable and unsets LAMADIST_REGISTRY_PASSWORD before the build, so no
# podman call has the password in its environment.  The login reads it
# on standard input (--password-stdin).  While the build runs, the value
# is still in this script's memory and in the process's initial
# environment block.  The runner may also hold a copy for the step's
# life: in Kubernetes hook mode, a step script under its temporary
# directory (a job log from the site shows that mode).
#
# Usage: builder-ci.sh [PODMAN]
#   PODMAN  podman binary (default /usr/bin/podman); tests pass a fake
#
# Environment:
#   LAMADIST_CONTAINER_IMAGE        local image name (required)
#   BUILDER_UID                     builder user id (default: caller's)
#   LAMADIST_REGISTRY               registry to push to
#   LAMADIST_REGISTRY_USER          registry user
#   LAMADIST_REGISTRY_PASSWORD      registry push credential (unset from
#                                   the environment before the build)
#   LAMADIST_REGISTRY_TLS_VERIFY    "false" turns TLS verification off
#
# A run without a registry and its credential builds the image to prove
# it builds, and does not push it.
#
# Exit status: 0 on success; 1 when LAMADIST_CONTAINER_IMAGE is unset or
# empty, or when a credential has no user; otherwise the non-zero status
# of the command that failed (a build, login, or push, for example).

PATH=/usr/sbin:/usr/bin
export PATH
unset BASH_ENV ENV # so no child shell reads them

set -o errexit
set -o nounset
set -o pipefail

_auth_dir=''
_cleanup() {
	if [ -n "${_auth_dir}" ]; then
		rm -rf -- "${_auth_dir}"
	fi
}
# Bash runs the EXIT trap when the script ends on SIGINT or SIGTERM as
# well as on exit, so no signal names are listed.
trap _cleanup EXIT

# Keep the password out of every child's environment, the build's
# included: copy it to an unexported variable, then unset the exported one.
# A variable that arrives exported keeps its export attribute when it is
# assigned, so remove the attribute right after the assignment.
_registry_password="${LAMADIST_REGISTRY_PASSWORD:-}"
declare +x _registry_password
unset LAMADIST_REGISTRY_PASSWORD

_podman="${1:-/usr/bin/podman}"

# The repository root comes from this file's own path.
_here="${BASH_SOURCE[0]}"
case "${_here}" in
	*/*) _here="${_here%/*}" ;;
	*) _here='.' ;;
esac
_context="${_here}/../../container/"

_version_tag="$(date -u +'%Y-%m-%dT%H%M%SZ')"
_local_image="${LAMADIST_CONTAINER_IMAGE:?LAMADIST_CONTAINER_IMAGE is unset}"
_build_uid="${BUILDER_UID:-$(id -u)}"

"${_podman}" build --format docker --net=host --dns=8.8.8.8 \
	--build-arg BUILDER_UID="${_build_uid}" \
	-t "${_local_image}" "${_context}"

# Pushing needs the site's registry and its push credential
# (LAMADIST_REGISTRY, LAMADIST_REGISTRY_USER, and
# LAMADIST_REGISTRY_PASSWORD, read above).
_registry="${LAMADIST_REGISTRY:-}"
_tls_verify="${LAMADIST_REGISTRY_TLS_VERIFY:-true}"
if [ -z "${_registry}" ] || [ -z "${_registry_password}" ]; then
	echo '==> No registry credential in this run: built, not pushed'
elif [ -z "${LAMADIST_REGISTRY_USER:-}" ]; then
	echo '==> ERROR: LAMADIST_REGISTRY_USER is unset; not pushing.' >&2
	exit 1
else
	_auth_dir="$(mktemp -d)"
	_authfile="${_auth_dir}/auth.json"
	printf '%s' "${_registry_password}" \
		| "${_podman}" login --authfile="${_authfile}" \
			--tls-verify="${_tls_verify}" --password-stdin \
			-u "${LAMADIST_REGISTRY_USER}" "${_registry}"
	_registry_image="${_registry}/lamagrid/lamadist-builder"
	"${_podman}" tag "${_local_image}" "${_registry_image}:${_version_tag}"
	"${_podman}" tag "${_local_image}" "${_registry_image}:latest"
	"${_podman}" push --authfile="${_authfile}" --tls-verify="${_tls_verify}" \
		"${_registry_image}:${_version_tag}"
	"${_podman}" push --authfile="${_authfile}" --tls-verify="${_tls_verify}" \
		"${_registry_image}:latest"
	echo "Pushed ${_registry_image}:${_version_tag}"
	echo "Pushed ${_registry_image}:latest"
fi
