from types import SimpleNamespace
from unittest.mock import MagicMock
import time

import pytest

from wes.jobs.job import TransferResult
from wes.tasks import Task
from weshub.config import Settings
from weshub.discovery import find_status_dirs
from weshub.manager import DiscoveredJob, Hub, JobRecord, run_status
from weshub.store import Store


def test_active_jobs_prevent_early_run_completion():
    assert run_status(['FAILED', 'RUNNING']) == 'RUNNING'
    assert run_status(['FAILED', 'PENDING']) == 'PENDING'
    assert run_status(['FAILED', 'COMPLETED']) == 'FAILED'


def test_failed_scan_is_not_an_empty_scan():
    runner = MagicMock()
    runner.run_command.return_value = (False, [])
    with pytest.raises(RuntimeError):
        find_status_dirs(runner, '.')


def test_failed_discovery_never_prunes_cached_jobs(tmp_path, monkeypatch):
    hub = Hub(Settings(data_dir=tmp_path))
    runner = MagicMock()
    runner.run_command.return_value = (False, [])
    scanner = MagicMock(return_value=SimpleNamespace(runner=runner))
    monkeypatch.setattr('weshub.manager.JobScanner', scanner)
    prune = MagicMock()
    monkeypatch.setattr(hub, '_prune_unseen', prune)
    hub.store.upsert_job('existing', ssh='hpc', state='COMPLETED')

    assert hub.discover('hpc') == []
    prune.assert_not_called()
    assert hub.store.get_job('existing') is not None
    hub.stop()


def test_failed_transfer_does_not_mark_artifacts_pulled(tmp_path):
    hub = Hub(Settings(data_dir=tmp_path))
    item = SimpleNamespace(r_path='job', r_name='results', sync=MagicMock(
        return_value=TransferResult('failed', error='rsync failed')))
    job = SimpleNamespace(namespace='ns', job_name='job', artifacts=[item], status_files=[])
    record = JobRecord(job, None, None, True)
    record.pulled = True
    hub.store.upsert_job('ns', artifacts_pulled=1)

    hub._pull_results(record)

    row = hub.store.get_job('ns')
    assert not record.pulled
    assert row['artifacts_pulled'] == 0
    assert row['transfer_state'] == 'failed'
    assert 'rsync failed' in row['transfer_error']
    hub.stop()


def test_missing_artifact_is_reported_separately(tmp_path):
    hub = Hub(Settings(data_dir=tmp_path))
    item = SimpleNamespace(r_path='job', r_name='results', sync=MagicMock(
        return_value=TransferResult('missing')))
    job = SimpleNamespace(namespace='ns', job_name='job', artifacts=[item], status_files=[])
    record = JobRecord(job, None, None, True)
    hub.store.upsert_job('ns')
    hub._pull_results(record)
    assert hub.store.get_job('ns')['transfer_state'] == 'partial'
    hub.stop()


def slow_operation():
    time.sleep(0.2)


def test_timeout_returns_without_waiting_for_worker(tmp_path):
    hub = Hub(Settings(data_dir=tmp_path))
    started = time.monotonic()
    assert hub._bounded(slow_operation, timeout=0.01) is None
    assert time.monotonic() - started < 0.15
    hub.stop()


def test_restart_restores_job_paths_patterns_and_run_links(tmp_path):
    hub = Hub(Settings(data_dir=tmp_path))
    pipeline = hub.store.add_pipeline('sweep', 'sequence: {}', 'hpc', '', True)
    run = hub.store.add_run(pipeline['id'], 'manual')
    task = Task(name='sweep', git_url='', ssh_config='hpc', artifacts=['results'],
                progress_artifacts=['results/**/chart.png'])
    job = DiscoveredJob(task, 'hpc', 'ns_array_2', 'job', 'sweep/ns/tasks/2')
    hub._register(job, JobRecord(job, run['id'], pipeline['id'], True))
    hub.stop()

    restored = Hub(Settings(data_dir=tmp_path))

    record = restored.registry['ns_array_2']
    assert record.run_id == run['id']
    assert record.job.job_dir == 'sweep/ns/tasks/2'
    assert record.job.task.progress_artifacts == ['results/**/chart.png']
    assert restored.store.add_run(pipeline['id'], 'manual')['id'] > run['id']
    restored.stop()


def test_store_preserves_deleted_id_high_water_marks(tmp_path):
    path = tmp_path / 'state.json'
    store = Store(path)
    first = store.add_pipeline('one', '', '', '', True)
    store.delete_pipeline(first['id'])
    restored = Store(path)
    assert restored.add_pipeline('two', '', '', '', True)['id'] > first['id']
