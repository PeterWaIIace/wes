from __future__ import annotations

import pytest

from src.states import State


def test_state_values() -> None:
    assert State.PENDING.value == "PENDING"
    assert State.RUNNING.value == "RUNNING"
    assert State.COMPLETED.value == "COMPLETED"
    assert State.FAILED.value == "FAILED"
    assert State.CANCELLED.value == "CANCELLED"


def test_state_from_string() -> None:
    assert State("PENDING") is State.PENDING
    assert State("RUNNING") is State.RUNNING
    assert State("COMPLETED") is State.COMPLETED
    assert State("FAILED") is State.FAILED


def test_state_invalid() -> None:
    with pytest.raises(ValueError):
        State("INVALID")


def test_state_is_str() -> None:
    assert isinstance(State.PENDING, str)
    assert State.PENDING == "PENDING"
