"""Pick the time in the week ahead that is actually worth going down for.

The week report shows everything; this narrows it to an answer.  A candidate is
a run of consecutive blocks inside your preferred window, long enough for a
swim, open, and with enough free lanes the whole way through.  They are ranked
on the lanes you are guaranteed, then on how much of the session lands in the
hour you really want, then on which half of the pool it is.

What counts as preferred lives in preferences.toml -- see `config`.
"""

from __future__ import annotations

import datetime as dt
import math
from dataclasses import dataclass, replace
from itertools import pairwise

from .config import Preferences, preferences
from .hours import is_open
from .model import SLOT_MINUTES, PoolDay, Slot, _h

# One guaranteed free lane beats any amount of everything else; landing on the
# ideal hour is worth a bit less than a lane; the right half of the pool, less
# again.  Tuned so the ranking reads the way you would argue it out loud.
LANE_WEIGHT = 10.0
IDEAL_WEIGHT = 8.0
END_WEIGHT = 4.0


@dataclass(frozen=True, slots=True)
class Suggestion:
    """A swim worth turning up for."""

    date: dt.date
    end: str
    calendar_name: str
    start: dt.time
    stop: dt.time
    lanes_low: int
    lanes_high: int
    lanes_total: int
    score: float

    def time_range(self) -> str:
        return f"{_h(self.start)}-{_h(self.stop)}"

    def lanes(self) -> str:
        if self.lanes_low == self.lanes_high:
            return f"{self.lanes_low} lanes free"
        return f"{self.lanes_low}-{self.lanes_high} lanes free"

    def describe(self) -> str:
        return (
            f"{self.date:%A %-d %B}, {self.time_range()}, "
            f"{self.calendar_name} - {self.lanes()}"
        )


@dataclass(slots=True)
class Recommendation:
    """The pick of the week, and what it took to find one."""

    picks: list[Suggestion]
    prefs: Preferences  # what was asked for, even when nothing met it
    relaxed: bool = False  # nothing met min_lanes, so the bar was dropped

    @property
    def best(self) -> Suggestion | None:
        return self.picks[0] if self.picks else None


def best(
    days: list[PoolDay],
    prefs: Preferences | None = None,
    limit: int = 3,
    now: dt.datetime | None = None,
) -> Recommendation:
    """Rank the week's swimmable windows, one per day, best first."""
    prefs = prefs or preferences()
    picks = _rank(days, prefs, limit, now)
    if picks or prefs.min_lanes <= 1:
        return Recommendation(picks=picks, prefs=prefs)

    # Nothing cleared the bar all week -- worth saying so, and worth still
    # naming the least-bad option rather than shrugging.  The preferences
    # reported back are the ones you actually asked for, not the dropped bar.
    picks = _rank(days, replace(prefs, min_lanes=1), limit, now)
    return Recommendation(picks=picks, prefs=prefs, relaxed=bool(picks))


def _rank(
    days: list[PoolDay], prefs: Preferences, limit: int, now: dt.datetime | None
) -> list[Suggestion]:
    found: list[Suggestion] = []
    for day in days:
        if not prefs.wants_day(day.date):
            continue
        after = now.time() if now and now.date() == day.date else None
        if now and day.date < now.date():
            continue
        found += _candidates(day, prefs, after)

    # One suggestion per day: the runners-up are only useful as alternatives,
    # and a list of five overlapping half-hours on the same morning is not that.
    by_date: dict[dt.date, Suggestion] = {}
    for candidate in found:
        current = by_date.get(candidate.date)
        if current is None or _order(candidate) < _order(current):
            by_date[candidate.date] = candidate

    return sorted(by_date.values(), key=_order)[:limit]


def _candidates(day: PoolDay, prefs: Preferences, after: dt.time | None) -> list[Suggestion]:
    blocks_needed = max(1, math.ceil(prefs.session_minutes / SLOT_MINUTES))
    slots = sorted(day.slots, key=lambda s: s.start)

    out = []
    for index, first in enumerate(slots):
        if first.start < prefs.window_start or (after and first.start < after):
            continue
        run = slots[index : index + blocks_needed]
        if len(run) < blocks_needed or run[-1].end > prefs.window_stop:
            continue
        if not _contiguous(run):
            continue
        if any(not is_open(day.date, s) or s.lanes_free < prefs.min_lanes for s in run):
            continue

        free = [s.lanes_free for s in run]
        out.append(
            Suggestion(
                date=day.date,
                end=day.end,
                calendar_name=day.calendar_name,
                start=run[0].start,
                stop=run[-1].end,
                lanes_low=min(free),
                lanes_high=max(free),
                lanes_total=run[0].lanes_total,
                score=_score(day.end, run, prefs),
            )
        )
    return out


def _score(end: str, run: list[Slot], prefs: Preferences) -> float:
    free = [s.lanes_free for s in run]
    ideal = sum(
        _overlap(s.start, s.end, prefs.ideal_start, prefs.ideal_stop) for s in run
    )
    span = sum(_minutes(s.end) - _minutes(s.start) for s in run)
    return (
        LANE_WEIGHT * min(free)
        + sum(free) / len(free)
        + IDEAL_WEIGHT * (ideal / span if span else 0)
        + (END_WEIGHT if end == prefs.prefer_end else 0)
    )


def _order(suggestion: Suggestion) -> tuple:
    """Best first: highest score, then soonest, then earliest in the day."""
    return (-suggestion.score, suggestion.date, suggestion.start)


def _contiguous(run: list[Slot]) -> bool:
    return all(a.end == b.start for a, b in pairwise(run))


def _overlap(start: dt.time, stop: dt.time, other_start: dt.time, other_stop: dt.time) -> int:
    return max(
        0,
        min(_minutes(stop), _minutes(other_stop))
        - max(_minutes(start), _minutes(other_start)),
    )


def _minutes(t: dt.time) -> int:
    return t.hour * 60 + t.minute
