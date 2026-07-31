# WES

WES clones a git repo from a `.wes` YAML file, runs commands on an HPC cluster, and syncs results back.

## Install

```bash
pip install -e ".[dev]"
```

## Run

```bash
wes launch task.wes     # run tasks from a config
wes serve               # web interface at http://127.0.0.1:8000
wes sync --ssh hpc      # continuously sync job status
```

Or via Makefile: `make run`, `make serve`, `make test`, `make check`.

## Config

A `.wes` file is YAML. Each task clones a repo and runs a job:

```yaml
sequence:
  - my_task:
      git_url: ssh://git@host/user/repo.git
      branch: main
      ssh: hpc
      pre: scripts/pre.sh
      job: scripts/job.sh
      artifacts:
        - results
      cpus: "4"
      gpus: "1"
      memory: 16G
```

See `task.wes` for a working example.

Optional git credentials go in a `.env` file (see `.env.example`).
