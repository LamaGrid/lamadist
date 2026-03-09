#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
#
# KAS schema validation helper for hk pre-commit hooks.
# Resolves the KAS JSON schema (from local install or cached
# download) and validates the provided YAML files against it.

set -euo pipefail

_cache_dir="${LAMADIST_PROJECT_DIR:-.}/.cache/kas-schema"
_schema_file=""

# Try to find the schema from a local kas installation
_find_local_schema() {
	local _path
	_path=$(python3 -c \
		'import kas, os; print(os.path.join(os.path.dirname(kas.__file__), "schema-kas.json"))' \
		2>/dev/null) || return 1
	if [ -f "$_path" ]; then
		_schema_file="$_path"
		return 0
	fi
	return 1
}

# Determine the KAS version from PyPI JSON API.
# Respects PIP_INDEX_URL for custom mirrors.
_get_kas_version() {
	local _pypi_base _json _version
	_pypi_base="${PIP_INDEX_URL:-https://pypi.org/simple/}"

	# Normalize: PyPI JSON API lives at /pypi/<pkg>/json,
	# not at the simple index.  Strip /simple/ suffix and
	# build the JSON API URL.
	_pypi_base="${_pypi_base%%/simple/}"
	_pypi_base="${_pypi_base%%/simple}"
	_pypi_base="${_pypi_base%%/}"

	_json=$(curl -sL "${_pypi_base}/pypi/kas/json" 2>/dev/null) \
		|| return 1

	# Extract latest non-yanked version
	_version=$(printf '%s' "$_json" \
		| jq -r '.info.version // empty' 2>/dev/null) \
		|| return 1

	if [ -n "$_version" ]; then
		printf '%s' "$_version"
		return 0
	fi
	return 1
}

# Fetch the KAS schema for a given version and cache it
_fetch_schema() {
	local _version="$1"
	local _dest="${_cache_dir}/${_version}/schema-kas.json"

	if [ -f "$_dest" ]; then
		_schema_file="$_dest"
		return 0
	fi

	mkdir -p "${_cache_dir}/${_version}"

	local _url="https://raw.githubusercontent.com/siemens/kas/${_version}/kas/schema-kas.json"
	if curl -sL --fail -o "$_dest" "$_url" 2>/dev/null; then
		_schema_file="$_dest"
		return 0
	fi

	# Clean up failed download
	rm -f "$_dest"
	return 1
}

# Resolve the schema file
_resolve_schema() {
	# 1. Try local installation
	if _find_local_schema; then
		return 0
	fi

	# 2. Try cached version — use newest cached if PyPI
	#    is unavailable
	local _version
	_version=$(_get_kas_version) || true

	if [ -n "$_version" ]; then
		if _fetch_schema "$_version"; then
			return 0
		fi
	fi

	# 3. Fall back to any existing cached schema
	local _latest_cached
	_latest_cached=$(find "$_cache_dir" -name 'schema-kas.json' \
		-print -quit 2>/dev/null) || true
	if [ -n "$_latest_cached" ]; then
		_schema_file="$_latest_cached"
		return 0
	fi

	echo 'Warning: could not resolve KAS schema; skipping validation' >&2
	return 1
}

if ! _resolve_schema; then
	exit 0
fi

exec check-jsonschema --schemafile "$_schema_file" "$@"
