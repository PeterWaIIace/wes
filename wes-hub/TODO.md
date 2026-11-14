# TODO — wes-hub

Known gaps and next steps. Items marked *(wes-upstream)* would be cleaner as
changes in the `wes` library itself once it becomes a PyPI package — until then
`wes` stays untouched and the workarounds live in `weshub`.

## Core gaps (short term)

- [ ] **Cancel/retry jobs**: no `scancel` support yet (API + UI button).
      Needs an ssh call `scancel <job_id>` in the manager + job state refresh.
- [ ] **Rediscovery after server restart**: in-memory `Job` objects are lost on
      restart; unfinished jobs are only re-adopted when the discovery scan finds
      their `*_config.json` again. Should reconstruct job state from the store
      immediately on startup.
- [ ] **sacct fallback for finished jobs**: `JobsQuery.get()` is squeue-only;
      finished jobs vanish from the cluster view. Use `JobsQuery.get_recent()`
      in the monitor to fill in final slurm metadata.
- [ ] **Live logs**: only a "results pulled" indicator exists. Stream
      `job_output.txt` / `job_error.txt` into the run detail view (via the
      `*_config.json` job dir) once we can `cat`/tail them over ssh.
- [ ] **Concurrent auth session per ssh config**: all ssh traffic goes through
      the user's `~/.ssh` config; no credential management, no multi-user auth.
- [ ] **Race prevention for cron dispatch**: a dispatch thread is spawned per
      trigger; add a per-pipeline lock so cron cannot overlap runs of a
      still-running pipeline (max-in-flight option).
- [ ] **Artifacts browser**: `/results` is a raw static mount; make a browsable
      artifact tree per job (list artifacts known from the task spec).
- [ ] **Pagination + filters** on `/api/runs` and `/api/jobs` (currently capped).
- [ ] **Graceful handling of unreachable clusters**: ssh failures are printed
      to stdout; surface them in the UI (cluster status = offline + last error).

## Frontend

- [ ] Edit/delete pipeline from the UI (API already supports PATCH/DELETE).
- [ ] Edit assets from the UI (API supports POST assets; no UI form yet).
- [ ] YAML editor with validation feedback and .wes field docs.
- [ ] Run detail: step timeline (submitted → clone → pre → sbatch → running →
      finished) instead of the current flat job card; per-step log framing.
- [ ] Websocket/SSE push instead of the 4 s poll loop.
- [ ] Graph/history view per pipeline (success rate, durations, like Actions).

## Scheduling

- [ ] Timezone support for cron (currently local server time).
- [ ] More cron features (names, `L`, `W`, seconds) — or switch to `croniter`.
- [ ] Per-pipeline max parallelism & backpressure.
- [ ] Trigger rules: run only if branch/repo changed (poll GitHub API), manual
      approval gates.

## Packaging / operations

- [ ] Publish `wes` to PyPI first *(wes-upstream)*, then `wes-hub` can depend
      on it by version instead of a local path.
- [ ] Better upstream server hooks in wes *(wes-upstream)*:
      - `Engine.start_jobs` currently re-executes every registered job on each
        dispatch — wes-hub works around it by orchestrating `WESParser` +
        `Job` directly; a `dispatch(task_file)` that only touches new jobs and
        a queryable job registry would remove the workaround.
      - expose `wes.status` / JobStatus access without constructing `Job`s.
      - `Job.__init__` ignores its `namespace` argument and always generates a
        fresh identity — `JobScanner.scan()` therefore cannot reconstruct the
        job it found; wes-hub discovery works around it with a lightweight
        `DiscoveredJob` built from the `*_config.json`.
      - uploaded job/pre scripts are staged through a temp dir and lose the
        executable bit (mode 644) before `scp`, so `./pre.sh` fails with
        permission denied on strict clusters; mock runs `chmod 755` on `.sh`
        uploads to emulate a lenient cluster setup.
      - `SshRunner` subprocess calls have no timeout — wes-hub bounds them
        itself (`settings.ssh_timeout`), wes should pass `timeout=` natively.
- [x] `wes_status.sh` exit trap is invoked through an absolute path — a job
      script that `cd`s elsewhere still writes its final status. Array jobs
      now run in `tasks/<SLURM_ARRAY_TASK_ID>/` with a `wes.status` per element.
- [ ] Docker image + docker-compose example.
- [ ] Auth for the hub API/UI (even a simple token).
- [ ] Secrets: `.env`-style git credentials today; need a per-pipeline secret
      store (git tokens for private repos on the cluster).
- [ ] Retention policy for old runs/artifacts + cleanup jobs.
- [ ] Integration tests against a real (containerized) SLURM; current tests
      fake ssh via patching.
- [ ] Logging: replace prints with `logging` + log endpoint for the UI.
