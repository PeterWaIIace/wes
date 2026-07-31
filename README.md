# WES

WES runs tasks described in a `.wes` YAML file: it clones a git repo, executes commands on an HPC cluster, and syncs results back.

## Installation

Requires Python 3.10+.

```bash
pip install -e ".[dev]"
```

## How to run

### CLI (launch tasks from a config)

```bash
wes launch task.wes
```

### Web interface

```bash
wes serve
```

Opens at `http://127.0.0.1:8000`.

### Sync job status

```bash
wes sync --ssh hpc
```

Or use the Makefile targets:

```bash
make run     # launch task.wes
make serve   # start web interface
make test    # run tests
make check   # lint + format check + tests
```

### Git credentials (optional)

For HTTPS repos that need auth, copy the env file and add your credentials:

```bash
cp .env.example .env
```

Use a personal access token, not your password.

## Config format

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

### Fields

- **git_url** — git repository to clone
- **branch** — branch to check out (optional)
- **ssh** — SSH config name of the cluster to run on
- **pre** — script run before the job
- **job** — command or script to execute
- **artifacts** — folders to sync back after the job
- **cpus / gpus / memory / nodelist** — requested resources

See `task.wes` for a working example.

## Commands

```bash
wes launch <config.wes>   # run tasks once and exit
wes sync --ssh <name>     # continuously sync job status
wes serve [--port N]      # web interface
```
