#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
#
# Shared functions for mise tasks that run commands inside the builder container.
# Source this file from any task that needs to invoke the build container:
#   source "${LAMADIST_PROJECT_DIR}/.mise/tasks/_lib.sh"

# Resolve the Yocto MACHINE name from a LamaDist BSP name.
# Reads the machine: field from the BSP's KAS YAML file.
bsp_to_machine() {
    local bsp="$1"
    local kas_bsp="${LAMADIST_PROJECT_DIR}/kas/bsp/${bsp}.kas.yml"
    if [[ -f "${kas_bsp}" ]]; then
        grep '^machine:' "${kas_bsp}" | head -1 | awk '{print $2}'
    else
        echo "${bsp}"
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
    local interactive="-it"
    local entrypoint_args=()
    local cmd=()

    # Parse options
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --no-tty)
                interactive=""
                shift
                ;;
            --entrypoint)
                entrypoint_args=(--entrypoint "$2")
                shift 2
                ;;
            --)
                shift
                cmd=("$@")
                break
                ;;
            *)
                cmd=("$@")
                break
                ;;
        esac
    done

    # User namespace arguments (Podman-specific)
    local userns_args=()
    if [[ "${LAMADIST_CONTAINER_CMD}" == "podman" ]]; then
        userns_args=(--userns=keep-id --group-add keep-groups)
    fi

    # Optional local env file
    local env_local_args=()
    if [[ -f "${LAMADIST_PROJECT_DIR}/.kas.env.local" ]]; then
        env_local_args=(--env-file "${LAMADIST_PROJECT_DIR}/.kas.env.local")
    fi

    # Build and deploy directory mounts
    mkdir -p "${LAMADIST_HOST_BUILD_DIR}" "${LAMADIST_HOST_DEPLOY_DIR}"

    mkdir -p "${LAMADIST_HOST_SSTATE_DIR}"

    # shellcheck disable=SC2086
    ${LAMADIST_CONTAINER_CMD} run --rm ${interactive} \
        --privileged \
        "${userns_args[@]}" \
        -v "${LAMADIST_HOST_SSTATE_DIR}:${SSTATE_DIR}" \
        -e "SSTATE_DIR=${SSTATE_DIR}" \
        -v "${LAMADIST_PROJECT_DIR}:${KAS_WORK_DIR}" \
        -e "KAS_WORK_DIR=${KAS_WORK_DIR}" \
        -v "${LAMADIST_HOST_BUILD_DIR}:${KAS_WORK_DIR}/build" \
        -v "${LAMADIST_HOST_DEPLOY_DIR}:${KAS_WORK_DIR}/deploy" \
        --env-file "${LAMADIST_PROJECT_DIR}/.kas.env" \
        "${env_local_args[@]}" \
        "${entrypoint_args[@]}" \
        "${LAMADIST_CONTAINER_IMAGE}" \
        "${cmd[@]}"
}
