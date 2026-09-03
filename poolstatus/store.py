"""Local history of what the calendars said.

The API clamps any past date to today, so yesterday is unrecoverable the moment
it passes.  Every run appends what it saw to a JSONL file, which turns the
4-week rolling window into a growing record you can mine for patterns -- and
which also captures *when* a booking appeared, so you can tell a standing
booking from one that landed last Tuesday.

Each line is one (end, date) observation with availability packed into a fixed
32-character grid covering 6:00am to 9:30pm in half hours:

    "0" - "8"  lanes free
    "-"        block not offered (outside opening hours, or no data)

Lines are only appended when the picture actually changed, so a quiet week adds
almost nothing.
"""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

from .model import PoolDay, Slot, Snapshot

DEFAULT_PATH = Path(__file__).resolve().parent.parent / "data" / "history.jsonl"

GRID_START = dt.time(6, 0)
GRID_SLOTS = 32  # 6:00am .. 9:30pm in half hours
MISSING = "-"


def grid_times() -> list[dt.time]:
    base = dt.datetime(2000, 1, 1, GRID_START.hour, GRID_START.minute)
    return [(base + dt.timedelta(minutes=30 * i)).time() for i in range(GRID_SLOTS)]


def encode(day: PoolDay) -> str:
    by_start = {s.start: s for s in day.slots}
    return "".join(
        str(by_start[t].lanes_free) if t in by_start else MISSING for t in grid_times()
    )


def decode(end: str, calendar_name: str, date: dt.date, grid: str, total: int) -> PoolDay:
    times = grid_times()
    slots = [
        Slot(
            start=t,
            end=(dt.datetime.combine(date, t) + dt.timedelta(minutes=30)).time(),
            lanes_free=int(ch),
            lanes_total=total,
        )
        for t, ch in zip(times, grid)
        if ch != MISSING
    ]
    return PoolDay(end=end, calendar_name=calendar_name, date=date, slots=slots)


def save(snapshot: Snapshot, path: Path | None = None) -> int:
    """Append changed observations.  Returns how many lines were written."""
    path = path or DEFAULT_PATH
    path.parent.mkdir(parents=True, exist_ok=True)

    latest = {(rec["end"], rec["date"]): rec["free"] for rec in _read(path)}

    new_lines = []
    for day in snapshot.days:
        if not day.slots:
            continue
        grid = encode(day)
        if latest.get((day.end, day.date.isoformat())) == grid:
            continue
        new_lines.append(
            json.dumps(
                {
                    "observed_at": snapshot.fetched_at.isoformat(timespec="seconds"),
                    "end": day.end,
                    "calendar_name": day.calendar_name,
                    "date": day.date.isoformat(),
                    "total": day.slots[0].lanes_total,
                    "free": grid,
                },
                separators=(",", ":"),
            )
        )

    if new_lines:
        with path.open("a", encoding="utf-8") as handle:
            handle.write("\n".join(new_lines) + "\n")
    return len(new_lines)


def load(path: Path | None = None) -> list[PoolDay]:
    """Every (end, date) we have ever seen, using the most recent observation."""
    latest: dict[tuple[str, str], dict] = {}
    for rec in _read(path or DEFAULT_PATH):
        latest[(rec["end"], rec["date"])] = rec
    return sorted(
        (
            decode(
                rec["end"],
                rec.get("calendar_name", rec["end"]),
                dt.date.fromisoformat(rec["date"]),
                rec["free"],
                rec.get("total", 8),
            )
            for rec in latest.values()
        ),
        key=lambda d: (d.date, d.end),
    )


def _read(path: Path):
    if not path.exists():
        return
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                yield json.loads(line)
