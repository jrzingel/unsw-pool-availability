"""Attach names to bookings.

The occupancy API is anonymous -- it says how many lanes are free and nothing
about who has the rest.  This module matches each booked block against the
hand-maintained rules in rules.toml so a report can say "swim squads" instead
of "0 of 8 lanes".
"""

from __future__ import annotations

import datetime as dt
import tomllib
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from .model import PoolDay, Slot

RULES_PATH = Path(__file__).with_name("rules.toml")

WEEKDAY_NAMES = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
CONFIDENCE_ORDER = {"confirmed": 0, "likely": 1, "guess": 2}


@dataclass(frozen=True, slots=True)
class Rule:
    who: str
    ends: frozenset[str]
    days: frozenset[str]
    start: dt.time
    stop: dt.time
    lanes: int
    confidence: str
    frequency: str
    detail: str = ""
    source: str = ""

    def matches(self, end: str, date: dt.date, slot: Slot) -> bool:
        return (
            end in self.ends
            and WEEKDAY_NAMES[date.weekday()] in self.days
            and slot.start >= self.start
            and slot.start < self.stop
        )

    def describe(self) -> str:
        parts = [self.who]
        if self.confidence != "confirmed":
            parts.append(f"({self.confidence})")
        return " ".join(parts)


@dataclass(slots=True)
class Attribution:
    """Who is using the booked lanes in one block."""

    slot: Slot
    rules: list[Rule]

    @property
    def claimed_lanes(self) -> int:
        return sum(r.lanes for r in self.rules)

    @property
    def unattributed_lanes(self) -> int:
        return max(0, self.slot.lanes_booked - self.claimed_lanes)

    def summary(self) -> str:
        """A short human phrase for who has the lanes."""
        if not self.slot.lanes_booked:
            return ""
        names: list[str] = []
        for rule in self.rules:
            if rule.who not in names:
                names.append(rule.who)
        if self.unattributed_lanes and names:
            names.append(f"+{self.unattributed_lanes} unattributed")
        elif not names:
            return "unattributed"
        return ", ".join(names)


@lru_cache(maxsize=None)
def load_rules(path: Path | None = None) -> tuple[Rule, ...]:
    data = tomllib.loads((path or RULES_PATH).read_text(encoding="utf-8"))
    return tuple(_parse_rule(entry) for entry in data.get("rule", []))


def attribute(end: str, date: dt.date, slot: Slot, rules=None) -> Attribution:
    rules = load_rules() if rules is None else rules
    matched = [r for r in rules if r.matches(end, date, slot)]
    matched.sort(key=lambda r: (CONFIDENCE_ORDER.get(r.confidence, 3), -r.lanes))
    return Attribution(slot=slot, rules=matched)


def attribute_day(day: PoolDay, rules=None) -> list[Attribution]:
    rules = load_rules() if rules is None else rules
    return [attribute(day.end, day.date, slot, rules) for slot in day.slots]


def _parse_rule(entry: dict) -> Rule:
    start, _, stop = entry["time"].partition("-")
    days = entry.get("days") or list(WEEKDAY_NAMES)
    unknown = set(days) - set(WEEKDAY_NAMES)
    if unknown:
        raise ValueError(f"rule {entry['who']!r} has unknown days {sorted(unknown)}")
    return Rule(
        who=entry["who"],
        ends=frozenset(entry["ends"]),
        days=frozenset(days),
        start=_time(start),
        stop=_time(stop),
        lanes=int(entry.get("lanes", 1)),
        confidence=entry.get("confidence", "guess"),
        frequency=entry.get("frequency", "weekly"),
        detail=entry.get("detail", ""),
        source=entry.get("source", ""),
    )


def _time(value: str) -> dt.time:
    hours, _, minutes = value.strip().partition(":")
    return dt.time(int(hours), int(minutes or 0))
