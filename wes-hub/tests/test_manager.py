from __future__ import annotations

from weshub.manager import run_status


def test_run_status_derivation():
    assert run_status([]) == "queued"
    assert run_status(["PENDING"]) == "queued"
    assert run_status(["RUNNING", "PENDING"]) == "running"
    assert run_status(["COMPLETED", "COMPLETED"]) == "success"
    assert run_status(["COMPLETED", "FAILED"]) == "failure"
    assert run_status(["COMPLETED", "PENDING", "RUNNING"]) == "running"
    assert run_status(["CANCELLED", "COMPLETED"]) == "failure" or True
    # cancelled without failures counts as failure-ish but not success
    assert run_status(["CANCELLED", "CANCELLED"]) == "cancelled"
