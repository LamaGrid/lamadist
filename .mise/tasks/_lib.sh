#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
#
# Shared functions for mise tasks that run commands inside the builder container.
# Source this file from any task that needs to invoke the build container:
#   source "${MISE_CONFIG_ROOT}/.mise/tasks/_lib.sh"

# Resolve the Yocto MACHINE name from a LamaDist BSP name.
# Reads the machine: field from the BSP's KAS YAML file.
bsp_to_machine() {
	local _bsp="$1"
	local _kas_bsp="${MISE_CONFIG_ROOT}/kas/bsp/${_bsp}.kas.yml"
	if [[ -f "${_kas_bsp}" ]]; then
		grep '^machine:' "${_kas_bsp}" | head -1 | awk '{print $2}'
	else
		echo "${_bsp}"
	fi
}

# run_in_container [--no-tty] [--entrypoint CMD] -- COMMAND [ARGS...]
#
# Runs a command inside the builder container with standard volume mounts,
# environment variables, and user namespace configuration.
#
# Options:
#   --no-tty        Do not allocate a TTY (for non-interactive/CI use)
#   --entrypoint    Override the container entrypoint
#
# All arguments after "--" (or after options) are passed as the container command.
run_in_container() {
	local _interactive="-it"
	local _entrypoint_args=()
	local _cmd=()

	# Parse options
	while [[ $# -gt 0 ]]; do
		case "$1" in
			--no-tty)
				_interactive=""
				shift
				;;
			--entrypoint)
				_entrypoint_args=(--entrypoint "$2")
				shift 2
				;;
			--)
				shift
				_cmd=("$@")
				break
				;;
			*)
				_cmd=("$@")
				break
				;;
		esac
	done

	# User namespace arguments (Podman-specific)
	local _userns_args=()
	if [[ "${LAMADIST_CONTAINER_CMD}" == "podman" ]]; then
		_userns_args=(--userns=keep-id --group-add keep-groups)
	fi

	# Optional local env file
	local _env_local_args=()
	if [[ -f "${MISE_CONFIG_ROOT}/.kas.env.local" ]]; then
		_env_local_args=(--env-file "${MISE_CONFIG_ROOT}/.kas.env.local")
	fi

	# Build and deploy directory mounts
	mkdir -p "${LAMADIST_HOST_BUILD_DIR}" "${LAMADIST_HOST_DEPLOY_DIR}"

	mkdir -p "${LAMADIST_HOST_SSTATE_DIR}" "${LAMADIST_HOST_BUILDSTATS_BASE}"

	# shellcheck disable=SC2086
	"${LAMADIST_CONTAINER_CMD}" run --rm ${_interactive} \
		--privileged \
		"${_userns_args[@]}" \
		-v "${LAMADIST_HOST_SSTATE_DIR}:${SSTATE_DIR}" \
		-e "SSTATE_DIR=${SSTATE_DIR}" \
		-v "${LAMADIST_HOST_BUILDSTATS_BASE}:${BUILDSTATS_BASE}" \
		-v "${MISE_CONFIG_ROOT}:${KAS_WORK_DIR}" \
		-e "KAS_WORK_DIR=${KAS_WORK_DIR}" \
		-v "${LAMADIST_HOST_BUILD_DIR}:${KAS_WORK_DIR}/build" \
		-v "${LAMADIST_HOST_DEPLOY_DIR}:${KAS_WORK_DIR}/deploy" \
		--env-file "${MISE_CONFIG_ROOT}/.kas.env" \
		"${_env_local_args[@]}" \
		"${_entrypoint_args[@]}" \
		"${LAMADIST_CONTAINER_IMAGE}" \
		"${_cmd[@]}"
}
