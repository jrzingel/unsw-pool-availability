"""Client for the UNSW Fitness & Aquatic Centre lane occupancy calendars.

The public page at https://unswfac.com.au/aquatics/lane-availability/ embeds two
PerfectGym "club zone occupancy" calendars, one per half of the pool.  The page
itself is an empty Vue shell, so there is nothing to scrape from the HTML -- the
numbers come from a JSON endpoint that needs no authentication:

    GET /ClientPortal2/api/Calendars/ClubZoneOccupancyCalendar/GetCalendar
        ?calendarId=<id>&startDate=YYYY-MM-DD&daysPerPage=<n>

Two quirks worth knowing:

* Past dates are silently clamped to today, so the API can only ever tell you
  about now and the next ~4 weeks.  History has to be accumulated locally --
  see `poolstatus.store`.
* The response grid is trimmed to the span of non-empty blocks across the whole
  page, so a small `daysPerPage` drops real early-morning and late-evening
  blocks.  Requesting a week or more always returns the full 6:00am-9:30pm grid,
  hence MIN_DAYS_PER_PAGE below.
"""

from __future__ import annotations

import datetime as dt

import requests

from .model import ENDS, PoolDay, Slot, Snapshot

API_URL = (
    "https://unswfac.perfectgym.com.au/ClientPortal2/api"
    "/Calendars/ClubZoneOccupancyCalendar/GetCalendar"
)

# Calendar ids from the embeds on the lane-availability page.
CALENDAR_IDS = {
    "deep": "07145b7c1",  # 25M Deep End
    "shallow": "b702872a2",  # 25M Shallow End
}

# Below this the API trims leading/trailing blocks off the grid (see docstring).
MIN_DAYS_PER_PAGE = 7

# Bookings open about four weeks ahead; past that the API returns no day blocks.
MAX_DAYS_AHEAD = 28

USER_AGENT = "poolstatus/0.1 (personal lane-availability checker)"


class PoolStatusError(RuntimeError):
    pass


def fetch_end(
    end: str,
    start_date: dt.date | None = None,
    days: int = MAX_DAYS_AHEAD,
    session: requests.Session | None = None,
    timeout: float = 30.0,
) -> list[PoolDay]:
    """Fetch `days` days of availability for one half of the pool."""
    if end not in CALENDAR_IDS:
        raise PoolStatusError(f"unknown pool end {end!r}, expected one of {ENDS}")
    start_date = start_date or dt.date.today()

    params = {
        "calendarId": CALENDAR_IDS[end],
        "startDate": start_date.isoformat(),
        # Ask for at least a week even when the caller wants fewer days, then
        # trim, so the returned grid is never truncated.
        "daysPerPage": max(days, MIN_DAYS_PER_PAGE),
    }
    get = (session or requests).get
    response = get(
        API_URL,
        params=params,
        headers={"Accept": "application/json", "User-Agent": USER_AGENT},
        timeout=timeout,
    )
    response.raise_for_status()
    payload = response.json()

    calendar_name = payload.get("calendarName") or end
    wanted = {start_date + dt.timedelta(days=i) for i in range(days)}

    result: list[PoolDay] = []
    for block in payload.get("dayBlocks", []):
        date = dt.date.fromisoformat(block["date"])
        if date not in wanted:
            continue
        result.append(
            PoolDay(
                end=end,
                calendar_name=calendar_name,
                date=date,
                slots=[_parse_slot(h) for h in block.get("hours", [])],
            )
        )
    return sorted(result, key=lambda d: d.date)


def fetch(
    start_date: dt.date | None = None,
    days: int = MAX_DAYS_AHEAD,
    timeout: float = 30.0,
) -> Snapshot:
    """Fetch both halves of the pool in one snapshot."""
    with requests.Session() as session:
        pool_days: list[PoolDay] = []
        for end in ENDS:
            pool_days += fetch_end(
                end, start_date=start_date, days=days, session=session, timeout=timeout
            )
    return Snapshot(fetched_at=dt.datetime.now().astimezone(), days=pool_days)


def _parse_slot(hour: dict) -> Slot:
    return Slot(
        start=_parse_time(hour["fromHour"]["value"]),
        end=_parse_time(hour["toHour"]["value"]),
        lanes_free=hour["totalCountOfOccupancyAvailability"],
        lanes_total=hour["numberOfFacilities"],
    )


def _parse_time(value: str) -> dt.time:
    hours, minutes, seconds = (int(part) for part in value.split(":"))
    # The API emits 24:00:00 for a block that ends at midnight.
    return dt.time(hours % 24, minutes, seconds)
