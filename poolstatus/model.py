"""Data model for pool lane availability."""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field

# The 50m pool is split in half; each half is a separate bookable "club zone"
# with eight 25m lanes.
END_DEEP = "deep"
END_SHALLOW = "shallow"
ENDS = (END_DEEP, END_SHALLOW)

SLOT_MINUTES = 30


@dataclass(frozen=True, slots=True)
class Slot:
    """One bookable half-hour block in one half of the pool."""

    start: dt.time
    end: dt.time
    lanes_free: int
    lanes_total: int

    @property
    def lanes_booked(self) -> int:
        return self.lanes_total - self.lanes_free

    @property
    def is_full(self) -> bool:
        return self.lanes_free == 0

    def label(self) -> str:
        return f"{_h(self.start)}-{_h(self.end)}"


@dataclass(slots=True)
class PoolDay:
    """One calendar day for one half of the pool."""

    end: str  # "deep" | "shallow"
    calendar_name: str  # e.g. "25M Deep End"
    date: dt.date
    slots: list[Slot] = field(default_factory=list)

    def slot_at(self, t: dt.time) -> Slot | None:
        return next((s for s in self.slots if s.start == t), None)

    def free_slots(self, min_lanes: int = 1) -> list[Slot]:
        return [s for s in self.slots if s.lanes_free >= min_lanes]


@dataclass(slots=True)
class Snapshot:
    """Everything fetched in one go, for both ends of the pool."""

    fetched_at: dt.datetime
    days: list[PoolDay] = field(default_factory=list)

    def dates(self) -> list[dt.date]:
        return sorted({d.date for d in self.days})

    def for_date(self, date: dt.date) -> dict[str, PoolDay]:
        return {d.end: d for d in self.days if d.date == date}


def _h(t: dt.time) -> str:
    """Render a time the way the centre does: 6am, 9:30am, 12pm, 4:15pm."""
    hour = t.hour % 12 or 12
    suffix = "am" if t.hour < 12 else "pm"
    return f"{hour}:{t.minute:02d}{suffix}" if t.minute else f"{hour}{suffix}"
