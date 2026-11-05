from __future__ import annotations

import re
from collections.abc import Callable

# minimal 5-field cron: m h dom mon dow  (supports * , - / )
_FIELDS = [("minute", 0, 59), ("hour", 0, 23), ("day", 1, 31), ("month", 1, 12), ("weekday", 0, 6)]


class CronError(Exception):
    """Raised when a cron expression is invalid."""


def _parse_field(expr: str, lo: int, hi: int) -> Callable[[int], bool]:
    def match_one(value: int) -> bool:
        return lo <= value <= hi

    expr = expr.strip()
    if expr == "*":
        return lambda v: True

    parts = []
    for chunk in expr.split(","):
        chunk = chunk.strip()
        if not chunk:
            raise CronError(f"empty cron field: {expr!r}")
        step = 1
        if "/" in chunk:
            chunk, _, step_s = chunk.partition("/")
            if not step_s.isdigit() or int(step_s) == 0:
                raise CronError(f"invalid step in cron field: {expr!r}")
            step = int(step_s)
        if chunk == "*":
            rng = list(range(lo, hi + 1, step))
        elif "-" in chunk:
            a, _, b = chunk.partition("-")
            if not (a.isdigit() and b.isdigit()):
                raise CronError(f"invalid range in cron field: {expr!r}")
            rng = list(range(int(a), int(b) + 1))
        elif chunk.isdigit():
            rng = [int(chunk)]
        else:
            raise CronError(f"invalid cron field: {expr!r}")
        parts += [v for v in rng if lo <= v <= hi]
    allowed = set(parts)
    return lambda v: v in allowed


class Cron:
    """A tiny, dependency-free 5-field cron matcher (minute granularity)."""

    def __init__(self, expression: str):
        fields = expression.split()
        if len(fields) != 5:
            raise CronError(f"cron must have 5 fields (m h dom mon dow), got: {expression!r}")
        self.expression = expression
        self._matchers = []
        for (name, lo, hi), raw in zip(_FIELDS, fields, strict=True):
            try:
                self._matchers.append(_parse_field(raw, lo, hi))
            except CronError as e:
                raise CronError(f"{name}: {e}") from e

    def __str__(self) -> str:
        return self.expression

    def matches(self, dt) -> bool:
        values = (dt.minute, dt.hour, dt.day, dt.month, (dt.weekday() + 1) % 7)
        return all(m(v) for m, v in zip(self._matchers, values, strict=True))

    def next_run(self, after):
        # scan forward minute by minute, capped at ~2 years of minutes
        dt = after.replace(second=0, microsecond=0)
        for _ in range(60 * 24 * 366 * 2):
            dt = _next_minute(dt)
            if self.matches(dt):
                return dt
        raise CronError("no upcoming run within 2 years")


def _next_minute(dt):
    import datetime as _dt

    return dt + _dt.timedelta(minutes=1)


_CRON_RE = re.compile(r"^\s*[\d*/,-]+\s+[\d*/,-]+\s+[\d*/,-]+\s+[\d*/,-]+\s+[\d*/,-]+\s*$")


def is_cron(expression: str) -> bool:
    return bool(_CRON_RE.match(expression or ""))
