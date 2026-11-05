STATUS_FILENAME = "wes.status"
STATUS_HELPER_NAME = "wes_status.sh"

# Uploaded into every remote job dir by StatusFile.write_helper(). The job's
# own shell scripts (pre.sh before submit, job.sh as the SLURM job) call it to
# create/update wes.status in their working directory, which is the job dir.
STATUS_HELPER_SCRIPT = """#!/bin/bash
# wes_status.sh STATE [MESSAGE]
# Create or update wes.status in the current directory (atomic replace).
# task/namespace/job_name/ssh are read from *_config.json the first time the
# file is created; SLURM_* variables fill job_id/node/partition when present.
set -u

status="wes.status"
state="${1:-PENDING}"
message="${2:-}"
tmp="${status}.tmp"

json_get() {
    awk -F'"' -v k="$2" '$2 == k { print $4; exit }' "$1" 2>/dev/null
}

{
    if [ -f "$status" ]; then
        grep -vE '^(state|updated|job_id|node|partition|message)=' "$status" || true
    else
        cfg="$(ls ./*_config.json 2>/dev/null | head -n 1)"
        if [ -n "$cfg" ]; then
            echo "task=$(json_get "$cfg" name)"
            echo "namespace=$(json_get "$cfg" namespace)"
            echo "job_name=$(json_get "$cfg" job_name)"
            echo "ssh=$(json_get "$cfg" ssh_config)"
            echo "wes_file=$(json_get "$cfg" wes_file)"
        fi
    fi
    echo "state=${state}"
    echo "updated=$(date '+%Y-%m-%d %H:%M:%S')"
    if [ -n "${SLURM_JOB_ID:-}" ]; then echo "job_id=${SLURM_JOB_ID}"; fi
    if [ -n "${SLURM_NODELIST:-}" ]; then echo "node=${SLURM_NODELIST}"; fi
    if [ -n "${SLURM_JOB_PARTITION:-}" ]; then echo "partition=${SLURM_JOB_PARTITION}"; fi
    if [ -n "$message" ]; then echo "message=${message}"; fi
} > "$tmp" && mv "$tmp" "$status"
"""

# Injected into the job script by inject_job_status() before it is scp'd to
# the server: report RUNNING when the SLURM job starts and COMPLETED/FAILED
# via an EXIT trap when it finishes.
JOB_STATUS_SNIPPET = """\
# --- wes status: injected by wes; pre.sh creates wes.status, this job updates it ---
./wes_status.sh RUNNING "job started"
wes_on_exit() {
    rc=$?
    if [ "$rc" -eq 0 ]; then
        ./wes_status.sh COMPLETED "exit code 0"
    else
        ./wes_status.sh FAILED "exit code $rc"
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
