"""What time it is where you are, and when you want to swim.

Two separate problems, both about the gap between the server and the pool:

* The box this runs on is on UTC; the pool is in Sydney.  Everything that asks
  "what day is it" or "what time is it now" goes through here, so a report is
  right no matter what the host clock says.
* The report suggests when to go.  What counts as a good time is a matter of
  taste, so it lives in `preferences.toml` -- hand-edited, like `rules.toml`.
"""

from __future__ import annotations

import datetime as dt
import os
import tomllib
from dataclasses import dataclass, replace
from functools import lru_cache
from pathlib import Path
from zoneinfo import ZoneInfo

from .model import WEEKDAY_NAMES

PREFERENCES_PATH = Path(__file__).with_name("preferences.toml")


@dataclass(frozen=True, slots=True)
class Preferences:
    """The contents of preferences.toml, parsed."""

    timezone: str
    window_start: dt.time
    window_stop: dt.time
    ideal_start: dt.time
    ideal_stop: dt.time
    session_minutes: int
    min_lanes: int
    prefer_end: str
    days: frozenset[str]

    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.timezone)

    def wants_day(self, date: dt.date) -> bool:
        return WEEKDAY_NAMES[date.weekday()] in self.days

    def in_window(self, start: dt.time, stop: dt.time) -> bool:
        """Does a block overlap the stretch of the day you would swim in?"""
        return start < self.window_stop and stop > self.window_start

    def describe(self) -> str:
        from .model import _h

        end = "" if self.prefer_end == "any" else f", {self.prefer_end} end preferred"
        return (
            f"{self.session_minutes} min between {_h(self.window_start)} and "
            f"{_h(self.window_stop)}, {self.min_lanes}+ lanes free{end}"
        )


@lru_cache(maxsize=None)
def preferences(path: Path | None = None) -> Preferences:
    """Load preferences.toml, or POOLSTATUS_PREFERENCES if that is set."""
    path = path or Path(os.environ.get("POOLSTATUS_PREFERENCES") or PREFERENCES_PATH)
    data = tomllib.loads(path.read_text(encoding="utf-8"))

    window_start, window_stop = _range(data.get("window", "8:00-10:00"))
    ideal_start, ideal_stop = _range(data.get("ideal", "8:00-9:00"))
    days = tuple(data.get("days") or WEEKDAY_NAMES)
    unknown = set(days) - set(WEEKDAY_NAMES)
    if unknown:
        raise ValueError(f"{path.name}: unknown days {sorted(unknown)}")

    prefer_end = data.get("prefer_end", "any")
    if prefer_end not in ("deep", "shallow", "any"):
        raise ValueError(f"{path.name}: prefer_end must be deep, shallow or any")

    return Preferences(
        timezone=data.get("timezone", "Australia/Sydney"),
        window_start=window_start,
        window_stop=window_stop,
        ideal_start=ideal_start,
        ideal_stop=ideal_stop,
        session_minutes=int(data.get("session_minutes", 60)),
        min_lanes=int(data.get("min_lanes", 3)),
        prefer_end=prefer_end,
        days=frozenset(days),
    )


def with_overrides(window: str | None = None, min_lanes: int | None = None) -> Preferences:
    """The saved preferences, with a one-off change from the command line."""
    prefs = preferences()
    if window:
        start, stop = _range(window)
        # The ideal hour has to stay inside the window it was asked to sit in;
        # if the two no longer overlap at all, the whole window is the ideal.
        ideal_start, ideal_stop = max(prefs.ideal_start, start), min(prefs.ideal_stop, stop)
        if ideal_start >= ideal_stop:
            ideal_start, ideal_stop = start, stop
        prefs = replace(
            prefs,
            window_start=start,
            window_stop=stop,
            ideal_start=ideal_start,
            ideal_stop=ideal_stop,
        )
    if min_lanes is not None:
        prefs = replace(prefs, min_lanes=min_lanes)
    return prefs


def now() -> dt.datetime:
    """The current time at the pool, not on whatever host this is running on."""
    return dt.datetime.now(preferences().tz)


def today() -> dt.date:
    return now().date()


def _range(value: str) -> tuple[dt.time, dt.time]:
    start, _, stop = value.partition("-")
    if not stop:
        raise ValueError(f"expected a time range like 8:00-10:00, got {value!r}")
    return _time(start), _time(stop)


def _time(value: str) -> dt.time:
    hours, _, minutes = value.strip().partition(":")
    return dt.time(int(hours), int(minutes or 0))
