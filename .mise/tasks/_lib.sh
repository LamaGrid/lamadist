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

# Effective CPU count for the build.  Inside a cgroup-namespaced
# container (CI pod, capped podman) cpu.max is the truth; nproc
# sees every node core because pod CPU limits are CFS quota, not
# an affinity mask.
_detect_cpus() {
	local _quota _period
	if [[ -r /sys/fs/cgroup/cpu.max ]]; then
		read -r _quota _period < /sys/fs/cgroup/cpu.max
		if [[ "$_quota" != "max" && -n "$_period" ]]; then
			echo $(((_quota + _period - 1) / _period))
			return
		fi
	fi
	nproc
}

# Effective memory envelope in whole GiB.  Preference order:
# cgroup limit (visible only inside a capped container), then the
# podman cap the build container will run under, then host
# MemTotal.
_detect_mem_gb() {
	local _v
	if [[ -r /sys/fs/cgroup/memory.max ]]; then
		_v=$(< /sys/fs/cgroup/memory.max)
		if [[ "$_v" != "max" ]]; then
			echo $((_v / 1073741824))
			return
		fi
	fi
	_v="${PODMAN_RUN_MEMORY:-}"
	case "$_v" in
		*[gG]) echo "${_v%[gG]}" && return ;;
		*[mM]) echo $((${_v%[mM]} / 1024)) && return ;;
		*[kK]) echo $((${_v%[kK]} / 1048576)) && return ;;
	esac
	awk '/^MemTotal:/ {printf "%d", $2 / 1048576}' /proc/meminfo
}

# Per-recipe make-job cuts for the measured heavy compilers, only
# when the memory envelope is tight (< 24 GiB).  Child ru_maxrss
# per compile process (buildstats 2026-09-01): cargo-native 3.0G,
# linux-yocto 2.5G, llvm-native 2.3G, clang-native 2.0G, rust
# ~1.5G, gcc 1.4G, spirv-llvm-translator-native 1.4G.  At -j6 one
# such recipe holds 6-12 GB alone and OOMs an 11 GiB cgroup even
# with BB_NUMBER_THREADS already reduced (observed: clang-native
# cc1plus kill in the 11 GiB validation build).  PARALLEL_MAKE is
# hash-ignored, so these change no task signatures.
# do_create_spdx concurrency cap, or empty for "schedule freely".
# LAMADIST_SPDX_THREADS forces a value; LAMADIST_SPDX_HEAVY (set
# by the build task for release builds, where full source
# inventory makes each task hold 2-3 GB) selects from the memory
# table.
_spdx_thread_cap() {
	local _mem_gb="$1"
	if [[ -n "${LAMADIST_SPDX_THREADS:-}" ]]; then
		echo "${LAMADIST_SPDX_THREADS}"
	elif [[ -n "${LAMADIST_SPDX_HEAVY:-}" ]]; then
		if ((_mem_gb < 16)); then
			echo 1
		elif ((_mem_gb < 32)); then
			echo 2
		else
			echo 4
		fi
	fi
}

_emit_heavy_recipe_caps() {
	local _overlay="$1" _cpus="$2" _mem_gb="$3"
	((_mem_gb < 24)) || return 0
	local _j=$((_mem_gb / 3)) _r
	((_j >= 2)) || _j=2
	((_j <= _cpus)) || _j=$_cpus
	for _r in clang-native llvm-native spirv-llvm-translator-native \
		gcc linux-yocto cargo-native rust-native; do
		cat >> "$_overlay" <<- OVERLAY
			    PARALLEL_MAKE:pn-${_r} = '-j ${_j}'
		OVERLAY
	done
}

