STATUS_FILENAME = "wes.status"
STATUS_HELPER_NAME = "wes_status.sh"

# Uploaded into every remote job dir by StatusFile.write_helper(). The job's
# injected job script calls it to
# create/update wes.status in their working directory. For array tasks the
# injected job script cd's into tasks/<index>/ first, so each array element
# gets its own wes.status next to its work.
STATUS_HELPER_SCRIPT = """#!/bin/bash
# wes_status.sh STATE [MESSAGE]
# Create or update wes.status (YAML) in the current directory (atomic replace).
# task/namespace/job_name/ssh are read from *_config.json the first time the
# file is created; SLURM_* variables fill job_id/node/partition when present.
# WES_STATUS_CONFIG_DIR points at the job dir when cwd is a task subdir.
set -u

state="${1:-PENDING}"
message="${2:-}"
status="wes.status"
tmp="${status}.tmp"
cfg_dir="${WES_STATUS_CONFIG_DIR:-.}"
cfg="$(ls "$cfg_dir"/*_config.json 2>/dev/null | head -n 1)"
status_fields='state|updated|job_id|parent_namespace|array_index|node|partition|message'

json_get() {
    awk -F'"' -v k="$2" '$2 == k { print $4; exit }' "$1" 2>/dev/null
}

yaml_kv() {
    # yaml_kv KEY VALUE - print one flat mapping entry, value double-quoted
    # with \\ and " escaped and newlines/tabs folded to spaces
    local v=${2//\\/\\\\}
    v=${v//\\"/\\\"}
    v=${v//$'\\n'/ }
    v=${v//$'\\r'/ }
    v=${v//$'\\t'/ }
    printf '%s: "%s"\\n' "$1" "$v"
}

{
    if [ -f "$status" ]; then
        grep -vE "^($status_fields)[:=]" "$status" || true
    else
        if [ -n "$cfg" ]; then
            yaml_kv task "$(json_get "$cfg" name)"
            if [ -n "${SLURM_ARRAY_TASK_ID:-}" ]; then
                yaml_kv namespace "$(json_get "$cfg" namespace)_array_${SLURM_ARRAY_TASK_ID}"
                yaml_kv job_name "$(json_get "$cfg" job_name)_array_${SLURM_ARRAY_TASK_ID}"
            else
                yaml_kv namespace "$(json_get "$cfg" namespace)"
                yaml_kv job_name "$(json_get "$cfg" job_name)"
            fi
            yaml_kv ssh "$(json_get "$cfg" ssh_config)"
            yaml_kv wes_file "$(json_get "$cfg" wes_file)"
        fi
    fi
    yaml_kv state "$state"
    yaml_kv updated "$(date '+%Y-%m-%d %H:%M:%S')"
    if [ -n "${SLURM_JOB_ID:-}" ]; then yaml_kv job_id "$SLURM_JOB_ID"; fi
    if [ -n "${SLURM_ARRAY_TASK_ID:-}" ]; then
        yaml_kv parent_namespace "$(json_get "$cfg" namespace)"
        yaml_kv array_index "$SLURM_ARRAY_TASK_ID"
    fi
    if [ -n "${SLURM_NODELIST:-}" ]; then yaml_kv node "$SLURM_NODELIST"; fi
    if [ -n "${SLURM_JOB_PARTITION:-}" ]; then yaml_kv partition "$SLURM_JOB_PARTITION"; fi
    if [ -n "$message" ]; then yaml_kv message "$message"; fi
} > "$tmp" && mv "$tmp" "$status"
"""

# Injected into the job script by inject_job_status() before it is scp'd to
# the server: report RUNNING when the SLURM job starts and COMPLETED/FAILED
# via an EXIT trap when it finishes.
#
# Array jobs get one work dir per element (tasks/<SLURM_ARRAY_TASK_ID>/) and
# the snippet cd's into it before the job body runs. The status helper always
# runs there, so every element owns a wes.status even if the job later cd's
# elsewhere or changes the working directory.
JOB_STATUS_SNIPPET = """\
# --- wes status: injected by wes; this job creates and updates wes.status ---
wes_script_dir="${SLURM_SUBMIT_DIR:-$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)}"
export WES_STATUS_CONFIG_DIR="$wes_script_dir"
if [ -n "${SLURM_ARRAY_TASK_ID:-}" ]; then
    wes_status_dir="$wes_script_dir/tasks/$SLURM_ARRAY_TASK_ID"
    mkdir -p "$wes_status_dir" || exit 1
    cd "$wes_status_dir" || exit 1
else
    wes_status_dir="$wes_script_dir"
fi
wes_status() {
    (cd "$wes_status_dir" && "$wes_script_dir/wes_status.sh" "$@")
}
wes_status RUNNING "job started"
wes_on_exit() {
    rc=$?
    if [ "$rc" -eq 0 ]; then
        wes_status COMPLETED "exit code 0"
    else
        wes_status FAILED "exit code $rc"
    fi
}
trap wes_on_exit EXIT
"""

# Injected into the pre script by inject_pre_status(): create wes.status
# before the job is submitted.
PRE_STATUS_SNIPPET = """\
# --- wes status: injected by wes; create the status file before the job runs ---
./wes_status.sh PENDING "pre-script"
"""
