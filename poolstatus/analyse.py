"""Find the recurring shape of the bookings.

Feed it every day we have (the live 4-week window, the saved history, or both)
and it reports, per pool end and weekday, the blocks that are reliably booked --
merged into runs, with how many of the observed weeks they held, and whether the
rules in rules.toml already name them.
"""

from __future__ import annotations

import datetime as dt
from collections import Counter, defaultdict
from dataclasses import dataclass

from .classify import WEEKDAY_NAMES, Rule, attribute, load_rules
from .hours import is_open
from .model import PoolDay, Slot, _h
from .store import grid_times


@dataclass(slots=True)
class Pattern:
    """A run of half-hour blocks that behave the same way week to week."""

    end: str
    weekday: str
    start: dt.time
    stop: dt.time
    lanes_booked: int
    weeks_seen: int
    weeks_total: int
    who: str

    @property
    def is_reliable(self) -> bool:
        return self.weeks_seen == self.weeks_total

    @property
    def frequency(self) -> str:
        if self.is_reliable:
            return "every week"
        return f"{self.weeks_seen}/{self.weeks_total} weeks"

    def time_range(self) -> str:
        return f"{_h(self.start)}-{_h(self.stop)}"


def find_patterns(
    days: list[PoolDay],
    min_weeks: int = 2,
    skip_dates: set[dt.date] | None = None,
) -> list[Pattern]:
    """Modal booking level for each (end, weekday, block), merged into runs."""
    skip_dates = skip_dates or set()
    rules = load_rules()

    observed: dict[tuple[str, str], dict[dt.time, list[int]]] = defaultdict(
        lambda: defaultdict(list)
    )
    for day in days:
        if day.date in skip_dates or not day.slots:
            continue
        key = (day.end, WEEKDAY_NAMES[day.date.weekday()])
        by_start = {s.start: s for s in day.slots}
        for t in grid_times():
            slot = by_start.get(t)
            if slot is None or not is_open(day.date, slot):
                continue
            observed[key][t].append(slot.lanes_booked)

    patterns: list[Pattern] = []
    order = {(e, w): (e, i) for e in {k[0] for k in observed} for i, w in enumerate(WEEKDAY_NAMES)}
    for (end, weekday) in sorted(observed, key=lambda k: order[k]):
        runs = _modal_runs(observed[(end, weekday)], min_weeks)
        for start, stop, booked, seen, total in runs:
            if not booked:
                continue
            patterns.append(
                Pattern(
                    end=end,
                    weekday=weekday,
                    start=start,
                    stop=stop,
                    lanes_booked=booked,
                    weeks_seen=seen,
                    weeks_total=total,
                    who=_attribute_run(end, weekday, start, stop, booked, rules),
                )
            )
    return patterns


def _attribute_run(
    end: str,
    weekday: str,
    start: dt.time,
    stop: dt.time,
    lanes_booked: int,
    rules: tuple[Rule, ...],
) -> str:
    """Merge the attributions of every block in a run.

    A run is merged on booking *level*, so a single run can span two different
    bookings back to back -- Friday's deep end goes straight from squad into the
    school block without ever freeing up.  Probing only the first block would
    miss the second.
    """
    date = _sample_date(weekday)
    names: list[str] = []
    residual = 0
    at = start
    while at < stop:
        block = Slot(at, _plus_30(at), 8 - lanes_booked, 8)
        found = attribute(end, date, block, rules)
        for rule in found.rules:
            if rule.who not in names:
                names.append(rule.who)
        residual = max(residual, found.unattributed_lanes)
        at = _plus_30(at)

    if not names:
        return "unattributed"
    if residual:
        names.append(f"+{residual} unattributed")
    return ", ".join(names)


def unnamed(patterns: list[Pattern]) -> list[Pattern]:
    """Patterns the rules do not fully explain -- the classification to-do list."""
    return [p for p in patterns if "unattributed" in p.who]


def _modal_runs(
    blocks: dict[dt.time, list[int]], min_weeks: int
) -> list[tuple[dt.time, dt.time, int, int, int]]:
    """Collapse consecutive blocks with the same modal booking into runs."""
    rows = []
    for t in grid_times():
        values = blocks.get(t)
        if not values:
            continue
        counts = Counter(values)
        booked, seen = counts.most_common(1)[0]
        if len(values) >= min_weeks and seen * 2 <= len(values):
            # No clear majority -- report the lower bound so we do not overstate.
            booked = min(values)
            seen = sum(1 for v in values if v >= booked)
        rows.append((t, booked, seen, len(values)))

    # Merge on the booking level *and* on whether it holds every week, so a
    # standing block never absorbs an intermittent one and inherits its
    # reliability -- Friday's deep end is squad every week, then school most
    # weeks, with no gap between them.
    def key(row):
        _, booked, seen, total = row
        return booked, seen == total

    runs = []
    index = 0
    while index < len(rows):
        end_index = index
        while (
            end_index + 1 < len(rows)
            and key(rows[end_index + 1]) == key(rows[index])
            and _is_adjacent(rows[end_index][0], rows[end_index + 1][0])
        ):
            end_index += 1
        span = rows[index : end_index + 1]
        start = span[0][0]
        stop = _plus_30(span[-1][0])
        booked = span[0][1]
        runs.append((start, stop, booked, min(r[2] for r in span), max(r[3] for r in span)))
        index = end_index + 1
    return runs


def _is_adjacent(a: dt.time, b: dt.time) -> bool:
    return _plus_30(a) == b


def _plus_30(t: dt.time) -> dt.time:
    return (dt.datetime(2000, 1, 1, t.hour, t.minute) + dt.timedelta(minutes=30)).time()


def _sample_date(weekday: str) -> dt.date:
    """Any date falling on that weekday -- rules only look at the weekday."""
    base = dt.date(2026, 1, 5)  # a Monday
    return base + dt.timedelta(days=WEEKDAY_NAMES.index(weekday))
