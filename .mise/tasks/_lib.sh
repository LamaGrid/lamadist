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
	# Post-quantum test key: ssh-mldsa44-ed25519, a hybrid of the
	# ML-DSA-44 signature with Ed25519, matching the image's
	# authentication policy.  Requires ssh-keygen from OpenSSH 10.4+.
	local _dir="${MISE_CONFIG_ROOT}/.local/share/lamadist/test-ssh"
	if [[ ! -f "${_dir}/id_mldsa44-ed25519.pub" ]]; then
		mkdir -p "${_dir}"
		ssh-keygen -q -t mldsa44-ed25519 -N '' -C 'lamadist-test' \
			-f "${_dir}/id_mldsa44-ed25519"
		echo "==> Generated test SSH key (cached): ${_dir}/id_mldsa44-ed25519" >&2
	fi
	echo "${_dir}/id_mldsa44-ed25519.pub"
}

# A tiny RAUC bundle signed by a certificate authority no image trusts,
# for the wrong-CA refusal check (ADR 0010 check 13).  Plain-format
# bundle laid out by hand -- squashfs, then a detached CMS signature,
# then the signature size as a big-endian 64-bit integer -- so the host
# needs only openssl and mksquashfs, not rauc.  The squashfs carries a
# coherent manifest, so the ONLY defect is the signer: the target must
# refuse it at signature verification, before any slot is touched.
# Generated once and cached (untracked); the signer is throwaway and
# classical (RSA) on purpose -- it exists to be rejected.
ensure_wrong_ca_bundle() {
	local _dir="${MISE_CONFIG_ROOT}/.local/share/lamadist/validate/wrong-ca"
	local _bundle="${_dir}/wrong-ca.raucb"
	if [[ ! -f "${_bundle}" ]]; then
		mkdir -p "${_dir}/tree"
		openssl req -x509 -newkey rsa:2048 -nodes -sha256 -days 3650 \
			-subj '/CN=LamaDist Validation Wrong CA' \
			-keyout "${_dir}/wrong-ca.key.pem" -out "${_dir}/wrong-ca.cert.pem" \
			2> /dev/null
		head -c 4096 /dev/zero > "${_dir}/tree/rootfs.img"
		cat > "${_dir}/tree/manifest.raucm" <<- EOF
			[update]
			compatible=lamadist-intel
			version=0

			[bundle]
			format=plain

			[image.rootfs]
			filename=rootfs.img
			size=4096
			sha256=$(sha256sum "${_dir}/tree/rootfs.img" | cut -d' ' -f1)
		EOF
		mksquashfs "${_dir}/tree" "${_dir}/wrong-ca.squashfs" \
			-noappend -no-progress -quiet > /dev/null
		openssl cms -sign -binary -nosmimecap -outform DER \
			-in "${_dir}/wrong-ca.squashfs" \
			-signer "${_dir}/wrong-ca.cert.pem" -inkey "${_dir}/wrong-ca.key.pem" \
			-out "${_dir}/wrong-ca.sig.der"
		# Self-check: the signature is well formed (verifies against its
		# own CA) and is NOT trusted by the image's development CA, so a
		# refusal on the target can only be about trust.
		openssl cms -verify -binary -inform DER -in "${_dir}/wrong-ca.sig.der" \
			-content "${_dir}/wrong-ca.squashfs" \
			-CAfile "${_dir}/wrong-ca.cert.pem" -out /dev/null 2> /dev/null
		if openssl cms -verify -binary -inform DER -in "${_dir}/wrong-ca.sig.der" \
			-content "${_dir}/wrong-ca.squashfs" \
			-CAfile "${MISE_CONFIG_ROOT}/meta-lamadist/files/rauc-dev/dev-ca.cert.pem" \
			-out /dev/null 2> /dev/null; then
			echo "ERROR: wrong-CA bundle verifies against the development CA" >&2
			return 1
		fi
		{
			cat "${_dir}/wrong-ca.squashfs" "${_dir}/wrong-ca.sig.der"
			python3 -c 'import struct, sys; sys.stdout.buffer.write(struct.pack(">Q", int(sys.argv[1])))' \
				"$(stat -c %s "${_dir}/wrong-ca.sig.der")"
		} > "${_bundle}"
		echo "==> Generated wrong-CA RAUC bundle (cached): ${_bundle}" >&2
	fi
	echo "${_bundle}"
}

