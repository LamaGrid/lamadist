#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
#
# Shared functions for mise tasks that run commands inside the builder container.
# Source this file from any task that needs to invoke the build container:
#   source "${MISE_CONFIG_ROOT}/.mise/tasks/_lib.sh"

# Ensure the host-cached TEST SSH key pair exists and print the
# public key's host path.  Generated once, cached indefinitely,
# never committed (.local/ is gitignored); consumed by
# kas/extras/test-ssh-key.kas.yml, which bakes the PUBLIC half into
# dev/test images as an authorized key for the lama user.
ensure_test_ssh_key() {
	local _dir="${MISE_CONFIG_ROOT}/.local/share/lamadist/test-ssh"
	if [[ ! -f "${_dir}/id_ed25519.pub" ]]; then
		mkdir -p "${_dir}"
		ssh-keygen -q -t ed25519 -N '' -C 'lamadist-test' -f "${_dir}/id_ed25519"
		echo "==> Generated test SSH key (cached): ${_dir}/id_ed25519" >&2
	fi
	echo "${_dir}/id_ed25519.pub"
}

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
	# A pty is only safe when stdin is a real terminal.  When the
	# caller is detached (CI, agents, nohup), the pty master can
	# vanish mid-build and every stdio write in the container then
	# fails with EIO, killing bitbake workers at random.
	local _interactive=""
	if [[ -t 0 ]]; then
		_interactive="-it"
	fi
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

	# Memory containment: a runaway bitbake must die inside the
	# container's cgroup instead of dragging the host into a global
	# OOM sweep.  Wrapping the *client* process in a memory-capped
	# unit does not work -- rootless podman detaches the container
	# into its own libpod scope, outside the wrapper's cgroup -- so
	# the cap has to ride on the container itself.
	#
	# Defaults auto-size to the host (90% of MemTotal; the swap
	# ceiling adds 90% of SwapTotal) so large build servers are
	# never artificially limited while small hosts still keep
	# enough headroom to stay alive.  Override via
	# PODMAN_RUN_MEMORY / PODMAN_RUN_MEMORY_SWAP (set both
	# together; --memory-swap is the memory+swap TOTAL and must be
	# >= --memory) in .mise.local.toml or the shell env.  Both
	# podman and docker accept the flags.  No /proc/meminfo and no
	# override means no limits at all.
	local _memory_args=()
	local _mem="${PODMAN_RUN_MEMORY:-}"
	local _swap="${PODMAN_RUN_MEMORY_SWAP:-}"
	if [[ -z "$_mem" || -z "$_swap" ]] && [[ -r /proc/meminfo ]]; then
		local _mem_kb _swap_kb
		_mem_kb=$(awk '/^MemTotal:/ {print $2}' /proc/meminfo)
		_swap_kb=$(awk '/^SwapTotal:/ {print $2}' /proc/meminfo)
		if [[ -z "$_mem" ]]; then
			_mem="$((_mem_kb * 90 / 100))k"
		fi
		if [[ -z "$_swap" ]]; then
			_swap="$(((_mem_kb * 90 / 100) + (_swap_kb * 90 / 100)))k"
		fi
	fi
	if [[ -n "$_mem" && -n "$_swap" ]]; then
		_memory_args=(--memory "$_mem" --memory-swap "$_swap")
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
		"${_memory_args[@]}" \
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