# Write the dynamic KAS overlay (.cache/dynamic.kas.yml) carrying
# version and build-stats settings, sourced from the gitversion env
# file stamped by the 'info' task.  A file stamped for a different
# HEAD is rejected: a stale DISTRO_VERSION (wrong branch, old sha)
# is worse than the bitbake snapshot fallback.
#
# bitbake parses local.conf BEFORE distro.conf and bbclasses, so:
#   - DISTRO_VERSION: use ?= in lamadist.conf, plain = here
#     (local.conf wins)
#   - BUILDSTATS_BASE: upstream class uses =, overrides local.conf;
#     use the :lamadist distro override, which has higher priority
#   - DISTRO_VERSION[vardepvalue] is intentionally NOT set here.
#     lamadist.conf pins it to the constant DISTRO_VERSION_BASE,
#     which keeps package sstate hashes stable across commits
#     (os-release opts back in via its bbappend).
write_dynamic_overlay() {
	local _gitversion_env="${MISE_CONFIG_ROOT}/.cache/gitversion.env"
	local _head_sha
	if [[ -f "${_gitversion_env}" ]]; then
		# shellcheck source=/dev/null
		source "${_gitversion_env}"
		_head_sha=$(git -C "${MISE_CONFIG_ROOT}" rev-parse HEAD 2> /dev/null || echo "")
		if [[ "${GITVERSION_ENV_SHA:-}" != "${_head_sha}" ]]; then
			echo "WARNING: ${_gitversion_env} is stale (stamped for" >&2
			echo "         '${GITVERSION_ENV_SHA:-none}', HEAD is '${_head_sha}');" >&2
			echo "         ignoring cached version variables." >&2
			unset BUILDNAME DISTRO_VERSION
		fi
	fi
	local _dynamic_overlay="${MISE_CONFIG_ROOT}/.cache/dynamic.kas.yml"
	mkdir -p "$(dirname "${_dynamic_overlay}")"
	cat > "${_dynamic_overlay}" <<- OVERLAY
		# Auto-generated by write_dynamic_overlay -- do not edit
		header:
		  version: 15
		local_conf_header:
		  05_dynamic: |
		    BUILDSTATS_BASE:lamadist = '${BUILDSTATS_BASE}'
	OVERLAY
	if [[ -n "${BUILDNAME:-}" ]]; then
		cat >> "${_dynamic_overlay}" <<- OVERLAY
			    BUILDNAME = '${BUILDNAME}'
		OVERLAY
	fi
	if [[ -n "${DISTRO_VERSION:-}" ]]; then
		cat >> "${_dynamic_overlay}" <<- OVERLAY
			    DISTRO_VERSION = '${DISTRO_VERSION}'
		OVERLAY
	fi
	# Parallelism.  LAMADIST_MAX_LOCAL_JOBS (e.g. .mise.local.toml)
	# is an explicit cap and wins outright.  Otherwise auto-size
	# from the detected envelope: N tasks, make jobs N+2 with a
	# load-average brake at N+4 (-l guards CPU thrash only; memory
	# is governed by the class caps below).  Under --icecc the same
	# cap bounds iceccd's local slots while ICECC_PARALLEL_MAKE
	# raises per-recipe make jobs for the remote pool.
	local _cpus _mem_gb
	_cpus=$(_detect_cpus)
	_mem_gb=$(_detect_mem_gb)
	if [[ -n "${LAMADIST_MAX_LOCAL_JOBS:-}" ]]; then
		cat >> "${_dynamic_overlay}" <<- OVERLAY
			    BB_NUMBER_THREADS = '${LAMADIST_MAX_LOCAL_JOBS}'
			    PARALLEL_MAKE = '-j ${LAMADIST_MAX_LOCAL_JOBS}'
		OVERLAY
	else
		cat >> "${_dynamic_overlay}" <<- OVERLAY
			    BB_NUMBER_THREADS = '${_cpus}'
			    PARALLEL_MAKE = '-j $((_cpus + 2)) -l $((_cpus + 4))'
		OVERLAY
	fi
	# Memory-aware cap for the measured outlier (buildstats,
	# 2026-09-01): with full source inventory on (release builds;
	# LAMADIST_SPDX_HEAVY set by the build task), do_create_spdx
	# holds 2-3 GB per task across ~650 instances, so cap its
	# concurrency by the memory envelope.  number_threads is
	# scheduling-only -- no task-signature impact.  Source-free
	# SPDX (dev/QA default) is a few hundred MB per task and
	# schedules freely.  Compressor thread counts default to
	# cpu_count(), which sees every node core from inside a pod,
	# so pin them to the detected envelope.
	local _spdx_threads
	_spdx_threads=$(_spdx_thread_cap "${_mem_gb}")
	if [[ -n "${_spdx_threads}" ]]; then
		cat >> "${_dynamic_overlay}" <<- OVERLAY
			    do_create_spdx[number_threads] = '${_spdx_threads}'
		OVERLAY
	fi
	# Compressor threads are memory-bound, not CPU-bound, at the
	# heavy presets.  zstd --ultra -22 holds ~1.6 GB per thread once
	# the per-worker job buffers are counted (measured: 5 threads =
	# 8.03 GB anon RSS, OOM-killed an 11 GiB cgroup in do_image_wic
	# with one SPDX task still resident; run 33823958778), xz -9e
	# ~0.9 GB.  A quarter-GiB-per-GB envelope keeps the worst preset
	# near mem/2.5 GB total, leaving room for the task graph to
	# overlap image compression with SPDX stragglers.
	local _zstd_threads=$((_mem_gb / 4))
	((_zstd_threads >= 2)) || _zstd_threads=2
	((_zstd_threads <= _cpus)) || _zstd_threads=$_cpus
	cat >> "${_dynamic_overlay}" <<- OVERLAY
		    XZ_THREADS = '${_zstd_threads}'
		    ZSTD_THREADS = '${_zstd_threads}'
	OVERLAY
	_emit_heavy_recipe_caps "${_dynamic_overlay}" "${_cpus}" "${_mem_gb}"
	# Host-local icecc fan-out cap (LAMADIST_ICECC_JOBS): overrides
	# the icecc overlay's weak -j40 default.  Every icecc job costs
	# a local preprocessor pass (ICECC_REMOTE_CPP=0), so
	# memory-tight hosts (9 GiB CI pods) must bound it or the
	# build OOMs its own cgroup.  Hash-ignored; no sstate impact.
	if [[ -n "${LAMADIST_ICECC_JOBS:-}" ]]; then
		cat >> "${_dynamic_overlay}" <<- OVERLAY
			    ICECC_PARALLEL_MAKE = '-j ${LAMADIST_ICECC_JOBS}'
		OVERLAY
	fi
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
