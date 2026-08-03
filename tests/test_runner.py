from __future__ import annotations

from unittest.mock import patch

from wes.remote.runner import SshRunner


class _FakeResult:
    def __init__(self, returncode: int, stdout: str = "", stderr: str = "") -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def test_run_command_no_retry_by_default() -> None:
    with patch("wes.remote.runner.subprocess.run") as mock_run:
        mock_run.side_effect = [_FakeResult(1, stderr="boom")]
        runner = SshRunner("host")
        ok, lines = runner.run_command("cmd")
    assert ok is False
    assert lines == []
    assert mock_run.call_count == 1


def test_run_command_retries_then_succeeds() -> None:
    with patch("wes.remote.runner.subprocess.run") as mock_run:
        mock_run.side_effect = [
            _FakeResult(1, stderr="Socket timed out"),
            _FakeResult(1, stderr="Socket timed out"),
            _FakeResult(0, stdout="12345\n"),
        ]
        runner = SshRunner("host")
        ok, lines = runner.run_command("squeue -o 'x'", retries=2, retry_delay=0)
    assert ok is True
    assert lines == ["12345"]
    assert mock_run.call_count == 3


def test_run_command_gives_up_after_retries() -> None:
    with patch("wes.remote.runner.subprocess.run") as mock_run:
        mock_run.side_effect = [_FakeResult(1, stderr="timeout")] * 4
        runner = SshRunner("host")
        ok, lines = runner.run_command("cmd", retries=3, retry_delay=0)
    assert ok is False
    assert lines == []
    assert mock_run.call_count == 4
