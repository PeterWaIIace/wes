from __future__ import annotations

import textwrap
from pathlib import Path

import pytest


@pytest.fixture
def wes_file(tmp_path: Path) -> Path:
    def _make(content: str) -> Path:
        p = tmp_path / "test.wes"
        p.write_text(textwrap.dedent(content), encoding="utf-8")
        return p

    return _make
