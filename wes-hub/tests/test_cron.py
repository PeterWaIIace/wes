from __future__ import annotations

from datetime import datetime

import pytest

from weshub.cron import Cron, CronError


def test_cron_basic_match():
    c = Cron("30 4 * * *")
    assert c.matches(datetime(2026, 1, 15, 4, 30))
    assert not c.matches(datetime(2026, 1, 15, 4, 31))
    assert not c.matches(datetime(2026, 1, 15, 5, 30))


def test_cron_step_and_list():
    c = Cron("*/15 * * * *")
    assert c.matches(datetime(2026, 1, 1, 0, 45))
    assert not c.matches(datetime(2026, 1, 1, 0, 44))
    c2 = Cron("0 9,17 * * 1-5")
    assert c2.matches(datetime(2026, 1, 5, 9, 0))  # monday
    assert not c2.matches(datetime(2026, 1, 10, 9, 0))  # saturday


def test_cron_next_run():
    c = Cron("0 4 * * *")
    after = datetime(2026, 1, 15, 5, 0)
    nxt = c.next_run(after)
    assert (nxt.day, nxt.hour, nxt.minute) == (16, 4, 0)


def test_cron_invalid():
    with pytest.raises(CronError):
        Cron("not a cron")
    with pytest.raises(CronError):
        Cron("* * * *")
    with pytest.raises(CronError):
        Cron("*/0 * * * *")