# Effective CPU count for the build.  Inside a cgroup-namespaced
# container (CI pod, capped podman) cpu.max is the truth; nproc
# sees every node core because pod CPU limits are CFS quota, not
# an affinity mask.  On the host, before a local build starts, the
# PODMAN_RUN_CPUS cap the container will run under wins over nproc,
# the same way PODMAN_RUN_MEMORY does for memory.
_detect_cpus() {
	local _quota _period
	if [[ -r /sys/fs/cgroup/cpu.max ]]; then
		read -r _quota _period < /sys/fs/cgroup/cpu.max
		if [[ "$_quota" != "max" && -n "$_period" ]]; then
			echo $(((_quota + _period - 1) / _period))
			return
		fi
	fi
	if [[ "${PODMAN_RUN_CPUS:-}" =~ ^[0-9]+(\.[0-9]+)?$ ]]; then
		local _whole="${PODMAN_RUN_CPUS%%.*}"
		[[ "${PODMAN_RUN_CPUS}" == *.* ]] && _whole=$((_whole + 1))
		echo "${_whole}"
		return
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

# Memory plan for a tight envelope (< 24 GiB): bound the worst case
# of concurrent compiler processes by memory, not by CPUs.  BitBake
# has no global process cap and no shared make jobserver, so the
# number of compilers alive at once is the sum of -j over running
# build tasks.  The controls:
#
#   do_compile[number_threads]  at most SLOTS compiles at once,
#                               counted across all recipes;
#   PARALLEL_MAKE -j JOBS       per compile, JOBS <= CPUs + 2 and
#                               small enough that the tail takes at
#                               most a quarter of the envelope while
#                               a heavy task runs;
#   per-recipe -j caps          from .mise/lib/compile-peaks.tsv (the
#                               largest single process per recipe and
#                               build task, measured from buildstats):
#                               a recipe over the tail budget gets the
#                               -j that keeps it inside one slot;
#   heavy tasks                 rows of 1 GiB or more, plus any row
#                               that builds outside do_compile (rust
#                               in do_install, ptest), run one at a
#                               time: the lamadist-memory scheduler
#                               (meta-lamadist/lib/lamadist/sched.py)
#                               does not start a second one, and a
#                               shared lockfile backs it up.  Each is
#                               sized to the memory left beside the
#                               tail compiles it can run with.
#
# Invariant: RESERVE + tail compiles + HEAVY + HEADROOM <= memory.
# TAIL is the p90 per-job peak of the long tail (230 MiB).  RESERVE
# covers the BitBake server and its workers plus ~128 MiB per extra
# non-compile task; HEADROOM covers measured non-compile peaks that
# are not budgeted per task (do_unpack of gcc-source 1.4 GiB,
# do_configure of cmake-native 0.6 GiB).  The 2026-09-23 cold CI
# build that took a node down was sized from 12 CPUs: 12 tasks at
# make -j 14 in a 12 GiB pod, with 44 cc1plus alive at once.
# ICECC_PARALLEL_MAKE gets the same caps: the icecc class replaces
# PARALLEL_MAKE with it for every icecc recipe, including when icecc
# then falls back to compiling locally.  -l is left out: in a pod the
# load average is the node's.  All of these are hash-ignored.
_emit_memory_plan() {
	local _overlay="$1" _threads="$2" _mem_gb="$3"
	local _tail_mib=230 _slot_mib=4096 _heavy_min_mib=1024 _headroom_mib=1024
	local _table="${MISE_CONFIG_ROOT}/.mise/lib/compile-peaks.tsv"
	if [[ ! -r "${_table}" ]]; then
		echo "ERROR: ${_table} missing; cannot size build memory" >&2
		return 1
	fi
	# Slots come from the envelope alone, so more CPUs never mean fewer
	# compile slots; the per-thread reserve only shrinks the budgets.
	local _base_usable=$((_mem_gb * 1024 - 2048))
	local _slots=$((_base_usable / _slot_mib))
	((_slots >= 1)) || _slots=1
	((_slots <= _threads)) || _slots=$_threads
	local _extra_threads=$((_threads > 6 ? _threads - 6 : 0))
	local _usable=$((_base_usable - _extra_threads * 128))
	local _jobs=$((_threads + 2))
	local _tail_slots=$((_slots > 1 ? _slots - 1 : 1))
	local _jobs_cap=$((_usable / (4 * _tail_slots * _tail_mib)))
	((_jobs <= _jobs_cap)) || _jobs=$_jobs_cap
	((_jobs >= 2)) || _jobs=2
	# A heavy do_compile holds one compile slot, so it shares memory
	# with SLOTS - 1 tail compiles; a heavy task outside do_compile
	# (rust-native do_install, a ptest build) can run beside SLOTS.
	local _heavy_compile_mib=$((_usable - (_slots - 1) * _jobs * _tail_mib - _headroom_mib))
	local _heavy_other_mib=$((_usable - _slots * _jobs * _tail_mib - _headroom_mib))
	local _slot_budget=$((_jobs * _tail_mib))
	local _icecc_jobs="${LAMADIST_ICECC_JOBS:-${_jobs}}"
	((_icecc_jobs <= _jobs)) || _icecc_jobs=$_jobs
	echo "==> Memory plan: ${_mem_gb} GiB, ${_threads} threads: ${_slots}" \
		"compile slot(s) at -j ${_jobs}; heavy budget ${_heavy_compile_mib} MiB" \
		"in do_compile, ${_heavy_other_mib} MiB outside it" >&2

	# Recipe names can carry a literal ${TARGET_ARCH}; bash before 5.2
	# expands an associative subscript again inside arithmetic, so the
	# cap table is only ever read into a plain variable first.
	local -A _cap=()
	local _heavy_tasks=() _tasks=() _fields=()
	local _line _pn _task _peak _serial _j _budget _prev _rows=0
	while IFS= read -r _line || [[ -n "${_line}" ]]; do
		_line="${_line%$'\r'}"
		[[ "${_line}" =~ ^[[:space:]]*(#|$) ]] && continue
		IFS=$'\t' read -r -a _fields <<< "${_line}"
		_pn="${_fields[0]:-}" _task="${_fields[1]:-}"
		_peak="${_fields[2]:-}" _serial="${_fields[3]:-0}"
		if [[ -z "${_pn}" || -z "${_task}" || ! "${_peak}" =~ ^[0-9]+$ ]] || ((_peak == 0)); then
			echo "ERROR: ${_table}: bad row '${_line}'" >&2
			return 1
		fi
		_rows=$((_rows + 1))
		if ((_peak >= _heavy_min_mib)) || [[ "${_task}" != do_compile ]]; then
			_heavy_tasks+=("${_pn}:${_task}")
			[[ " ${_tasks[*]} " == *" ${_task} "* ]] || _tasks+=("${_task}")
			cat >> "$_overlay" <<- OVERLAY
				    LAMADIST_HEAVY_LOCK_${_task}:pn-${_pn} = '\${TMPDIR}/lamadist-heavy.lock'
			OVERLAY
			_budget=$_heavy_compile_mib
			[[ "${_task}" == do_compile ]] || _budget=$_heavy_other_mib
		else
			_budget=$_slot_budget
		fi
		# A serial peak is one process: -j does not lower it.
		[[ "${_serial}" == 1 ]] && continue
		_j=$((_budget / _peak))
		((_j >= 1)) || _j=1
		# PARALLEL_MAKE is per recipe, so the tightest row wins.
		_prev="${_cap[${_pn}]:-}"
		if [[ -z "${_prev}" ]] || ((_j < _prev)); then
			_cap[${_pn}]=$_j
		fi
	done < "${_table}"
	if ((_rows == 0)); then
		echo "ERROR: ${_table} has no rows; cannot size build memory" >&2
		return 1
	fi

	cat >> "$_overlay" <<- OVERLAY
		    PARALLEL_MAKE = '-j ${_jobs}'
		    ICECC_PARALLEL_MAKE = '-j ${_icecc_jobs}'
		    do_compile[number_threads] = '${_slots}'
		    # Brake on new task starts only, read from the node's PSI
		    # (neighbour pods count too); not part of the invariant.
		    BB_PRESSURE_MAX_MEMORY ?= '20000'
		    LAMADIST_HEAVY_TASKS = '${_heavy_tasks[*]}'
		    BB_SCHEDULERS = 'lamadist.sched.RunQueueSchedulerMemory'
		    BB_SCHEDULER = 'lamadist-memory'
	OVERLAY
	for _task in "${_tasks[@]}"; do
		cat >> "$_overlay" <<- OVERLAY
			    LAMADIST_HEAVY_LOCK_${_task} ?= ''
			    ${_task}[lockfiles] += '\${LAMADIST_HEAVY_LOCK_${_task}}'
		OVERLAY
	done
	for _pn in "${!_cap[@]}"; do
		_j="${_cap[${_pn}]}"
		((_j < _jobs)) || continue
		cat >> "$_overlay" <<- OVERLAY
			    PARALLEL_MAKE:pn-${_pn} = '-j ${_j}'
			    ICECC_PARALLEL_MAKE:pn-${_pn} = '-j ${_j}'
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
	# is an explicit task cap and wins over the detected CPUs.  Tasks
	# and parser processes follow it (BitBake's parser default is the
	# host's full CPU count, which in a pod is the node's).  In a
	# tight envelope (< 24 GiB) the memory plan sizes compile
	# concurrency; on a roomy host make jobs are N+2 with a
	# load-average brake at N+4 (-l guards CPU thrash only).
	local _cpus _mem_gb _threads
	_cpus=$(_detect_cpus)
	_mem_gb=$(_detect_mem_gb)
	_threads="${LAMADIST_MAX_LOCAL_JOBS:-${_cpus}}"
	cat >> "${_dynamic_overlay}" <<- OVERLAY
		    BB_NUMBER_THREADS = '${_threads}'
		    BB_NUMBER_PARSE_THREADS = '${_threads}'
	OVERLAY
	if ((_mem_gb < 24)); then
		_emit_memory_plan "${_dynamic_overlay}" "${_threads}" "${_mem_gb}"
	elif [[ -n "${LAMADIST_MAX_LOCAL_JOBS:-}" ]]; then
		cat >> "${_dynamic_overlay}" <<- OVERLAY
			    PARALLEL_MAKE = '-j ${LAMADIST_MAX_LOCAL_JOBS}'
		OVERLAY
	else
		cat >> "${_dynamic_overlay}" <<- OVERLAY
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
	# Host-local icecc fan-out cap (LAMADIST_ICECC_JOBS): overrides
	# the icecc overlay's weak -j40 default on roomy hosts.  Every
	# icecc job costs a local preprocessor pass (ICECC_REMOTE_CPP=0).
	# In a tight envelope the memory plan above already set it, no
	# higher than the local -j.  Hash-ignored; no sstate impact.
	if ((_mem_gb >= 24)) && [[ -n "${LAMADIST_ICECC_JOBS:-}" ]]; then
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

# aavmf_firmware ROLE
#
# Prints the first readable NON-EMPTY edk2 aarch64 firmware file for
# ROLE, one of code, vars, sb-code, or sb-vars, and fails when none
# exists.  Distros ship the same edk2 builds under different names and
# formats (raw .fd or qcow2), so the first usable candidate wins and a
# LAMADIST_AAVMF_* environment override takes precedence.  A candidate
# must be non-empty: some images carry a 0-byte placeholder that is
# readable but not a varstore, and virt-fw-vars faults on it.
#
# Secure Boot capable AAVMF is a separate artifact only where qemu's own
# edk2 build has SB compiled out: Gentoo ships it as qcow2 (the INSECURE
# suffix records that ArmVirt has no SMM to isolate the variable store,
# acceptable for a boot gate).  The Debian family and the qemu package's
# own edk2 aarch64 build carry SB in the default image, so the sb-* roles
# fall back to the plain firmware; the smoke's in-guest SecureBoot=1
# assertion is what proves SB actually engaged.
#
# An sb-vars template must be an INITIALIZED varstore: Debian and Ubuntu
# ship the blank AAVMF_VARS.fd as erased flash that virt-fw-vars cannot
# parse, so the pre-keyed snakeoil template is preferred ahead of it.
# Enrolment sets our PK and adds our KEK/db; the template's own throwaway
# test keys stay in the CI-only varstore, which the gate tolerates
# because it asserts only that our signed UKI is trusted and a tampered
# one is refused, never that our key is the sole entry in db.  Both the
# vm task and ovmf-vars resolve through here so the enrolled vars
# artifact and the drift guard that checks it always name the same
# template.
aavmf_firmware() {
	local _role="$1" _f
	local -a _candidates
	case "${_role}" in
		code)
			_candidates=("${LAMADIST_AAVMF_CODE:-}"
				/usr/share/qemu/edk2-aarch64-code.fd
				/usr/share/AAVMF/AAVMF_CODE.fd
				/usr/share/edk2/aarch64/QEMU_EFI-pflash.raw)
			;;
		vars)
			_candidates=("${LAMADIST_AAVMF_VARS:-}"
				/usr/share/qemu/edk2-arm-vars.fd
				/usr/share/AAVMF/AAVMF_VARS.fd
				/usr/share/edk2/aarch64/vars-template-pflash.raw)
			;;
		sb-code)
			_candidates=("${LAMADIST_AAVMF_SB_CODE:-}"
				/usr/share/edk2/ArmVirtQemu-AARCH64/QEMU_EFI.secboot_INSECURE.qcow2
				/usr/share/AAVMF/AAVMF_CODE.secboot.fd
				/usr/share/AAVMF/AAVMF_CODE.fd
				/usr/share/qemu/edk2-aarch64-code.fd
				/usr/share/edk2/aarch64/QEMU_EFI-pflash.raw)
			;;
		sb-vars)
			_candidates=("${LAMADIST_AAVMF_SB_VARS:-}"
				/usr/share/edk2/ArmVirtQemu-AARCH64/QEMU_VARS.secboot_INSECURE.qcow2
				/usr/share/AAVMF/AAVMF_VARS.secboot.fd
				/usr/share/AAVMF/AAVMF_VARS.snakeoil.fd
				/usr/share/AAVMF/AAVMF_VARS.fd
				/usr/share/qemu/edk2-arm-vars.fd
				/usr/share/edk2/aarch64/vars-template-pflash.raw)
			;;
		*)
			echo "aavmf_firmware: unknown role '${_role}'" >&2
			return 2
			;;
	esac
	for _f in "${_candidates[@]}"; do
		if [[ -n "${_f}" && -r "${_f}" && -s "${_f}" ]]; then
			echo "${_f}"
			return 0
		fi
	done
	return 1
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
	# Optional CPU cap (PODMAN_RUN_CPUS, e.g. 6 to reproduce a CI
	# pod's limit locally); _detect_cpus sizes the build to it.
	if [[ -n "${PODMAN_RUN_CPUS:-}" ]]; then
		_memory_args+=(--cpus "${PODMAN_RUN_CPUS}")
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
