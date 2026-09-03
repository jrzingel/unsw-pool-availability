"""Centre opening hours.

The occupancy API reports closed periods exactly like fully-booked ones -- zero
lanes available -- so without this the weekend 6-7am and 7-9:30pm bands look
like enormous phantom bookings.  Hours are from unswfac.com.au/contact/:

    Mon-Fri           6:00am - 10:00pm
    Sat, Sun, pub hol 7:00am -  7:00pm
    (the pool itself closes 15 minutes before the centre)

Observed bookable blocks match that: weekdays run 6:00am-9:30pm and weekends
7:00am-7:00pm, so those are the windows used here.
"""

from __future__ import annotations

import datetime as dt

from .model import Slot

WEEKDAY_OPEN = dt.time(6, 0)
WEEKDAY_LAST_SLOT_END = dt.time(21, 30)

WEEKEND_OPEN = dt.time(7, 0)
WEEKEND_LAST_SLOT_END = dt.time(19, 0)

# NSW public holidays run on weekend hours.  Add dates here as needed; the
# centre publishes holiday hours each year and closes entirely on Good Friday.
PUBLIC_HOLIDAYS: set[dt.date] = set()
CLOSED_DATES: set[dt.date] = set()


def is_weekend_schedule(date: dt.date) -> bool:
    return date.weekday() >= 5 or date in PUBLIC_HOLIDAYS


def opening_window(date: dt.date) -> tuple[dt.time, dt.time] | None:
    """(first bookable slot start, last bookable slot end), or None if closed."""
    if date in CLOSED_DATES:
        return None
    if is_weekend_schedule(date):
        return WEEKEND_OPEN, WEEKEND_LAST_SLOT_END
    return WEEKDAY_OPEN, WEEKDAY_LAST_SLOT_END


def is_open(date: dt.date, slot: Slot) -> bool:
    """Is the pool open for this block, as opposed to booked out?"""
    window = opening_window(date)
    if window is None:
        return False
    open_at, close_at = window
    return slot.start >= open_at and slot.end <= close_at


def describe(date: dt.date) -> str:
    window = opening_window(date)
    if window is None:
        return "closed"
    open_at, close_at = window
    from .model import _h

    return f"{_h(open_at)}-{_h(close_at)}"
