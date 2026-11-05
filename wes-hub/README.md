# wes-hub

Scheduling server and web UI for WES (WUT Experiment Scheduler).
The `wes` library lives one directory up ([../wes](../wes)) and is used strictly
as a library - the `wes` package is never modified.

```
┌────────────┐   REST/SSE    ┌───────────────────────────────────────────┐
│  browser   │◄─────────────►│  wes-hub server                           │
│ (Actions-  │                │  ┌───────────┐ ┌──────────┐ ┌─────────┐ │     ssh      ┌─────────┐
│  like UI)  │                │  │ scheduler │►│ manager  │││ store   │ │◄────────────►│ cluster │
└────────────┘                │  └───────────┘ └────┬─────┘ └─────────┘ │              │ (SLURM) │
                              │                     │  ┌─────────────┐  │              └─────────┘
                              │  mounts /results ◄──┘  │ monitor     │  │   git clone / sbatch /
                              └──────────────────────────└─────────────┘──┘   wes.status protocol
```

## What it does

- **Pipelines**: a pipeline is a `.wes` YAML file (the WES task format) plus
  any script assets it references (`job.sh`, `pre.sh`, ...), stored server-side.
- **Scheduling**: each pipeline can carry a cron expression; due pipelines are
  dispatched automatically (`manual` dispatch also available from the UI/API).
- **Job discovery**: scans `*_config.json` on the cluster (same protocol the
  `wes` CLI uses) and adopts jobs it did not dispatch itself.
- **Status**: follows the `wes.status` protocol written by the job scripts on
  the server; no extra per-job logic on the cluster.
- **Results**: when a job reaches a finished state, artifacts and logs are
  pulled automatically under `<data-dir>/results/` and browsable at `/results`.
- **Cluster view**: squeue jobs, node info and capacity (WesObserver).

## Install (dev)

```bash
cd wes-hub            # inside the wes repo
uv sync --extra dev   # [tool.uv.sources] resolves the wes dep from ../
```

## Run

```bash
uv run wes-hub serve --host 127.0.0.1 --port 8420 --data-dir ./data
```

UI at http://127.0.0.1:8420/ - API docs at http://127.0.0.1:8420/docs

Note: WES resolves script paths and the `results/` prefix against the process
working directory, so `wes-hub serve` changes into the data dir at startup.

## Mock cluster (no ssh / no SLURM)

```bash
uv run wes-hub serve --mock
```

`--mock` swaps the wes `SshRunner` for a sandbox runner at runtime: all
ssh/scp/rsync traffic runs inside `<data-dir>/mock/cluster`, and the SLURM
tools (`sbatch`, `squeue`, `sacct`, `sinfo`, `scontrol`, `scancel`) are
python stand-ins in `weshub/mock/bin`. `sbatch` really executes the job in
the background and the job scripts keep writing `wes.status`, so the whole
protocol - dispatch, discovery, status, artifact download - works.

On first start with `--mock` a `mock-demo` pipeline is seeded (it clones a
local git repo from `<data-dir>/mock/repos/example-repo`). Dispatch it:

```bash
curl -X POST localhost:8420/api/pipelines/1/dispatch
```

and watch the run go queued -> running -> success in the UI; afterwards the
artifacts are downloadable under http://localhost:8420/results/.

Gotchas the mock surfaced (also apply to real pipelines, see TODO.md):

- job scripts must not `cd` into the cloned repo, or the injected
  `./wes_status.sh` exit trap breaks and the job stays RUNNING forever;
- `pre.sh`/`job.sh` assets must be executable (`hub.write_assets` chmods
  pipeline scripts, but wes also uploads staged copies without the bit).

## API overview

| Endpoint | Description |
|---|---|
| `POST /api/pipelines` | create pipeline (name, `wes_yaml`, `cron`, `ssh`, assets inline) |
| `GET/PATCH/DELETE /api/pipelines[/{id}]` | manage pipelines |
| `POST /api/pipelines/{id}/dispatch` | trigger a run now |
| `GET /api/runs` / `GET /api/runs/{id}` | runs with job states |
| `GET /api/jobs` | every known job (dispatched + discovered) |
| `POST /api/jobs/{namespace}/pull` | pull artifacts/logs on demand |
| `GET /api/clusters` | nodes, capacity, squeue snapshot |
| `GET /api/state` | combined snapshot (used by the UI poll loop) |
| `/results/*` | downloaded artifacts (static) |

## Example

```bash
curl -X POST localhost:8420/api/pipelines -H 'content-type: application/json' -d @examples/create-pipeline.json
curl -X POST localhost:8420/api/pipelines/1/dispatch
```

See `examples/` and `TODO.md` for the roadmap.
